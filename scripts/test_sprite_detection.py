#!/usr/bin/env python3
"""
スプライト検出テストスクリプト。

【使い方】
1. pip install opencv-python Pillow
2. スクリーンショットを pokemon フォルダに保存（例: screenshot.png）
3. python scripts/test_sprite_detection.py screenshot.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image
except ImportError:
    print("Pillow が必要です: pip install Pillow")
    sys.exit(1)

try:
    import cv2
except ImportError:
    print("OpenCV が必要です: pip install opencv-python")
    sys.exit(1)

from capture.sprite_detector import SpriteDatabase, detect_opponent_team, REGION_CONFIG


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/test_sprite_detection.py <画像ファイル>")
        print("例:    python scripts/test_sprite_detection.py screenshot.png")
        sys.exit(1)

    img_path = Path(sys.argv[1])
    if not img_path.exists():
        print(f"ファイルが見つかりません: {img_path}")
        sys.exit(1)

    img = Image.open(img_path)
    w, h = img.size
    print(f"画像サイズ: {w} x {h}")

    # 切り出し座標を確認表示
    print("\n右パネル座標 (REGION_CONFIG):")
    print(f"  X: {int(w * REGION_CONFIG['panel_x1'])} 〜 {int(w * REGION_CONFIG['panel_x2'])}")
    for idx, top in enumerate(REGION_CONFIG["slot_tops"]):
        y1 = int(h * top)
        y2 = int(h * (top + REGION_CONFIG["slot_height"]))
        print(f"  スロット{idx+1}: Y {y1} 〜 {y2}")

    print("\nスプライトデータベース構築中...")
    db = SpriteDatabase()

    print("\n相手チーム検出中...")
    results = detect_opponent_team(img, db)

    print(f"\n検出結果: {len(results)} 体")
    print("-" * 50)
    for i, (key, name_ja, score) in enumerate(results, 1):
        bar = "█" * int(score * 30)
        label = "✅ 高" if score >= 0.7 else ("⚠ 中" if score >= 0.4 else "❌ 低")
        print(f"  {i}. {name_ja:12s}  {bar:<30s} {score*100:.1f}%  {label}")

    # 切り出したアイコンを保存（確認用）
    out_dir = Path(img_path).parent / "sprite_debug"
    out_dir.mkdir(exist_ok=True)
    cfg = REGION_CONFIG
    for idx, top in enumerate(cfg["slot_tops"]):
        x1 = int(w * cfg["panel_x1"])
        x2 = int(w * cfg["panel_x2"])
        y1 = int(h * top)
        y2 = int(h * (top + cfg["slot_height"]))
        slot_w = x2 - x1
        ix1 = x1 + int(slot_w * cfg["icon_x1"])
        ix2 = x1 + int(slot_w * cfg["icon_x2"])
        icon = img.crop((ix1, y1, ix2, y2))
        icon.save(out_dir / f"slot{idx+1}.png")
    print(f"\n切り出し画像を {out_dir} に保存しました（ズレ確認用）")


if __name__ == "__main__":
    main()
