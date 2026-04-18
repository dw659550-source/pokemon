#!/usr/bin/env python3
"""
切り出し領域を元画像に描画して確認するスクリプト。
使い方: python scripts/visualize_regions.py screenshot.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("pip install Pillow")
    sys.exit(1)

from capture.sprite_detector import REGION_CONFIG


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/visualize_regions.py <画像ファイル>")
        sys.exit(1)

    img = Image.open(sys.argv[1]).convert("RGB")
    w, h = img.size
    print(f"画像サイズ: {w} x {h}")

    draw = ImageDraw.Draw(img)
    cfg = REGION_CONFIG

    panel_x1 = int(w * cfg["panel_x1"])
    panel_x2 = int(w * cfg["panel_x2"])

    # 右パネル全体を青枠で表示
    draw.rectangle([panel_x1, 0, panel_x2, h], outline=(0, 100, 255), width=3)

    colors = [
        (255, 80,  80),
        (255, 160, 0),
        (80,  200, 80),
        (0,   200, 200),
        (180, 0,   255),
        (255, 255, 0),
    ]

    for idx, top_ratio in enumerate(cfg["slot_tops"]):
        y1 = int(h * top_ratio)
        y2 = int(h * (top_ratio + cfg["slot_height"]))
        slot_w = panel_x2 - panel_x1
        ix1 = panel_x1 + int(slot_w * cfg["icon_x1"])
        ix2 = panel_x1 + int(slot_w * cfg["icon_x2"])

        c = colors[idx % len(colors)]
        # スロット全体（薄枠）
        draw.rectangle([panel_x1, y1, panel_x2, y2], outline=c, width=2)
        # アイコン領域（太枠）
        draw.rectangle([ix1, y1, ix2, y2], outline=c, width=4)
        draw.text((ix1 + 4, y1 + 4), f"slot{idx+1}", fill=c)

    out = Path(sys.argv[1]).parent / "region_check.png"
    img.save(out)
    print(f"保存: {out}")
    print("region_check.png を開いて枠の位置を確認してください")


if __name__ == "__main__":
    main()
