#!/usr/bin/env python3
"""
使用率スクレイパーの動作確認スクリプト。
Windows 機から実行してください。

使い方:
  python scripts/test_scraper.py
  python scripts/test_scraper.py garchomp
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("pip install requests beautifulsoup4 が必要です")
    sys.exit(1)

from scraper.usage_scraper import BASE_URL, HEADERS, _parse_page


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "garchomp"
    url = BASE_URL.format(name=name)
    print(f"URL: {url}\n")

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"ステータス: {r.status_code}")
    except Exception as e:
        print(f"接続失敗: {e}")
        return

    if r.status_code != 200:
        print(f"エラー内容: {r.text[:500]}")
        print("\n→ ブラウザで pokechamdb.com を開き、ポケモンページの URL を確認してください。")
        return

    # HTML を保存
    debug_html = Path("scraper_debug.html")
    debug_html.write_text(r.text, encoding="utf-8")
    print(f"HTML 保存: {debug_html} ({len(r.text)} bytes)")

    # BeautifulSoup でページ構造を簡易確認
    soup = BeautifulSoup(r.text, "html.parser")
    print(f"タイトル: {soup.title.string if soup.title else 'なし'}")
    headings = [h.get_text(strip=True) for h in soup.find_all(["h1","h2","h3"])]
    print(f"見出し: {headings[:10]}")
    tables = soup.find_all("table")
    print(f"テーブル数: {len(tables)}")

    # パース試行
    data = _parse_page(r.text)
    print(f"\n技 ({len(data['moves'])} 件): {data['moves'][:5]}")
    print(f"持ち物 ({len(data['items'])} 件): {data['items'][:5]}")

    if not data["moves"] and not data["items"]:
        print("\n→ パース失敗。scraper_debug.html を見てサイト構造を確認してください。")
        print("  見出しやテーブルのクラス名を教えてもらえれば修正できます。")


if __name__ == "__main__":
    main()
