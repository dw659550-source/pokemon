#!/usr/bin/env python3
"""
切り出し領域を元画像に描画して確認するスクリプト。

使い方:
  python scripts/visualize_regions.py screenshot.png
  python scripts/visualize_regions.py screenshot.png --dx 0.02 --dy -0.01  # X右へ2%,Y上へ1%ずらす

引数:
  --dx  X方向のオフセット調整 (正=右, 負=左)
  --dy  Y方向のオフセット調整 (正=下, 負=上)
  --dh  スロット高さ調整 (正=大きく, 負=小さく)
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("pip install Pillow")
    sys.exit(1)

from capture.sprite_detector import REGION_CONFIG


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--dx", type=float, default=0.0, help="X offset adjustment")
    parser.add_argument("--dy", type=float, default=0.0, help="Y offset adjustment")
    parser.add_argument("--dh", type=float, default=0.0, help="slot height adjustment")
    args = parser.parse_args()

    img = Image.open(args.image).convert("RGB")
    w, h = img.size
    print(f"画像サイズ: {w} x {h}")

    cfg = dict(REGION_CONFIG)
    cfg["panel_x1"] += args.dx
    cfg["panel_x2"] += args.dx
    cfg["slot_tops"] = [v + args.dy for v in cfg["slot_tops"]]
    cfg["slot_height"] += args.dh

    panel_x1 = int(w * cfg["panel_x1"])
    panel_x2 = int(w * cfg["panel_x2"])

    print(f"\n現在の設定 (オフセット dx={args.dx:+.3f} dy={args.dy:+.3f} dh={args.dh:+.3f}):")
    print(f"  panel X: {panel_x1} 〜 {panel_x2}  (比率 {cfg['panel_x1']:.3f} 〜 {cfg['panel_x2']:.3f})")

    draw = ImageDraw.Draw(img)
    draw.rectangle([panel_x1, 0, panel_x2, h], outline=(0, 100, 255), width=3)

    colors = [
        (255, 60,  60),
        (255, 160, 0),
        (80,  210, 80),
        (0,   200, 220),
        (180, 0,   255),
        (255, 230, 0),
    ]

    for idx, top_ratio in enumerate(cfg["slot_tops"]):
        y1 = int(h * top_ratio)
        y2 = int(h * (top_ratio + cfg["slot_height"]))
        slot_w = panel_x2 - panel_x1
        ix1 = panel_x1 + int(slot_w * cfg["icon_x1"])
        ix2 = panel_x1 + int(slot_w * cfg["icon_x2"])

        c = colors[idx % len(colors)]
        draw.rectangle([panel_x1, y1, panel_x2, y2], outline=c, width=2)
        draw.rectangle([ix1, y1, ix2, y2], outline=c, width=4)
        draw.text((ix1 + 4, y1 + 4), f"slot{idx+1}  y={top_ratio:.3f}", fill=c)
        print(f"  slot{idx+1}: y={y1}〜{y2}px  icon x={ix1}〜{ix2}px  (比率 {top_ratio:.3f})")

    out = Path(args.image).parent / "region_check.png"
    img.save(out)
    print(f"\n保存: {out}")


if __name__ == "__main__":
    main()
