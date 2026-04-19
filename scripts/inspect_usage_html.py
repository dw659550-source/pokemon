#!/usr/bin/env python3
"""
pokechamdb.com の HTML 構造を調べて、技/持ち物/パートナーのデータがどこにあるか特定する。
Windows PowerShell 対応（head コマンド不要）。

使い方:
  python scripts/inspect_usage_html.py
  python scripts/inspect_usage_html.py garchomp
"""
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import requests
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    print("pip install requests beautifulsoup4 が必要です")
    sys.exit(1)

from scraper.usage_scraper import BASE_URL, HEADERS


def ancestors_summary(tag) -> str:
    """タグの祖先要素（class付き）を / で連結して返す"""
    parts = []
    for p in tag.parents:
        if p.name in (None, "[document]"):
            break
        cls = " ".join(p.get("class", []))[:40]
        if cls:
            parts.append(f"{p.name}.{cls}")
        else:
            parts.append(p.name)
        if len(parts) >= 5:
            break
    return " > ".join(reversed(parts))


def find_pct_elements(soup):
    """% を含むテキストノードを持つ要素を列挙"""
    pct_re = re.compile(r'\d+\.?\d*\s*%')
    results = []
    for tag in soup.find_all(True):
        direct_text = "".join(
            str(c) for c in tag.children if isinstance(c, NavigableString)
        ).strip()
        if pct_re.search(direct_text):
            results.append((tag, direct_text))
    return results


def print_section(title, items, limit=15):
    print(f"\n{'='*60}")
    print(f"  {title}  ({len(items)} 件)")
    print(f"{'='*60}")
    for i, item in enumerate(items[:limit]):
        print(f"  [{i}] {item}")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "garchomp"
    url = BASE_URL.format(name=name)
    print(f"URL: {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"ステータス: {r.status_code}")
    except Exception as e:
        print(f"接続失敗: {e}")
        return

    if r.status_code != 200:
        print(f"エラー: {r.text[:300]}")
        return

    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # ── 1. 見出し一覧 ──
    headings = [(h.name, h.get_text(strip=True)) for h in soup.find_all(re.compile(r'^h[1-6]$'))]
    print_section("見出し (h1-h6)", [f"<{n}> {t}" for n, t in headings])

    # ── 2. % を含む要素とその祖先 ──
    pct_elems = find_pct_elements(soup)
    print_section("% を含む要素（上位15件）", [
        f"{e.name} | text={t!r:.50} | ancestors={ancestors_summary(e):.80}"
        for e, t in pct_elems
    ])

    # ── 3. % を含む要素の近傍テキスト（名前を探す）──
    print(f"\n{'='*60}")
    print("  % 要素のコンテキスト（前後の兄弟 / 親テキスト）")
    print(f"{'='*60}")
    for idx, (elem, direct_text) in enumerate(pct_elems[:20]):
        parent = elem.parent
        sibs = [s.get_text(strip=True) for s in parent.children
                if s.name and s.get_text(strip=True)]
        print(f"  [{idx}] % テキスト={direct_text!r}")
        print(f"        親タグ={parent.name} class={' '.join(parent.get('class', []))[:60]!r}")
        print(f"        親の子テキスト={sibs[:6]}")

    # ── 4. 'space-y' クラスを持つ div の中身 ──
    print(f"\n{'='*60}")
    print("  space-y-* クラス を持つ div（セクションコンテナ候補）")
    print(f"{'='*60}")
    for div in soup.find_all("div", class_=re.compile(r'space-y')):
        cls = " ".join(div.get("class", []))
        children_names = [
            f"{c.name}({' '.join(c.get('class',[]))[:30]})"
            for c in div.children if hasattr(c, "name") and c.name
        ]
        text_preview = div.get_text(" ", strip=True)[:80]
        print(f"  div.{cls[:60]}")
        print(f"    子要素: {children_names[:8]}")
        print(f"    テキスト: {text_preview!r}")
        print()

    # ── 5. rounded-2xl / rounded クラスを持つ div（カード候補）──
    print(f"\n{'='*60}")
    print("  rounded-2xl / rounded クラスを持つ div（カード候補）（上位10件）")
    print(f"{'='*60}")
    cards = soup.find_all("div", class_=re.compile(r'rounded'))
    for card in cards[:10]:
        cls = " ".join(card.get("class", []))
        text = card.get_text(" ", strip=True)[:100]
        print(f"  div.{cls[:60]}")
        print(f"    {text!r}")
        print()

    # ── 6. section タグ ──
    sections = soup.find_all("section")
    print_section("section タグ", [
        f"class={' '.join(s.get('class',[]))[:50]} text={s.get_text(' ',strip=True)[:60]!r}"
        for s in sections
    ])

    # ── 7. bg-gradient クラスを持つ要素（プログレスバー候補）──
    print(f"\n{'='*60}")
    print("  bg-gradient クラスを持つ要素（プログレスバー候補）")
    print(f"{'='*60}")
    for elem in soup.find_all(class_=re.compile(r'bg-gradient')):
        cls = " ".join(elem.get("class", []))
        style = elem.get("style", "")
        text = elem.get_text(strip=True)[:60]
        print(f"  {elem.name}.{cls[:60]}")
        print(f"    style={style!r}  text={text!r}")
        print()

    # ── 8. inline style で width % を持つ要素 ──
    print(f"\n{'='*60}")
    print("  style='width: XX%' を持つ要素（バー候補）")
    print(f"{'='*60}")
    for elem in soup.find_all(style=re.compile(r'width\s*:\s*\d')):
        style = elem.get("style", "")
        cls = " ".join(elem.get("class", []))[:40]
        parent_text = elem.parent.get_text(" ", strip=True)[:80] if elem.parent else ""
        print(f"  {elem.name}.{cls}  style={style!r}")
        print(f"    親テキスト: {parent_text!r}")
        print()


if __name__ == "__main__":
    main()
