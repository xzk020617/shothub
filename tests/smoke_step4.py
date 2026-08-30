"""第 4 步冒烟测试：托盘常驻 + 单实例 + 退出清理。

验收标准对应（Plan.md 第 7 节·第 4 步）：
1. 关窗口 → 最小化到托盘（不清理数据、进程不退）
2. 托盘退出 → 清理未保留截图
3. 单实例：二次启动唤起已有窗口而不是双开
4. 无托盘环境退化：关闭即退出并清理

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/smoke_step4.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtNetwork import QLocalServer  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from app.mainwindow import MainWindow  # noqa: E402
from app.storage import StorageManager  # noqa: E402
from app.widgets import build_tray_icon  # noqa: E402
from main import create_instance_server, notify_running_instance  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeTray:
    """模拟托盘图标：记录 showMessage / hide 调用。"""

    def __init__(self):
        self.messages: list[tuple] = []
        self.hidden = False

    def showMessage(self, *args) -> None:
        self.messages.append(args)

    def hide(self) -> None:
        self.hidden = True


def seed(storage: StorageManager, n: int) -> None:
    for i in range(n):
        storage.save_image(Image.new("RGB", (100 + i, 100), (i * 40, 10, 200)), source="clipboard")


def main() -> int:
    app = QApplication([])
    work = Path(tempfile.mkdtemp(prefix="shothub_test4_"))
    print(f"测试目录: {work}\n")

    # ===== 用例 1：托盘图标构建 =====
    icon = build_tray_icon()
    check("1.1 托盘图标非空", not icon.isNull())

    # ===== 用例 2：无托盘环境（offscreen）→ 关闭即退出并清理 =====
    check("2.0 offscreen 环境无托盘区",
          not QSystemTrayIcon.isSystemTrayAvailable())
    storage = StorageManager(root=work / "data1")
    seed(storage, 3)
    window = MainWindow(storage)
    check("2.1 无托盘区时 tray 为 None", window.tray is None)
    storage.items[0].pinned = True  # pin 一张
    storage._save_manifest()
    evt = QCloseEvent()
    window.closeEvent(evt)
    check("2.2 关闭事件被接受（真退出）", evt.isAccepted())
    check("2.3 未 pin 的 2 张被清理", len(storage.list()) == 1,
          f"实际 {len(storage.list())}")
    check("2.4 pinned 的保留", storage.list()[0].pinned)

    # ===== 用例 3：有托盘时关窗口 → 隐藏而非退出 =====
    storage2 = StorageManager(root=work / "data2")
    seed(storage2, 3)
    window2 = MainWindow(storage2)
    fake_tray = FakeTray()
    window2.tray = fake_tray  # 模拟托盘可用
    evt2 = QCloseEvent()
    window2.closeEvent(evt2)
    check("3.1 关闭事件被拒绝（不退出）", not evt2.isAccepted())
    check("3.2 数据未被清理", len(storage2.list()) == 3)
    check("3.3 首次最小化弹气泡提示", len(fake_tray.messages) == 1)
    evt3 = QCloseEvent()
    window2.closeEvent(evt3)
    check("3.4 第二次最小化不再弹气泡", len(fake_tray.messages) == 1)

    # ===== 用例 4：托盘退出 → 清理未保留 =====
    storage2.items[1].pinned = True
    storage2._save_manifest()
    window2.quit_app()  # 无运行中的事件循环，QApplication.quit() 安全
    check("4.1 退出后仅剩 pinned 的 1 张", len(storage2.list()) == 1)
    check("4.2 托盘图标被隐藏", fake_tray.hidden)
    check("4.3 _force_quit 已置位", window2._force_quit)

    # ===== 用例 5：单实例 =====
    key = "shothub_test_single"
    storage3 = StorageManager(root=work / "data3")
    window3 = MainWindow(storage3)
    server = create_instance_server(window3, key=key)
    check("5.1 实例服务器监听成功", server.isListening())

    raised = {"count": 0}
    window3.show_and_raise = lambda: raised.__setitem__("count", raised["count"] + 1)
    ok = notify_running_instance(key=key)
    app.processEvents()
    check("5.2 二次启动检测到已有实例", ok)
    check("5.3 已有实例收到唤起请求", raised["count"] == 1)

    server.close()  # 模拟实例退出：服务关闭（真实崩溃时管道随进程消失，
    # create_instance_server 内的 removeServer 会清理残留名称）
    QLocalServer.removeServer(key)
    ok2 = notify_running_instance(key=key, timeout_ms=100)
    check("5.4 实例退出后可正常新启动", not ok2)

    print()
    if failures:
        print(f"共 {len(failures)} 项失败: {failures}")
        shutil.rmtree(work, ignore_errors=True)
        return 1
    print("✅ 第 4 步全部验收用例通过")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
