#!/usr/bin/env python3
"""
切り出し領域を元画像に描画して確認するスクリプト。
赤タイルを色で自動検出し、枠を描画します。

使い方: python scripts/visualize_regions.py screenshot.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("pip install Pillow")
    sys.exit(1)

try:
    import cv2, numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from capture.sprite_detector import auto_detect_slots, REGION_CONFIG


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/visualize_regions.py <画像ファイル>")
        sys.exit(1)

    img = Image.open(sys.argv[1]).convert("RGB")
    w, h = img.size
    print(f"画像サイズ: {w} x {h}")

    cfg = REGION_CONFIG
    draw = ImageDraw.Draw(img)

    # パネル範囲（青枠）
    px1 = int(w * cfg["panel_x1"])
    px2 = int(w * cfg["panel_x2"])
    draw.rectangle([px1, 0, px2, h], outline=(0, 100, 255), width=3)

    colors = [(255,60,60),(255,160,0),(80,210,80),(0,200,220),(180,0,255),(255,230,0)]

    # 自動検出を試みる
    slots = auto_detect_slots(img, panel_x1=cfg["panel_x1"], panel_x2=cfg["panel_x2"])

    if slots:
        print(f"\n✅ 赤タイル自動検出成功: {len(slots)} スロット")
        for idx, (ix1, iy1, ix2, iy2) in enumerate(slots):
            c = colors[idx % len(colors)]
            # タイル全体の外枠
            tile_x2 = px2
            draw.rectangle([px1, iy1, tile_x2, iy2], outline=c, width=2)
            # アイコン領域（太枠）
            draw.rectangle([ix1, iy1, ix2, iy2], outline=c, width=4)
            draw.text((ix1 + 4, iy1 + 4), f"slot{idx+1}", fill=c)
            print(f"  slot{idx+1}: y={iy1}〜{iy2}px  icon x={ix1}〜{ix2}px")

        # 個別スロット画像を保存
        out_dir = Path(sys.argv[1]).parent / "sprite_debug"
        out_dir.mkdir(exist_ok=True)
        for idx, (ix1, iy1, ix2, iy2) in enumerate(slots):
            icon = img.crop((ix1, iy1, ix2, iy2))
            icon.save(out_dir / f"slot{idx+1}.png")
        print(f"\n切り出し画像: {out_dir}/slot1.png 〜 slot{len(slots)}.png")
    else:
        print("\n⚠ 自動検出失敗 → REGION_CONFIG フォールバックで表示")
        for idx, top in enumerate(cfg["slot_tops"]):
            y1 = int(h * top)
            y2 = int(h * (top + cfg["slot_height"]))
            slot_w = px2 - px1
            ix1 = px1 + int(slot_w * cfg["icon_x1"])
            ix2 = px1 + int(slot_w * cfg["icon_x2"])
            c = colors[idx % len(colors)]
            draw.rectangle([px1, y1, px2, y2], outline=c, width=2)
            draw.rectangle([ix1, y1, ix2, y2], outline=c, width=4)
            draw.text((ix1 + 4, y1 + 4), f"slot{idx+1}", fill=c)

    out = Path(sys.argv[1]).parent / "region_check.png"
    img.save(out)
    print(f"\n保存: {out}")


if __name__ == "__main__":
    main()
