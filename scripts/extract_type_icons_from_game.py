"""
diagnose_full.png から実際のゲーム内タイプアイコンを切り出し、
data/type_icons/ のテンプレートを上書きするスクリプト。

アイコンの実測y位置から切り出すため、背景のない「クリーンな」テンプレートを生成します。

使い方:
  python scripts/extract_type_icons_from_game.py

前提: scripts/diagnose_type_icons.py を実行済みで
      diagnose_full.png が pokemon/ フォルダにあること。
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
from capture.sprite_detector import REGION_CONFIG

# ── アイコン切り出し仕様 ─────────────────────────────────────────────────
# (slot_idx, zone_idx, type_name, y_offset)
#   slot_idx : 0始まり (Slot1=0 … Slot6=5)
#   zone_idx : 0=Zone1(第1アイコン), 1=Zone2(第2アイコン)
#   type_name: 保存するタイプ名（ファイル名になる）
#   y_offset : スロット上端からアイコン上端までのピクセル数（実測値）
#              ← この値だけずらして切り出すことで背景なしのテンプレートを作成
# ─────────────────────────────────────────────────────────────────────────
ICON_SPECS = [
    # ══════════════════════════════════════════════════════════════════
    # 【このバトル構成（バトル3）】
    #   Slot 1: はがね・むし   Slot 2: いわ・あく
    #   Slot 3: じめん・はがね Slot 4: みず（単タイプ）
    #   Slot 5: ほのお・あく   Slot 6: はがね・ドラゴン
    #
    # y_offset: Slot1≈28 Slot2≈17 Slot3≈8 Slot4≈0 Slot5≈0 Slot6≈0
    # ──────────────────────────────────────────────────────────────────
    # steel: Zone1/Zone2 で視覚が異なるため別テンプレートを使用
    #   steel    = Slot6 Zone1 (y=0) …「下段 Zone1」代表
    #   steel_z1 = Slot1 Zone1 (y=28)…「上段 Zone1」代表（→ steel に正規化）
    #   steel_z2 = Slot3 Zone2 (y=8) …「Zone2 全般」代表（→ steel に正規化）
    # fire: 古いテンプレートが現在の画面と合わないため Slot5 から再取得
    # ══════════════════════════════════════════════════════════════════
    (0, 0, "steel_z1", 28),  # Slot 1 Zone1: はがね（上段Zone1版、y=28）
    (0, 1, "bug",      28),  # Slot 1 Zone2: むし（y=28）
    (2, 1, "steel_z2",  8),  # Slot 3 Zone2: はがね（Zone2版、y=8）
    (4, 0, "fire",      0),  # Slot 5 Zone1: ほのお（y=0）← 再取得
    (5, 0, "steel",     0),  # Slot 6 Zone1: はがね（下段Zone1版、y=0）
    (5, 1, "dragon",    0),  # Slot 6 Zone2: ドラゴン（Zone2版、y=0）
    # ← 上記以外は既存テンプレートを保持（上書きしない）
]

# slot全幅294pxにおけるアイコン位置（実測値）
ICON_X_RATIOS = [0.663, 0.830]   # Zone1, Zone2 の左端比率
ICON_W_RATIO  = 0.136             # アイコン幅（~40px）
ICON_H_PX     = 42                # 切り出し高さ（アイコンより少し多め）

FULL_PNG   = Path("diagnose_full.png")
ICONS_DIR  = Path(__file__).parent.parent / "data" / "type_icons"
BACKUP_DIR = Path(__file__).parent.parent / "data" / "type_icons_backup"


def main():
    if not FULL_PNG.exists():
        print(f"Error: {FULL_PNG} が見つかりません。")
        print("  先に: python scripts/diagnose_type_icons.py を実行してください。")
        sys.exit(1)

    img = Image.open(FULL_PNG)
    W, H = img.size
    print(f"画像サイズ: {W}x{H}")

    cfg    = REGION_CONFIG
    px1    = int(W * cfg["panel_x1"])
    px2    = int(W * cfg["panel_x2"])
    slot_w = px2 - px1

    # 既存テンプレートのバックアップ
    if ICONS_DIR.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for f in ICONS_DIR.glob("*.png"):
            shutil.copy(f, BACKUP_DIR / f.name)
        print(f"既存テンプレートを {BACKUP_DIR}/ にバックアップしました。")

    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    saved = []
    for slot_idx, zone_idx, type_name, y_offset in ICON_SPECS:
        top_ratio = cfg["slot_tops"][slot_idx]
        slot_top  = int(H * top_ratio)

        ix1 = px1 + int(slot_w * ICON_X_RATIOS[zone_idx])
        ix2 = px1 + int(slot_w * (ICON_X_RATIOS[zone_idx] + ICON_W_RATIO))
        iy1 = slot_top + y_offset         # ← アイコン実位置から開始（背景なし）
        iy2 = iy1 + ICON_H_PX

        # 画面端クリップ
        iy2 = min(iy2, H)

        crop = img.crop((ix1, iy1, ix2, iy2))
        out_path = ICONS_DIR / f"{type_name}.png"
        crop.save(out_path)
        saved.append(type_name)
        print(f"  Slot{slot_idx+1} Zone{zone_idx+1} → {type_name:10s}: "
              f"全画像({ix1},{iy1})-({ix2},{iy2})  size={crop.size}")

    print(f"\n保存完了: {saved}")
    print(f"テンプレート保存先: {ICONS_DIR}/")
    print("\n次のステップ:")
    print("  python scripts/diagnose_type_icons.py")
    print("  ※ 同じ画面を表示して精度を確認してください。")


if __name__ == "__main__":
    main()
