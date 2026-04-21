#!/usr/bin/env python3
"""
対戦画面の相手ポケモン名領域を2クリックで指定するキャリブレーションツール。

使い方:
  python scripts/calibrate_battle.py screenshot.png
  python scripts/calibrate_battle.py screenshot.png --monitor 2  # セカンダリモニター

操作:
  1. 相手ポケモン名テキストの左上をクリック
  2. 右下をクリック → プレビュー確認 → Enter で保存、R でやり直し
"""
import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent))
from capture.battle_monitor import BATTLE_CONFIG_PATH, save_battle_config


def run_calibration(img_path: str, monitor: int):
    img_orig = Image.open(img_path).convert("RGB")
    orig_w, orig_h = img_orig.size

    max_w, max_h = 1400, 800
    scale = min(max_w / orig_w, max_h / orig_h, 1.0)
    disp_w = int(orig_w * scale)
    disp_h = int(orig_h * scale)
    img_disp = img_orig.resize((disp_w, disp_h), Image.LANCZOS)

    clicks: list[tuple[int, int]] = []
    photo_ref = [None]

    root = tk.Tk()
    root.title("対戦画面キャリブレーション")

    instr = tk.Label(root,
        text="① 相手ポケモン名テキストの左上をクリック  →  ② 右下をクリック",
        font=("", 12), bg="#2c3e50", fg="white", pady=6)
    instr.pack(fill=tk.X)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="crosshair")
    canvas.pack()

    status = tk.Label(root, text="相手ポケモン名の左上をクリックしてください",
                      font=("", 11), pady=4)
    status.pack()

    def redraw(overlay=None):
        src = overlay or img_disp
        photo_ref[0] = ImageTk.PhotoImage(src)
        canvas.create_image(0, 0, anchor=tk.NW, image=photo_ref[0])

    def on_click(event):
        x, y = event.x, event.y
        clicks.append((x, y))

        if len(clicks) == 1:
            canvas.create_line(x - 10, y, x + 10, y, fill="cyan", width=2)
            canvas.create_line(x, y - 10, x, y + 10, fill="cyan", width=2)
            status.config(text="右下をクリックしてください")

        elif len(clicks) == 2:
            x1d, y1d = clicks[0]
            x2d, y2d = clicks[1]
            preview = img_disp.copy()
            draw = ImageDraw.Draw(preview)

            # 名前領域（水色）
            draw.rectangle([x1d, y1d, x2d, y2d], outline=(0, 200, 255), width=3)
            draw.text((x1d + 4, y1d + 4), "名前領域", fill=(0, 200, 255))

            # 変化検出領域（黄：名前領域を右・下に拡張）
            det_x2d = min(int(disp_w * 0.98), disp_w)
            det_y2d = min(int(y2d + (y2d - y1d) * 0.8), disp_h)
            draw.rectangle([x1d, y1d, det_x2d, det_y2d], outline=(255, 200, 0), width=2)
            draw.text((x1d + 4, det_y2d - 16), "変化検出領域", fill=(255, 200, 0))

            redraw(preview)
            status.config(text="確認: Enter で保存 / R でやり直し")

    def on_key(event):
        key = event.keysym.lower()

        if key == "return" and len(clicks) == 2:
            x1d, y1d = clicks[0]
            x2d, y2d = clicks[1]
            x1o, y1o = x1d / scale, y1d / scale
            x2o, y2o = x2d / scale, y2d / scale
            det_x2o = orig_w * 0.98
            det_y2o = min(y2o + (y2o - y1o) * 0.8, orig_h)

            cfg = {
                "monitor":   monitor,
                "name_x1":   round(x1o / orig_w, 4),
                "name_y1":   round(y1o / orig_h, 4),
                "name_x2":   round(x2o / orig_w, 4),
                "name_y2":   round(y2o / orig_h, 4),
                "detect_x1": round(x1o / orig_w, 4),
                "detect_y1": round(y1o / orig_h, 4),
                "detect_x2": round(det_x2o / orig_w, 4),
                "detect_y2": round(det_y2o / orig_h, 4),
                "own_name_x1": 0.0,
                "own_name_y1": 0.0,
                "own_name_x2": 0.0,
                "own_name_y2": 0.0,
            }

            # 既存の own_name 設定があれば引き継ぐ
            if BATTLE_CONFIG_PATH.exists():
                try:
                    import json as _json
                    old = _json.loads(BATTLE_CONFIG_PATH.read_text(encoding="utf-8"))
                    for k in ("own_name_x1","own_name_y1","own_name_x2","own_name_y2"):
                        if k in old:
                            cfg[k] = old[k]
                except Exception:
                    pass

            save_battle_config(cfg)
            # 自分ポケモン領域の設定へ進む
            clicks.clear()
            instr.config(text="② 自分のポケモン名テキストの左上をクリック  →  右下をクリック  （スキップ: S キー）")
            status.config(text="自分のポケモン名の左上をクリック（スキップするには S キー）")
            redraw()
            # フラグで2段階目に
            root._phase = "own"

        elif key == "s" and getattr(root, "_phase", "") == "own":
            print(f"\n保存完了（自分側スキップ）: {BATTLE_CONFIG_PATH}")
            root.destroy()

        elif key == "return" and getattr(root, "_phase", "") == "own" and len(clicks) == 2:
            x1d, y1d = clicks[0]
            x2d, y2d = clicks[1]
            x1o, y1o = x1d / scale, y1d / scale
            x2o, y2o = x2d / scale, y2d / scale
            import json as _json
            cfg = _json.loads(BATTLE_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg["own_name_x1"] = round(x1o / orig_w, 4)
            cfg["own_name_y1"] = round(y1o / orig_h, 4)
            cfg["own_name_x2"] = round(x2o / orig_w, 4)
            cfg["own_name_y2"] = round(y2o / orig_h, 4)
            save_battle_config(cfg)
            print(f"\n保存完了: {BATTLE_CONFIG_PATH}")
            print(_json.dumps(cfg, indent=2, ensure_ascii=False))
            root.destroy()

        elif key == "r":
            clicks.clear()
            redraw()
            if getattr(root, "_phase", "") == "own":
                status.config(text="自分のポケモン名の左上をクリック（スキップするには S キー）")
            else:
                status.config(text="相手ポケモン名の左上をクリックしてください")

        elif key == "escape":
            root.destroy()

    canvas.bind("<Button-1>", on_click)
    root.bind("<Key>", on_key)
    redraw()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="対戦画面のスクリーンショット")
    parser.add_argument("--monitor", type=int, default=1,
                        help="キャプチャするモニター番号 (1=プライマリ, 2=セカンダリ)")
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"ファイルが見つかりません: {args.image}")
        sys.exit(1)

    run_calibration(args.image, args.monitor)


if __name__ == "__main__":
    main()
