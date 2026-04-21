"""
対戦画面を常時監視し、相手ポケモン名を自動検出する QThread。
mss で画面をキャプチャ → HP バー領域の変化検出 → EasyOCR で名前読み取り
"""
import difflib
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

BATTLE_CONFIG_PATH = Path(__file__).parent.parent / "data" / "battle_config.json"
POKEMON_PATH       = Path(__file__).parent.parent / "data" / "pokemon.json"

# SV 系のデフォルト位置（キャリブレーションで上書きされる）
DEFAULT_BATTLE_CONFIG = {
    "monitor": 1,
    # 相手ポケモン名領域
    "name_x1":   0.515,
    "name_y1":   0.048,
    "name_x2":   0.790,
    "name_y2":   0.110,
    "detect_x1": 0.515,
    "detect_y1": 0.048,
    "detect_x2": 0.950,
    "detect_y2": 0.175,
    # 自分のポケモン名領域（未設定時はスキップ）
    "own_name_x1": 0.0,
    "own_name_y1": 0.0,
    "own_name_x2": 0.0,
    "own_name_y2": 0.0,
}


def load_battle_config() -> dict:
    if BATTLE_CONFIG_PATH.exists():
        try:
            with open(BATTLE_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_BATTLE_CONFIG)


def save_battle_config(cfg: dict):
    BATTLE_CONFIG_PATH.parent.mkdir(exist_ok=True)
    with open(BATTLE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── ポケモン名マッチング ──────────────────────────────────────────────────────

_name_map_cache: dict[str, str] | None = None  # name_ja → key


def _get_name_map() -> dict[str, str]:
    global _name_map_cache
    if _name_map_cache is None:
        try:
            with open(POKEMON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            _name_map_cache = {
                v.get("name_ja", k): k
                for k, v in data.items()
                if not k.startswith("_")
            }
        except Exception:
            _name_map_cache = {}
    return _name_map_cache


def _normalize(s: str) -> str:
    """OCR ノイズ除去・文字正規化（半角カタカナ→全角、記号除去など）"""
    s = unicodedata.normalize("NFKC", s)          # 半角カナ→全角、全角英数→半角
    s = re.sub(r"[♂♀☆★◯×・/\-\s　]", "", s)   # ゴミ文字・スペース除去
    s = re.sub(r"Lv\.?\d+", "", s)                # "Lv.50" などを除去
    s = re.sub(r"\d+/\d+", "", s)                 # "120/340" などHP表示除去
    return s.strip()


# OCR が混同しやすい文字の置換候補（カタカナ）
_OCR_SUBS: list[tuple[str, str]] = [
    ("ン", "ソ"), ("ソ", "ン"),
    ("リ", "リ"), ("ウ", "ヴ"),
    ("ー", "一"), ("一", "ー"),
]


def _ocr_variants(text: str) -> list[str]:
    """OCR 誤読パターンの代替候補を生成"""
    variants = [text]
    for src, dst in _OCR_SUBS:
        if src in text:
            variants.append(text.replace(src, dst, 1))
    return variants


def match_pokemon_name(text: str) -> tuple[str, str] | tuple[None, None]:
    """
    OCR テキストをポケモン名にマッチング。
    正規化 → 完全一致 → 部分一致 → ファジーマッチ の順に試みる。
    Returns: (key, name_ja) または (None, None)
    """
    name_map = _get_name_map()
    if not text or not name_map:
        return None, None

    text_n = _normalize(text)
    if not text_n:
        return None, None

    # 正規化済みの name_ja → (原文, key) マップを構築
    norm_map: dict[str, tuple[str, str]] = {
        _normalize(n): (n, k) for n, k in name_map.items()
    }

    # ① 完全一致（正規化後）
    if text_n in norm_map:
        orig, key = norm_map[text_n]
        return key, orig

    # ② 部分一致（正規化後）: name が text に含まれる / text が name に含まれる
    for n_norm, (orig, key) in norm_map.items():
        if n_norm and (n_norm in text_n or text_n in n_norm):
            return key, orig

    # ③ OCR 誤読バリアントで再試行
    for variant in _ocr_variants(text_n):
        if variant == text_n:
            continue
        if variant in norm_map:
            orig, key = norm_map[variant]
            return key, orig
        for n_norm, (orig, key) in norm_map.items():
            if n_norm and (n_norm in variant or variant in n_norm):
                return key, orig

    # ④ ファジーマッチ（閾値を少し下げて拾いやすくする）
    candidates = difflib.get_close_matches(text_n, norm_map.keys(), n=1, cutoff=0.60)
    if candidates:
        orig, key = norm_map[candidates[0]]
        return key, orig

    return None, None


# ── BattleMonitor ─────────────────────────────────────────────────────────────

def _ocr_preprocess(crop_bgr, cv2_mod, np_mod):
    """白文字を抽出して3倍拡大した画像を返す"""
    hsv  = cv2_mod.cvtColor(crop_bgr, cv2_mod.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((np_mod.array(s) < 60) & (np_mod.array(v) > 150)).astype("uint8") * 255
    return cv2_mod.resize(
        mask,
        (mask.shape[1] * 3, mask.shape[0] * 3),
        interpolation=cv2_mod.INTER_NEAREST,
    )


class BattleMonitor(QThread):
    """
    対戦画面を ~15fps でキャプチャし、相手・自分のHPバー名前領域を監視する。
    ポケモンが変わったと判断したら各シグナルを emit する。
    window_title が設定されている場合はそのウィンドウだけをキャプチャする。
    """
    opponent_changed = pyqtSignal(str, str)  # (key, name_ja)
    own_changed      = pyqtSignal(str, str)  # (key, name_ja)
    status_changed   = pyqtSignal(str)

    def __init__(self, config: dict | None = None, window_title: str = ""):
        super().__init__()
        self._cfg          = config or load_battle_config()
        self._window_title = window_title
        self._running      = False
        self._prev_mean: np.ndarray | None = None
        self._prev_name    = ""
        self._prev_own     = ""

    def update_config(self, cfg: dict):
        self._cfg = cfg

    def stop(self):
        self._running = False

    def _grab_frame(self, sct, mon):
        """ウィンドウ or モニターをキャプチャして BGR numpy array を返す。失敗時は None。"""
        if self._window_title:
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(self._window_title)
                if not wins:
                    return None
                w = wins[0]
                if w.width <= 0 or w.height <= 0:
                    return None
                region = {"left": w.left, "top": w.top,
                          "width": w.width, "height": w.height}
                shot = sct.grab(region)
            except Exception:
                return None
        else:
            shot = sct.grab(mon)
        return np.array(shot)[:, :, :3]

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

        self.status_changed.emit("OCRモデル読み込み中（初回は数分かかる場合があります）...")
        try:
            reader = easyocr.Reader(["ja", "en"], gpu=False, verbose=False)
        except Exception as e:
            self.status_changed.emit(f"OCR初期化失敗: {e}")
            return

        self.status_changed.emit("監視中...")
        self._running = True

        with mss.mss() as sct:
            monitors = sct.monitors
            mon_idx  = int(self._cfg.get("monitor", 1))
            mon      = monitors[mon_idx] if mon_idx < len(monitors) else monitors[1]

            while self._running:
                try:
                    frame = self._grab_frame(sct, mon)
                    if frame is None:
                        time.sleep(0.3)
                        continue
                    h, w  = frame.shape[:2]
                    h, w  = frame.shape[:2]
                    cfg   = self._cfg

                    # ── 変化検出（ダウンサンプル平均色で比較）──
                    dx1 = int(w * cfg["detect_x1"])
                    dy1 = int(h * cfg["detect_y1"])
                    dx2 = int(w * cfg["detect_x2"])
                    dy2 = int(h * cfg["detect_y2"])
                    region   = frame[dy1:dy2, dx1:dx2]
                    cur_mean = region[::4, ::4].mean(axis=(0, 1))

                    if self._prev_mean is not None:
                        if float(np.abs(cur_mean - self._prev_mean).max()) < 8:
                            time.sleep(0.07)
                            continue

                    self._prev_mean = cur_mean

                    import cv2 as _cv2
                    import numpy as _np

                    # ── 相手ポケモン OCR ──
                    pad = int(w * 0.03)
                    nx1 = max(0, int(w * cfg["name_x1"]) - pad)
                    ny1 = max(0, int(h * cfg["name_y1"]) - 8)
                    nx2 = min(w, int(w * cfg["name_x2"]) + pad)
                    ny2 = min(h, int(h * cfg["name_y2"]) + 8)
                    opp_crop = frame[ny1:ny2, nx1:nx2]
                    proc = _ocr_preprocess(opp_crop, _cv2, _np)
                    texts = reader.readtext(proc, detail=0)
                    text  = "".join(texts).strip()
                    if text and text != self._prev_name:
                        key, name_ja = match_pokemon_name(text)
                        if key:
                            self._prev_name = text
                            self.opponent_changed.emit(key, name_ja)
                            self.status_changed.emit(f"相手: {name_ja}")
                        else:
                            self.status_changed.emit(f"マッチなし: [{text}]")

                    # ── 自分のポケモン OCR（領域が設定されている場合のみ）──
                    ox1 = cfg.get("own_name_x1", 0.0)
                    ox2 = cfg.get("own_name_x2", 0.0)
                    if ox1 < ox2:
                        on1 = max(0, int(w * ox1) - pad)
                        on2 = max(0, int(h * cfg["own_name_y1"]) - 8)
                        on3 = min(w, int(w * ox2) + pad)
                        on4 = min(h, int(h * cfg["own_name_y2"]) + 8)
                        own_crop = frame[on2:on4, on1:on3]
                        proc2 = _ocr_preprocess(own_crop, _cv2, _np)
                        texts2 = reader.readtext(proc2, detail=0)
                        text2  = "".join(texts2).strip()
                        if text2 and text2 != self._prev_own:
                            key2, name2 = match_pokemon_name(text2)
                            if key2:
                                self._prev_own = text2
                                self.own_changed.emit(key2, name2)

                except Exception as e:
                    logger.error("監視エラー: %s", e)

                time.sleep(0.07)
