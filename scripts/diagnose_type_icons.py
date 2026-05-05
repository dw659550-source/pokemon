"""
タイプアイコン検出の診断スクリプト。
選出画面を表示した状態で実行してください。
各スロットのタイプアイコン領域を切り出して保存し、
検出されたタイプを表示します。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np
from PIL import Image

from capture.sprite_detector import (
    REGION_CONFIG, _pil_to_bgr, detect_slot_types,
)

try:
    from capture.screen_capture import list_windows, capture_window, capture_primary_monitor
    HAS_CAPTURE = True
except ImportError:
    HAS_CAPTURE = False


def grab_frame(window_title: str = "") -> Image.Image | None:
    if HAS_CAPTURE:
        if window_title:
            wins = [w for w in list_windows() if window_title.lower() in w[1].lower()]
            if wins:
                img = capture_window(wins[0])
                if img:
                    return img
        return capture_primary_monitor()
    # mss フォールバック
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            return Image.fromarray(np.array(shot)[:, :, :3])
    except Exception as e:
        print(f"キャプチャ失敗: {e}")
        return None


def run(window_title: str = ""):
    print("3秒後に画面をキャプチャします。選出画面を表示してください...")
    time.sleep(3)

    img = grab_frame(window_title)
    if img is None:
        print("画面のキャプチャに失敗しました。")
        return

    w, h = img.size
    print(f"キャプチャサイズ: {w}x{h}")
    img.save("diagnose_full.png")
    print("フル画像を diagnose_full.png に保存しました。")

    cfg = REGION_CONFIG
    panel_x1 = int(w * cfg["panel_x1"])
    panel_x2 = int(w * cfg["panel_x2"])
    slot_w   = panel_x2 - panel_x1
    ix2_off  = int(slot_w * cfg["icon_x2"])  # sprite 右端 = タイプアイコン開始

    print(f"\n右パネル: x={panel_x1}〜{panel_x2} ({slot_w}px幅)")
    print(f"タイプアイコン開始 x={panel_x1 + ix2_off}")
    print()

    type_crops = []

    for i, top in enumerate(cfg["slot_tops"]):
        ty1 = int(h * top)
        ty2 = int(h * (top + cfg["slot_height"]))
        # スロット全体を保存（タイプアイコンがどこにあるか確認用）
        full_slot = img.crop((panel_x1, ty1, panel_x2, ty2))
        type_crops.append(cv2.resize(_pil_to_bgr(full_slot), (294, 80)))

        # タイプアイコン検索：スロット上半分の全幅
        tx1 = panel_x1
        tx2 = panel_x2
        ty2_crop = int(h * (top + cfg["slot_height"] * 0.55))

        if tx2 <= tx1 or ty2_crop <= ty1:
            print(f"Slot {i+1}: 座標エラー")
            continue

        type_img = img.crop((tx1, ty1, tx2, ty2_crop))
        type_bgr = _pil_to_bgr(type_img)

        # フルエリアでスコア収集＋ゾーン別に表示
        from capture.sprite_detector import _load_type_templates
        import numpy as _np
        templates = _load_type_templates()
        area_h, area_w = type_bgr.shape[:2]
        scales = _np.arange(0.55, 1.05, 0.05)  # detect_slot_types と同じ範囲

        ZONES = [
            (int(area_w * 0.622), int(area_w * 0.799)),
            (int(area_w * 0.799), int(area_w * 0.972)),
        ]

        all_res = []
        for tname, tmpl in templates.items():
            th, tw = tmpl.shape[:2]
            best = 0.0
            best_x = 0
            for scale in scales:
                nw = max(4, int(tw * scale))
                nh = max(4, int(th * scale))
                if nw > area_w or nh > area_h:
                    continue
                tmpl_r = cv2.resize(tmpl, (nw, nh))
                res = cv2.matchTemplate(type_bgr, tmpl_r, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if mv > best:
                    best = mv
                    best_x = ml[0]
            all_res.append((tname, best, best_x))
        all_res.sort(key=lambda x: x[1], reverse=True)

        detected = detect_slot_types(type_bgr)
        print(f"\nSlot {i+1}: 検出={detected or '(なし)'}")
        for zi, (zx1, zx2) in enumerate(ZONES, 1):
            zone_res = [(n, s) for n, s, x in all_res if zx1 <= x < zx2]
            top3 = "  ".join(f"{n}:{s:.3f}" for n, s in zone_res[:3])

            # ── ゾーン列の HSV 実測値を表示（デバッグ用）──────────────────
            import numpy as _np2
            _zone_bgr = type_bgr[:, zx1:zx2]
            _hsv_z = cv2.cvtColor(_zone_bgr, cv2.COLOR_BGR2HSV)
            _h = _hsv_z[:, :, 0].astype(float).flatten()
            _s = _hsv_z[:, :, 1].astype(float).flatten()
            _v = _hsv_z[:, :, 2].astype(float).flatten()
            # 背景除去: クリムゾン (H<12 or H>165, S>100)
            _is_bg = ((_h < 12) | (_h > 165)) & (_s > 100)
            _icon = ~_is_bg
            if _icon.sum() >= 10:
                _mh = _h[_icon].mean()
                _ms = _s[_icon].mean()
                _mv = _v[_icon].mean()
                _n  = int(_icon.sum())
                hsv_info = f"  H={_mh:.0f} S={_ms:.0f} V={_mv:.0f} n={_n}"
            else:
                hsv_info = f"  (icon px={int(_icon.sum())})"
            # ──────────────────────────────────────────────────────────────

            print(f"  Zone{zi}(x={zx1}-{zx2}): {top3 or '(なし)'}{hsv_info}")
        print(f"  ゾーン外トップ: " + "  ".join(
            f"{n}:{s:.3f}@x={x}" for n, s, x in all_res[:3]
            if not any(z[0] <= x < z[1] for z in ZONES)
        )[:80])

    # タイプ領域を縦に並べて1枚の画像に保存
    if type_crops:
        combined = np.vstack(type_crops)
        cv2.imwrite("diagnose_type_areas.png", combined)
        print("\nタイプアイコン領域を diagnose_type_areas.png に保存しました。")
    print("※ タイプが検出されない場合、コンソールの 主要H= の値を教えてください。")


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else ""
    run(title)
