"""第 1 步冒烟测试（离屏模式，无需真实显示器）。

验收标准对应：
1. 添加 10 张不同尺寸图 → 网格显示 10 张缩略图和时间
2. 删除某张 → 列表与磁盘文件同时消失
3. "杀进程重启"（重建 StorageManager）→ 列表仍在（manifest 生效）
4. 退出清理 → 未 pin 的截图被清除
5. 崩溃残留清理（orphans）

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/smoke_step1.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from app.mainwindow import MainWindow  # noqa: E402
from app.storage import StorageManager  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def make_images(folder: Path, n: int = 10) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        p = folder / f"src_{i}.png"
        Image.new("RGB", (200 + i * 37, 150 + i * 53), (i * 25 % 255, 80, 160)).save(p)
        paths.append(p)
    return paths


def main() -> int:
    app = QApplication([])
    work = Path(tempfile.mkdtemp(prefix="shothub_test_"))
    src_dir = work / "incoming"
    data_root = work / "data"
    print(f"测试目录: {work}\n")

    # ===== 用例 1：添加 10 张不同尺寸图 =====
    storage = StorageManager(root=data_root)
    window = MainWindow(storage)
    paths = make_images(src_dir, 10)

    # 模拟文件对话框选择全部 10 张
    QFileDialog.getOpenFileNames = staticmethod(
        lambda *a, **k: ([str(p) for p in paths], "")
    )
    window._on_add()

    items = storage.list()
    check("1.1 入库数量为 10", len(items) == 10, f"实际 {len(items)}")
    check("1.2 网格卡片为 10 张", len(window._cards) == 10)
    check("1.3 网格显示（非空状态）", window.stack.currentIndex() == 1)
    check("1.4 计数标签正确", "10 张" in window.count_label.text(),
          window.count_label.text())
    check("1.5 每张都生成了缩略图文件",
          all(Path(it.thumb_path).exists() for it in items))
    check("1.6 每张都记录了原始尺寸",
          all(it.width > 0 and it.height > 0 for it in items))
    check("1.7 新图在上（最后添加的排第一）",
          items[0].width == 200 + 9 * 37, f"首图宽 {items[0].width}")
    check("1.8 清空按钮可用", window.clear_btn.isEnabled())

    # ===== 用例 2：删除单张 → 列表与磁盘同步消失 =====
    victim = items[3]
    victim_file = Path(victim.file_path)
    victim_thumb = Path(victim.thumb_path)
    window._on_delete(victim.id)
    check("2.1 manifest 剩 9 条", len(storage.list()) == 9)
    check("2.2 网格剩 9 张卡片", len(window._cards) == 9)
    check("2.3 原图文件已删除", not victim_file.exists())
    check("2.4 缩略图文件已删除", not victim_thumb.exists())

    # ===== 用例 3：模拟"杀进程重启" → manifest 持久化 =====
    # 注意：不调用 window.close()（会触发退出清理），直接新建实例模拟重启
    window.hide()
    storage2 = StorageManager(root=data_root)
    window2 = MainWindow(storage2)
    check("3.1 重启后列表仍为 9 条", len(storage2.list()) == 9)
    check("3.2 重启后网格恢复 9 张卡片", len(window2._cards) == 9)
    check("3.3 重启后非空状态", window2.stack.currentIndex() == 1)

    # ===== 用例 4：崩溃残留清理 =====
    orphan = storage2.cache_dir / "orphan_crash.png"
    Image.new("RGB", (10, 10)).save(orphan)
    storage3 = StorageManager(root=data_root)
    removed = storage3.cleanup_orphans()
    check("4.1 残留文件被清理", removed >= 1 and not orphan.exists())

    # ===== 用例 5：退出清理（未 pin 的全部清除）=====
    storage3.items[0].pinned = True  # 模拟用户 pin 了一张
    pinned_path = Path(storage3.items[0].file_path)
    storage3._save_manifest()
    window3 = MainWindow(storage3)
    window3.close()  # closeEvent 触发 cleanup_unpinned
    remaining = StorageManager(root=data_root).list()
    check("5.1 退出后仅剩 pinned 的 1 张", len(remaining) == 1,
          f"实际 {len(remaining)}")
    check("5.2 pinned 文件仍在", pinned_path.exists())

    # ===== 用例 6：空状态 =====
    storage3.clear()
    window4 = MainWindow(storage3)
    check("6.1 清空后显示空状态", window4.stack.currentIndex() == 0)
    check("6.2 清空按钮置灰", not window4.clear_btn.isEnabled())

    print()
    if failures:
        print(f"共 {len(failures)} 项失败: {failures}")
        shutil.rmtree(work, ignore_errors=True)
        return 1
    print("✅ 第 1 步全部验收用例通过")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
