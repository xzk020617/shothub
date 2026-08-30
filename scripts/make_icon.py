"""程序化生成 ShotHub 应用图标：靛蓝→紫罗兰渐变圆角方块 + 白色相框 + 环绕传输箭头。

输出：
- assets/icon_src.png  1024×1024 主图
- assets/icon.ico      多尺寸 Windows 图标（16~256）

运行：.venv/Scripts/python.exe scripts/make_icon.py
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
OUT_DIR = Path(__file__).resolve().parent.parent / "assets"


def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def make_gradient(size, c1, c2):
    """对角线渐变。"""
    base = Image.new("RGB", (size, size))
    px = base.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = lerp(c1, c2, t)
    return base


def rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def draw_glyph(img, u):
    """白色相框 + 太阳 + 山，u = 比例尺（size/1024）。"""
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)

    # 相框（圆角矩形描边）
    fw = int(44 * u)  # 描边宽
    d.rounded_rectangle(
        [280 * u, 330 * u, 744 * u, 674 * u], radius=42 * u,
        outline=white, width=fw,
    )
    # 太阳
    r = 40 * u
    d.ellipse([392 * u - r, 448 * u - r, 392 * u + r, 448 * u + r], fill=white)
    # 山
    d.polygon(
        [(330 * u, 630 * u), (472 * u, 462 * u), (566 * u, 572 * u),
         (628 * u, 500 * u), (700 * u, 630 * u)],
        fill=white,
    )


def draw_transfer_arrows(img, u):
    """上下两条环绕箭头，表达"中转/传输"。"""
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 235)
    w = int(34 * u)

    # 上弧：左上 → 右上，箭头朝右（顺时针）
    d.arc([190 * u, 150 * u, 834 * u, 794 * u], start=200, end=340,
          fill=white, width=w)
    # 下弧：右下 → 左下，箭头朝左
    d.arc([190 * u, 230 * u, 834 * u, 874 * u], start=20, end=160,
          fill=white, width=w)

    # 箭头头部：三角形，沿切线方向
    def arrowhead(cx, cy, r, angle_deg, direction, size=64 * u):
        a = math.radians(angle_deg)
        tip = (cx + r * math.cos(a), cy + r * math.sin(a))
        tang = a + math.pi / 2 * direction
        back = (tip[0] - size * math.cos(tang), tip[1] - size * math.sin(tang))
        half = size * 0.55
        p1 = (back[0] + half * math.cos(a), back[1] + half * math.sin(a))
        p2 = (back[0] - half * math.cos(a), back[1] - half * math.sin(a))
        d.polygon([tip, p1, p2], fill=white)

    cx, cy, r = 512 * u, 472 * u, 322 * u
    arrowhead(cx, cy, r, 340, direction=1)   # 上弧末端，顺时针
    arrowhead(cx, cy + 80 * u, r, 160, direction=-1)  # 下弧末端，逆时针


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    c1 = (91, 127, 255)    # #5B7FFF 靛蓝
    c2 = (139, 92, 246)    # #8B5CF6 紫罗兰

    grad = make_gradient(SIZE, c1, c2)
    mask = rounded_mask(SIZE, radius=int(SIZE * 0.23))

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), mask)

    # 顶部柔和高光
    highlight = Image.new("L", (SIZE, SIZE), 0)
    hd = ImageDraw.Draw(highlight)
    hd.ellipse([-SIZE * 0.3, -SIZE * 0.55, SIZE * 1.3, SIZE * 0.45], fill=70)
    highlight = highlight.filter(ImageFilter.GaussianBlur(60))
    white_layer = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    icon.paste(white_layer, (0, 0), Image.composite(highlight, Image.new("L", (SIZE, SIZE), 0), mask))

    u = SIZE / 1024.0
    glyph_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw_transfer_arrows(glyph_layer, u)
    draw_glyph(glyph_layer, u)
    icon = Image.alpha_composite(icon, glyph_layer)

    src = OUT_DIR / "icon_src.png"
    icon.save(src)

    ico = OUT_DIR / "icon.ico"
    icon.save(ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    # 目检用：256 预览
    icon.resize((256, 256), Image.LANCZOS).save(OUT_DIR / "icon_preview_256.png")
    print("saved:", src)
    print("saved:", ico)
    return 0


if __name__ == "__main__":
    sys.exit(main())
