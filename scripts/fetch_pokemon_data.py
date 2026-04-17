#!/usr/bin/env python3
"""
PokeAPI から全ポケモンデータを取得して data/pokemon.json を生成するスクリプト。

【使い方】
1. pip install requests
2. python scripts/fetch_pokemon_data.py
3. 数分待つと data/pokemon.json が更新されます

※ インターネット接続が必要です
"""
import json
import time
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests が見つかりません。以下を実行してください：")
    print("  pip install requests")
    sys.exit(1)

BASE_URL = "https://pokeapi.co/api/v2"
OUT_PATH = Path(__file__).parent.parent / "data" / "pokemon.json"

TYPE_MAP = {
    "normal": "normal", "fire": "fire", "water": "water",
    "electric": "electric", "grass": "grass", "ice": "ice",
    "fighting": "fighting", "poison": "poison", "ground": "ground",
    "flying": "flying", "psychic": "psychic", "bug": "bug",
    "rock": "rock", "ghost": "ghost", "dragon": "dragon",
    "dark": "dark", "steel": "steel", "fairy": "fairy",
}

STAT_MAP = {
    "hp": "hp", "attack": "attack", "defense": "defense",
    "special-attack": "sp_attack", "special-defense": "sp_defense", "speed": "speed",
}


def get(url: str, retries=3) -> dict:
    for i in range(retries):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1)


def ja_name(names: list) -> str:
    """名前リストから日本語名を取得"""
    for n in names:
        if n["language"]["name"] == "ja":
            return n["name"]
    for n in names:
        if n["language"]["name"] == "ja-Hrkt":
            return n["name"]
    return ""


def fetch_all():
    print("全ポケモン一覧を取得中...")
    species_list = get(f"{BASE_URL}/pokemon-species?limit=2000")["results"]
    print(f"  {len(species_list)} 種類を取得しました")

    result = {}
    total = len(species_list)

    for i, species_ref in enumerate(species_list, 1):
        species_name = species_ref["name"]
        try:
            # 種族データ（日本語名・進化情報など）
            species_data = get(species_ref["url"])
            name_ja = ja_name(species_data.get("names", []))
            if not name_ja:
                name_ja = species_name  # フォールバック

            # 基本フォルムのポケモンデータ
            # フォルム違いがある場合 species_name では 404 になるため
            # varieties リストから is_default=True のURLを使う
            default_url = f"{BASE_URL}/pokemon/{species_name}"
            for v in species_data.get("varieties", []):
                if v["is_default"]:
                    default_url = v["pokemon"]["url"]
                    break
            poke_data = get(default_url)

            types = [t["type"]["name"] for t in poke_data["types"]
                     if t["type"]["name"] in TYPE_MAP]

            base_stats = {}
            for s in poke_data["stats"]:
                key = STAT_MAP.get(s["stat"]["name"])
                if key:
                    base_stats[key] = s["base_stat"]

            abilities = [a["ability"]["name"] for a in poke_data["abilities"]]

            result[species_name] = {
                "name_ja": name_ja,
                "types": types,
                "base_stats": base_stats,
                "abilities": abilities,
            }

            # フォルム違いも取得（メガ、リージョンフォーム等）
            for variant in species_data.get("varieties", []):
                if variant["is_default"]:
                    continue
                var_name = variant["pokemon"]["name"]
                try:
                    var_data = get(variant["pokemon"]["url"])
                    var_types = [t["type"]["name"] for t in var_data["types"]
                                 if t["type"]["name"] in TYPE_MAP]
                    var_stats = {}
                    for s in var_data["stats"]:
                        key = STAT_MAP.get(s["stat"]["name"])
                        if key:
                            var_stats[key] = s["base_stat"]
                    var_abilities = [a["ability"]["name"] for a in var_data["abilities"]]

                    # フォルム名から日本語名を生成（"pikachu-original" → "ピカチュウ(オリジナル)")
                    suffix = var_name.replace(species_name + "-", "")
                    var_name_ja = f"{name_ja}({suffix})"

                    # メガシンカの場合、元のエントリに追加
                    if "mega" in suffix:
                        form_key = suffix.replace("-", "_")
                        result[species_name][form_key] = {
                            "types": var_types,
                            "base_stats": var_stats,
                        }
                    else:
                        result[var_name] = {
                            "name_ja": var_name_ja,
                            "types": var_types,
                            "base_stats": var_stats,
                            "abilities": var_abilities,
                        }
                except Exception:
                    pass

            if i % 50 == 0 or i == total:
                print(f"  {i}/{total} 完了... ({name_ja})")

        except Exception as e:
            print(f"  警告: {species_name} の取得に失敗 ({e})")
            continue

    return result


def main():
    print("=" * 50)
    print("ポケモンデータ取得スクリプト")
    print("=" * 50)

    pokemon = fetch_all()
    print(f"\n合計 {len(pokemon)} 件取得完了")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(pokemon, f, ensure_ascii=False, indent=2)

    print(f"保存先: {OUT_PATH}")
    print("完了！ python gui.py で起動してください。")


if __name__ == "__main__":
    main()
