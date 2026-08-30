"""第 2 步冒烟测试：剪贴板闭环（捕获入库 + 复制出去 + 自我过滤）。

为避免测试改写真实系统剪贴板，向 ClipboardHub 注入假剪贴板/假序号，
并拦截 _write_os_clipboard 仅记录写出的字节流做校验。

验收标准对应（Plan.md 第 7 节·第 2 步）：
1. 连截 3 张 → 全部按序出现在列表顶部，无需手动操作
2. 复制出去 → 写出的剪贴板数据包含 PNG + DIB 双格式，且内容正确
3. 复制出去不会导致该图重复入库（自我写入过滤）
4. 剪贴板是文字等非图片内容 → 静默忽略

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/smoke_step2.py
"""
import os
import shutil
import struct
import sys
import tempfile
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.clipboard_hub import png_to_dib_bytes  # noqa: E402
from app.mainwindow import MainWindow  # noqa: E402
from app.storage import StorageManager  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeMime:
    def __init__(self, has_image: bool):
        self._has = has_image

    def hasImage(self) -> bool:
        return self._has


class FakeClipboard(QObject):
    """假剪贴板：模拟外部截图工具写入/读取。"""

    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self._img = QImage()
        self._has_image = False

    def set_image(self, pil_img: Image.Image) -> None:
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        self._img = QImage.fromData(buf.getvalue())
        self._has_image = True

    def set_text(self) -> None:
        self._img = QImage()
        self._has_image = False

    def image(self) -> QImage:
        return self._img

    def mimeData(self) -> FakeMime:
        return FakeMime(self._has_image)

    def poke(self) -> None:  # 模拟外部程序改动了剪贴板
        self.dataChanged.emit()


class FakeSeq:
    """模拟 GetClipboardSequenceNumber：剪贴板每次变化 +1。"""

    def __init__(self):
        self.value = 1000

    def get(self) -> int:
        return self.value

    def bump(self) -> None:
        self.value += 1


def main() -> int:
    app = QApplication([])
    work = Path(tempfile.mkdtemp(prefix="shothub_test2_"))
    print(f"测试目录: {work}\n")

    storage = StorageManager(root=work / "data")
    fake_clip = FakeClipboard()
    seq = FakeSeq()
    from app.clipboard_hub import ClipboardHub

    hub = ClipboardHub(clipboard=fake_clip, seq_provider=seq.get)
    written: list[tuple[bytes, bytes]] = []  # 拦截真实剪贴板写入
    hub._write_os_clipboard = lambda png, dib: written.append((png, dib))

    window = MainWindow(storage, hub=hub)

    # ===== 用例 1：连截 3 张（模拟 Win+Shift+S）=====
    sizes = [(1920, 1080), (800, 600), (480, 1200)]
    for w, h in sizes:
        fake_clip.set_image(Image.new("RGB", (w, h), (w % 255, 100, h % 255)))
        seq.bump()
        fake_clip.poke()
    app.processEvents()

    items = storage.list()
    check("1.1 连截 3 张全部入库", len(items) == 3, f"实际 {len(items)}")
    check("1.2 网格显示 3 张卡片", len(window._cards) == 3)
    check("1.3 最新截图排在最前",
          (items[0].width, items[0].height) == sizes[-1],
          f"首图 {items[0].width}×{items[0].height}")
    check("1.4 来源标记为 clipboard",
          all(it.source == "clipboard" for it in items))
    check("1.5 捕获图片尺寸无损",
          {(it.width, it.height) for it in items} == set(sizes))

    # ===== 用例 2：复制出去 → 双格式 + 内容正确 =====
    target = items[0]
    window._on_activated(target.id)  # 等效双击卡片
    check("2.1 复制触发了剪贴板写入", len(written) == 1)
    png_bytes, dib_bytes = written[0]
    check("2.2 PNG 数据与原文件一致",
          png_bytes == Path(target.file_path).read_bytes())
    check("2.3 DIB 头是 BITMAPINFOHEADER(40)",
          struct.unpack("<I", dib_bytes[:4])[0] == 40)
    with Image.open(BytesIO(b"BM" + b"\x00" * 12 + dib_bytes)) as bmp:
        check("2.4 DIB 可还原为原尺寸图片", bmp.size == (target.width, target.height))

    # ===== 用例 3：自我写入过滤（复制出去不得重复入库）=====
    before = len(storage.list())
    fake_clip.set_image(Image.open(target.file_path))  # 剪贴板现在是我们写出的图
    fake_clip.poke()  # seq 未变（写入是我们自己做的，seq_provider 同步序号）
    fake_clip.poke()  # 连发两次也得挡住
    app.processEvents()
    check("3.1 复制出去后未重复入库", len(storage.list()) == before,
          f"实际 {len(storage.list())}")

    # ===== 用例 4：外部应用随后复制了别的图（seq 变化）→ 正常捕获 =====
    fake_clip.set_image(Image.new("RGB", (300, 200), (10, 200, 10)))
    seq.bump()
    fake_clip.poke()
    app.processEvents()
    items = storage.list()
    check("4.1 外部新截图正常入库", len(items) == before + 1)
    check("4.2 新图排在最前", (items[0].width, items[0].height) == (300, 200))

    # ===== 用例 5：剪贴板是文字 → 静默忽略 =====
    fake_clip.set_text()
    seq.bump()
    fake_clip.poke()
    app.processEvents()
    check("5.1 非图片内容静默忽略", len(storage.list()) == before + 1)

    # ===== 用例 6：png_to_dib 纯函数对带透明通道的图不炸 =====
    rgba = Image.new("RGBA", (64, 64), (255, 0, 0, 128))
    buf = BytesIO()
    rgba.save(buf, format="PNG")
    dib = png_to_dib_bytes(buf.getvalue())
    check("6.1 RGBA 图转 DIB 成功", struct.unpack("<I", dib[:4])[0] == 40)

    print()
    if failures:
        print(f"共 {len(failures)} 项失败: {failures}")
        shutil.rmtree(work, ignore_errors=True)
        return 1
    print("✅ 第 2 步全部验收用例通过")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
