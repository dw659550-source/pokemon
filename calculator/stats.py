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


def calculate_stat(base: int, iv: int, ev: int, level: int,
                   nature: str, stat: str) -> int:
    """個別ステータス計算 (Gen6+ 標準式)"""
    if stat == "hp":
        # シェディンジャは HP=1 固定だが Phase1 では省略
        return math.floor((2 * base + iv + math.floor(ev / 4)) * level / 100) + level + 10
    else:
        raw = math.floor((2 * base + iv + math.floor(ev / 4)) * level / 100) + 5
        return math.floor(raw * _nature_multiplier(nature, stat))


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

    ev_map = {
        "hp":        build.ev_hp,
        "attack":    build.ev_attack,
        "defense":   build.ev_defense,
        "sp_attack": build.ev_sp_attack,
        "sp_defense":build.ev_sp_defense,
        "speed":     build.ev_speed,
    }
    iv_map = {
        "hp":        build.iv_hp,
        "attack":    build.iv_attack,
        "defense":   build.iv_defense,
        "sp_attack": build.iv_sp_attack,
        "sp_defense":build.iv_sp_defense,
        "speed":     build.iv_speed,
    }

    return {
        s: calculate_stat(base.get(s, 0), iv_map[s], ev_map[s],
                          build.level, build.nature, s)
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
