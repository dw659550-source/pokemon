#!/usr/bin/env python3
"""
2クリックでスロット位置を指定するキャリブレーションツール。

使い方:
  python scripts/calibrate_slots.py screenshot.png

操作:
  1. 開いた画像で「slot1 の左上」をクリック
  2. 「slot6 の右下」をクリック
  3. プレビューを確認 → Enter で保存、R でやり直し
"""
import sys
import json
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIG_PATH = Path(__file__).parent.parent / "data" / "region_config.json"


def run_calibration(img_path: str):
    img_orig = Image.open(img_path).convert("RGB")
    orig_w, orig_h = img_orig.size

    # 画面に収まるようにリサイズ
    max_w, max_h = 1400, 800
    scale = min(max_w / orig_w, max_h / orig_h, 1.0)
    disp_w = int(orig_w * scale)
    disp_h = int(orig_h * scale)
    img_disp = img_orig.resize((disp_w, disp_h), Image.LANCZOS)

    clicks: list[tuple[int, int]] = []   # 表示座標
    photo_ref = [None]

    root = tk.Tk()
    root.title("スロットキャリブレーション")

    instr = tk.Label(root,
        text="① slot1（1体目）の左上をクリック  →  ② slot6（6体目）の右下をクリック",
        font=("", 12), bg="#2c3e50", fg="white", pady=6)
    instr.pack(fill=tk.X)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="crosshair")
    canvas.pack()

    status = tk.Label(root, text="slot1の左上をクリックしてください",
                      font=("", 11), pady=4)
    status.pack()

    def redraw(overlay_img=None):
        src = overlay_img if overlay_img else img_disp
        photo_ref[0] = ImageTk.PhotoImage(src)
        canvas.create_image(0, 0, anchor=tk.NW, image=photo_ref[0])

    def draw_preview(x1d, y1d, x2d, y2d):
        """6分割プレビューを描画"""
        preview = img_disp.copy()
        draw = ImageDraw.Draw(preview)
        colors = [(255,60,60),(255,160,0),(80,210,80),
                  (0,200,220),(180,0,255),(255,230,0)]
        slot_h = (y2d - y1d) / 6
        for i in range(6):
            sy = y1d + i * slot_h
            ey = sy + slot_h
            c = colors[i]
            draw.rectangle([x1d, sy, x2d, ey], outline=c, width=3)
            draw.text((x1d + 4, sy + 2), f"slot{i+1}", fill=c)
        redraw(preview)

    def on_click(event):
        x, y = event.x, event.y
        clicks.append((x, y))

        if len(clicks) == 1:
            # 1点目：クロス表示
            canvas.create_line(x-10, y, x+10, y, fill="red", width=2)
            canvas.create_line(x, y-10, x, y+10, fill="red", width=2)
            status.config(text="slot6の右下をクリックしてください")

        elif len(clicks) == 2:
            x1d, y1d = clicks[0]
            x2d, y2d = clicks[1]
            draw_preview(x1d, y1d, x2d, y2d)
            status.config(
                text="確認: 枠が合っていれば Enter で保存 / R でやり直し"
            )

    def on_key(event):
        key = event.keysym.lower()

        if key == "return" and len(clicks) == 2:
            x1d, y1d = clicks[0]
            x2d, y2d = clicks[1]
            # 表示座標 → 元画像座標 → 比率
            x1o = x1d / scale
            y1o = y1d / scale
            x2o = x2d / scale
            y2o = y2d / scale
            slot_h = (y2o - y1o) / 6
            slot_w = x2o - x1o

            config = {
                "panel_x1":    round(x1o / orig_w, 4),
                "panel_x2":    round(x2o / orig_w, 4),
                "slot_tops":   [round((y1o + i * slot_h) / orig_h, 4) for i in range(6)],
                "slot_height": round(slot_h / orig_h, 4),
                "icon_x1":     0.0,
                "icon_x2":     1.0,
            }
            CONFIG_PATH.parent.mkdir(exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"\n保存完了: {CONFIG_PATH}")
            print(json.dumps(config, indent=2))
            root.destroy()

        elif key == "r":
            clicks.clear()
            redraw()
            status.config(text="slot1の左上をクリックしてください")

        elif key == "escape":
            root.destroy()

    canvas.bind("<Button-1>", on_click)
    root.bind("<Key>", on_key)
    redraw()
    root.mainloop()


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/calibrate_slots.py <画像ファイル>")
        sys.exit(1)
    run_calibration(sys.argv[1])


if __name__ == "__main__":
    main()
