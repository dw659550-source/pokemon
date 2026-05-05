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
    "panel_x2": 0.960,   # 実際のパネル右端（1.000だとゲーム背景が入る）
    "slot_tops":   [0.126, 0.255, 0.380, 0.508, 0.635, 0.762],
    "slot_height": 0.118,
    "icon_x1": 0.00,
    "icon_x2": 0.55,     # タイプアイコン開始位置（0.65だと右にズレる）
}

# pHash キャッシュバージョン（旧ヒストグラムキャッシュを無効化）
_CACHE_VERSION = 3

# ── タイプアイコン色定義（OpenCV HSV: H=0-180, S=0-255, V=0-255）─────────
# 各タイプの標準カラーをHSVに変換した近似値
# (H_lo, H_hi, S_lo, S_hi, V_lo, V_hi)
_TYPE_HSV: dict[str, tuple] = {
    "fire":     (10,  25, 160, 255, 180, 255),
    "water":    (100, 122, 100, 255, 140, 255),
    "grass":    (45,  75,  80, 255, 100, 235),
    "electric": (22,  38, 160, 255, 200, 255),
    "ice":      (85, 106,  40, 185, 165, 255),
    "fighting": ( 0,  12, 120, 255,  80, 215),
    "poison":   (130, 155,  80, 255,  80, 220),
    "ground":   (15,  32,  50, 165, 150, 255),
    "flying":   (115, 142,  30, 165, 160, 255),
    "psychic":  (155, 180, 100, 255, 145, 255),
    "bug":      (35,  66, 150, 255,  90, 225),
    "rock":     (15,  35, 120, 255,  95, 205),
    "ghost":    (125, 150,  35, 205,  50, 175),
    "dragon":   (120, 142, 150, 255, 175, 255),
    "dark":     ( 5,  35,  25, 125,  15, 125),
    "steel":    (85, 142,   5,  85, 115, 225),
    "fairy":    (148, 180,  55, 255, 145, 255),
    "normal":   (18,  42,  10, 105, 125, 235),
}
# タイルの暗赤背景（H≈172-175）を除外するための基準値
_TILE_BG_H_LO, _TILE_BG_H_HI = 162, 180  # crimson tile hue range
_TILE_BG_S_LO = 150                        # 背景は高彩度

# ラップアラウンド判定（現在は使用なし）
_TYPE_HSV_WRAP: dict[str, tuple] = {}


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
        self._types: dict[str, list[str]] = {}  # key → ["fire", "flying"] etc.
        self._load_pokemon_names()
        self._load_or_build_cache()

    def _load_pokemon_names(self):
        try:
            with open(POKEMON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self._names = {k: v.get("name_ja", k) for k, v in data.items()}
            self._types = {k: v.get("types", []) for k, v in data.items()}
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

    def find_best_match_typed(
        self,
        icon_bgr: "np.ndarray",
        detected_types: list[str],
        top_n: int = 3,
    ) -> list[tuple[str, str, float]]:
        """
        タイプで候補を絞ってから pHash マッチング。
        detected_types が空の場合は全件対象（fallback）。
        Returns: [(key, name_ja, score), ...]
        """
        if not self._phashes:
            return []

        if detected_types:
            type_set = set(detected_types)
            candidate_keys = {
                k for k, types in self._types.items()
                if k in self._phashes and type_set.intersection(types)
            }
            # 候補が少なすぎる場合は全件にフォールバック
            if len(candidate_keys) < 5:
                candidate_keys = set(self._phashes.keys())
                logger.debug("タイプ候補が少ないため全件フォールバック")
            else:
                logger.debug("タイプ絞り込み: %s → %d 体", detected_types, len(candidate_keys))
        else:
            candidate_keys = set(self._phashes.keys())

        pil_clean = _remove_bg(icon_bgr)
        query_hash = compute_phash(pil_clean)

        scores = [
            (k, phash_score(query_hash, self._phashes[k]))
            for k in candidate_keys
        ]
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
# タイプアイコン テンプレートマッチング
# ─────────────────────────────────────────────────────────────────────────────

TYPE_ICONS_DIR = Path(__file__).parent.parent / "data" / "type_icons"

# テンプレート画像キャッシュ {type_name: bgr_array}
_type_templates: dict[str, "np.ndarray"] | None = None

# Zone別バリアントテンプレート名 → 正規タイプ名
# （Zone1/Zone2で視覚的に異なるため別テンプレートを使う型）
_ZONE_VARIANT_MAP: dict[str, str] = {
    "steel_z1": "steel",
    "steel_z2": "steel",
    "dragon_z1": "dragon",
    "dragon_z2": "dragon",
    "bug_z1": "bug",
    "bug_z2": "bug",
}


def _load_type_templates() -> dict[str, "np.ndarray"]:
    """data/type_icons/ から PNG を読み込んでキャッシュ。"""
    global _type_templates
    if _type_templates is not None:
        return _type_templates

    _type_templates = {}
    if not HAS_CV2 or not TYPE_ICONS_DIR.exists():
        return _type_templates

    for png in TYPE_ICONS_DIR.glob("*.png"):
        tmpl = cv2.imread(str(png))
        if tmpl is not None:
            _type_templates[png.stem.lower()] = tmpl
            logger.debug("タイプアイコン読み込み: %s (%dx%d)", png.stem, tmpl.shape[1], tmpl.shape[0])

    logger.info("タイプアイコンテンプレート: %d 件", len(_type_templates))
    return _type_templates


def reload_type_templates():
    """テンプレートキャッシュをクリアして再読み込みさせる。"""
    global _type_templates
    _type_templates = None


def _detect_type_by_zone_color(
    type_area_bgr: "np.ndarray",
    zx1: int,
    zx2: int,
    candidates: "list[str]",
) -> "str | None":
    """
    Zone列の非背景ピクセルの平均Hueを計算し、
    candidates の中で最も近い _TYPE_HSV のタイプを返す。

    テンプレートマッチングのスコアが拮抗している場合の
    タイブレーカーとして使う。
    """
    zone = type_area_bgr[:, zx1:zx2]
    if zone.size == 0:
        return None

    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.float32).flatten()
    s = hsv[:, :, 1].flatten()

    # 背景マスク: クリムゾンタイル (H≈0-12 or 165-180, 高彩度)
    is_bg = ((h < 12) | (h > 165)) & (s.astype(np.float32) > 100)
    icon_px = ~is_bg

    if icon_px.sum() < 10:
        logger.debug("  zone color: icon pixels too few (%d)", icon_px.sum())
        return None

    mean_h = float(h[icon_px].mean())
    logger.debug("  zone(%d-%d) mean_H=%.1f candidates=%s", zx1, zx2, mean_h, candidates)

    best_type: "str | None" = None
    best_dist = float("inf")
    for type_name in candidates:
        if type_name not in _TYPE_HSV:
            continue
        h_lo, h_hi = _TYPE_HSV[type_name][0], _TYPE_HSV[type_name][1]
        h_center = (h_lo + h_hi) / 2.0
        dist = abs(mean_h - h_center)
        if dist < best_dist:
            best_dist = dist
            best_type = type_name

    logger.debug("  zone color winner: %s (dist=%.1f)", best_type, best_dist)
    return best_type


def detect_slot_types(type_area_bgr: "np.ndarray", threshold: float = 0.58) -> list[str]:
    """
    スロット全幅画像に対してマルチスケールマッチングを行い、
    有効アイコンゾーン内のマッチのみを採用する（ゾーンフィルタ方式）。

    スコアが拮抗している場合（margin < COLOR_TIEBREAK_MARGIN）は
    HSVカラーによるタイブレークを行う。

    実測値: slot全幅294pxのとき、
      第1アイコン左端 ≈ x=195 (66.3%), 第2アイコン左端 ≈ x=244 (83.0%)
    アイコンゾーン:
      Zone0: x=183〜235  Zone1: x=235〜286

    type_area_bgr: スロット全幅・上部クロップの BGR 画像
    threshold: マッチスコアの閾値（0〜1）
    """
    # スコア差がこれ以下のとき HSV カラーでタイブレーク
    # ※ 現在 HSV レンジ未校正のため無効化中 (0.0 = 常に無効)
    COLOR_TIEBREAK_MARGIN = 0.0

    if not HAS_CV2 or type_area_bgr is None or type_area_bgr.size == 0:
        return []

    templates = _load_type_templates()
    if not templates:
        return []

    area_h, area_w = type_area_bgr.shape[:2]

    # 有効アイコンゾーン (slot全幅に対する比率)
    ZONES = [
        (int(area_w * 0.622), int(area_w * 0.799)),  # Zone0: 第1アイコン
        (int(area_w * 0.799), int(area_w * 0.972)),  # Zone1: 第2アイコン
    ]

    # scale=1.0 を含めることで「抽出時と同じ解像度」での精密比較を可能にする。
    # 下限 0.55: 0.65 だと一部テンプレート（fire 等）がしきい値を下回るため少し緩める。
    # 0.40 未満は全バッジが同形に見えて誤マッチするため除外。
    scales = np.arange(0.55, 1.05, 0.05)

    # 全テンプレートをフルエリアでスキャン
    all_results: list[tuple[str, float, int]] = []  # (type_name, score, best_x)
    for type_name, tmpl in templates.items():
        th, tw = tmpl.shape[:2]
        best_score = 0.0
        best_x = 0
        for scale in scales:
            nw = max(4, int(tw * scale))
            nh = max(4, int(th * scale))
            if nw > area_w or nh > area_h:
                continue
            tmpl_r = cv2.resize(tmpl, (nw, nh))
            result = cv2.matchTemplate(type_area_bgr, tmpl_r, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_x = max_loc[0]
        all_results.append((type_name, best_score, best_x))
        logger.debug("  %s: %.3f @x=%d", type_name, best_score, best_x)

    all_results.sort(key=lambda r: r[1], reverse=True)

    # ゾーン別に閾値以上の候補リストを構築 (canonical 名, score)
    zone_candidates: list[list[tuple[str, float]]] = [[] for _ in ZONES]
    for type_name, score, bx in all_results:
        if score < threshold:
            break
        canonical = _ZONE_VARIANT_MAP.get(type_name, type_name)
        for zi, (zx1, zx2) in enumerate(ZONES):
            if zx1 <= bx < zx2:
                zone_candidates[zi].append((canonical, score))
                break

    # ゾーンごとに勝者を決定 (必要なら HSV カラーでタイブレーク)
    detected: list[str] = []
    for zi, (zx1, zx2) in enumerate(ZONES):
        cands = zone_candidates[zi]
        if not cands:
            continue

        # 重複 canonical 名を除去しつつ順序保持
        seen: set[str] = set()
        unique_cands: list[tuple[str, float]] = []
        for t, s in cands:
            if t not in seen:
                seen.add(t)
                unique_cands.append((t, s))

        winner, top_score = unique_cands[0]

        if len(unique_cands) >= 2:
            second_score = unique_cands[1][1]
            margin = top_score - second_score
            if margin < COLOR_TIEBREAK_MARGIN:
                # 拮抗 → HSV カラーで再判定
                candidate_names = [t for t, _ in unique_cands]
                color_winner = _detect_type_by_zone_color(
                    type_area_bgr, zx1, zx2, candidate_names
                )
                if color_winner:
                    logger.debug(
                        "  Zone%d tiebreak: template=%s(%.3f) color→%s",
                        zi, winner, top_score, color_winner,
                    )
                    winner = color_winner

        if winner not in detected:
            detected.append(winner)

    logger.debug("タイプ検出(ゾーンフィルタ): %s", detected)
    return detected


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
    タイプアイコン色で候補を絞ってから pHash マッチングを行う。
    """
    cfg = config or _load_config()
    w, h = image.size

    use_manual = config is None and REGION_CONFIG_PATH.exists()
    if use_manual:
        slots = None
        logger.info("キャリブレーション済み設定を使用 (自動検出スキップ)")
    else:
        slots = auto_detect_slots(image, panel_x1=cfg["panel_x1"], panel_x2=cfg["panel_x2"])

    # slots は sprite_area 座標。type_slots はスロット全体座標（タイプアイコン用）
    panel_x1 = int(w * cfg["panel_x1"])
    panel_x2 = int(w * cfg["panel_x2"])

    if slots is None:
        logger.info("フォールバック: REGION_CONFIG を使用")
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
        # タイプアイコン用：スロット全幅の上 60%（固定位置パッチ方式のため全幅必須）
        type_slots = [
            (panel_x1,
             int(h * top),
             panel_x2,
             int(h * (top + cfg["slot_height"] * 0.60)))
            for top in cfg["slot_tops"]
        ]
    else:
        # auto_detect_slots の結果から右端エリアを計算
        type_slots = []
        for ix1, iy1, ix2, iy2 in slots:
            slot_w = panel_x2 - panel_x1
            type_x1 = ix1 + int((ix2 - ix1) / 0.65 * 0.65)  # icon_x2 位置
            type_slots.append((type_x1, iy1, panel_x2, iy1 + int((iy2 - iy1) * 0.60)))

    results = []
    debug_imgs = []
    for i, ((ix1, iy1, ix2, iy2), (tx1, ty1, tx2, ty2)) in enumerate(zip(slots, type_slots)):
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        icon_img = image.crop((ix1, iy1, ix2, iy2))
        debug_imgs.append(icon_img)

        # タイプアイコン検出
        detected_types: list[str] = []
        if HAS_CV2 and tx2 > tx1 and ty2 > ty1:
            type_img = image.crop((tx1, ty1, tx2, ty2))
            type_bgr = _pil_to_bgr(type_img)
            detected_types = detect_slot_types(type_bgr)

        if HAS_CV2:
            icon_bgr = _pil_to_bgr(icon_img)
            matches  = db.find_best_match_typed(icon_bgr, detected_types, top_n=1)
        else:
            # cv2 なしフォールバック：PIL で直接 pHash（タイプ絞り込みなし）
            query_hash = compute_phash(icon_img)
            scores = [
                (k, phash_score(query_hash, v))
                for k, v in db._phashes.items()
            ]
            scores.sort(key=lambda x: x[1], reverse=True)
            matches = [(k, db._names.get(k, k), s) for k, s in scores[:1]]

        if matches:
            key, name_ja, score = matches[0]
            results.append((key, name_ja, float(score)))
            logger.info("Slot %d: %s %s (score=%.3f)", i + 1, name_ja, detected_types, score)

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
