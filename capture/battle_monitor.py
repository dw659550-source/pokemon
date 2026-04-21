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
    "name_x1":   0.515,
    "name_y1":   0.048,
    "name_x2":   0.790,
    "name_y2":   0.110,
    "detect_x1": 0.515,
    "detect_y1": 0.048,
    "detect_x2": 0.950,
    "detect_y2": 0.175,
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

class BattleMonitor(QThread):
    """
    対戦画面を ~15fps でキャプチャし、相手HPバー名前領域を監視する。
    ポケモンが変わったと判断したら opponent_changed を emit する。
    """
    opponent_changed = pyqtSignal(str, str)  # (key, name_ja)
    status_changed   = pyqtSignal(str)

    def __init__(self, config: dict | None = None):
        super().__init__()
        self._cfg     = config or load_battle_config()
        self._running = False
        self._prev_mean: np.ndarray | None = None
        self._prev_name = ""

    def update_config(self, cfg: dict):
        self._cfg = cfg

    def stop(self):
        self._running = False

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
            monitors = sct.monitors  # 0=全体, 1=プライマリ, 2=セカンダリ
            mon_idx  = int(self._cfg.get("monitor", 1))
            if mon_idx >= len(monitors):
                self.status_changed.emit(
                    f"モニター{mon_idx}が見つかりません（利用可能: 1〜{len(monitors)-1}）"
                )
                return
            mon = monitors[mon_idx]

            while self._running:
                try:
                    shot  = sct.grab(mon)
                    frame = np.array(shot)[:, :, :3]  # BGRA → BGR
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

                    # ── OCR ──
                    nx1 = int(w * cfg["name_x1"])
                    ny1 = int(h * cfg["name_y1"])
                    nx2 = int(w * cfg["name_x2"])
                    ny2 = int(h * cfg["name_y2"])
                    name_crop = frame[ny1:ny2, nx1:nx2]

                    texts = reader.readtext(name_crop, detail=0)
                    text  = "".join(texts).strip()
                    if not text or text == self._prev_name:
                        continue

                    key, name_ja = match_pokemon_name(text)
                    if key:
                        self._prev_name = text
                        self.opponent_changed.emit(key, name_ja)
                        self.status_changed.emit(f"検出: {name_ja}  [OCR: {text}]")
                    else:
                        self.status_changed.emit(f"マッチなし: [{text}]")

                except Exception as e:
                    logger.error("監視エラー: %s", e)

                time.sleep(0.07)
