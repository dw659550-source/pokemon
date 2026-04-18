"""
スプライト画像認識によるポケモン検出モジュール。
チーム選択画面の右パネルから相手チーム6体のアイコンを切り出し、
data/sprites/ の既知スプライトとヒストグラム照合する。
"""
import json
import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

SPRITES_DIR     = Path(__file__).parent.parent / "data" / "sprites"
POKEMON_PATH    = Path(__file__).parent.parent / "data" / "pokemon.json"
HIST_CACHE_PATH = Path(__file__).parent.parent / "data" / "sprite_hists.pkl"

SPRITE_SIZE = 80  # ヒストグラム計算時の正規化サイズ

# ── 右パネル（相手チーム）の位置設定 ──────────────────────────────────────
# スクリーン全体に対する比率。画面解像度が異なる場合は調整してください。
REGION_CONFIG = {
    # 右パネル（相手チーム）の位置 ── 画面幅・高さに対する比率
    # region_check.png で確認しながら調整してください
    "panel_x1": 0.780,   # 右パネル左端
    "panel_x2": 0.960,   # 右パネル右端
    # 各スロットの上端（6体分）── region_check.png で確認済み
    "slot_tops":   [0.107, 0.197, 0.287, 0.377, 0.467, 0.557],
    "slot_height": 0.086,
    # スロット内でのアイコン領域（スロット幅に対する比率）
    "icon_x1": 0.00,
    "icon_x2": 0.40,
}


# ─────────────────────────────────────────────────────────────────────────────
# ヒストグラム計算
# ─────────────────────────────────────────────────────────────────────────────

def _pil_to_bgr(img: "Image.Image") -> "np.ndarray":
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _make_alpha_mask(img: "Image.Image") -> "np.ndarray | None":
    """透明背景スプライトのアルファマスク（なければ None）"""
    if img.mode == "RGBA":
        alpha = np.array(img)[:, :, 3]
        return (alpha > 20).astype(np.uint8) * 255
    return None


def _compute_hist(bgr: "np.ndarray", mask: "np.ndarray | None") -> "np.ndarray":
    """HSV 3 チャンネルのヒストグラムを計算・正規化して返す"""
    resized = cv2.resize(bgr, (SPRITE_SIZE, SPRITE_SIZE))
    if mask is not None:
        mask_r = cv2.resize(mask, (SPRITE_SIZE, SPRITE_SIZE))
    else:
        mask_r = None
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist(
        [hsv], [0, 1, 2], mask_r,
        [18, 8, 8],
        [0, 180, 0, 256, 0, 256],
    )
    cv2.normalize(hist, hist)
    return hist.flatten()


# ─────────────────────────────────────────────────────────────────────────────
# スプライトデータベース
# ─────────────────────────────────────────────────────────────────────────────

class SpriteDatabase:
    """既知スプライトのヒストグラムを管理する"""

    def __init__(self):
        if not HAS_CV2:
            raise RuntimeError("opencv-python が必要: pip install opencv-python")
        if not HAS_PIL:
            raise RuntimeError("Pillow が必要: pip install Pillow")

        self._hists: dict[str, np.ndarray] = {}
        self._names: dict[str, str] = {}  # key → name_ja
        self._load_pokemon_names()
        self._load_or_build_cache()

    def _load_pokemon_names(self):
        try:
            with open(POKEMON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self._names = {k: v.get("name_ja", k) for k, v in data.items()}
        except Exception as e:
            logger.error("pokemon.json 読み込み失敗: %s", e)

    def _load_or_build_cache(self):
        """キャッシュがあれば読み込み、なければスプライトから構築"""
        sprite_count = len(list(SPRITES_DIR.glob("*.png"))) if SPRITES_DIR.exists() else 0

        if HIST_CACHE_PATH.exists():
            try:
                with open(HIST_CACHE_PATH, "rb") as f:
                    cached = pickle.load(f)
                if cached.get("_count") == sprite_count and sprite_count > 0:
                    self._hists = {k: v for k, v in cached.items() if not k.startswith("_")}
                    logger.info("スプライトキャッシュ読み込み: %d 件", len(self._hists))
                    return
            except Exception:
                pass

        self._build_cache(sprite_count)

    def _build_cache(self, sprite_count: int):
        """スプライト画像からヒストグラムを計算してキャッシュ"""
        if not SPRITES_DIR.exists() or sprite_count == 0:
            logger.warning("スプライトが見つかりません: %s", SPRITES_DIR)
            logger.warning("  先に python scripts/download_sprites.py を実行してください")
            return

        logger.info("スプライトヒストグラムを構築中 (%d 件)...", sprite_count)
        built = 0
        for png in SPRITES_DIR.glob("*.png"):
            key = png.stem
            try:
                img  = Image.open(png)
                mask = _make_alpha_mask(img)
                bgr  = _pil_to_bgr(img)
                self._hists[key] = _compute_hist(bgr, mask)
                built += 1
            except Exception as e:
                logger.debug("スプライト読み込み失敗 %s: %s", key, e)

        cache = dict(self._hists)
        cache["_count"] = sprite_count
        with open(HIST_CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)
        logger.info("ヒストグラムキャッシュ保存: %d 件", built)

    def find_best_match(self, icon_bgr: "np.ndarray", top_n: int = 3) -> list[tuple[str, str, float]]:
        """
        アイコン画像と最も類似するポケモンを返す。
        Returns: [(key, name_ja, score), ...] 上位 top_n 件
        """
        if not self._hists:
            return []
        query_hist = _compute_hist(icon_bgr, None)
        scores = []
        for key, tmpl_hist in self._hists.items():
            score = float(cv2.compareHist(query_hist, tmpl_hist, cv2.HISTCMP_CORREL))
            scores.append((key, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [
            (k, self._names.get(k, k), s)
            for k, s in scores[:top_n]
        ]

    def rebuild(self):
        """スプライトが追加された場合にキャッシュを再構築"""
        if HIST_CACHE_PATH.exists():
            HIST_CACHE_PATH.unlink()
        sprite_count = len(list(SPRITES_DIR.glob("*.png")))
        self._hists.clear()
        self._build_cache(sprite_count)


# ─────────────────────────────────────────────────────────────────────────────
# 赤タイル自動検出
# ─────────────────────────────────────────────────────────────────────────────

def auto_detect_slots(
    image: "Image.Image",
    panel_x1: float = 0.75,
    panel_x2: float = 0.99,
    n_slots: int = 6,
) -> list[tuple[int, int, int, int]] | None:
    """
    右パネルの赤いタイルをHSV色検出で自動認識し、
    各スロットの (x1, y1, x2, y2) ピクセル座標リストを返す。
    失敗時は None。
    """
    if not HAS_CV2:
        return None

    w, h = image.size
    px1 = int(w * panel_x1)
    px2 = int(w * panel_x2)

    panel_bgr = cv2.cvtColor(np.array(image.crop((px1, 0, px2, h))), cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2HSV)

    # 暗い赤/マルーン色のマスク（HSV: 赤は H=0〜15 と H=165〜180）
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([0,   80, 30]), np.array([15,  255, 180])),
        cv2.inRange(hsv, np.array([165, 80, 30]), np.array([180, 255, 180])),
    )
    # ノイズ除去
    k = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)

    # 各行の赤ピクセル数 → パネル幅の20%以上なら「タイル行」
    row_red = mask.sum(axis=1) / 255
    threshold = (px2 - px1) * 0.20
    in_tile = row_red > threshold

    # 連続する赤帯を区間としてまとめる
    bands: list[tuple[int, int]] = []
    start = None
    for y, flag in enumerate(in_tile):
        if flag and start is None:
            start = y
        elif not flag and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, len(in_tile)))

    # 最小高さ(全体の4%)未満を除外、高さ順に大きい n_slots 個を選ぶ
    min_h = h * 0.04
    bands = [(s, e) for s, e in bands if (e - s) >= min_h]
    bands.sort(key=lambda b: b[1] - b[0], reverse=True)
    bands = bands[:n_slots]
    bands.sort(key=lambda b: b[0])  # Y順に並び替え

    if len(bands) < n_slots:
        logger.warning("赤タイル検出: %d/%d 件のみ検出 (フォールバックに切り替え)", len(bands), n_slots)
        return None

    # アイコン領域は各タイルの左40%
    icon_w = int((px2 - px1) * 0.40)
    slots = [(px1, s, px1 + icon_w, e) for s, e in bands]
    logger.info("赤タイル自動検出成功: %d スロット", len(slots))
    return slots


# ─────────────────────────────────────────────────────────────────────────────
# チーム検出
# ─────────────────────────────────────────────────────────────────────────────

def detect_opponent_team(
    image: "Image.Image",
    db: SpriteDatabase,
    config: dict | None = None,
) -> list[tuple[str, str, float]]:
    """
    チーム選択画面の右パネルから相手チーム最大6体を検出する。
    赤タイルを色検出で自動認識し、失敗時は REGION_CONFIG にフォールバック。
    """
    cfg = config or REGION_CONFIG
    w, h = image.size

    # ── まず赤タイルを自動検出 ──
    slots = auto_detect_slots(image, panel_x1=cfg["panel_x1"], panel_x2=cfg["panel_x2"])

    # ── 失敗時は REGION_CONFIG のフォールバック ──
    if slots is None:
        logger.info("フォールバック: REGION_CONFIG を使用")
        panel_x1 = int(w * cfg["panel_x1"])
        panel_x2 = int(w * cfg["panel_x2"])
        slot_w   = panel_x2 - panel_x1
        ix1_off  = int(slot_w * cfg["icon_x1"])
        ix2_off  = int(slot_w * cfg["icon_x2"])
        slots = [
            (panel_x1 + ix1_off,
             int(h * top),
             panel_x1 + ix2_off,
             int(h * (top + cfg["slot_height"])))
            for top in cfg["slot_tops"]
        ]

    results = []
    for ix1, iy1, ix2, iy2 in slots:
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        icon_img = image.crop((ix1, iy1, ix2, iy2))
        icon_bgr = _pil_to_bgr(icon_img)
        matches  = db.find_best_match(icon_bgr, top_n=1)
        if matches:
            key, name_ja, score = matches[0]
            results.append((key, name_ja, float(score)))
            logger.debug("Slot %d: %s (%.2f)", len(results), name_ja, score)

    return results
