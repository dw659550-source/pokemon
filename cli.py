#!/usr/bin/env python3
"""
ポケモンチャンピオンズ ダメージ計算CLI (Phase 1)
使い方: python cli.py
"""
import json
import sys
from pathlib import Path

from calculator import DamageCalculator
from calculator.models import PokemonBuild, BattleState
from calculator.stats import (calculate_all_stats, get_types,
                               list_pokemon, get_pokemon_data)

_DATA = Path(__file__).parent / "data"

with open(_DATA / "moves.json",   encoding="utf-8") as f:
    _MOVES: dict = json.load(f)
with open(_DATA / "natures.json", encoding="utf-8") as f:
    _NATURES: dict = json.load(f)
with open(_DATA / "items.json",   encoding="utf-8") as f:
    _ITEMS: dict = json.load(f)
with open(_DATA / "pokemon.json", encoding="utf-8") as f:
    _POKEMON: dict = json.load(f)

CALC = DamageCalculator()

# ── ユーティリティ ─────────────────────────────────────────────────────────

def _sep(char="─", width=60):
    print(char * width)


def _ask(prompt: str, default: str = "") -> str:
    val = input(f"  {prompt}" + (f" [{default}]" if default else "") + " > ").strip()
    return val if val else default


def _ask_int(prompt: str, default: int, lo: int = 0, hi: int = 9999) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"    ※ {lo}〜{hi} の整数を入力してください")


def _fuzzy_pokemon(query: str) -> str | None:
    """英語キー or 日本語名で部分一致検索、候補1件なら返す"""
    query = query.lower().replace(" ", "-")
    if query in _POKEMON:
        return query
    hits = [k for k, v in _POKEMON.items()
            if query in k or query in v.get("name_ja", "").lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        print("    候補:")
        for h in hits[:10]:
            print(f"      {h} ({_POKEMON[h]['name_ja']})")
    return None


def _fuzzy_move(query: str) -> str | None:
    query_l = query.lower().replace(" ", "-")
    if query_l in _MOVES:
        return query_l
    hits = [k for k, v in _MOVES.items()
            if query_l in k or query_l in v.get("name_ja", "").lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        print("    候補:")
        for h in hits[:10]:
            print(f"      {h} ({_MOVES[h]['name_ja']})")
    return None


def _fuzzy_nature(query: str) -> str | None:
    query_l = query.lower()
    if query_l in _NATURES:
        return query_l
    hits = [k for k, v in _NATURES.items()
            if query_l in k or query_l in v.get("name_ja", "")]
    if len(hits) == 1:
        return hits[0]
    if hits:
        for h in hits[:5]:
            print(f"      {h} ({_NATURES[h]['name_ja']})")
    return None


def _fuzzy_item(query: str) -> str | None:
    query_l = query.lower().replace(" ", "-")
    if query_l in _ITEMS:
        return query_l
    hits = [k for k, v in _ITEMS.items()
            if query_l in k or query_l in v.get("name_ja", "").lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        for h in hits[:5]:
            print(f"      {h} ({_ITEMS[h]['name_ja']})")
    return None


# ── 入力フォーム ───────────────────────────────────────────────────────────

def _input_pokemon(label: str) -> PokemonBuild:
    print(f"\n【{label}のポケモン入力】")
    while True:
        raw = _ask("ポケモン名(英語キー or 日本語)")
        species = _fuzzy_pokemon(raw)
        if species:
            pd = get_pokemon_data(species)
            print(f"    → {pd['name_ja']} ({'/'.join(get_types_str(species))})")
            break
        print("    見つかりません。再入力してください。")

    level  = _ask_int("レベル", 50, 1, 100)

    while True:
        raw = _ask("性格", "hardy")
        nature = _fuzzy_nature(raw)
        if nature:
            nd = _NATURES[nature]
            boost = nd["boosted"] or "なし"
            reduce= nd["reduced"] or "なし"
            print(f"    → {nd['name_ja']} (↑{boost} ↓{reduce})")
            break
        print("    見つかりません。")

    while True:
        raw = _ask("持ち物", "none")
        item = _fuzzy_item(raw)
        if item:
            print(f"    → {_ITEMS[item]['name_ja']}")
            break
        print("    見つかりません。")

    ability = _ask("特性 (英語キー、省略可)", "")

    print("  技を4つ入力 (不要な欄は空Enter でスキップ)")
    moves = []
    for i in range(1, 5):
        while True:
            raw = _ask(f"技{i}", "")
            if not raw:
                break
            mid = _fuzzy_move(raw)
            if mid:
                print(f"    → {_MOVES[mid]['name_ja']}")
                moves.append(mid)
                break
            print("    見つかりません。")

    print("  努力値 (各0〜252, 合計510以内)")
    evs = {}
    for stat, label in [("hp","HP"),("attack","こうげき"),("defense","ぼうぎょ"),
                         ("sp_attack","とくこう"),("sp_defense","とくぼう"),("speed","すばやさ")]:
        evs[stat] = _ask_int(f"  {label} EV", 0, 0, 252)

    print("  個体値 (各0〜31)")
    use_max = _ask("全て31にする? (y/n)", "y").lower() == "y"
    ivs = {}
    if use_max:
        ivs = {s: 31 for s in ["hp","attack","defense","sp_attack","sp_defense","speed"]}
    else:
        for stat, label in [("hp","HP"),("attack","こうげき"),("defense","ぼうぎょ"),
                             ("sp_attack","とくこう"),("sp_defense","とくぼう"),("speed","すばやさ")]:
            ivs[stat] = _ask_int(f"  {label} IV", 31, 0, 31)

    # メガシンカ確認
    pd = get_pokemon_data(species)
    mega_forms = [k for k in pd if k.startswith("mega")]
    is_mega = False
    mega_form = ""
    if mega_forms:
        if _ask(f"メガシンカ? ({'/'.join(mega_forms)}) (y/n)", "n").lower() == "y":
            is_mega = True
            mega_form = mega_forms[0] if len(mega_forms) == 1 else _ask("フォーム名", mega_forms[0])

    build = PokemonBuild(
        species=species, level=level, nature=nature, item=item, ability=ability,
        moves=moves,
        ev_hp=evs["hp"], ev_attack=evs["attack"], ev_defense=evs["defense"],
        ev_sp_attack=evs["sp_attack"], ev_sp_defense=evs["sp_defense"], ev_speed=evs["speed"],
        iv_hp=ivs["hp"], iv_attack=ivs["attack"], iv_defense=ivs["defense"],
        iv_sp_attack=ivs["sp_attack"], iv_sp_defense=ivs["sp_defense"], iv_speed=ivs["speed"],
        is_mega=is_mega, mega_form=mega_form,
    )
    return build


def get_types_str(species: str) -> list[str]:
    return get_pokemon_data(species).get("types", [])


def _input_battle_state(label: str) -> BattleState:
    print(f"\n【{label}の対戦状態 (EnterでOK)】")
    state = BattleState()

    weather_raw = _ask("天気 (none/sun/rain/sand/snow)", "none").lower()
    state.weather = weather_raw if weather_raw in ("none","sun","rain","sand","snow","hail") else "none"

    terrain_raw = _ask("フィールド (none/electric/grassy/misty/psychic)", "none").lower()
    state.terrain = terrain_raw if terrain_raw in ("none","electric","grassy","misty","psychic") else "none"

    burned = _ask("やけど状態? (y/n)", "n").lower() == "y"
    state.burned = burned

    is_crit = _ask("急所を仮定? (y/n)", "n").lower() == "y"
    state.is_critical = is_crit

    return state


def _show_stats(build: PokemonBuild):
    stats = calculate_all_stats(build)
    pd = get_pokemon_data(build.species)
    types_str = "/".join(get_types(build, pd))
    print(f"\n  ステータス ({pd['name_ja']} Lv{build.level} {'メガ' if build.is_mega else ''} {types_str})")
    print(f"  HP:{stats['hp']}  こう:{stats['attack']}  ぼう:{stats['defense']}"
          f"  とこ:{stats['sp_attack']}  とぼ:{stats['sp_defense']}  すば:{stats['speed']}")


# ── 計算・表示 ─────────────────────────────────────────────────────────────

def _show_damage_table(results, title: str):
    _sep()
    print(f"  {title}")
    _sep()
    if not results:
        print("  (ダメージ技なし)")
        return
    for r in results:
        print(f"  {r.summary()}")


def _calc_and_show(attacker: PokemonBuild, defender: PokemonBuild,
                   atk_state: BattleState, def_state: BattleState):
    _show_stats(attacker)
    _show_stats(defender)

    # 自分→相手
    results_atk = CALC.calculate_all_moves(attacker, defender, atk_state, def_state)
    def_pd = get_pokemon_data(defender.species)
    _show_damage_table(
        results_atk,
        f"【自分 → {def_pd['name_ja']}】 相手HP: {calculate_all_stats(defender)['hp']}"
    )

    # 相手→自分
    results_def = CALC.calculate_all_moves(defender, attacker, def_state, atk_state)
    atk_pd = get_pokemon_data(attacker.species)
    _show_damage_table(
        results_def,
        f"【{def_pd['name_ja']} → 自分({atk_pd['name_ja']})】 自分HP: {calculate_all_stats(attacker)['hp']}"
    )


# ── 自パーティ管理 ─────────────────────────────────────────────────────────

party: list[PokemonBuild] = []


def _register_party():
    global party
    print("\n【自分のパーティ登録】 (最大6体)")
    party = []
    for i in range(1, 7):
        print(f"\n  ── {i}体目 ──")
        b = _input_pokemon(f"自分{i}")
        party.append(b)
        if _ask(f"続けて{i+1}体目を登録? (y/n)", "n" if i >= 1 else "y").lower() != "y":
            break
    print(f"\n  {len(party)}体登録しました。")


def _select_party_pokemon() -> PokemonBuild | None:
    if not party:
        print("  パーティが未登録です。まず登録してください。")
        return None
    print("\n  パーティから選択:")
    for i, b in enumerate(party, 1):
        pd = get_pokemon_data(b.species)
        print(f"    {i}: {pd['name_ja']} (Lv{b.level} {b.nature} {b.item})")
    idx = _ask_int("番号", 1, 1, len(party))
    return party[idx - 1]


# ── メインメニュー ─────────────────────────────────────────────────────────

def _print_menu():
    _sep("═")
    print("  ポケモンチャンピオンズ ダメージ計算ツール v1.0 (Phase 1)")
    _sep("═")
    print("  1) パーティ登録")
    print("  2) ダメージ計算 (パーティ選択 vs 相手入力)")
    print("  3) ダメージ計算 (両方手動入力)")
    print("  4) 登録パーティ確認")
    print("  q) 終了")
    _sep()


def _menu_calc_with_party():
    atk = _select_party_pokemon()
    if atk is None:
        return
    def_ = _input_pokemon("相手")
    atk_state = _input_battle_state("自分")
    def_state  = _input_battle_state("相手")
    _calc_and_show(atk, def_, atk_state, def_state)


def _menu_calc_manual():
    atk  = _input_pokemon("自分")
    def_ = _input_pokemon("相手")
    atk_state = _input_battle_state("自分")
    def_state  = _input_battle_state("相手")
    _calc_and_show(atk, def_, atk_state, def_state)


def _menu_show_party():
    if not party:
        print("  (未登録)")
        return
    for b in party:
        pd = get_pokemon_data(b.species)
        stats = calculate_all_stats(b)
        types_str = "/".join(get_types(b, pd))
        print(f"\n  {pd['name_ja']} ({types_str}) Lv{b.level}")
        print(f"    性格:{b.nature}  持ち物:{b.item}  特性:{b.ability or '未設定'}")
        print(f"    技: {', '.join(_MOVES.get(m,{}).get('name_ja', m) for m in b.moves)}")
        print(f"    HP:{stats['hp']} A:{stats['attack']} B:{stats['defense']}"
              f" C:{stats['sp_attack']} D:{stats['sp_defense']} S:{stats['speed']}")


def main():
    print("\nポケモンチャンピオンズ ダメージ計算ツールへようこそ！")
    print("'list'と入力するとポケモン一覧が表示されます。\n")

    while True:
        _print_menu()
        choice = input("  選択 > ").strip().lower()

        if choice == "1":
            _register_party()
        elif choice == "2":
            _menu_calc_with_party()
        elif choice == "3":
            _menu_calc_manual()
        elif choice == "4":
            _menu_show_party()
        elif choice in ("q", "quit", "exit"):
            print("  終了します。")
            break
        elif choice == "list":
            print("  登録ポケモン一覧:")
            for k in list_pokemon():
                print(f"    {k} ({_POKEMON[k]['name_ja']})")
        else:
            print("  1〜4 または q を入力してください。")


if __name__ == "__main__":
    main()
