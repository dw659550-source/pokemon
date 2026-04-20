#!/usr/bin/env python3
"""PokeAPI から全特性の日本語名・説明を data/abilities.json にダウンロードする"""
import json, time, sys
from pathlib import Path
try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)

OUT = Path(__file__).parent.parent / "data" / "abilities.json"
BASE = "https://pokeapi.co/api/v2"

def get(url, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=10); r.raise_for_status(); return r
        except Exception as e:
            if i == retries - 1: raise
            time.sleep(1)

def main():
    existing = {}
    if OUT.exists():
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)

    resp = get(f"{BASE}/ability?limit=400").json()
    all_abilities = resp["results"]
    print(f"特性数: {len(all_abilities)}")

    done = skip = fail = 0
    for i, ab in enumerate(all_abilities, 1):
        key = ab["name"]
        # 説明が空のエントリは再取得する
        entry = existing.get(key)
        if entry and (entry.get("description_ja") or entry.get("description_en")):
            skip += 1
            continue
        try:
            data = get(ab["url"]).json()
            # 日本語名
            name_ja = next(
                (n["name"] for n in data.get("names", [])
                 if n["language"]["name"] == "ja"),
                key
            )
            # 日本語説明（最新世代を優先）
            desc_ja = ""
            for fe in reversed(data.get("flavor_text_entries", [])):
                if fe["language"]["name"] == "ja":
                    desc_ja = fe["flavor_text"].replace("\n", " ").replace("\u00ad", "")
                    break
            # 英語説明（日本語がない場合のフォールバック）
            desc_en = ""
            if not desc_ja:
                for fe in reversed(data.get("flavor_text_entries", [])):
                    if fe["language"]["name"] == "en":
                        desc_en = fe["flavor_text"].replace("\n", " ")
                        break
            existing[key] = {"name_ja": name_ja, "description_ja": desc_ja,
                             "description_en": desc_en}
            done += 1
        except Exception as e:
            print(f"  {key}: 失敗 ({e})")
            fail += 1
        if i % 50 == 0:
            print(f"  {i}/{len(all_abilities)} 完了")
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        time.sleep(0.08)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"\n完了: 取得={done} スキップ={skip} 失敗={fail} → {OUT}")

if __name__ == "__main__":
    main()
