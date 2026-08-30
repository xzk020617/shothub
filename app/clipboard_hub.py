"""剪贴板中枢：监听图片入库 + 双格式写回。

对应 Plan.md 第 4/5 节：
- 监听：QClipboard.dataChanged（Qt 在 Windows 已封装剪贴板变更事件）
- 自我过滤：写入后记录 GetClipboardSequenceNumber()，命中即忽略，防死循环
- 写回：同时放置 CF_DIB + 注册格式 "PNG"，兼容 微信/PS/Office
- 剪贴板被占用：OpenClipboard 失败时重试，仍失败则抛 ClipboardError
"""
from __future__ import annotations

import hashlib
import time
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

import win32clipboard
import win32con
from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
from PySide6.QtGui import QGuiApplication, QImage

CLIPBOARD_OPEN_RETRIES = 5
CLIPBOARD_RETRY_INTERVAL = 0.05
DUPE_WINDOW_SECONDS = 2.0  # 同一图片在此时间窗内重复出现视为同一次截图


class ClipboardError(Exception):
    """剪贴板读写失败。"""


def qimage_to_png_bytes(qimg: QImage) -> bytes:
    """QImage → PNG 字节。"""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not qimg.save(buf, "PNG"):
        buf.close()
        raise ClipboardError("剪贴板图片解码失败")
    buf.close()
    return bytes(ba)


def qimage_to_pil(qimg: QImage) -> Image.Image:
    """QImage → PIL Image（经 PNG 中转，保留透明通道）。"""
    im = Image.open(BytesIO(qimage_to_png_bytes(qimg)))
    im.load()
    return im


def png_to_dib_bytes(png_bytes: bytes) -> bytes:
    """PNG 字节 → CF_DIB 数据（BMP 去掉 14 字节 BITMAPFILEHEADER）。"""
    with Image.open(BytesIO(png_bytes)) as im:
        im = im.convert("RGB")  # DIB 不带透明，白底化交给接收方
        out = BytesIO()
        im.save(out, format="BMP")
    bmp = out.getvalue()
    if bmp[:2] != b"BM":
        raise ClipboardError("DIB 转换失败")
    return bmp[14:]


class ClipboardHub(QObject):
    imageCaptured = Signal(object)  # PIL.Image
    clipboardError = Signal(str)

    def __init__(
        self,
        clipboard=None,
        seq_provider: Optional[Callable[[], int]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        # clipboard / seq_provider 可注入，便于测试；默认用系统真实剪贴板
        self._clipboard = clipboard or QGuiApplication.clipboard()
        self._seq = seq_provider or win32clipboard.GetClipboardSequenceNumber
        self._own_seq: Optional[int] = None
        self._last_seq: Optional[int] = None
        self._last_hash: Optional[str] = None
        self._last_capture_at: float = 0.0
        self.dupe_window: float = DUPE_WINDOW_SECONDS
        self._listening = False

    # ---------- 监听入库 ----------

    def start(self) -> None:
        if not self._listening:
            self._clipboard.dataChanged.connect(self._on_clipboard_changed)
            self._listening = True

    def stop(self) -> None:
        if self._listening:
            self._clipboard.dataChanged.disconnect(self._on_clipboard_changed)
            self._listening = False

    def _on_clipboard_changed(self) -> None:
        try:
            seq = self._seq()
        except Exception:
            seq = None
        # 第一道去重：剪贴板序号。同一序号的事件直接跳过；
        # 截图工具一次写入多个格式可能触发多次事件、每次序号还不同，
        # 所以仅靠序号不够，下面还有第二道内容指纹去重
        if seq is not None:
            if seq == self._own_seq or seq == self._last_seq:
                return
            self._last_seq = seq
        mime = self._clipboard.mimeData()
        if not mime.hasImage():
            return  # 剪贴板里是文字/文件，静默忽略
        qimg = self._clipboard.image()
        if qimg.isNull():
            return
        try:
            png_bytes = qimage_to_png_bytes(qimg)
        except ClipboardError as exc:
            self.clipboardError.emit(str(exc))
            return
        # 第二道去重：内容指纹 + 时间窗（挡住同一次截图的重复事件）
        digest = hashlib.md5(png_bytes).hexdigest()
        now = time.monotonic()
        if (
            digest == self._last_hash
            and now - self._last_capture_at < self.dupe_window
        ):
            return
        self._last_hash = digest
        self._last_capture_at = now
        im = Image.open(BytesIO(png_bytes))
        im.load()
        self.imageCaptured.emit(im)

    # ---------- 直读剪贴板（Ctrl+V 粘贴用） ----------

    def clipboard_mime(self):
        """当前剪贴板的 mimeData（调用方自行判断 hasUrls/hasImage）。"""
        return self._clipboard.mimeData()

    def clipboard_image_pil(self) -> Optional[Image.Image]:
        """直读剪贴板图片为 PIL Image；无图片返回 None。"""
        qimg = self._clipboard.image()
        if qimg.isNull():
            return None
        return qimage_to_pil(qimg)

    # ---------- 写回剪贴板 ----------

    def put_image(self, path) -> None:
        """把图片文件写入系统剪贴板（CF_DIB + PNG 双格式）。"""
        png_bytes = Path(path).read_bytes()
        dib_bytes = png_to_dib_bytes(png_bytes)
        self._write_os_clipboard(png_bytes, dib_bytes)
        # 写入完成后再记录序号；dataChanged 经事件队列异步到达，
        # 此时 _own_seq 已就位，可正确过滤自身写入
        self._own_seq = self._seq()

    def _write_os_clipboard(self, png_bytes: bytes, dib_bytes: bytes) -> None:
        png_format = win32clipboard.RegisterClipboardFormat("PNG")
        last_exc: Optional[Exception] = None
        for _ in range(CLIPBOARD_OPEN_RETRIES):
            try:
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_DIB, dib_bytes)
                    win32clipboard.SetClipboardData(png_format, png_bytes)
                finally:
                    win32clipboard.CloseClipboard()
                return
            except Exception as exc:  # 剪贴板被其他程序短暂占用
                last_exc = exc
                time.sleep(CLIPBOARD_RETRY_INTERVAL)
        raise ClipboardError(f"剪贴板被占用，复制失败: {last_exc}")
