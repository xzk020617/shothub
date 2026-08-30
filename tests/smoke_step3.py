"""第 3 步冒烟测试：拖拽双向 + Ctrl+V 粘贴。

验收标准对应（Plan.md 第 7 节·第 3 步）：
1. 拖入图片文件 → 入库成功；拖入 .txt → 被拒绝且有提示
2. 拖出 mime 数据携带真实文件路径（资源管理器/微信可接收）
3. Ctrl+V 支持文件形式与位图形式两种粘贴

说明：事件处理逻辑在 MainWindow 中与 Qt 事件解耦为 _handle_drag_enter/_handle_drop，
测试用 FakeEvent 模拟接受/拒绝协议直接驱动 handler（PySide6 手工构造的
QDropEvent.mimeData() 会退化为 QObject，真实运行时无此问题）。

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/smoke_step3.py
"""
import os
import shutil
import sys
import tempfile
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QMimeData, QObject, Qt, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.clipboard_hub import ClipboardHub  # noqa: E402
from app.mainwindow import MainWindow  # noqa: E402
from app.storage import StorageManager  # noqa: E402
from app.widgets import build_file_mimedata  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeClipboard(QObject):
    """假剪贴板：mimeData 用真实 QMimeData，image 单独持有。"""

    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self._mime = QMimeData()
        self._img = QImage()

    def set_files(self, paths) -> None:
        self._mime = QMimeData()
        self._mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])

    def set_image(self, pil_img: Image.Image) -> None:
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        self._img = QImage.fromData(buf.getvalue())
        self._mime = QMimeData()
        self._mime.setImageData(self._img)

    def set_text(self) -> None:
        self._img = QImage()
        self._mime = QMimeData()
        self._mime.setText("plain text")

    def mimeData(self) -> QMimeData:
        return self._mime

    def image(self) -> QImage:
        return self._img


def make_urls_mime(paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


class FakeEvent:
    """模拟 Qt 拖放事件的接受/拒绝协议（PySide6 构造的 QDropEvent
    其 mimeData() 会退化为 QObject，故测试直接调用解耦后的 handler）。"""

    def __init__(self):
        self._accepted = False

    def acceptProposedAction(self) -> None:
        self._accepted = True

    def ignore(self) -> None:
        self._accepted = False

    def isAccepted(self) -> bool:
        return self._accepted


def main() -> int:
    app = QApplication([])
    work = Path(tempfile.mkdtemp(prefix="shothub_test3_"))
    src = work / "incoming"
    src.mkdir()
    print(f"测试目录: {work}\n")

    storage = StorageManager(root=work / "data")
    fake_clip = FakeClipboard()
    hub = ClipboardHub(clipboard=fake_clip, seq_provider=lambda: 42)
    window = MainWindow(storage, hub=hub)

    # 准备素材：2 张图 + 1 个 txt
    imgs = []
    for i, size in enumerate([(640, 480), (300, 800)]):
        p = src / f"pic_{i}.png"
        Image.new("RGB", size, (50, 120, 200)).save(p)
        imgs.append(p)
    txt = src / "note.txt"
    txt.write_text("hello", encoding="utf-8")

    # ===== 用例 1：拖出 mime 数据携带真实文件路径 =====
    fake_path = str(src / "pic_0.png")
    mime = build_file_mimedata(fake_path)
    check("1.1 拖出 mime 含 URL", mime.hasUrls())
    check("1.2 URL 回读为原文件路径",
          Path(mime.urls()[0].toLocalFile()) == Path(fake_path),
          mime.urls()[0].toLocalFile())

    # ===== 用例 2：拖入分类 =====
    check("2.1 图片文件 urls → files",
          window._classify_drop(make_urls_mime(imgs)) == "files")
    check("2.2 纯 txt urls → reject",
          window._classify_drop(make_urls_mime([txt])) == "reject")
    img_mime = QMimeData()
    img_mime.setImageData(QImage(10, 10, QImage.Format.Format_RGB32))
    check("2.3 位图数据 → image", window._classify_drop(img_mime) == "image")
    text_mime = QMimeData()
    text_mime.setText("hello")
    check("2.4 纯文本 → reject", window._classify_drop(text_mime) == "reject")

    # ===== 用例 3：拖入图片（走解耦后的 handler，逻辑与真实事件一致）=====
    enter_evt = FakeEvent()
    window._handle_drag_enter(make_urls_mime(imgs), enter_evt)
    check("3.1 dragEnter 接受图片拖入", enter_evt.isAccepted())
    check("3.2 拖入时遮罩显示", not window.drop_overlay.isHidden())  # 窗口未 show，用 isHidden 判断显式状态

    drop_evt = FakeEvent()
    window._handle_drop(make_urls_mime(imgs + [txt]), drop_evt)  # 混入 1 个 txt
    app.processEvents()
    items = storage.list()
    check("3.3 drop 事件被接受", drop_evt.isAccepted())
    check("3.4 2 张图入库、txt 被过滤", len(items) == 2, f"实际 {len(items)}")
    check("3.5 来源标记为 dragin", all(it.source == "dragin" for it in items))
    check("3.6 drop 后遮罩隐藏", window.drop_overlay.isHidden())
    check("3.7 网格卡片为 2 张", len(window._cards) == 2)

    # ===== 用例 4：拖入 txt → 拒绝 =====
    enter_txt = FakeEvent()
    window._handle_drag_enter(make_urls_mime([txt]), enter_txt)
    check("4.1 dragEnter 拒绝 txt", not enter_txt.isAccepted())
    check("4.2 拒绝时遮罩提示仅支持图片",
          not window.drop_overlay.isHidden()
          and "仅支持图片" in window.drop_overlay.text())
    drop_txt = FakeEvent()
    window._handle_drop(make_urls_mime([txt]), drop_txt)
    check("4.3 drop txt 未入库", len(storage.list()) == 2)
    check("4.4 drop 后遮罩隐藏", window.drop_overlay.isHidden())

    # ===== 用例 5：Ctrl+V 粘贴 =====
    fake_clip.set_files([imgs[0]])
    window._on_paste()
    items = storage.list()
    check("5.1 粘贴文件形式入库", len(items) == 3)
    check("5.2 文件粘贴来源为 paste", items[0].source == "paste")

    fake_clip.set_image(Image.new("RGB", (320, 240), (200, 50, 50)))
    window._on_paste()
    items = storage.list()
    check("5.3 粘贴位图形式入库", len(items) == 4)
    check("5.4 位图尺寸正确", (items[0].width, items[0].height) == (320, 240))
    check("5.5 位图粘贴来源为 paste", items[0].source == "paste")

    fake_clip.set_text()
    window._on_paste()
    check("5.6 粘贴纯文本无操作", len(storage.list()) == 4)

    print()
    if failures:
        print(f"共 {len(failures)} 项失败: {failures}")
        shutil.rmtree(work, ignore_errors=True)
        return 1
    print("✅ 第 3 步全部验收用例通过")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
