#!/usr/bin/env python3
"""PokeAPI から全技データ（日本語名・カテゴリ・威力・タイプ）を data/moves.json にダウンロードする"""
import json, time, sys
from pathlib import Path
try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)

OUT  = Path(__file__).parent.parent / "data" / "moves.json"
BASE = "https://pokeapi.co/api/v2"

CATEGORY_MAP = {"damage": "physical", "ailment": "status", "net-good-stats": "status",
                "heal": "status", "damage+ailment": "physical", "swagger": "status",
                "damage+lower": "physical", "damage+raise": "physical",
                "damage+heal": "physical", "ohko": "physical", "whole-field-effect": "status",
                "field-effect": "status", "force-switch": "status", "unique": "status"}

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

    resp = get(f"{BASE}/move?limit=2000").json()
    all_moves = resp["results"]
    print(f"技数: {len(all_moves)}")

    done = skip = fail = 0
    for i, mv in enumerate(all_moves, 1):
        key = mv["name"]
        if key in existing and existing[key].get("name_ja"):
            skip += 1
            continue
        try:
            data = get(mv["url"]).json()

            name_ja = next(
                (n["name"] for n in data.get("names", [])
                 if n["language"]["name"] == "ja"),
                ""
            )
            if not name_ja:
                skip += 1
                continue

            # カテゴリ（物理/特殊/変化）
            dc = data.get("damage_class", {}).get("name", "")
            category = dc  # physical / special / status

            power   = data.get("power")    # None or int
            pp      = data.get("pp")
            type_   = data.get("type", {}).get("name", "")
            acc     = data.get("accuracy")

            existing[key] = {
                "name_ja":  name_ja,
                "category": category,
                "power":    power,
                "pp":       pp,
                "type":     type_,
                "accuracy": acc,
            }
            done += 1
        except Exception as e:
            print(f"  {key}: 失敗 ({e})")
            fail += 1

        if i % 100 == 0:
            print(f"  {i}/{len(all_moves)} 完了 (取得={done} スキップ={skip})")
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        time.sleep(0.05)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"\n完了: 取得={done} スキップ={skip} 失敗={fail} → {OUT}")

if __name__ == "__main__":
    main()
