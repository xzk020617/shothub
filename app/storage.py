"""存储层：缓存目录管理、manifest 持久化、缩略图生成。

对应 Plan.md 第 4 节数据结构：
- 图片原图存放在 <root>/cache/ 下，统一保存为 PNG
- 缩略图存放在 <root>/cache/thumbs/ 下，最长边 512px
- manifest.json 持久化所有 Item，防止崩溃丢列表
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image

THUMB_MAX_EDGE = 512
APP_DIR_NAME = "ShotHub"
VALID_SOURCES = ("clipboard", "dragin", "paste", "picker")


def default_data_root() -> Path:
    """数据根目录：%LOCALAPPDATA%\\ShotHub，取不到时回退到用户目录。"""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_DIR_NAME


@dataclass
class Item:
    id: str
    file_path: str
    thumb_path: str
    created_at: str
    source: str = "picker"
    pinned: bool = False
    width: int = 0
    height: int = 0
    bytes: int = 0
    status: str = "active"


class StorageError(Exception):
    """存储层错误（目录不可写、磁盘满等）。"""


class StorageManager:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else default_data_root()
        self.cache_dir = self.root / "cache"
        self.thumb_dir = self.cache_dir / "thumbs"
        self.manifest_path = self.root / "manifest.json"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.thumb_dir.mkdir(parents=True, exist_ok=True)
            self._check_writable()
        except OSError as exc:
            raise StorageError(f"缓存目录不可写: {self.cache_dir} ({exc})") from exc
        self.items: List[Item] = []
        self._load_manifest()

    # ---------- 内部：目录与 manifest ----------

    def _check_writable(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".probe")
        os.close(fd)
        os.unlink(tmp)

    def _load_manifest(self) -> None:
        if not self.manifest_path.exists():
            self.items = []
            return
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self.items = [Item(**raw) for raw in data.get("items", [])]
        except (json.JSONDecodeError, TypeError, KeyError):
            # manifest 损坏时备份后重置，不阻塞启动
            self.manifest_path.rename(
                self.manifest_path.with_suffix(".json.broken")
            )
            self.items = []

    def _save_manifest(self) -> None:
        payload = {"items": [asdict(it) for it in self.items]}
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.manifest_path)  # 原子替换，防写入中断损坏

    # ---------- 入库 ----------

    def save_image(self, image: Image.Image, source: str = "clipboard") -> Item:
        """从 PIL Image 入库（剪贴板/粘贴路径）。"""
        if source not in VALID_SOURCES:
            source = "clipboard"
        item_id = uuid.uuid4().hex[:12]
        file_path = self.cache_dir / self._make_name(item_id)
        try:
            image.save(file_path, format="PNG")
        except OSError as exc:
            raise StorageError(f"图片写入失败: {exc}") from exc
        return self._register(item_id, file_path, image.size, source)

    def save_from_file(self, src_path: Path, source: str = "picker") -> Item:
        """从已有图片文件入库（文件选择/拖入路径），统一转 PNG。"""
        src_path = Path(src_path)
        if source not in VALID_SOURCES:
            source = "picker"
        try:
            with Image.open(src_path) as im:
                im.load()
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                return self.save_image(im, source=source)
        except Image.UnidentifiedImageError as exc:
            raise StorageError(f"不支持的图片格式: {src_path.name}") from exc

    def _make_name(self, item_id: str) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return f"{stamp}_{item_id}.png"

    def _register(
        self, item_id: str, file_path: Path, size: tuple[int, int], source: str
    ) -> Item:
        thumb_path = self.thumb_dir / f"{item_id}_{THUMB_MAX_EDGE}.png"
        self._make_thumb(file_path, thumb_path)
        item = Item(
            id=item_id,
            file_path=str(file_path),
            thumb_path=str(thumb_path),
            created_at=datetime.now().isoformat(timespec="seconds"),
            source=source,
            pinned=False,
            width=size[0],
            height=size[1],
            bytes=file_path.stat().st_size,
            status="active",
        )
        self.items.insert(0, item)  # 新图在上
        self._save_manifest()
        return item

    @staticmethod
    def _make_thumb(file_path: Path, thumb_path: Path) -> None:
        with Image.open(file_path) as im:
            im.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            im.save(thumb_path, format="PNG")

    # ---------- 查询 ----------

    def list(self) -> List[Item]:
        return list(self.items)

    def get(self, item_id: str) -> Optional[Item]:
        return next((it for it in self.items if it.id == item_id), None)

    def total_bytes(self) -> int:
        return sum(it.bytes for it in self.items)

    # ---------- 删除 ----------

    def delete(self, item_id: str) -> bool:
        """删除单张：移除 manifest 记录并删除磁盘文件。"""
        item = self.get(item_id)
        if item is None:
            return False
        self.items = [it for it in self.items if it.id != item_id]
        self._remove_files(item)
        self._save_manifest()
        return True

    def clear(self, include_pinned: bool = True) -> int:
        """清空。返回删除数量。"""
        targets = [
            it for it in self.items if include_pinned or not it.pinned
        ]
        for it in targets:
            self._remove_files(it)
        removed = len(targets)
        self.items = [it for it in self.items if it not in targets]
        self._save_manifest()
        return removed

    @staticmethod
    def _remove_files(item: Item) -> None:
        for p in (item.file_path, item.thumb_path):
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass  # 文件被占用则跳过，留给 cleanup_orphans

    # ---------- 退出/崩溃清理 ----------

    def cleanup_unpinned(self) -> int:
        """退出时调用：清除所有未保留的截图。"""
        return self.clear(include_pinned=False)

    def cleanup_orphans(self) -> int:
        """启动时调用：清除缓存目录中 manifest 未记录的残留文件。"""
        known = {str(Path(it.file_path).resolve()) for it in self.items}
        known |= {str(Path(it.thumb_path).resolve()) for it in self.items}
        removed = 0
        for p in self.cache_dir.rglob("*.png"):
            if str(p.resolve()) not in known:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
