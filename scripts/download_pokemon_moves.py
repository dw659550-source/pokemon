#!/usr/bin/env python3
"""
PokeAPI から各ポケモンのスカーレット・バイオレット覚え技一覧を
data/pokemon_moves.json にダウンロードする。

使い方:
  python scripts/download_pokemon_moves.py
"""
import json, time, sys
from pathlib import Path
try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)

OUT          = Path(__file__).parent.parent / "data" / "pokemon_moves.json"
POKEMON_PATH = Path(__file__).parent.parent / "data" / "pokemon.json"
BASE         = "https://pokeapi.co/api/v2"
SV_GROUP     = "scarlet-violet"


def get(url, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def main():
    with open(POKEMON_PATH, encoding="utf-8") as f:
        pokemon_data = json.load(f)
    keys = [k for k in pokemon_data if not k.startswith("_")]

    existing: dict[str, list] = {}
    if OUT.exists():
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f)

    done = skip = fail = 0
    total = len(keys)
    print(f"ポケモン数: {total}")

    for i, key in enumerate(keys, 1):
        if key in existing:
            skip += 1
            continue
        try:
            data = get(f"{BASE}/pokemon/{key}").json()
            moves = []
            for entry in data.get("moves", []):
                move_key = entry["move"]["name"]
                for vgd in entry.get("version_group_details", []):
                    if vgd["version_group"]["name"] == SV_GROUP:
                        moves.append(move_key)
                        break
            existing[key] = moves
            done += 1
        except Exception as e:
            existing[key] = []
            fail += 1
            if "404" not in str(e):
                print(f"  {key}: 失敗 ({e})")

        if i % 50 == 0:
            print(f"  {i}/{total} 完了 (取得={done} スキップ={skip} 失敗={fail})")
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False)
        time.sleep(0.1)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    print(f"\n完了: 取得={done} スキップ={skip} 失敗={fail} → {OUT}")


if __name__ == "__main__":
    main()
