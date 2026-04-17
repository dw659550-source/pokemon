#!/usr/bin/env python3
"""
ポケモンチャンピオンズ ダメージ計算ツール - デスクトップ版 (Phase 1)
起動方法: python gui.py
"""
import sys
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QSpinBox, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QCompleter

from calculator import DamageCalculator
from calculator.models import PokemonBuild, BattleState
from calculator.stats import calculate_all_stats, get_types, get_pokemon_data

_DATA = Path(__file__).parent / "data"

with open(_DATA / "pokemon.json", encoding="utf-8") as f:
    _POKEMON: dict = json.load(f)
with open(_DATA / "moves.json", encoding="utf-8") as f:
    _MOVES: dict = json.load(f)
with open(_DATA / "natures.json", encoding="utf-8") as f:
    _NATURES: dict = json.load(f)
with open(_DATA / "items.json", encoding="utf-8") as f:
    _ITEMS: dict = json.load(f)

CALC = DamageCalculator()

TYPE_JA = {
    "normal": "ノーマル", "fire": "ほのお", "water": "みず",
    "electric": "でんき", "grass": "くさ", "ice": "こおり",
    "fighting": "かくとう", "poison": "どく", "ground": "じめん",
    "flying": "ひこう", "psychic": "エスパー", "bug": "むし",
    "rock": "いわ", "ghost": "ゴースト", "dragon": "ドラゴン",
    "dark": "あく", "steel": "はがね", "fairy": "フェアリー",
}
TYPE_COLOR = {
    "normal": "#A8A878", "fire": "#F08030", "water": "#6890F0",
    "electric": "#F8D030", "grass": "#78C850", "ice": "#98D8D8",
    "fighting": "#C03028", "poison": "#A040A0", "ground": "#E0C068",
    "flying": "#A890F0", "psychic": "#F85888", "bug": "#A8B820",
    "rock": "#B8A038", "ghost": "#705898", "dragon": "#7038F8",
    "dark": "#705848", "steel": "#B8B8D0", "fairy": "#EE99AC",
}

# ドロップダウン用リスト（日本語名でソート）
POKEMON_LIST = sorted(
    [(k, v["name_ja"]) for k, v in _POKEMON.items() if not k.startswith("_")],
    key=lambda x: x[1],
)
DAMAGE_MOVE_LIST = [("", "（なし）")] + sorted(
    [(k, v["name_ja"]) for k, v in _MOVES.items()
     if not k.startswith("_") and v.get("category") != "status"],
    key=lambda x: x[1],
)
ITEM_LIST = sorted(
    [(k, v["name_ja"]) for k, v in _ITEMS.items() if not k.startswith("_")],
    key=lambda x: x[1],
)


# ─────────────────────────────────────────────────────────────────────────────
# 共通ウィジェット
# ─────────────────────────────────────────────────────────────────────────────

class SearchableComboBox(QComboBox):
    """入力でフィルタリングできるコンボボックス"""

    def __init__(self, items: list[tuple], parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for key, name in items:
            self.addItem(name, userData=key)
        completer = QCompleter([name for _, name in items], self)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(completer)

    def current_key(self) -> str:
        return self.currentData() or ""

    def set_key(self, key: str):
        for i in range(self.count()):
            if self.itemData(i) == key:
                self.setCurrentIndex(i)
                return


class EVWidget(QWidget):
    """EV 6ステータス入力（3列×2行）"""
    changed = pyqtSignal()

    _STATS = [("HP", "hp"), ("こうげき", "attack"), ("ぼうぎょ", "defense"),
              ("とくこう", "sp_attack"), ("とくぼう", "sp_defense"), ("すばやさ", "speed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self._spins: dict[str, QSpinBox] = {}
        for i, (label, key) in enumerate(self._STATS):
            row, col = divmod(i, 3)
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 10px; color: #555;")
            spin = QSpinBox()
            spin.setRange(0, 252)
            spin.setFixedWidth(58)
            spin.valueChanged.connect(self.changed.emit)
            layout.addWidget(lbl,  row * 2,     col)
            layout.addWidget(spin, row * 2 + 1, col)
            self._spins[key] = spin

    def get_evs(self) -> dict:
        return {k: s.value() for k, s in self._spins.items()}


class StatsDisplay(QWidget):
    """計算済みステータス表示"""

    _STATS = [("HP", "hp"), ("こうげき", "attack"), ("ぼうぎょ", "defense"),
              ("とくこう", "sp_attack"), ("とくぼう", "sp_defense"), ("すばやさ", "speed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._vals: dict[str, QLabel] = {}
        for i, (name, key) in enumerate(self._STATS):
            row, col = divmod(i, 3)
            hdr = QLabel(name)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setStyleSheet("font-size: 10px; color: #777;")
            val = QLabel("—")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val.setStyleSheet("font-weight: bold; font-size: 13px;")
            layout.addWidget(hdr, row * 2,     col)
            layout.addWidget(val, row * 2 + 1, col)
            self._vals[key] = val

    def update(self, stats: dict):
        for key, lbl in self._vals.items():
            lbl.setText(str(stats.get(key, "—")))


# ─────────────────────────────────────────────────────────────────────────────
# ポケモン入力パネル
# ─────────────────────────────────────────────────────────────────────────────

class PokemonPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._build_ui()
        self._connect()
        QTimer.singleShot(0, self._on_pokemon_changed)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ── ポケモン名 + レベル ──
        r = QHBoxLayout()
        r.addWidget(QLabel("ポケモン"))
        self.pokemon_cb = SearchableComboBox(POKEMON_LIST)
        self.pokemon_cb.setMinimumWidth(140)
        r.addWidget(self.pokemon_cb, 3)
        r.addWidget(QLabel("Lv"))
        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 100)
        self.level_spin.setValue(50)
        self.level_spin.setFixedWidth(48)
        r.addWidget(self.level_spin)
        root.addLayout(r)

        # ── タイプ表示 ──
        self.type_label = QLabel()
        self.type_label.setTextFormat(Qt.TextFormat.RichText)
        self.type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.type_label)

        # ── 性格 + 持ち物 ──
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("性格"))
        self.nature_cb = QComboBox()
        for k, v in _NATURES.items():
            if not k.startswith("_"):
                nd = v
                boost  = nd["boosted"]  or "なし"
                reduce = nd["reduced"]  or "なし"
                self.nature_cb.addItem(
                    f"{nd['name_ja']}  ↑{boost} ↓{reduce}", userData=k
                )
        r2.addWidget(self.nature_cb, 2)
        r2.addWidget(QLabel("持ち物"))
        self.item_cb = SearchableComboBox(ITEM_LIST)
        self.item_cb.setMinimumWidth(120)
        r2.addWidget(self.item_cb, 2)
        root.addLayout(r2)

        # ── 特性 + メガシンカ ──
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("特性"))
        self.ability_edit = QLineEdit()
        self.ability_edit.setPlaceholderText("例: rough-skin")
        r3.addWidget(self.ability_edit, 3)
        self.mega_cb = QCheckBox("メガシンカ")
        self.mega_cb.setVisible(False)
        r3.addWidget(self.mega_cb)
        root.addLayout(r3)

        # ── 技 4つ ──
        move_grp = QGroupBox("技")
        mg = QGridLayout(move_grp)
        mg.setSpacing(4)
        self.move_cbs: list[SearchableComboBox] = []
        for i in range(4):
            mg.addWidget(QLabel(f"技{i+1}"), i, 0)
            cb = SearchableComboBox(DAMAGE_MOVE_LIST)
            mg.addWidget(cb, i, 1)
            self.move_cbs.append(cb)
        root.addWidget(move_grp)

        # ── EV ──
        ev_grp = QGroupBox("努力値 (EV  各0〜252)")
        ev_layout = QVBoxLayout(ev_grp)
        self.ev_widget = EVWidget()
        ev_layout.addWidget(self.ev_widget)
        root.addWidget(ev_grp)

        # ── IV ──
        iv_row = QHBoxLayout()
        self.iv_max_cb = QCheckBox("個体値 全31（変更不要なら ON のまま）")
        self.iv_max_cb.setChecked(True)
        iv_row.addWidget(self.iv_max_cb)
        root.addLayout(iv_row)

        # ── ステータス表示 ──
        stat_grp = QGroupBox("実数値（自動計算）")
        sl = QVBoxLayout(stat_grp)
        self.stats_disp = StatsDisplay()
        sl.addWidget(self.stats_disp)
        root.addWidget(stat_grp)

        root.addStretch()

    def _connect(self):
        self.pokemon_cb.currentIndexChanged.connect(self._on_pokemon_changed)
        self.level_spin.valueChanged.connect(self._fire)
        self.nature_cb.currentIndexChanged.connect(self._fire)
        self.item_cb.currentIndexChanged.connect(self._fire)
        self.ability_edit.textChanged.connect(self._fire)
        self.mega_cb.stateChanged.connect(self._fire)
        for cb in self.move_cbs:
            cb.currentIndexChanged.connect(self._fire)
        self.ev_widget.changed.connect(self._fire)
        self.iv_max_cb.stateChanged.connect(self._fire)

    def _on_pokemon_changed(self):
        key = self.pokemon_cb.current_key()
        if not key:
            return
        pd = get_pokemon_data(key)
        # タイプバッジ
        badges = []
        for t in pd.get("types", []):
            c = TYPE_COLOR.get(t, "#888")
            n = TYPE_JA.get(t, t)
            badges.append(
                f'<span style="background:{c};color:white;'
                f'padding:2px 8px;border-radius:4px;font-size:11px"> {n} </span>'
            )
        self.type_label.setText("  ".join(badges))
        # メガ
        mega_forms = [k for k in pd if k.startswith("mega")]
        self.mega_cb.setVisible(bool(mega_forms))
        if mega_forms:
            self.mega_cb.setText("メガシンカ")
            self.mega_cb.setProperty("mega_form", mega_forms[0])
        # 特性ヒント
        abilities = pd.get("abilities", [])
        if abilities:
            self.ability_edit.setPlaceholderText(abilities[0])
        self._fire()

    def _fire(self):
        self._refresh_stats()
        self.changed.emit()

    def _refresh_stats(self):
        try:
            stats = calculate_all_stats(self.get_build())
            self.stats_disp.update(stats)
        except Exception:
            pass

    def get_build(self) -> PokemonBuild:
        species = self.pokemon_cb.current_key() or POKEMON_LIST[0][0]
        nature  = self.nature_cb.currentData() or "hardy"
        item    = self.item_cb.current_key()   or "none"
        ability = self.ability_edit.text().strip() or self.ability_edit.placeholderText()
        moves   = [cb.current_key() for cb in self.move_cbs if cb.current_key()]
        evs     = self.ev_widget.get_evs()
        iv_val  = 31 if self.iv_max_cb.isChecked() else 0
        is_mega = self.mega_cb.isVisible() and self.mega_cb.isChecked()
        mega_form = (self.mega_cb.property("mega_form") or "") if is_mega else ""
        return PokemonBuild(
            species=species, level=self.level_spin.value(),
            nature=nature, item=item, ability=ability, moves=moves,
            ev_hp=evs["hp"],       ev_attack=evs["attack"],
            ev_defense=evs["defense"], ev_sp_attack=evs["sp_attack"],
            ev_sp_defense=evs["sp_defense"], ev_speed=evs["speed"],
            iv_hp=iv_val, iv_attack=iv_val, iv_defense=iv_val,
            iv_sp_attack=iv_val, iv_sp_defense=iv_val, iv_speed=iv_val,
            is_mega=is_mega, mega_form=mega_form,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 対戦状態パネル
# ─────────────────────────────────────────────────────────────────────────────

class BattleStatePanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("⚙  対戦状態", parent)
        layout = QHBoxLayout(self)

        layout.addWidget(QLabel("天気"))
        self.weather_cb = QComboBox()
        for k, lbl in [("none","なし"),("sun","晴れ"),("rain","雨"),
                        ("sand","砂嵐"),("snow","雪")]:
            self.weather_cb.addItem(lbl, userData=k)
        layout.addWidget(self.weather_cb)

        layout.addSpacing(16)
        layout.addWidget(QLabel("フィールド"))
        self.terrain_cb = QComboBox()
        for k, lbl in [("none","なし"),("electric","エレキ"),("grassy","グラス"),
                        ("misty","ミスト"),("psychic","サイコ")]:
            self.terrain_cb.addItem(lbl, userData=k)
        layout.addWidget(self.terrain_cb)

        layout.addSpacing(16)
        layout.addWidget(QLabel("【自分】"))
        self.burn_atk  = QCheckBox("やけど")
        self.crit_cb   = QCheckBox("急所")
        layout.addWidget(self.burn_atk)
        layout.addWidget(self.crit_cb)

        layout.addSpacing(16)
        layout.addWidget(QLabel("【相手】"))
        self.burn_def = QCheckBox("やけど")
        layout.addWidget(self.burn_def)

        layout.addStretch()

        for w in [self.weather_cb, self.terrain_cb,
                  self.burn_atk, self.crit_cb, self.burn_def]:
            (w.currentIndexChanged if isinstance(w, QComboBox)
             else w.stateChanged).connect(self.changed.emit)

    def atk_state(self) -> BattleState:
        return BattleState(
            weather=self.weather_cb.currentData(),
            terrain=self.terrain_cb.currentData(),
            burned=self.burn_atk.isChecked(),
            is_critical=self.crit_cb.isChecked(),
        )

    def def_state(self) -> BattleState:
        return BattleState(
            weather=self.weather_cb.currentData(),
            terrain=self.terrain_cb.currentData(),
            burned=self.burn_def.isChecked(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 結果テーブル
# ─────────────────────────────────────────────────────────────────────────────

class ResultTable(QTableWidget):
    HEADERS = ["技名", "威力", "タイプ相性", "ダメージ", "割合", "判定"]
    EFF_BG = {
        0.0:  QColor(200, 200, 200, 120),
        0.25: QColor(150, 210, 255, 120),
        0.5:  QColor(180, 225, 255, 120),
        2.0:  QColor(255, 210, 160, 150),
        4.0:  QColor(255, 160, 130, 170),
    }
    EFF_LABEL = {0: "無効", 0.25: "1/4", 0.5: "今ひとつ",
                 1.0: "等倍", 2.0: "抜群", 4.0: "2倍抜群"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(150)

    def show_results(self, results):
        self.setRowCount(0)
        for r in results:
            row = self.rowCount()
            self.insertRow(row)
            name = r.move_name_ja + ("◎" if r.is_stab else "")
            power_str = str(r.base_power) if r.base_power else "可変"
            eff_str   = self.EFF_LABEL.get(r.type_effectiveness,
                                            str(r.type_effectiveness))
            dmg_str   = f"{r.damage_min} 〜 {r.damage_max}"
            pct_str   = f"{r.damage_percent_min:.1f}% 〜 {r.damage_percent_max:.1f}%"

            for col, text in enumerate([name, power_str, eff_str,
                                         dmg_str, pct_str, r.ko_chance]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(row, col, item)

            # 背景色（タイプ相性）
            bg = self.EFF_BG.get(r.type_effectiveness)
            if bg:
                for col in range(self.columnCount()):
                    itm = self.item(row, col)
                    if itm:
                        itm.setBackground(bg)

            # STAB は太字
            if r.is_stab:
                bold = QFont()
                bold.setBold(True)
                for col in range(self.columnCount()):
                    itm = self.item(row, col)
                    if itm:
                        itm.setFont(bold)

            # 確定1発は赤
            if "確定1発" in r.ko_chance:
                itm = self.item(row, 5)
                if itm:
                    itm.setForeground(QColor(200, 30, 30))
            elif "確定2発" in r.ko_chance:
                itm = self.item(row, 5)
                if itm:
                    itm.setForeground(QColor(200, 120, 0))


# ─────────────────────────────────────────────────────────────────────────────
# メインウィンドウ
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ポケモンチャンピオンズ ダメージ計算ツール v1.0")
        self.setMinimumSize(1060, 800)
        self._build_ui()
        # 入力変更 → 300ms後に自動計算（タイピング中に何度も走らないよう間引き）
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._calculate)
        self.atk_panel.changed.connect(self._timer.start)
        self.def_panel.changed.connect(self._timer.start)
        self.state_panel.changed.connect(self._timer.start)
        QTimer.singleShot(400, self._calculate)  # 初回計算

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setSpacing(8)
        vbox.setContentsMargins(10, 10, 10, 10)

        # タイトル
        title = QLabel("ポケモンチャンピオンズ  ダメージ計算ツール")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 17px; font-weight: bold; "
            "padding: 8px; background: #2c3e50; color: white; border-radius: 6px;"
        )
        vbox.addWidget(title)

        # ポケモンパネル（左＝自分、右＝相手）
        panels = QHBoxLayout()
        panels.setSpacing(10)
        self.atk_panel = PokemonPanel("⚔   自分のポケモン")
        self.def_panel = PokemonPanel("🛡   相手のポケモン")
        for panel in (self.atk_panel, self.def_panel):
            scroll = QScrollArea()
            scroll.setWidget(panel)
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(400)
            panels.addWidget(scroll)
        vbox.addLayout(panels, stretch=4)

        # 対戦状態パネル
        self.state_panel = BattleStatePanel()
        vbox.addWidget(self.state_panel)

        # 結果テーブル
        result_row = QHBoxLayout()
        result_row.setSpacing(10)
        atk_grp = QGroupBox("⚔   自分 → 相手（与えるダメージ）")
        atk_lay = QVBoxLayout(atk_grp)
        self.atk_table = ResultTable()
        atk_lay.addWidget(self.atk_table)

        def_grp = QGroupBox("🛡   相手 → 自分（受けるダメージ）")
        def_lay = QVBoxLayout(def_grp)
        self.def_table = ResultTable()
        def_lay.addWidget(self.def_table)

        result_row.addWidget(atk_grp)
        result_row.addWidget(def_grp)
        vbox.addLayout(result_row, stretch=2)

        self.statusBar().showMessage("準備完了  —  ポケモンと技を選ぶと自動計算されます")

    def _calculate(self):
        try:
            atk = self.atk_panel.get_build()
            df  = self.def_panel.get_build()
            as_ = self.state_panel.atk_state()
            ds  = self.state_panel.def_state()

            r_atk = CALC.calculate_all_moves(atk, df,  as_, ds)
            r_def = CALC.calculate_all_moves(df,  atk, ds,  as_)

            self.atk_table.show_results(r_atk)
            self.def_table.show_results(r_def)

            atk_name = _POKEMON.get(atk.species, {}).get("name_ja", atk.species)
            def_name = _POKEMON.get(df.species,  {}).get("name_ja", df.species)
            atk_hp   = calculate_all_stats(atk)["hp"]
            def_hp   = calculate_all_stats(df)["hp"]
            self.statusBar().showMessage(
                f"計算完了   {atk_name}（HP {atk_hp}）  vs  {def_name}（HP {def_hp}）"
            )
        except Exception as e:
            self.statusBar().showMessage(f"エラー: {e}")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Meiryo, Yu Gothic, Noto Sans JP, sans-serif", 10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
