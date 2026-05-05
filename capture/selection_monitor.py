"""
選出画面を監視し「選出してください」を検出したら
相手6体（スプライト照合）・自分6体（OCR）を解析する QThread。
"""
import logging
import time

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from capture.battle_monitor import load_battle_config, match_pokemon_name

logger = logging.getLogger(__name__)

# 自分チーム左パネルの座標比率（実画面計測値）
OWN_X1, OWN_X2 = 0.034, 0.200  # ポケモン名テキスト列のみ（スプライト除く）
OWN_Y1, OWN_Y2 = 0.100, 0.840  # 6スロット全体

# 同一スロット内y間隔(~130px) vs スロット間(~240px) の境界（3x拡大画像基準）
_SAME_SLOT_GAP = 190

# OCRトリガー検索領域（中央）
TRIGGER_X1, TRIGGER_X2 = 0.30, 0.75
TRIGGER_Y1, TRIGGER_Y2 = 0.15, 0.45

TRIGGER_TEXT = "選出してください"
COOLDOWN_SEC = 25  # 同じ選出画面での再トリガー防止


class SelectionMonitor(QThread):
    """
    ~1fps でキャプチャしてOCRトリガーを監視。
    選出画面を検出したら相手・自分チームを解析してシグナルを emit する。
    """
    teams_detected = pyqtSignal(list, list)  # own_keys: list[str], opp_results: list[tuple]
    status_changed = pyqtSignal(str)

    def __init__(self, window_title: str = ""):
        super().__init__()
        self._window_title = window_title
        self._running = False
        self._last_trigger = 0.0
        self._party_keys: list[str] = []

    def set_party_keys(self, keys: list[str]):
        """登録済みパーティの種族キーをセット。非空のとき OCR をスキップする。"""
        self._party_keys = [k for k in keys if k]

    def stop(self):
        self._running = False

    def _grab_frame(self, sct, mon):
        """BattleMonitor と同じロジックでフレームを取得"""
        if self._window_title:
            try:
                from capture.screen_capture import capture_window_direct
                import cv2 as _cv2
                img = capture_window_direct(self._window_title)
                if img is not None:
                    arr = np.array(img)
                    return _cv2.cvtColor(arr, _cv2.COLOR_RGB2BGR)
            except Exception:
                pass
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(self._window_title)
                if wins:
                    w = wins[0]
                    if w.width > 0 and w.height > 0:
                        region = {"left": w.left, "top": w.top,
                                  "width": w.width, "height": w.height}
                        shot = sct.grab(region)
                        return np.array(shot)[:, :, :3]
            except Exception:
                pass
            return None
        shot = sct.grab(mon)
        return np.array(shot)[:, :, :3]

    def _ocr_trigger(self, frame, reader):
        """中央領域をOCRして選出画面かどうか判定"""
        import cv2 as _cv2
        h, w = frame.shape[:2]
        x1 = int(w * TRIGGER_X1)
        y1 = int(h * TRIGGER_Y1)
        x2 = int(w * TRIGGER_X2)
        y2 = int(h * TRIGGER_Y2)
        crop = frame[y1:y2, x1:x2]
        gray = _cv2.cvtColor(crop, _cv2.COLOR_BGR2GRAY)
        _, thresh = _cv2.threshold(gray, 0, 255,
                                   _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)
        big = _cv2.resize(thresh, (thresh.shape[1] * 2, thresh.shape[0] * 2),
                          interpolation=_cv2.INTER_NEAREST)
        texts = reader.readtext(big, detail=0)
        joined = "".join(texts)
        return TRIGGER_TEXT in joined

    def _detect_own_team(self, frame, reader) -> list[str]:
        """
        左パネル全体をOCRして自分の6体を特定する。
        y座標ギャップでポケモン名行とアイテム名行を判別するため
        スロット座標の分割が不要。
        """
        import cv2 as _cv2
        h, w = frame.shape[:2]
        x1 = int(w * OWN_X1)
        x2 = int(w * OWN_X2)
        y1 = int(h * OWN_Y1)
        y2 = int(h * OWN_Y2)

        panel = frame[y1:y2, x1:x2]
        hsv = _cv2.cvtColor(panel, _cv2.COLOR_BGR2HSV)
        mask = (
            (hsv[:, :, 1].astype(int) < 60) &
            (hsv[:, :, 2].astype(int) > 160)
        ).astype("uint8") * 255
        if mask.sum() < 1000:
            gray = _cv2.cvtColor(panel, _cv2.COLOR_BGR2GRAY)
            _, mask = _cv2.threshold(gray, 0, 255,
                                     _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
        big = _cv2.resize(mask, (mask.shape[1] * 3, mask.shape[0] * 3),
                          interpolation=_cv2.INTER_NEAREST)

        ocr_results = reader.readtext(big, detail=1)
        items = []
        for (bbox, text, conf) in ocr_results:
            if not text or conf < 0.25:
                continue
            ys = [pt[1] for pt in bbox]
            items.append((sum(ys) / len(ys), text.strip()))
        items.sort(key=lambda x: x[0])

        results: list[str] = []
        seen_keys: set[str] = set()
        last_y = -9999
        for y_center, text in items:
            if y_center - last_y < _SAME_SLOT_GAP:
                last_y = y_center
                continue  # アイテム行スキップ
            last_y = y_center
            key, _ = match_pokemon_name(text)
            if key and key not in seen_keys:
                seen_keys.add(key)
                results.append(key)
                logger.debug("Own team OCR: [%s] → %s", text, key)

        return results

    def _detect_opponent_team(self, frame) -> list[tuple]:
        """スプライト照合で相手6体を特定する"""
        try:
            from PIL import Image
            from capture.sprite_detector import SpriteDatabase, detect_opponent_team
            rgb = frame[:, :, ::-1]  # BGR→RGB
            pil_img = Image.fromarray(rgb)
            db = SpriteDatabase()
            return detect_opponent_team(pil_img, db)
        except Exception as e:
            logger.error("相手チーム検出失敗: %s", e)
            return []

    def run(self):
        try:
            import mss
        except ImportError:
            self.status_changed.emit("mss が必要: pip install mss")
            return
        try:
            import easyocr
        except ImportError:
            self.status_changed.emit("easyocr が必要: pip install easyocr")
            return

        reader = None
        if not self._party_keys:
            self.status_changed.emit("OCRモデル読み込み中...")
            try:
                reader = easyocr.Reader(["ja", "en"], gpu=False, verbose=False)
            except Exception as e:
                self.status_changed.emit(f"OCR初期化失敗: {e}")
                return

        self.status_changed.emit("選出画面を監視中...")
        self._running = True
        cfg = load_battle_config()

        with mss.mss() as sct:
            monitors = sct.monitors
            mon_idx = int(cfg.get("monitor", 1))
            mon = monitors[mon_idx] if mon_idx < len(monitors) else monitors[1]

            while self._running:
                try:
                    frame = self._grab_frame(sct, mon)
                    if frame is None:
                        time.sleep(1.0)
                        continue

                    if not self._ocr_trigger(frame, reader):
                        time.sleep(1.0)
                        continue

                    now = time.time()
                    if now - self._last_trigger < COOLDOWN_SEC:
                        time.sleep(1.0)
                        continue

                    self._last_trigger = now
                    self.status_changed.emit("選出画面を検出しました。解析中...")

                    if self._party_keys:
                        own = list(self._party_keys)
                    else:
                        own = self._detect_own_team(frame, reader)
                    opp = self._detect_opponent_team(frame)

                    self.teams_detected.emit(own, opp)
                    self.status_changed.emit(
                        f"解析完了 — 相手: {len([r for r in opp if r])} 体検出"
                    )

                except Exception as e:
                    logger.error("選出監視エラー: %s", e)

                time.sleep(1.0)
