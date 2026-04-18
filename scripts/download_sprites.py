#!/usr/bin/env python3
"""
PokeAPI から全ポケモンのスプライト画像を data/sprites/ にダウンロードするスクリプト。

【使い方】
1. pip install requests
2. python scripts/download_sprites.py
3. 数分待つと data/sprites/*.png が作られます
"""
import json
import time
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

BASE_URL    = "https://pokeapi.co/api/v2"
SPRITES_DIR = Path(__file__).parent.parent / "data" / "sprites"
POKE_PATH   = Path(__file__).parent.parent / "data" / "pokemon.json"


def get(url: str, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1)


def main():
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)

    with open(POKE_PATH, encoding="utf-8") as f:
        pokemon: dict = json.load(f)

    keys  = [k for k in pokemon if not k.startswith("_")]
    total = len(keys)
    done  = skip = fail = 0

    print(f"スプライト取得開始: {total} 件")
    print("=" * 50)

    for i, key in enumerate(keys, 1):
        out = SPRITES_DIR / f"{key}.png"
        if out.exists():
            skip += 1
            continue

        try:
            poke_url = f"{BASE_URL}/pokemon/{key}"
            try:
                poke_data = get(poke_url).json()
            except Exception:
                # 404 の場合はスペシーズ経由でデフォルトフォームを取得
                species_data = get(f"{BASE_URL}/pokemon-species/{key}").json()
                poke_url = next(
                    (v["pokemon"]["url"] for v in species_data.get("varieties", [])
                     if v["is_default"]),
                    poke_url,
                )
                poke_data = get(poke_url).json()

            # official-artwork を優先し、なければ通常スプライト
            url = (
                (poke_data.get("sprites") or {})
                .get("other", {})
                .get("official-artwork", {})
                .get("front_default")
                or (poke_data.get("sprites") or {}).get("front_default")
            )
            if url:
                out.write_bytes(get(url).content)
                done += 1
            else:
                print(f"  {key}: スプライト URL なし")
                fail += 1
        except Exception as e:
            print(f"  {key}: 失敗 ({e})")
            fail += 1

        if i % 100 == 0:
            print(f"  {i}/{total} 完了")

        time.sleep(0.08)

    print(f"\n完了: 取得={done} スキップ={skip} 失敗={fail}")
    print(f"保存先: {SPRITES_DIR}")


if __name__ == "__main__":
    main()
