"""UI 组件：流式布局、缩略图卡片、空状态、托盘图标。

对应 Plan.md 第 3 节中的 ThumbnailGrid / ThumbnailCard / EmptyState。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

CARD_WIDTH = 176
THUMB_BOX = 160
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def build_file_mimedata(file_path: str) -> QMimeData:
    """构造"拖出为文件"的 mime 数据（缓存文件真实存在，天然支持 CF_HDROP）。"""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(file_path)])
    return mime


def build_tray_icon(size: int = 64) -> QIcon:
    """程序化绘制托盘图标：蓝底圆角 + 白色"照片"图形（纯几何，不依赖字体）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 蓝底圆角方块
    painter.setBrush(QColor("#6d8dff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.22, size * 0.22)

    white = QColor("white")
    u = size / 64.0  # 以 64px 为基准的比例尺

    # 相框
    pen = QPen(white)
    pen.setWidthF(4.5 * u)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(
        QRectF(14 * u, 16 * u, 36 * u, 32 * u), 3 * u, 3 * u
    )
    # 太阳（左上角小圆点）
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(white)
    painter.drawEllipse(QPointF(23 * u, 25 * u), 3.5 * u, 3.5 * u)
    # 山（底部三角）
    mountain = QPolygonF(
        [QPointF(18 * u, 44 * u), QPointF(30 * u, 30 * u),
         QPointF(38 * u, 40 * u), QPointF(43 * u, 34 * u), QPointF(48 * u, 44 * u)]
    )
    painter.drawPolygon(mountain)

    painter.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    """应用图标：优先用 assets/icon.ico（源码目录或 PyInstaller 包内），
    缺失时回退到程序化几何图标。"""
    candidates = []
    if getattr(sys, "frozen", False):  # PyInstaller 打包后的运行环境
        candidates.append(Path(sys._MEIPASS) / "assets" / "icon.ico")
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / "icon.ico")
    for p in candidates:
        if p.exists():
            icon = QIcon(str(p))
            if not icon.isNull():
                return icon
    return build_tray_icon()


class FlowLayout(QLayout):
    """自动换行的流式布局（Qt 官方 FlowLayout 示例的 PySide6 移植）。"""

    def __init__(self, parent=None, margin: int = 12, spacing: int = 12):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def __del__(self):  # pragma: no cover - 防御性
        while self._items:
            self.takeAt(0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            wid = item.widget()
            space_x = self.spacing()
            space_y = self.spacing()
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(
                    QRect(QPoint(x, y), item.sizeHint())
                )
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + m.bottom()


class ThumbnailCard(QFrame):
    """单张截图卡片：缩略图 + 时间/尺寸 + hover 删除按钮。"""

    deleteRequested = Signal(str)
    copyRequested = Signal(str)
    activated = Signal(str)  # 双击 = 复制到剪贴板

    def __init__(self, item, parent: QWidget | None = None):
        super().__init__(parent)
        self.item_id: str = item.id
        self.file_path: str = item.file_path
        self._drag_start: QPoint | None = None
        self.setFixedWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "ThumbnailCard { background: #ffffff; border: 1px solid #e2e2e8;"
            " border-radius: 10px; }"
            "ThumbnailCard:hover { border-color: #6d8dff; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._image_label = QLabel()
        self._image_label.setFixedSize(THUMB_BOX, THUMB_BOX)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: #f4f4f7; border-radius: 6px;")
        pixmap = QPixmap(item.thumb_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                THUMB_BOX,
                THUMB_BOX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image_label.setPixmap(scaled)
        layout.addWidget(self._image_label)

        info = QLabel(f"{item.created_at[11:]} · {item.width}×{item.height}")
        info.setStyleSheet("color: #888; font-size: 11px; border: none;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        self._delete_btn = QToolButton(self)
        self._delete_btn.setText("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setStyleSheet(
            "QToolButton { background: rgba(255,80,80,230); color: white;"
            " border: none; border-radius: 12px; font-weight: bold; }"
            "QToolButton:hover { background: #e03030; }"
        )
        self._delete_btn.move(CARD_WIDTH - 30, 6)
        self._delete_btn.hide()
        self._delete_btn.clicked.connect(
            lambda: self.deleteRequested.emit(self.item_id)
        )

        self._copy_btn = QToolButton(self)
        self._copy_btn.setText("📋")
        self._copy_btn.setFixedSize(24, 24)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setToolTip("复制到剪贴板（双击卡片同效）")
        self._copy_btn.setStyleSheet(
            "QToolButton { background: rgba(80,120,255,230); color: white;"
            " border: none; border-radius: 12px; }"
            "QToolButton:hover { background: #4060e0; }"
        )
        self._copy_btn.move(6, 6)
        self._copy_btn.hide()
        self._copy_btn.clicked.connect(
            lambda: self.copyRequested.emit(self.item_id)
        )

    def enterEvent(self, event) -> None:
        self._delete_btn.show()
        self._delete_btn.raise_()
        self._copy_btn.show()
        self._copy_btn.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._delete_btn.hide()
        self._copy_btn.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """按住拖动超过系统阈值 → 以文件形式拖出（可拖进资源管理器/微信等）。"""
        if (
            self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_start).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._drag_start = None
            self._start_drag()
        super().mouseMoveEvent(event)

    def _start_drag(self) -> None:
        drag = QDrag(self)
        drag.setMimeData(build_file_mimedata(self.file_path))
        pixmap = self._image_label.pixmap()
        if not pixmap.isNull():
            drag.setPixmap(
                pixmap.scaled(
                    96, 96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            drag.setHotSpot(QPoint(48, 48))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseDoubleClickEvent(self, event) -> None:
        self.activated.emit(self.item_id)
        super().mouseDoubleClickEvent(event)


class EmptyState(QWidget):
    """空状态提示。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("🖼️")
        icon.setStyleSheet("font-size: 48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("还没有截图\n\n用 Win+Shift+S 截图，会自动出现在这里\n也可以点击右上角「添加」或直接把图片拖进来")
        text.setStyleSheet("color: #999; font-size: 14px; line-height: 1.6;")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(text)
