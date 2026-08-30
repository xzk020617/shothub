"""真实剪贴板写入验证（会覆盖当前系统剪贴板一次）。

走真实 win32 写入路径，再用 win32 API 读回，确认：
- 剪贴板同时存在 CF_DIB 与 "PNG" 两种格式
- PNG 字节与原文件一致，DIB 可还原为原尺寸图
"""
import sys
import time
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import win32clipboard  # noqa: E402
import win32con  # noqa: E402
from PIL import Image  # noqa: E402

from app.clipboard_hub import ClipboardHub, png_to_dib_bytes  # noqa: E402

work = Path(__file__).resolve().parent.parent / "tests" / "_tmp_realclip"
work.mkdir(exist_ok=True)
png_path = work / "sample.png"
Image.new("RGB", (640, 400), (30, 144, 255)).save(png_path)

hub = ClipboardHub.__new__(ClipboardHub)  # 不需要 Qt 事件循环，直接调写路径
png_bytes = png_path.read_bytes()
hub._write_os_clipboard(png_bytes, png_to_dib_bytes(png_bytes))

time.sleep(0.1)
win32clipboard.OpenClipboard()
try:
    png_fmt = win32clipboard.RegisterClipboardFormat("PNG")
    has_dib = win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB)
    has_png = win32clipboard.IsClipboardFormatAvailable(png_fmt)
    got_png = win32clipboard.GetClipboardData(png_fmt) if has_png else b""
    got_dib = win32clipboard.GetClipboardData(win32con.CF_DIB) if has_dib else b""
finally:
    win32clipboard.CloseClipboard()

ok_dib_size = False
if got_dib:
    with Image.open(BytesIO(b"BM" + b"\x00" * 12 + bytes(got_dib))) as bmp:
        ok_dib_size = bmp.size == (640, 400)

print("CF_DIB 可用:", has_dib)
print("PNG 格式可用:", has_png)
print("PNG 字节一致:", bytes(got_png) == png_bytes)
print("DIB 尺寸还原:", ok_dib_size)
ok = has_dib and has_png and bytes(got_png) == png_bytes and ok_dib_size
print("✅ 真实剪贴板写入验证通过" if ok else "❌ 验证失败")
png_path.unlink()
work.rmdir()
sys.exit(0 if ok else 1)
