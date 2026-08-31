"""第 5 步冒烟测试：编辑合并 + 窗口置顶。

验收标准：
1. images_similar：同图/小编辑 → 相似；不同内容（同尺寸）→ 不相似
2. StorageManager.replace_image：原位覆盖原图、重建缩略图、元数据更新、id 不变
3. 主窗口编辑合并：连续捕获同图的编辑版本 → 仍只有 1 条；捕获不同内容 → 新增
4. 合并豁免：最新条目是手动添加的、或超出时间窗 → 不合并，正常新增
5. 置顶按钮：切换 WindowStaysOnTopHint 标志

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/smoke_step5.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.mainwindow import MainWindow  # noqa: E402
from app.storage import StorageManager, images_similar  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def make_shot(color=(240, 240, 245), size=(320, 200)) -> Image.Image:
    """模拟一张截图：底色 + 一些内容块。"""
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 140, 80], fill=(90, 140, 255))
    d.rectangle([160, 40, 300, 120], fill=(240, 180, 60))
    d.text((24, 150), "ShotHub test", fill=(40, 40, 40))
    return im


def edit_stroke(im: Image.Image) -> Image.Image:
    """模拟截图工具的一次编辑：画一条红线和标注。"""
    out = im.copy()
    d = ImageDraw.Draw(out)
    d.line([10, 10, 200, 120], fill=(230, 40, 40), width=4)
    d.ellipse([240, 130, 280, 170], outline=(230, 40, 40), width=3)
    return out


def main() -> int:
    app = QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="shothub_step5_"))
    try:
        storage = StorageManager(root=tmp)
        base = make_shot()

        # ===== 1. images_similar =====
        item = storage.save_image(base, source="clipboard")
        check("同一张图 → 判定相似", images_similar(item.file_path, base.copy()))
        edited = edit_stroke(base)
        check("小编辑（画线+标注）→ 判定相似", images_similar(item.file_path, edited))
        other = make_shot(color=(30, 60, 30))  # 同尺寸但内容完全不同
        check("不同内容同尺寸 → 判定不相似", not images_similar(item.file_path, other))
        check("文件不存在 → 判定不相似", not images_similar(tmp / "nope.png", base))

        # ===== 2. replace_image =====
        old_id, old_path = item.id, item.file_path
        old_bytes = item.bytes
        storage.replace_image(old_id, edited)
        updated = storage.get(old_id)
        check("replace 后条目 id 不变", updated is not None and updated.id == old_id)
        check("replace 后文件路径不变", updated.file_path == old_path)
        check("replace 后文件内容已更新", updated.bytes != old_bytes)
        check(
            "replace 后磁盘文件确实是新图",
            images_similar(old_path, edited) and not _same_bytes(old_path, base),
        )
        check("replace 不存在的 id → 返回 None", storage.replace_image("zzzzzz", base) is None)

        # ===== 3. 主窗口编辑合并 =====
        storage2 = StorageManager(root=tmp / "w")
        window = MainWindow(storage2)
        shot = make_shot()
        window._on_captured(shot)
        check("第 1 次捕获 → 1 条", len(storage2.list()) == 1)
        first_id = storage2.list()[0].id
        first_bytes = storage2.list()[0].bytes

        window._on_captured(edit_stroke(shot))  # 编辑第 1 步
        check("编辑第 1 步 → 仍 1 条（合并）", len(storage2.list()) == 1)
        check("合并后条目 id 不变", storage2.list()[0].id == first_id)
        check("合并后文件内容已更新", storage2.list()[0].bytes != first_bytes)
        check("合并后卡片仍在", first_id in window._cards)

        window._on_captured(edit_stroke(edit_stroke(shot)))  # 编辑第 2 步
        check("编辑第 2 步 → 仍 1 条（连续合并）", len(storage2.list()) == 1)

        window._on_captured(make_shot(color=(30, 60, 30)))  # 另一张截图
        check("不同内容截图 → 新增为第 2 条", len(storage2.list()) == 2)
        check("卡片数与条目数一致", len(window._cards) == 2)

        # ===== 4. 合并豁免 =====
        # 4a. 最新条目是手动添加的 → 不合并
        manual = storage2.save_image(make_shot(color=(30, 60, 30)), source="picker")
        window._add_card(manual)
        window._on_captured(make_shot(color=(30, 60, 30)))  # 与手动图同内容
        check("最新条目是手动添加 → 不合并，正常新增", len(storage2.list()) == 4)

        # 4b. 超出编辑合并时间窗 → 不合并
        window._on_captured(shot)
        n_before = len(storage2.list())
        window._last_capture_at = time.monotonic() - 9999  # 模拟上次捕获是很久以前
        window._on_captured(edit_stroke(shot))
        check("超出时间窗 → 不合并，正常新增", len(storage2.list()) == n_before + 1)

        # ===== 5. 置顶按钮 =====
        check("默认不置顶", not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        window.pin_btn.setChecked(True)
        check("点置顶 → WindowStaysOnTopHint 生效",
              bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        window.pin_btn.setChecked(False)
        check("再点 → 取消置顶", not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

        print(f"\n{'=' * 48}\n结果：{'全部通过' if not failures else f'{len(failures)} 项失败: {failures}'}")
        return 0 if not failures else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _same_bytes(path: str, image: Image.Image) -> bool:
    from io import BytesIO
    buf = BytesIO()
    image.save(buf, format="PNG")
    return Path(path).read_bytes() == buf.getvalue()


if __name__ == "__main__":
    sys.exit(main())
