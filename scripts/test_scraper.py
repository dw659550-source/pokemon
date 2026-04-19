#!/usr/bin/env python3
"""
使用率スクレイパーの動作確認スクリプト。
Windows 機から実行してください。

使い方:
  python scripts/test_scraper.py
  python scripts/test_scraper.py garchomp      # ポケモン名を直接指定
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

from scraper.usage_scraper import fetch_usage_data, BASE_URL, HEADERS


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "garchomp"
    url = BASE_URL.format(name=name)
    print(f"URL: {url}")

    # まず生アクセスを確認
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"ステータス: {r.status_code}")
        if r.status_code != 200:
            print(f"エラー内容: {r.text[:300]}")
            print()
            print("URL フォーマットが違う可能性があります。")
            print("ブラウザで pokechamdb.com を開いてポケモンページの URL を確認してください。")
            return
    except Exception as e:
        print(f"接続失敗: {e}")
        return

    # パース
    try:
        data = fetch_usage_data(name)
        print(f"\n技 ({len(data['moves'])} 件):")
        for n, p in data["moves"][:5]:
            print(f"  {n}: {p:.1f}%")
        print(f"\n持ち物 ({len(data['items'])} 件):")
        for n, p in data["items"][:5]:
            print(f"  {n}: {p:.1f}%")
        if not data["moves"] and not data["items"]:
            print("データが取得できませんでした。HTML 構造が変わった可能性があります。")
            # HTML を保存してデバッグ用に出力
            out = Path("scraper_debug.html")
            out.write_text(r.text, encoding="utf-8")
            print(f"HTML を {out} に保存しました（構造確認用）")
    except Exception as e:
        print(f"パース失敗: {e}")


if __name__ == "__main__":
    main()
