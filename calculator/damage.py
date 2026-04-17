import math
import json
from pathlib import Path
from typing import Optional

from .models import PokemonBuild, BattleState, DamageResult
from .stats import (calculate_all_stats, get_types, rank_multiplier,
                    get_pokemon_data)

_DATA = Path(__file__).parent.parent / "data"

with open(_DATA / "moves.json",      encoding="utf-8") as f:
    _MOVES: dict = json.load(f)
with open(_DATA / "items.json",      encoding="utf-8") as f:
    _ITEMS: dict = json.load(f)
with open(_DATA / "type_chart.json", encoding="utf-8") as f:
    _TYPE_CHART: dict = json.load(f)


# ── ユーティリティ ──────────────────────────────────────────────────────────

def type_effectiveness(move_type: str, defender_types: list[str]) -> float:
    chart = _TYPE_CHART.get(move_type, {})
    mult = 1.0
    for t in defender_types:
        mult *= chart.get(t, 1.0)
    return mult


def _ko_label(percent_min: float, percent_max: float) -> str:
    """確定・乱数 n 発ラベル"""
    for n in range(1, 7):
        threshold = 100.0 / n
        if percent_min >= threshold:
            return f"確定{n}発"
        if percent_max >= threshold:
            # 16乱数の何本で倒せるか概算
            hits = math.ceil(threshold / (percent_max / 16))
            return f"乱数{n}発({16 - hits + 1}/16)"
    return "6発以上"


# ── メイン計算クラス ────────────────────────────────────────────────────────

class DamageCalculator:
    """Gen9 準拠ダメージ計算エンジン"""

    def calculate(
        self,
        attacker: PokemonBuild,
        defender: PokemonBuild,
        move_id: str,
        attacker_state: Optional[BattleState] = None,
        defender_state: Optional[BattleState] = None,
    ) -> Optional[DamageResult]:
        """
        attacker の move_id を defender に打ったときのダメージを返す。
        status技 / 無効技 は None を返す。
        """
        if attacker_state is None:
            attacker_state = BattleState()
        if defender_state is None:
            defender_state = BattleState()

        move = _MOVES.get(move_id)
        if move is None:
            return None
        if move["category"] == "status":
            return None

        atk_stats  = calculate_all_stats(attacker)
        def_stats  = calculate_all_stats(defender)
        atk_types  = get_types(attacker)
        def_types  = get_types(defender)
        atk_pdata  = get_pokemon_data(attacker.species)
        def_pdata  = get_pokemon_data(defender.species)
        move_type  = move["type"]
        category   = move["category"]   # "physical" or "special"
        flags      = move.get("flags", [])
        effect     = move.get("effect")

        # ── 技のベースパワーを決定 ──────────────────────────────────────
        base_power = self._resolve_base_power(
            move_id, move, attacker, defender, atk_stats, def_stats,
            attacker_state, defender_state
        )
        if base_power == 0:
            return None

        # ── 攻撃・防御ステータス選択 ────────────────────────────────────
        if effect == "body_press":
            # ボディプレスは自分の防御を攻撃として使用
            atk_val = atk_stats["defense"]
            atk_rank = attacker_state.rank_defense
        elif category == "physical":
            atk_val  = atk_stats["attack"]
            atk_rank = attacker_state.rank_attack
        else:
            atk_val  = atk_stats["sp_attack"]
            atk_rank = attacker_state.rank_sp_attack

        if effect in ("psyshock",):
            # サイコショック系は相手の物理防御
            def_val  = def_stats["defense"]
            def_rank = defender_state.rank_defense
        elif category == "physical":
            def_val  = def_stats["defense"]
            def_rank = defender_state.rank_defense
        else:
            def_val  = def_stats["sp_defense"]
            def_rank = defender_state.rank_sp_defense

        atk_val_ranked = math.floor(atk_val * rank_multiplier(atk_rank))
        def_val_ranked = math.floor(def_val * rank_multiplier(def_rank))

        # 急所: 攻撃ランクはプラス側のみ・防御ランクはマイナス側のみ採用
        is_crit = attacker_state.is_critical or (effect == "always_crit") or (effect == "triple_always_crit")
        if is_crit:
            if atk_rank < 0:
                atk_val_ranked = atk_val
            if def_rank > 0:
                def_val_ranked = def_val

        # ── アイテム補正（攻撃側） ──────────────────────────────────────
        atk_item_mult = self._attacker_item_mult(
            attacker.item, attacker.species, move_type, category, flags
        )
        atk_val_ranked = math.floor(atk_val_ranked * atk_item_mult)

        # ── 特性補正（攻撃側）─── ability が空欄の場合はスキップ ─────────
        ability_mult = self._attacker_ability_mult(
            attacker.ability, move_type, category, flags,
            attacker_state, defender_state, atk_types
        )
        atk_val_ranked = math.floor(atk_val_ranked * ability_mult)

        # ── やけど補正 ───────────────────────────────────────────────────
        burn_mult = 1.0
        if category == "physical" and attacker_state.burned:
            if attacker.ability not in ("guts",):
                burn_mult = 0.5

        # ── ベースダメージ計算 ───────────────────────────────────────────
        level = attacker.level
        base = math.floor(
            math.floor(
                math.floor(2 * level / 5 + 2) * base_power
                * atk_val_ranked / def_val_ranked
            ) / 50
        ) + 2

        # ── 連打技補正（例: 連撃ウーラオス3連 等）──────────────────────
        hit_count = 3 if effect in ("triple_always_crit", "surging-strikes") else 1

        # ── 各種倍率チェーン ─────────────────────────────────────────────
        eff = type_effectiveness(move_type, def_types)

        # フリーズドライは水に等倍→抜群
        if effect == "freeze_dry" and "water" in def_types:
            eff_list = [_TYPE_CHART.get(move_type, {}).get(t, 1.0)
                        for t in def_types if t != "water"]
            eff = 2.0
            for e in eff_list:
                eff *= e

        if eff == 0.0:
            return DamageResult(
                move_name=move_id, move_name_ja=move["name_ja"],
                move_type=move_type, category=category,
                base_power=base_power,
                damage_min=0, damage_max=0,
                damage_percent_min=0.0, damage_percent_max=0.0,
                type_effectiveness=0.0,
                is_stab=move_type in atk_types,
                ko_chance="無効",
            )

        stab_mult = self._stab_mult(move_type, atk_types, attacker.ability)
        weather_mult = self._weather_mult(move_type, attacker_state.weather)
        spread_mult = 0.75 if attacker_state.is_spread else 1.0
        crit_mult   = (1.5 if not attacker.ability == "sniper" else 2.25) if is_crit else 1.0

        # 防御側アイテム・特性
        def_item_mult = self._defender_item_mult(defender.item)
        def_ability_mult = self._defender_ability_mult(
            defender.ability, move_type, eff, category, attacker_state
        )

        def _apply(damage: int, *mults) -> int:
            for m in mults:
                damage = math.floor(damage * m)
            return damage

        def calc_damage(rand: float) -> int:
            d = base
            d = _apply(d, spread_mult)
            d = _apply(d, weather_mult)
            d = _apply(d, crit_mult)
            d = math.floor(d * rand)
            d = _apply(d, stab_mult)
            d = _apply(d, eff)
            d = _apply(d, burn_mult)
            d = _apply(d, def_item_mult)
            d = _apply(d, def_ability_mult)
            return max(1, d) * hit_count

        dmg_min = calc_damage(0.85)
        dmg_max = calc_damage(1.00)

        defender_hp = calculate_all_stats(defender)["hp"]
        pct_min = dmg_min / defender_hp * 100
        pct_max = dmg_max / defender_hp * 100

        return DamageResult(
            move_name=move_id,
            move_name_ja=move["name_ja"],
            move_type=move_type,
            category=category,
            base_power=base_power,
            damage_min=dmg_min,
            damage_max=dmg_max,
            damage_percent_min=pct_min,
            damage_percent_max=pct_max,
            type_effectiveness=eff,
            is_stab=move_type in atk_types,
            ko_chance=_ko_label(pct_min, pct_max),
        )

    def calculate_all_moves(
        self,
        attacker: PokemonBuild,
        defender: PokemonBuild,
        attacker_state: Optional[BattleState] = None,
        defender_state: Optional[BattleState] = None,
    ) -> list[DamageResult]:
        """attacker の4技全てを計算して返す（status技・無効技は除外）"""
        results = []
        for move_id in attacker.moves:
            r = self.calculate(attacker, defender, move_id,
                               attacker_state, defender_state)
            if r is not None:
                results.append(r)
        return results

    # ── 内部ヘルパー ────────────────────────────────────────────────────────

    def _resolve_base_power(self, move_id, move, attacker, defender,
                            atk_stats, def_stats,
                            atk_state, def_state) -> int:
        power = move.get("power")
        effect = move.get("effect")

        if power is not None:
            return power

        # 可変威力技
        if effect == "grass_knot":
            # くさむすび: 相手の重さで決まる（Phase1では固定60で近似）
            return 60
        if effect == "gyro_ball":
            p = math.floor(25 * def_stats["speed"] / max(1, atk_stats["speed"]))
            return min(150, max(1, p))
        if effect == "acrobatics":
            # 持ち物なしなら2倍
            return 110 if attacker.item == "none" else 55
        if effect == "facade":
            return 140 if atk_state.burned or atk_state.poisoned or atk_state.paralyzed else 70
        if effect == "knock_off":
            # 持ち物あり相手には1.5倍
            if defender.item != "none":
                return math.floor(65 * 1.5)
            return 65

        return 60  # フォールバック

    def _attacker_item_mult(self, item: str, species: str,
                            move_type: str, category: str,
                            flags: list[str]) -> float:
        data = _ITEMS.get(item, {})
        eff = data.get("effect")
        val = data.get("value", 1.0)
        if eff == "atk_mult"      and category == "physical":  return val
        if eff == "spatk_mult"    and category == "special":   return val
        if eff == "damage_mult":                                return val
        if eff == "punch_mult"    and "punch" in flags:        return val
        if eff == "type_mult"     and data.get("move_type") == move_type: return val
        if eff == "holder_type_mult":
            if data.get("holder", "") in species and move_type in data.get("move_types", []):
                return val
        if eff == "holder_atk_mult" and category == "physical":
            if data.get("holder", "") in species:              return val
        if eff == "holder_spatk_mult" and category == "special":
            if data.get("holder", "") in species:              return val
        return 1.0

    def _attacker_ability_mult(self, ability: str, move_type: str,
                                category: str, flags: list[str],
                                atk_state: BattleState, def_state: BattleState,
                                atk_types: list[str]) -> float:
        a = ability.lower()
        # 一致補正系
        if a == "adaptability":
            pass  # STAB側で処理
        if a == "technician":
            pass  # base_power 側で処理できないのでここでは1.0
        if a == "sheer-force":
            pass  # 副作用消しは省略
        if a == "iron-fist"      and "punch"   in flags: return 1.2
        if a == "tough-claws"    and "contact" in flags: return 1.3
        if a == "strong-jaw"     and "bite"    in flags: return 1.5
        if a == "mega-launcher"  and "pulse"   in flags: return 1.5
        if a == "punk-rock"      and "sound"   in flags: return 1.3
        if a == "reckless"       and "recoil"  in flags: return 1.2
        if a == "guts"           and category  == "physical" and atk_state.burned: return 1.5
        if a == "hustle"         and category  == "physical": return 1.5
        if a in ("pure-power","huge-power") and category == "physical": return 2.0
        if a == "gorilla-tactics" and category == "physical": return 1.5
        if a == "transistor"     and move_type == "electric": return 1.5
        if a == "dragons-maw"    and move_type == "dragon":   return 1.5
        if a == "steelworker"    and move_type == "steel":    return 1.5
        if a == "rocky-payload"  and move_type == "rock":     return 1.5
        if a == "orichalcum-pulse" and move_type == "fire" and atk_state.weather == "sun": return 5461/4096
        if a == "hadron-engine"  and move_type == "electric" and atk_state.terrain == "electric": return 5461/4096
        if a == "protosynthesis" or a == "quark-drive":
            pass  # 最高ステータス補正は事前計算が必要→Phase1省略
        if a == "neuroforce":
            # 抜群技に1.25倍
            pass  # effectiveness は後で掛けるのでここでは判断できない
        if a == "pixilate"       and move_type == "fairy":    return 1.2
        if a == "refrigerate"    and move_type == "ice":      return 1.2
        if a == "aerilate"       and move_type == "flying":   return 1.2
        if a == "galvanize"      and move_type == "electric": return 1.2
        return 1.0

    def _stab_mult(self, move_type: str, atk_types: list[str], ability: str) -> float:
        if move_type not in atk_types:
            return 1.0
        if ability.lower() == "adaptability":
            return 2.0
        return 1.5

    def _weather_mult(self, move_type: str, weather: str) -> float:
        if weather == "sun":
            if move_type == "fire":   return 1.5
            if move_type == "water":  return 0.5
        if weather == "rain":
            if move_type == "water":  return 1.5
            if move_type == "fire":   return 0.5
        return 1.0

    def _defender_item_mult(self, item: str) -> float:
        data = _ITEMS.get(item, {})
        eff = data.get("effect")
        # Assault Vest / Eviolite は防御ステータスに影響→ここでは省略（stats側）
        return 1.0

    def _defender_ability_mult(self, ability: str, move_type: str,
                                eff: float, category: str,
                                atk_state: BattleState) -> float:
        a = ability.lower()
        if a in ("filter", "solid-rock", "prism-armor") and eff > 1.0:
            return 0.75
        if a == "multiscale" and atk_state.hp_ratio >= 1.0:
            # defender の HP は BattleState で管理するが、ここでは attacker_state 経由で近似
            return 0.5
        if a == "fur-coat"  and category == "physical": return 0.5
        if a == "ice-scales" and category == "special": return 0.5
        if a in ("water-absorb","volt-absorb","flash-fire","storm-drain","motor-drive",
                 "sap-sipper","lightning-rod","dry-skin"):
            pass  # 完全無効化は type_effectiveness 側で 0 になるケースが多い
        if a == "wonder-guard":
            return 1.0 if eff > 1.0 else 0.0
        return 1.0
