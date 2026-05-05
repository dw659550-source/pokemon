"""
自分チーム（左パネル）のOCR検出を診断するスクリプト。
選出画面を表示した状態で実行してください（3秒カウントダウンあり）。

実行:
  cd C:\\Users\\r\\Desktop\\claude\\pokemon
  python scripts/diagnose_own_team.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np
from PIL import Image

from capture.battle_monitor import match_pokemon_name

# 自分チーム左パネル全体の座標比率
OWN_X1, OWN_X2 = 0.034, 0.200   # ポケモン名テキスト列のみ（スプライト除く）
OWN_Y1, OWN_Y2 = 0.100, 0.840   # 6スロット全体

OUT_DIR = Path("diagnose_own_slots")
OUT_DIR.mkdir(exist_ok=True)


def grab_frame() -> np.ndarray | None:
    try:
        from capture.screen_capture import capture_primary_monitor
        img = capture_primary_monitor()
        if img:
            arr = np.array(img)
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        pass
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            return np.array(shot)[:, :, :3]
    except Exception as e:
        print(f"キャプチャ失敗: {e}")
        return None


def detect_own_team_full_panel(frame: np.ndarray, reader) -> list[str]:
    """
    左パネル全体をOCRし、検出テキストをy座標順にソートして
    ポケモン名を上から順に返す。
    同一スロット内のy間隔（~130px）と別スロット間（~240px）の差で
    アイテム行をスキップする。
    """
    h, w = frame.shape[:2]
    x1 = int(w * OWN_X1)
    x2 = int(w * OWN_X2)
    y1 = int(h * OWN_Y1)
    y2 = int(h * OWN_Y2)

    panel = frame[y1:y2, x1:x2]
    cv2.imwrite(str(OUT_DIR / "panel_name_col.png"), panel)

    # 白文字マスク（ポケモン名は白）
    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    mask_white = (
        (hsv[:, :, 1].astype(int) < 60) &
        (hsv[:, :, 2].astype(int) > 160)
    ).astype("uint8") * 255

    if mask_white.sum() < 1000:
        gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
        _, mask_white = cv2.threshold(gray, 0, 255,
                                      cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    big = cv2.resize(mask_white, (mask_white.shape[1] * 3, mask_white.shape[0] * 3),
                     interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(OUT_DIR / "panel_mask.png"), big)

    ocr_results = reader.readtext(big, detail=1)

    items = []
    for (bbox, text, conf) in ocr_results:
        if not text or conf < 0.10:
            continue
        ys = [pt[1] for pt in bbox]
        y_center = sum(ys) / len(ys)
        items.append((y_center, text.strip(), conf))
        print(f"  OCR検出: y={y_center:.0f} [{text.strip()}] conf={conf:.2f}")

    items.sort(key=lambda x: x[0])

    # スロット内ギャップ(~130) vs スロット間ギャップ(~240) で名前行のみ抽出
    # 3x拡大画像のy座標なので閾値も3x基準（190px≒原寸63px）
    SAME_SLOT_GAP = 190

    team: list[str] = []
    seen_keys: set[str] = set()
    last_y = -9999
    in_slot = False  # 現スロットの名前行を読んだか

    for y_center, text, _ in items:
        gap = y_center - last_y
        last_y = y_center

        if gap < SAME_SLOT_GAP:
            # 同じスロット内 → アイテム行なのでスキップ
            print(f"    (gap={gap:.0f} → アイテム行スキップ: {text})")
            continue

        # 新しいスロットの最初のテキスト = ポケモン名
        key, name_ja = match_pokemon_name(text)
        if key and key not in seen_keys:
            seen_keys.add(key)
            team.append(key)
            print(f"  → ポケモン: {name_ja} ({key})")
        else:
            print(f"    (未マッチ: {text})")

    return team


def run():
    print("3秒後にキャプチャします。選出画面を表示してください...")
    time.sleep(3)

    frame = grab_frame()
    if frame is None:
        print("キャプチャ失敗")
        return

    h, w = frame.shape[:2]
    print(f"キャプチャサイズ: {w}x{h}")
    cv2.imwrite("diagnose_full.png", frame)

    px1, px2 = int(w * OWN_X1), int(w * OWN_X2)
    py1, py2 = int(h * OWN_Y1), int(h * OWN_Y2)
    print(f"名前列パネル: x={px1}-{px2}, y={py1}-{py2}")
    print()

    try:
        import easyocr
        reader = easyocr.Reader(["ja", "en"], gpu=False, verbose=False)
    except ImportError:
        print("easyocr が必要: pip install easyocr")
        return

    team = detect_own_team_full_panel(frame, reader)
    print()
    print("=== 検出結果 ===")
    for i, key in enumerate(team, 1):
        print(f"  {i}. {key}")
    if not team:
        print("  (検出なし)")
    print()
    print(f"画像: {OUT_DIR}/panel_name_col.png, panel_mask.png を確認してください")


if __name__ == "__main__":
    run()
