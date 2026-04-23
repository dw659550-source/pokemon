"""
スプライト画像認識によるポケモン検出モジュール。
チーム選択画面の右パネルから相手チーム6体のアイコンを切り出し、
data/sprites/ の既知スプライトとpHash照合する。
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
REGION_CONFIG_PATH = Path(__file__).parent.parent / "data" / "region_config.json"

SPRITE_SIZE = 80  # リサイズ用

# ── 右パネル（相手チーム）の位置設定 ──────────────────────────────────────
REGION_CONFIG = {
    "panel_x1": 0.807,
    "panel_x2": 1.000,
    "slot_tops":   [0.126, 0.255, 0.380, 0.508, 0.635, 0.762],
    "slot_height": 0.118,
    "icon_x1": 0.00,
    "icon_x2": 0.65,
}

# pHash キャッシュバージョン（旧ヒストグラムキャッシュを無効化）
_CACHE_VERSION = 3


# ─────────────────────────────────────────────────────────────────────────────
# pHash 計算（numpy + PIL のみ、追加依存なし）
# ─────────────────────────────────────────────────────────────────────────────

def _make_dct_matrix(n: int) -> "np.ndarray":
    """DCT-II 基底行列 M[k,n] = cos(π*k*(2n+1)/(2N))"""
    k = np.arange(n, dtype=np.float32)[:, np.newaxis]  # (N,1)
    idx = np.arange(n, dtype=np.float32)[np.newaxis, :]  # (1,N)
    return np.cos(np.pi * k * (2 * idx + 1) / (2 * n))  # (N,N)


# キャッシュして毎回生成しない
_DCT32: "np.ndarray | None" = None


def _get_dct32() -> "np.ndarray":
    global _DCT32
    if _DCT32 is None:
        _DCT32 = _make_dct_matrix(32)
    return _DCT32


def compute_phash(pil_img: "Image.Image", hash_size: int = 8) -> "np.ndarray":
    """
    64bit pHash（DCT-II ベース）。
    Returns: uint8 array of length hash_size**2 (0 or 1)
    """
    size = hash_size * 4  # 32x32
    gray = pil_img.convert("L").resize((size, size), Image.LANCZOS)
    pixels = np.array(gray, dtype=np.float32)

    M = _get_dct32()
    dct2d = M @ pixels @ M.T  # 2D DCT-II

    low = dct2d[:hash_size, :hash_size]  # 低周波 8x8 = 64値
    mean = low.mean()
    return (low > mean).flatten().astype(np.uint8)


def phash_distance(h1: "np.ndarray", h2: "np.ndarray") -> int:
    """ハミング距離（0 = 完全一致、64 = 完全不一致）"""
    return int(np.count_nonzero(h1 != h2))


def phash_score(h1: "np.ndarray", h2: "np.ndarray") -> float:
    """類似度スコア [0, 1]（1 = 完全一致）"""
    return 1.0 - phash_distance(h1, h2) / len(h1)


# ─────────────────────────────────────────────────────────────────────────────
# BGR/mask ユーティリティ（アイコン前処理用）
# ─────────────────────────────────────────────────────────────────────────────

def _pil_to_bgr(img: "Image.Image") -> "np.ndarray":
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _bgr_to_pil(bgr: "np.ndarray") -> "Image.Image":
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _remove_bg(bgr: "np.ndarray") -> "Image.Image":
    """
    キャプチャアイコンから赤/暗い背景を除去して PIL Image を返す。
    透明部分は白で塗りつぶし（pHash はグレースケールなので色は不問）。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([0,   50, 15]), np.array([15,  255, 160])),
        cv2.inRange(hsv, np.array([160, 50, 15]), np.array([180, 255, 160])),
    )
    dark = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 30]))
    bg_mask = cv2.bitwise_or(red, dark)
    k = np.ones((3, 3), np.uint8)
    bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_CLOSE, k)

    # 背景を白に置換
    result = bgr.copy()
    result[bg_mask > 0] = [255, 255, 255]
    return _bgr_to_pil(result)


# ─────────────────────────────────────────────────────────────────────────────
# スプライトデータベース
# ─────────────────────────────────────────────────────────────────────────────

class SpriteDatabase:
    """既知スプライトの pHash を管理する"""

    def __init__(self):
        if not HAS_PIL:
            raise RuntimeError("Pillow が必要: pip install Pillow")

        self._phashes: dict[str, np.ndarray] = {}
        self._names: dict[str, str] = {}
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
        sprite_count = len(list(SPRITES_DIR.glob("*.png"))) if SPRITES_DIR.exists() else 0

        if HIST_CACHE_PATH.exists():
            try:
                with open(HIST_CACHE_PATH, "rb") as f:
                    cached = pickle.load(f)
                if (
                    cached.get("_version") == _CACHE_VERSION
                    and cached.get("_count") == sprite_count
                    and sprite_count > 0
                ):
                    self._phashes = {k: v for k, v in cached.items() if not k.startswith("_")}
                    logger.info("pHash キャッシュ読み込み: %d 件", len(self._phashes))
                    return
            except Exception:
                pass

        self._build_cache(sprite_count)

    def _build_cache(self, sprite_count: int):
        if not SPRITES_DIR.exists() or sprite_count == 0:
            logger.warning("スプライトが見つかりません: %s", SPRITES_DIR)
            logger.warning("  先に python scripts/download_sprites.py を実行してください")
            return

        logger.info("pHash キャッシュ構築中 (%d 件)...", sprite_count)
        valid_keys = set(self._names.keys())
        built = 0
        for png in SPRITES_DIR.glob("*.png"):
            key = png.stem
            if key not in valid_keys:
                continue
            try:
                img = Image.open(png).convert("RGBA")
                # アルファチャンネルがある場合は透明部分を白に
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
                self._phashes[key] = compute_phash(bg)
                built += 1
            except Exception as e:
                logger.debug("スプライト読み込み失敗 %s: %s", key, e)

        cache: dict = dict(self._phashes)
        cache["_version"] = _CACHE_VERSION
        cache["_count"] = sprite_count
        with open(HIST_CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)
        logger.info("pHash キャッシュ保存: %d 件", built)

    def find_best_match(
        self, icon_bgr: "np.ndarray", top_n: int = 3
    ) -> list[tuple[str, str, float]]:
        """
        アイコン画像と最も類似するポケモンを返す。
        Returns: [(key, name_ja, score), ...] 上位 top_n 件（score は 0–1）
        """
        if not self._phashes:
            return []

        # 背景除去してから pHash 計算
        pil_clean = _remove_bg(icon_bgr)
        query_hash = compute_phash(pil_clean)

        scores = []
        for key, tmpl_hash in self._phashes.items():
            score = phash_score(query_hash, tmpl_hash)
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
        self._phashes.clear()
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

    mask = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([0,   80, 30]), np.array([15,  255, 180])),
        cv2.inRange(hsv, np.array([165, 80, 30]), np.array([180, 255, 180])),
    )
    k = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)

    row_red   = mask.sum(axis=1) / 255
    threshold = (px2 - px1) * 0.20
    in_tile   = row_red > threshold

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

    header_limit = int(len(in_tile) * 0.10)
    bands = [(s, e) for s, e in bands if s >= header_limit]

    min_h = h * 0.04
    bands = [(s, e) for s, e in bands if (e - s) >= min_h]

    bands.sort(key=lambda b: b[1] - b[0], reverse=True)
    bands = bands[:n_slots]
    bands.sort(key=lambda b: b[0])

    if len(bands) < n_slots:
        logger.warning("赤タイル検出: %d/%d 件のみ検出", len(bands), n_slots)
        return None

    heights    = sorted(e - s for s, e in bands)
    ref_height = int(heights[len(heights) // 2] * 0.88)
    icon_w     = int((px2 - px1) * 0.65)

    slots = [
        (px1, s, px1 + icon_w, s + ref_height)
        for s, _ in bands
    ]
    logger.info("赤タイル自動検出成功: %d スロット (高さ %dpx 幅 %dpx)", len(slots), ref_height, icon_w)
    return slots


# ─────────────────────────────────────────────────────────────────────────────
# チーム検出
# ─────────────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    if REGION_CONFIG_PATH.exists():
        try:
            with open(REGION_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return REGION_CONFIG


def detect_opponent_team(
    image: "Image.Image",
    db: SpriteDatabase,
    config: dict | None = None,
) -> list[tuple[str, str, float]]:
    """
    チーム選択画面の右パネルから相手チーム最大6体を検出する。
    """
    cfg = config or _load_config()
    w, h = image.size

    use_manual = config is None and REGION_CONFIG_PATH.exists()
    if use_manual:
        slots = None
        logger.info("キャリブレーション済み設定を使用 (自動検出スキップ)")
    else:
        slots = auto_detect_slots(image, panel_x1=cfg["panel_x1"], panel_x2=cfg["panel_x2"])

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
    debug_imgs = []
    for ix1, iy1, ix2, iy2 in slots:
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        icon_img = image.crop((ix1, iy1, ix2, iy2))
        debug_imgs.append(icon_img)

        if HAS_CV2:
            icon_bgr = _pil_to_bgr(icon_img)
            matches  = db.find_best_match(icon_bgr, top_n=1)
        else:
            # cv2 なしフォールバック：PIL で直接 pHash
            query_hash = compute_phash(icon_img)
            scores = [
                (k, phash_score(query_hash, h))
                for k, h in db._phashes.items()
            ]
            scores.sort(key=lambda x: x[1], reverse=True)
            matches = [(k, db._names.get(k, k), s) for k, s in scores[:1]]

        if matches:
            key, name_ja, score = matches[0]
            results.append((key, name_ja, float(score)))
            logger.info("Slot %d: %s (score=%.3f)", len(results), name_ja, score)

    # デバッグ用：検出したスロット画像を横並びで保存
    if debug_imgs and HAS_CV2:
        try:
            strip = np.hstack([
                cv2.resize(_pil_to_bgr(img), (80, 80))
                for img in debug_imgs
            ])
            cv2.imwrite("debug_opp_slots.png", strip)
        except Exception:
            pass

    return results
