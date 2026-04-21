import math
import json
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"

with open(_DATA / "natures.json", encoding="utf-8") as f:
    _NATURES: dict = json.load(f)
with open(_DATA / "pokemon.json", encoding="utf-8") as f:
    _POKEMON: dict = json.load(f)


STAT_KEYS = ["hp", "attack", "defense", "sp_attack", "sp_defense", "speed"]


def _nature_multiplier(nature: str, stat: str) -> float:
    """性格による補正値 (0.9 / 1.0 / 1.1)"""
    data = _NATURES.get(nature, {})
    if data.get("boosted") == stat:
        return 1.1
    if data.get("reduced") == stat:
        return 0.9
    return 1.0


def calculate_stat(base: int, ap: int, nature: str, stat: str) -> int:
    """個別ステータス計算（チャンピオンズ式）
    HP：種族値 + 75 + AP
    他：(種族値 + 20 + AP) × 性格補正
    AP は 0〜32
    """
    if stat == "hp":
        return base + 75 + ap
    else:
        return math.floor((base + 20 + ap) * _nature_multiplier(nature, stat))


def calculate_all_stats(build, pokemon_data: dict | None = None) -> dict[str, int]:
    """PokemonBuild から全6ステータスを計算して返す"""
    from .models import PokemonBuild
    assert isinstance(build, PokemonBuild)

    if pokemon_data is None:
        pokemon_data = _POKEMON.get(build.species, {})

    # メガシンカ / フォルムで base_stats を切り替え
    base = pokemon_data.get("base_stats", {})
    if build.is_mega and build.mega_form:
        form_data = pokemon_data.get(build.mega_form, {})
        base = form_data.get("base_stats", base)

    ap_map = {
        "hp":        build.ev_hp,
        "attack":    build.ev_attack,
        "defense":   build.ev_defense,
        "sp_attack": build.ev_sp_attack,
        "sp_defense":build.ev_sp_defense,
        "speed":     build.ev_speed,
    }

    return {
        s: calculate_stat(base.get(s, 0), ap_map[s], build.nature, s)
        for s in STAT_KEYS
    }


def get_types(build, pokemon_data: dict | None = None) -> list[str]:
    """現在のタイプリストを返す（メガシンカ考慮）"""
    if pokemon_data is None:
        pokemon_data = _POKEMON.get(build.species, {})
    if build.is_mega and build.mega_form:
        form = pokemon_data.get(build.mega_form, {})
        return form.get("types", pokemon_data.get("types", []))
    return pokemon_data.get("types", [])


def rank_multiplier(rank: int) -> float:
    """ランク補正の倍率（攻撃・防御系）"""
    if rank >= 0:
        return (2 + rank) / 2
    else:
        return 2 / (2 - rank)


def get_pokemon_data(species: str) -> dict:
    return _POKEMON.get(species, {})


def list_pokemon() -> list[str]:
    return sorted(_POKEMON.keys())
