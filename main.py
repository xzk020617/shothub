"""截图中转站入口：单实例 + 主窗口。

运行方式（在项目根目录）：
    .venv\\Scripts\\python.exe main.py

单实例：通过 QLocalServer/QLocalSocket 实现。
- 后启动的实例连接已有实例的本地 socket，通知其唤起窗口后自己退出
- 已有实例收到连接后 show_and_raise 主窗口
"""
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from app.mainwindow import MainWindow
from app.storage import StorageManager, StorageError

INSTANCE_KEY = "shothub_single_instance"


def notify_running_instance(key: str = INSTANCE_KEY, timeout_ms: int = 300) -> bool:
    """尝试联系已运行的实例。成功返回 True（表示本实例应直接退出）。"""
    socket = QLocalSocket()
    socket.connectToServer(key)
    if socket.waitForConnected(timeout_ms):
        socket.write(b"raise")
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True
    return False


def create_instance_server(window: MainWindow, key: str = INSTANCE_KEY) -> QLocalServer:
    """监听后续实例的唤起请求。server 需保持引用防止被 GC。"""
    server = QLocalServer(window)  # 挂在窗口上，随窗口生命周期
    QLocalServer.removeServer(key)  # 清理上次异常退出残留的 socket 文件
    server.listen(key)

    def _on_new_connection() -> None:
        sock = server.nextPendingConnection()
        if sock is not None:
            sock.deleteLater()
        window.show_and_raise()

    server.newConnection.connect(_on_new_connection)
    return server


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ShotHub")
    app.setOrganizationName("ShotHub")
    app.setQuitOnLastWindowClosed(False)  # 关窗口 = 进托盘，不退出进程

    if notify_running_instance():
        return 0  # 已有实例在运行：唤起它，本实例退出

    try:
        storage = StorageManager()
    except StorageError as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1

    window = MainWindow(storage)
    create_instance_server(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
