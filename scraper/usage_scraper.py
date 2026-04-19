"""
pokechamdb.com から各ポケモンの使用率データ（技・持ち物・パートナー）を取得しキャッシュする。
"""
import json
import re
import logging
import time
import urllib.parse
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup, NavigableString
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "data" / "usage_cache.json"
BASE_URL = "https://pokechamdb.com/pokemon/{name}?season=M-1&format=single"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9",
}

_MOVES_PATH = Path(__file__).parent.parent / "data" / "moves.json"
_ITEMS_PATH = Path(__file__).parent.parent / "data" / "items.json"
_POKEMON_PATH = Path(__file__).parent.parent / "data" / "pokemon.json"

_MOVE_JA: dict[str, str] = {}
_ITEM_JA: dict[str, str] = {}
_POKE_JA: dict[str, str] = {}


def _ensure_maps():
    global _MOVE_JA, _ITEM_JA, _POKE_JA
    if not _MOVE_JA:
        try:
            with open(_MOVES_PATH, encoding="utf-8") as f:
                moves = json.load(f)
            _MOVE_JA = {v["name_ja"]: k for k, v in moves.items() if "name_ja" in v}
        except Exception:
            pass
    if not _ITEM_JA:
        try:
            with open(_ITEMS_PATH, encoding="utf-8") as f:
                items = json.load(f)
            _ITEM_JA = {v["name_ja"]: k for k, v in items.items() if "name_ja" in v}
        except Exception:
            pass
    if not _POKE_JA:
        try:
            with open(_POKEMON_PATH, encoding="utf-8") as f:
                pokes = json.load(f)
            _POKE_JA = {v["name_ja"]: k for k, v in pokes.items() if "name_ja" in v}
        except Exception:
            pass


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _pct_from_text(text: str) -> float | None:
    """テキストから % 値を抽出"""
    m = re.search(r'(\d+\.?\d*)\s*%', text)
    if m:
        return float(m.group(1))
    return None


def _pct_from_style(style: str) -> float | None:
    """style 属性の width: XX% から数値を抽出"""
    m = re.search(r'width\s*:\s*(\d+\.?\d*)\s*%', style)
    if m:
        return float(m.group(1))
    return None


def _is_junk_name(name: str) -> bool:
    """ランク番号・日付・統計値など名前として無効な文字列を弾く"""
    if not name:
        return True
    if re.fullmatch(r'[\d.,\s%/\-]+', name):
        return True
    # ISO 日付
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', name):
        return True
    # 短すぎる（1文字）
    if len(name) <= 1:
        return True
    return False


def _parse_page(html: str) -> dict:
    """HTML から技・持ち物・パートナーの使用率をパース"""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, list] = {"moves": [], "items": [], "partners": []}

    logger.debug("Page title: %s", soup.title.string if soup.title else "N/A")

    # ── 方法1: style="width: XX%" を持つ要素（Tailwind プログレスバー）──
    # pokechamdb.com では各行が
    #   <div class="flex ...">
    #     <span>技名</span>
    #     <div class="relative flex-1">
    #       <div class="absolute bg-gradient-to-r ..." style="width: 75.3%"></div>
    #     </div>
    #     <span>75.3%</span>   ← あるいは % テキストがここ
    #   </div>
    # のような構造と推定される。
    _parse_style_width_bars(soup, result)

    # ── 方法2: h2/h3 見出しでセクション分け ──
    if not any(result.values()):
        _parse_by_heading(soup, result)

    # ── 方法3: クラス名パターン ──
    if not any(result.values()):
        _parse_by_class(soup, result)

    # ── 方法4: 全テーブル総なめ（フォールバック）──
    if not any(result.values()):
        _parse_all_tables(soup, result)

    logger.info("Parsed: moves=%d items=%d partners=%d",
                len(result["moves"]), len(result["items"]), len(result["partners"]))
    return result


# ── セクション見出しキーワード ──────────────────────────────────────────────
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "moves":    ["技", "わざ", "move", "わざ使用率"],
    "items":    ["持ち物", "もちもの", "item", "道具", "持ち物使用率"],
    "partners": ["パートナー", "相方", "partner", "一緒", "よく一緒"],
}

_EV_STAT_NAMES = {"hp", "攻", "防", "特攻", "特防", "素早", "採用率", "順位",
                  "hp", "atk", "def", "spa", "spd", "spe"}

def _guess_section(text: str) -> str | None:
    t = text.lower()
    for cat, kws in _SECTION_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return cat
    return None


def _parse_style_width_bars(soup, result: dict):
    """
    style="width: XX%" を持つ div をプログレスバーとみなし、
    親フレックス行から名前・割合を抽出する。
    セクションは直近の見出しで判定。
    """
    current_section: str | None = None
    collected: dict[str, list] = {"moves": [], "items": [], "partners": []}

    # ドキュメント順に走査
    for elem in soup.find_all(True):
        # 見出しに当たったらセクションを更新
        if elem.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            txt = elem.get_text(strip=True)
            cat = _guess_section(txt)
            if cat:
                current_section = cat
            elif current_section:
                # 無関係な見出しが来たらリセット（EV見出し等）
                ev_like = any(kw in txt for kw in ["努力値", "EV", "種族値", "採用率"])
                if ev_like:
                    current_section = None
            continue

        # style="width: XX%" を持つ要素
        style = elem.get("style", "")
        if not style:
            continue
        pct = _pct_from_style(style)
        if pct is None or pct <= 0:
            continue

        # 親の行（flex コンテナ）からテキストを収集
        row = elem.parent
        if row is None:
            continue
        # 2階層まで遡って flex 行を探す
        for _ in range(3):
            cls = " ".join(row.get("class", []))
            if "flex" in cls or row.name in ("li", "tr"):
                break
            if row.parent:
                row = row.parent

        # 行内の直接テキストノードまたは子テキストを収集
        texts = []
        for child in row.children:
            if isinstance(child, NavigableString):
                t = child.strip()
                if t:
                    texts.append(t)
            elif hasattr(child, "get_text"):
                # バー要素はスキップ
                if child.get("style") and "width" in child.get("style", ""):
                    continue
                t = child.get_text(strip=True)
                if t:
                    texts.append(t)

        # % テキスト・ランク番号・ゴミを除いた名前候補
        name = ""
        for t in texts:
            if _pct_from_text(t) is not None:
                continue
            if re.fullmatch(r'\d+', t):
                continue
            if _is_junk_name(t):
                continue
            name = t
            break

        if not name:
            continue

        if current_section:
            collected[current_section].append((name, pct))
        else:
            # セクション不明 → 後で分類を試みる
            logger.debug("section unknown for %r pct=%.1f", name, pct)

    for cat in ("moves", "items", "partners"):
        if collected[cat]:
            result[cat] = collected[cat][:10]


def _parse_by_heading(soup, result: dict):
    """見出しタグでセクションを区切り、後続のテーブル/リストをパース"""
    SECTION_KEYWORDS = {
        "moves":    ["技", "わざ", "move"],
        "items":    ["持ち物", "もちもの", "item", "道具"],
        "partners": ["パートナー", "相方", "partner", "一緒"],
    }

    all_headings = soup.find_all(re.compile(r"^h[1-6]$"))
    sections_found = {}
    for h in all_headings:
        text = h.get_text(strip=True).lower()
        for cat, keywords in SECTION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                sections_found[cat] = h
                break

    for cat, heading_tag in sections_found.items():
        sibling = heading_tag.find_next_sibling()
        items_found = []
        while sibling and sibling.name not in ("h1","h2","h3","h4","h5","h6"):
            rows = []
            if sibling.name == "table":
                rows = sibling.find_all("tr")
            elif sibling.name in ("ul", "ol"):
                rows = sibling.find_all("li")
            elif sibling.name == "div":
                sub = sibling.find("table")
                if sub:
                    rows = sub.find_all("tr")
                else:
                    rows = sibling.find_all(re.compile(r"^(div|p|li)$"))

            for row in rows:
                cells = row.find_all(["td", "th", "span", "div"])
                texts = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
                for i in range(len(texts) - 1, -1, -1):
                    pct = _pct_from_text(texts[i])
                    if pct is not None and pct > 0:
                        name = texts[0] if i > 0 else ""
                        if re.fullmatch(r'\d+', name):
                            name = texts[1] if len(texts) > 1 else ""
                        if name and not _is_junk_name(name):
                            items_found.append((name, pct))
                        break
            sibling = sibling.find_next_sibling()

        result[cat] = items_found[:10]


def _parse_by_class(soup, result: dict):
    """クラス名の文字列パターンで技・持ち物・パートナーを推定"""
    CLASS_CAT = [
        ("moves",    re.compile(r'move|waza|skill', re.I)),
        ("items",    re.compile(r'item|hold|tool|mochi', re.I)),
        ("partners", re.compile(r'partner|ally|friend', re.I)),
    ]
    for cat, pat in CLASS_CAT:
        containers = soup.find_all(attrs={"class": pat})
        for c in containers:
            rows = c.find_all(re.compile(r"^(tr|li|div)$"))
            for row in rows:
                text = row.get_text("|", strip=True)
                parts = [p for p in text.split("|") if p]
                if len(parts) >= 2:
                    for i, p in enumerate(reversed(parts)):
                        pct = _pct_from_text(p)
                        if pct and pct > 0:
                            name_idx = len(parts) - 1 - i - 1
                            if name_idx >= 0:
                                name = parts[name_idx]
                                if name and not _is_junk_name(name):
                                    result[cat].append((name, pct))
                            break
        result[cat] = result[cat][:10]


def _parse_all_tables(soup, result: dict):
    """全テーブルの行をパースして使用率データを抽出（フォールバック）"""
    all_rows = []
    for table in soup.find_all("table"):
        # EV 表（HP/攻/防… 列を持つ）はスキップ
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if any(h in _EV_STAT_NAMES for h in headers):
            continue
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])]
            if cells:
                all_rows.append(cells)

    ranked_items = []
    for cells in all_rows:
        for i, c in enumerate(cells):
            pct = _pct_from_text(c)
            if pct and 0 < pct <= 100 and len(cells) >= 2:
                name = cells[i-1] if i > 0 else ""
                if re.fullmatch(r'\d+', name) and i >= 2:
                    name = cells[i-2]
                if name and not _is_junk_name(name):
                    ranked_items.append((name, pct))
                break

    if ranked_items and not result["moves"]:
        result["moves"] = ranked_items[:10]


def _pokemon_name_ja(pokemon_key: str) -> str:
    """pokemon.json から日本語名を返す（なければキーをそのまま）"""
    try:
        with open(_POKEMON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(pokemon_key, {}).get("name_ja", pokemon_key)
    except Exception:
        return pokemon_key


def fetch_usage_data(pokemon_key: str) -> dict:
    """pokechamdb.com から使用率データをフェッチしてパース。
    英語キー → 404 なら日本語名で再試行。"""
    if not HAS_DEPS:
        raise RuntimeError("requests と beautifulsoup4 が必要です")

    candidates = [
        pokemon_key,
        urllib.parse.quote(_pokemon_name_ja(pokemon_key)),
    ]

    for name in candidates:
        url = BASE_URL.format(name=name)
        logger.info("Fetching: %s", url)
        try:
            resp = requests.get(url, timeout=15, headers=HEADERS)
            if resp.status_code == 404:
                logger.debug("404 for %s, trying next", name)
                continue
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return _parse_page(resp.text)
        except Exception as e:
            if "404" in str(e):
                continue
            raise

    logger.info("使用率データなし（未登録）: %s", pokemon_key)
    return {"moves": [], "items": [], "partners": []}


def get_usage_data(pokemon_key: str, force_refresh: bool = False) -> dict | None:
    """
    キャッシュから使用率データを返す。なければフェッチしてキャッシュ。

    Returns:
        {"moves": [(name, pct), ...], "items": [...], "partners": [...]} or None
    """
    _ensure_maps()
    cache = _load_cache()

    if not force_refresh and pokemon_key in cache:
        logger.debug("Cache hit: %s", pokemon_key)
        return cache[pokemon_key]

    try:
        data = fetch_usage_data(pokemon_key)
        cache[pokemon_key] = data
        _save_cache(cache)
        return data
    except Exception as e:
        logger.info("使用率取得失敗 %s: %s", pokemon_key, e)
        return None


def clear_cache():
    """キャッシュをクリア"""
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
