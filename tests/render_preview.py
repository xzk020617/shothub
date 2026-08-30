"""离屏渲染主窗口预览图，用于人工核对界面效果。"""
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.mainwindow import MainWindow  # noqa: E402
from app.storage import StorageManager  # noqa: E402

app = QApplication([])
work = Path(tempfile.mkdtemp(prefix="shothub_preview_"))
storage = StorageManager(root=work / "data")

random.seed(7)
for i in range(8):
    w, h = random.choice([(1920, 1080), (800, 600), (480, 1200), (2560, 1440)])
    im = Image.new("RGB", (w, h), (random.randint(60, 220),) * 3)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, w - 40, h - 40], outline=(255, 255, 255), width=8)
    storage.save_image(im, source="picker")

window = MainWindow(storage)
window.resize(760, 560)
window.show()
app.processEvents()
out = Path(__file__).resolve().parent.parent / "preview_step1.png"
window.grab().save(str(out))
print("saved:", out)

# 空状态也渲染一张
storage.clear()
window2 = MainWindow(storage)
window2.resize(760, 560)
window2.show()
app.processEvents()
out2 = out.with_name("preview_step1_empty.png")
window2.grab().save(str(out2))
print("saved:", out2)
