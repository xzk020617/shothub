"""主窗口：顶栏 + 缩略图网格 + 空状态。

第 1 步范围：手动添加（文件选择）、单张删除、一键清空、退出清理。
剪贴板监听（第 2 步）、拖拽（第 3 步）、托盘（第 4 步）后续接入。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from .clipboard_hub import ClipboardError, ClipboardHub
from .storage import StorageManager, StorageError
from .widgets import EmptyState, FlowLayout, ThumbnailCard

IMAGE_FILTER = "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*)"


def format_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes}B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.0f}KB"
    return f"{nbytes / 1024 / 1024:.1f}MB"


class MainWindow(QMainWindow):
    def __init__(self, storage: StorageManager, hub: ClipboardHub | None = None, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.hub = hub or ClipboardHub(parent=self)
        self._cards: dict[str, ThumbnailCard] = {}

        self.setWindowTitle("截图中转站")
        self.resize(760, 560)
        self.setMinimumSize(420, 320)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 顶栏 ----------
        topbar = QWidget()
        topbar.setStyleSheet("background: #f7f7fa; border-bottom: 1px solid #e5e5ea;")
        bar = QHBoxLayout(topbar)
        bar.setContentsMargins(16, 10, 16, 10)

        title = QLabel("📋 截图中转站")
        title.setStyleSheet("font-size: 15px; font-weight: bold; border: none;")
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #888; font-size: 12px; border: none;")
        bar.addWidget(title)
        bar.addWidget(self.count_label)
        bar.addStretch(1)

        self.add_btn = QPushButton("＋ 添加")
        self.add_btn.clicked.connect(self._on_add)
        self.clear_btn = QPushButton("🗑 清空全部")
        self.clear_btn.clicked.connect(self._on_clear)
        for btn in (self.add_btn, self.clear_btn):
            btn.setStyleSheet(
                "QPushButton { padding: 6px 14px; border: 1px solid #d0d0d8;"
                " border-radius: 6px; background: white; }"
                "QPushButton:hover { background: #eef1ff; border-color: #6d8dff; }"
                "QPushButton:disabled { color: #bbb; background: #f5f5f5; }"
            )
            bar.addWidget(btn)
        root.addWidget(topbar)

        # ---------- 内容区：空状态 / 网格 ----------
        self.stack = QStackedLayout()
        root.addLayout(self.stack, 1)

        self.empty_state = EmptyState()
        self.stack.addWidget(self.empty_state)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #fafafc; }")
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host)
        scroll.setWidget(self.grid_host)
        self.stack.addWidget(scroll)

        # ---------- 初始数据 ----------
        self.storage.cleanup_orphans()
        for item in self.storage.list():
            self._add_card(item)
        self._refresh_state()

        # ---------- 剪贴板监听 ----------
        self.hub.imageCaptured.connect(self._on_captured)
        self.hub.clipboardError.connect(
            lambda msg: self.statusBar().showMessage(msg, 4000)
        )
        self.hub.start()

    # ---------- 卡片管理 ----------

    def _add_card(self, item) -> None:
        card = ThumbnailCard(item)
        card.deleteRequested.connect(self._on_delete)
        card.copyRequested.connect(self._on_activated)
        card.activated.connect(self._on_activated)
        self._cards[item.id] = card
        self.grid.addWidget(card)  # 新卡片排最前：重排顺序在 _reorder 处理
        self._reorder_cards()

    def _reorder_cards(self) -> None:
        """按 storage.items 的顺序（新图在上）重排网格。"""
        for item in self.storage.list():
            card = self._cards.get(item.id)
            if card is not None:
                self.grid.removeWidget(card)
                self.grid.addWidget(card)

    def _remove_card(self, item_id: str) -> None:
        card = self._cards.pop(item_id, None)
        if card is not None:
            self.grid.removeWidget(card)
            card.deleteLater()

    def _refresh_state(self) -> None:
        items = self.storage.list()
        has_items = bool(items)
        self.stack.setCurrentIndex(1 if has_items else 0)
        self.clear_btn.setEnabled(has_items)
        self.count_label.setText(
            f"{len(items)} 张 · {format_size(self.storage.total_bytes())}"
            if has_items
            else ""
        )

    # ---------- 槽：添加 / 删除 / 清空 ----------

    def _on_add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", IMAGE_FILTER
        )
        if not paths:
            return
        failed: list[str] = []
        for p in paths:  # 每次插入列表头部，最后添加的排在最前
            try:
                item = self.storage.save_from_file(Path(p), source="picker")
                self._add_card(item)
            except StorageError as exc:
                failed.append(str(exc))
        self._refresh_state()
        if failed:
            QMessageBox.warning(self, "部分图片添加失败", "\n".join(failed))

    def _on_delete(self, item_id: str) -> None:
        if self.storage.delete(item_id):
            self._remove_card(item_id)
            self._refresh_state()

    def _on_clear(self) -> None:
        count = len(self.storage.list())
        if count == 0:
            return
        ret = QMessageBox.question(
            self,
            "清空全部",
            f"确定要删除全部 {count} 张截图吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            for item in self.storage.list():
                self._remove_card(item.id)
            self.storage.clear()
            self._refresh_state()

    def _on_captured(self, image) -> None:
        """剪贴板捕获到新截图：入库并置顶显示。"""
        try:
            item = self.storage.save_image(image, source="clipboard")
        except StorageError as exc:
            self.statusBar().showMessage(f"截图入库失败：{exc}", 4000)
            return
        self._add_card(item)
        self._refresh_state()
        self.statusBar().showMessage(
            f"已捕获截图 {item.width}×{item.height}", 2500
        )

    def _on_activated(self, item_id: str) -> None:
        """双击/点复制按钮：把原图写回剪贴板（CF_DIB + PNG 双格式）。"""
        item = self.storage.get(item_id)
        if item is None:
            return
        try:
            self.hub.put_image(item.file_path)
            self.statusBar().showMessage(
                f"已复制 {item.width}×{item.height}，可直接 Ctrl+V 粘贴", 3000
            )
        except (ClipboardError, OSError) as exc:
            self.statusBar().showMessage(f"复制失败：{exc}", 4000)

    # ---------- 退出清理 ----------

    def closeEvent(self, event) -> None:
        # 托盘常驻在第 4 步接入；当前关闭即退出，清理未保留截图
        self.storage.cleanup_unpinned()
        super().closeEvent(event)
