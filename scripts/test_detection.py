"""
diagnose_full.png を使って detect_opponent_team() の結果を確認するテストスクリプト。
GUIを起動しなくても相手チームの検出結果（ポケモン名）を確認できます。

使い方:
  python scripts/test_detection.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np
from PIL import Image
from capture.sprite_detector import (
    SpriteDatabase, REGION_CONFIG,
    _pil_to_bgr, _remove_bg, compute_phash, phash_score,
    detect_slot_types,
)

FULL_PNG = Path("diagnose_full.png")
DEBUG_DIR = Path("debug_sprites")

# 実際に出ているポケモン（正解）
CORRECT = [
    "scizor",
    "tyranitar",
    "excadrill",
    "milotic",
    "incineroar",
    "archaludon",
]


def main():
    if not FULL_PNG.exists():
        print(f"Error: {FULL_PNG} が見つかりません。")
        sys.exit(1)

    DEBUG_DIR.mkdir(exist_ok=True)

    print("スプライトDB を読み込み中...")
    db = SpriteDatabase()
    print(f"  登録ポケモン数: {len(db._phashes)} 体\n")

    img = Image.open(FULL_PNG)
    W, H = img.size
    cfg = REGION_CONFIG
    panel_x1 = int(W * cfg["panel_x1"])
    panel_x2 = int(W * cfg["panel_x2"])
    slot_w   = panel_x2 - panel_x1

    for i, (top, correct_key) in enumerate(zip(cfg["slot_tops"], CORRECT)):
        iy1 = int(H * top)
        iy2 = int(H * (top + cfg["slot_height"]))

        # スプライトアイコン領域
        ix1 = panel_x1 + int(slot_w * cfg["icon_x1"])
        ix2 = panel_x1 + int(slot_w * cfg["icon_x2"])
        icon_img = img.crop((ix1, iy1, ix2, iy2))
        icon_bgr = _pil_to_bgr(icon_img)
        icon_img.save(DEBUG_DIR / f"slot{i+1}_raw.png")
        _remove_bg(icon_bgr).save(DEBUG_DIR / f"slot{i+1}_clean.png")

        # タイプアイコン領域
        ty2 = int(H * (top + cfg["slot_height"] * 0.60))
        type_img = img.crop((panel_x1, iy1, panel_x2, ty2))
        type_bgr = _pil_to_bgr(type_img)
        detected_types = detect_slot_types(type_bgr)

        # タイプ絞り込み
        if detected_types:
            type_set = set(detected_types)
            candidates = {
                k for k, t in db._types.items()
                if k in db._phashes and type_set.intersection(t)
            }
            if len(candidates) < 5:
                candidates = set(db._phashes.keys())
                note = "（候補少→全件）"
            else:
                note = f"（{len(candidates)}体に絞り込み）"
        else:
            candidates = set(db._phashes.keys())
            note = "（タイプ未検出→全件）"

        # pHash計算
        query_hash = compute_phash(_remove_bg(icon_bgr))
        scores = [
            (k, phash_score(query_hash, db._phashes[k]))
            for k in candidates
        ]
        scores.sort(key=lambda x: x[1], reverse=True)

        # 正解のランクとスコア
        correct_name = db._names.get(correct_key, correct_key)
        correct_score = None
        correct_rank  = None
        for rank, (k, s) in enumerate(scores, 1):
            if k == correct_key:
                correct_score = s
                correct_rank  = rank
                break

        judge = "✅" if correct_rank == 1 else f"❌ ({correct_rank}位)" if correct_rank else "❌ (圏外)"
        print(f"Slot {i+1}: タイプ={detected_types} {note}")
        print(f"  正解: {correct_name} ({correct_key})  スコア={correct_score}  {judge}")
        print(f"  1位:  {db._names.get(scores[0][0], scores[0][0])} ({scores[0][0]})  スコア={scores[0][1]:.3f}")
        print()


if __name__ == "__main__":
    main()
