"""截图中转站入口。

运行方式（在项目根目录）：
    .venv\\Scripts\\python.exe main.py
"""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.mainwindow import MainWindow
from app.storage import StorageManager, StorageError


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ShotHub")
    app.setOrganizationName("ShotHub")
    try:
        storage = StorageManager()
    except StorageError as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    window = MainWindow(storage)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
