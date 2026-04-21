from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PokemonBuild:
    """対戦ポケモン1体のビルド情報"""
    species: str                  # pokemon.jsonのキー（例: "garchomp"）
    level: int = 50
    nature: str = "hardy"         # natures.jsonのキー
    item: str = "none"            # items.jsonのキー
    ability: str = ""
    moves: list[str] = field(default_factory=list)  # moves.jsonのキー×4

    # 能力ポイント (AP) 0–32 each（チャンピオンズ独自仕様）
    ev_hp:        int = 0
    ev_attack:    int = 0
    ev_defense:   int = 0
    ev_sp_attack: int = 0
    ev_sp_defense:int = 0
    ev_speed:     int = 0

    is_mega: bool = False         # メガシンカ状態か
    mega_form: str = ""           # "mega" / "mega_x" / "mega_y" など


@dataclass
class BattleState:
    """対戦中の一時状態（ランク補正・天気など）"""
    # ランク補正 -6～+6
    rank_attack:    int = 0
    rank_defense:   int = 0
    rank_sp_attack: int = 0
    rank_sp_defense:int = 0
    rank_speed:     int = 0

    # 状態異常
    burned:    bool = False
    poisoned:  bool = False
    paralyzed: bool = False

    # 天気
    weather: str = "none"  # "sun" / "rain" / "sand" / "hail" / "snow" / "none"

    # フィールド
    terrain: str = "none"  # "electric" / "grassy" / "misty" / "psychic" / "none"

    # 残りHP割合 (0.0–1.0)
    hp_ratio: float = 1.0

    # ダブルバトルで複数対象技か
    is_spread: bool = False

    # 急所
    is_critical: bool = False


@dataclass
class DamageResult:
    """ダメージ計算結果"""
    move_name: str
    move_name_ja: str
    move_type: str
    category: str
    base_power: Optional[int]

    damage_min: int
    damage_max: int
    damage_percent_min: float  # 相手の最大HPに対する割合
    damage_percent_max: float

    type_effectiveness: float  # 0 / 0.25 / 0.5 / 1 / 2 / 4
    is_stab: bool
    ko_chance: str             # "確定1発" / "乱数1発(x/16)" / "確定2発" / etc.
    hit_count: str = ""        # "×2〜5" など複数回ヒット技のみ設定

    def summary(self) -> str:
        eff = {0: "無効", 0.25: "1/4", 0.5: "今ひとつ", 1: "等倍",
               2: "抜群", 4: "2倍抜群"}.get(self.type_effectiveness, "")
        stab = "◎" if self.is_stab else ""
        return (
            f"{self.move_name_ja}{stab} [{eff}]  "
            f"{self.damage_min}〜{self.damage_max}  "
            f"({self.damage_percent_min:.1f}%〜{self.damage_percent_max:.1f}%)  "
            f"{self.ko_chance}"
        )
