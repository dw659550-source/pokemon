#!/usr/bin/env python3
"""
ポケモンチャンピオンズ ダメージ計算ツール - デスクトップ版 (Phase 2)
起動方法: python gui.py
"""
import sys
import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QSpinBox, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea,
    QPushButton, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QCompleter

logging.basicConfig(level=logging.INFO)

# ── Phase 2 オプション依存（未インストールでも起動できる）──
try:
    from scraper.usage_scraper import get_usage_data
    HAS_SCRAPER = True
except Exception:
    HAS_SCRAPER = False

try:
    from capture.screen_capture import list_windows, capture_window, capture_primary_monitor
    from capture.ocr_detector import PokemonOCRDetector
    from capture.sprite_detector import SpriteDatabase, detect_opponent_team
    HAS_CAPTURE = True
except Exception:
    HAS_CAPTURE = False

try:
    from capture.battle_monitor import BattleMonitor, load_battle_config
    HAS_BATTLE_MONITOR = True
except Exception:
    HAS_BATTLE_MONITOR = False

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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 バックグラウンドワーカー
# ─────────────────────────────────────────────────────────────────────────────

class UsageFetcher(QThread):
    """使用率データを別スレッドで取得する"""
    finished = pyqtSignal(str, dict)   # (pokemon_key, data)
    failed   = pyqtSignal(str, str)    # (pokemon_key, error_message)

    def __init__(self, pokemon_key: str, force: bool = False):
        super().__init__()
        self._key   = pokemon_key
        self._force = force

    def run(self):
        try:
            data = get_usage_data(self._key, force_refresh=self._force)
            if data:
                self.finished.emit(self._key, data)
            else:
                self.failed.emit(self._key, "データなし")
        except Exception as e:
            self.failed.emit(self._key, str(e))


class OCRWorker(QThread):
    """スクリーンキャプチャ → OCR を別スレッドで実行する"""
    detected = pyqtSignal(list)   # list[DetectionResult]
    error    = pyqtSignal(str)
    _detector = None              # クラス変数でシングルトン

    def __init__(self, window_info=None):
        super().__init__()
        self._window_info = window_info

    def run(self):
        try:
            if OCRWorker._detector is None:
                OCRWorker._detector = PokemonOCRDetector()
            if self._window_info:
                img = capture_window(self._window_info)
            else:
                img = capture_primary_monitor()
            if img is None:
                self.error.emit("キャプチャに失敗しました")
                return
            results = OCRWorker._detector.detect(img)
            self.detected.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class SpriteWorker(QThread):
    """スクリーンキャプチャ → スプライト照合を別スレッドで実行する"""
    detected = pyqtSignal(list)   # [(key, name_ja, score), ...]
    error    = pyqtSignal(str)
    _db = None  # SpriteDatabase シングルトン

    def __init__(self, window_info=None):
        super().__init__()
        self._window_info = window_info

    def run(self):
        try:
            if SpriteWorker._db is None:
                SpriteWorker._db = SpriteDatabase()
            if self._window_info:
                img = capture_window(self._window_info)
            else:
                img = capture_primary_monitor()
            if img is None:
                self.error.emit("キャプチャに失敗しました")
                return
            results = detect_opponent_team(img, SpriteWorker._db)
            self.detected.emit(results)
        except Exception as e:
            self.error.emit(str(e))


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


class OpponentTeamWidget(QGroupBox):
    """スプライト検出で得た相手チームを6つのボタンで表示するパネル"""
    pokemon_selected = pyqtSignal(str)  # pokemon_key

    def __init__(self, parent=None):
        super().__init__("相手チーム（スプライト認識）", parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(4)

        self._status = QLabel("「スプライト検出」を押すと相手チーム6体を認識します")
        self._status.setStyleSheet("color:#888; font-size:11px;")
        outer.addWidget(self._status)

        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(6)
        outer.addLayout(self._btn_row)
        self._buttons: list[QPushButton] = []

    def show_team(self, detections: list):
        """[(key, name_ja, score), ...] を受け取り、ボタンとして表示する"""
        for btn in self._buttons:
            btn.deleteLater()
        self._buttons.clear()

        if not detections:
            self._status.setText("認識結果なし（スプライトが未ダウンロードの可能性）")
            return

        self._status.setText("クリックすると相手パネルに反映されます")
        for key, name_ja, score in detections:
            pct = int(score * 100)
            btn = QPushButton(f"{name_ja}\n{pct}%")
            btn.setFixedSize(88, 48)
            btn.setToolTip(f"{key}  一致度 {pct}%")
            # 一致度で色を変える
            if score >= 0.7:
                btn.setStyleSheet("background:#27ae60; color:white; border-radius:4px;")
            elif score >= 0.4:
                btn.setStyleSheet("background:#e67e22; color:white; border-radius:4px;")
            else:
                btn.setStyleSheet("background:#7f8c8d; color:white; border-radius:4px;")
            btn.clicked.connect(lambda checked, k=key: self.pokemon_selected.emit(k))
            self._btn_row.addWidget(btn)
            self._buttons.append(btn)


class UsageRateWidget(QGroupBox):
    """相手ポケモンの使用率（技・持ち物）を表示するパネル"""

    def __init__(self, parent=None):
        super().__init__("使用率データ（pokechamdb.com）", parent)
        self._layout = QVBoxLayout(self)
        self._status = QLabel("ポケモンを選ぶと自動取得します")
        self._status.setStyleSheet("color: #888; font-size: 11px;")
        self._layout.addWidget(self._status)
        self._move_labels: list[QLabel] = []
        self._item_labels: list[QLabel] = []
        self._worker: UsageFetcher | None = None
        self._current_key = ""

        if not HAS_SCRAPER:
            self._status.setText("⚠ pip install requests beautifulsoup4 が必要です")
            self.setEnabled(False)

    def fetch(self, pokemon_key: str, force: bool = False):
        if not HAS_SCRAPER:
            return
        if pokemon_key == self._current_key and not force:
            return
        self._current_key = pokemon_key
        self._status.setText("取得中...")
        self._clear_labels()

        self._worker = UsageFetcher(pokemon_key, force)
        self._worker.finished.connect(self._on_data)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _clear_labels(self):
        for lbl in self._move_labels + self._item_labels:
            lbl.deleteLater()
        self._move_labels.clear()
        self._item_labels.clear()

    @pyqtSlot(str, dict)
    def _on_data(self, key: str, data: dict):
        if key != self._current_key:
            return
        self._clear_labels()
        moves    = data.get("moves", [])
        items    = data.get("items", [])

        if not moves and not items:
            self._status.setText("データが見つかりませんでした（サイト構造が変わった可能性）")
            return

        self._status.setText("")

        # 技
        if moves:
            hdr = QLabel("技")
            hdr.setStyleSheet("font-weight: bold; font-size: 11px; color: #444; margin-top:4px;")
            self._layout.addWidget(hdr)
            self._move_labels.append(hdr)
            for name, pct in moves[:5]:
                bar_len = int(pct / 2)
                bar = "█" * bar_len
                lbl = QLabel(f"  {name}  {bar} {pct:.1f}%")
                lbl.setStyleSheet("font-size: 11px; font-family: monospace;")
                self._layout.addWidget(lbl)
                self._move_labels.append(lbl)

        # 持ち物
        if items:
            hdr2 = QLabel("持ち物")
            hdr2.setStyleSheet("font-weight: bold; font-size: 11px; color: #444; margin-top:4px;")
            self._layout.addWidget(hdr2)
            self._item_labels.append(hdr2)
            for name, pct in items[:5]:
                bar_len = int(pct / 2)
                bar = "█" * bar_len
                lbl = QLabel(f"  {name}  {bar} {pct:.1f}%")
                lbl.setStyleSheet("font-size: 11px; font-family: monospace;")
                self._layout.addWidget(lbl)
                self._item_labels.append(lbl)

    @pyqtSlot(str, str)
    def _on_fail(self, key: str, msg: str):
        if key == self._current_key:
            self._status.setText(f"取得失敗: {msg}")


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
# 対戦中リアルタイム監視ウィジェット
# ─────────────────────────────────────────────────────────────────────────────

class BattleMonitorWidget(QGroupBox):
    """対戦画面を常時監視し、相手ポケモン名を自動検出するパネル"""
    opponent_detected = pyqtSignal(str, str)  # (key, name_ja)

    def __init__(self, parent=None):
        super().__init__("対戦中 — 相手ポケモン自動検出（リアルタイム）", parent)
        self._monitor: "BattleMonitor | None" = None

        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("モニター:"))
        self.monitor_spin = QSpinBox()
        self.monitor_spin.setRange(1, 8)
        self.monitor_spin.setValue(1)
        self.monitor_spin.setFixedWidth(48)
        self.monitor_spin.setToolTip("キャプチャカードのモニター番号 (1=プライマリ, 2=セカンダリ...)")
        layout.addWidget(self.monitor_spin)

        self.toggle_btn = QPushButton("監視開始")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; padding:4px 14px; border-radius:4px; }"
            "QPushButton:checked { background:#c0392b; }"
        )
        self.toggle_btn.toggled.connect(self._on_toggle)
        layout.addWidget(self.toggle_btn)

        self.status_lbl = QLabel("停止中")
        self.status_lbl.setStyleSheet("color:#888; font-size:11px;")
        self.status_lbl.setMinimumWidth(320)
        layout.addWidget(self.status_lbl)

        hint = QLabel("位置調整: python scripts/calibrate_battle.py <スクショ>")
        hint.setStyleSheet("color:#aaa; font-size:10px;")
        layout.addWidget(hint)

        layout.addStretch()

        if not HAS_BATTLE_MONITOR:
            self.toggle_btn.setEnabled(False)
            self.status_lbl.setText("⚠ pip install mss easyocr が必要です")
            self.status_lbl.setStyleSheet("color:#c0392b; font-size:11px;")

    def _on_toggle(self, checked: bool):
        if checked:
            self._start()
        else:
            self._stop()

    def _start(self):
        cfg = load_battle_config()
        cfg["monitor"] = self.monitor_spin.value()
        self._monitor = BattleMonitor(config=cfg)
        self._monitor.opponent_changed.connect(self._on_detected)
        self._monitor.status_changed.connect(self._on_status)
        self._monitor.start()
        self.toggle_btn.setText("監視停止")
        self.monitor_spin.setEnabled(False)
        self.status_lbl.setText("起動中...")
        self.status_lbl.setStyleSheet("color:#2980b9; font-size:11px;")

    def _stop(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(2000)
            self._monitor = None
        self.toggle_btn.setText("監視開始")
        self.status_lbl.setText("停止中")
        self.status_lbl.setStyleSheet("color:#888; font-size:11px;")
        self.monitor_spin.setEnabled(True)

    @pyqtSlot(str, str)
    def _on_detected(self, key: str, name_ja: str):
        self.opponent_detected.emit(key, name_ja)

    @pyqtSlot(str)
    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)
        if "検出:" in msg:
            self.status_lbl.setStyleSheet("color:#27ae60; font-weight:bold; font-size:11px;")
        elif "失敗" in msg or "エラー" in msg or "見つかりません" in msg:
            self.status_lbl.setStyleSheet("color:#c0392b; font-size:11px;")
        else:
            self.status_lbl.setStyleSheet("color:#2980b9; font-size:11px;")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 キャプチャパネル
# ─────────────────────────────────────────────────────────────────────────────

class CapturePanel(QGroupBox):
    """画面キャプチャ＋OCR / スプライト認識パネル"""
    pokemon_detected  = pyqtSignal(str)   # OCR 検出: pokemon_key
    sprites_detected  = pyqtSignal(list)  # スプライト検出: [(key, name_ja, score), ...]

    def __init__(self, parent=None):
        super().__init__("Phase 2 — 画面キャプチャ / 相手自動検出", parent)
        self._worker: OCRWorker | None = None
        self._windows: list = []
        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        # ウィンドウ選択
        layout.addWidget(QLabel("キャプチャ対象:"))
        self.win_cb = QComboBox()
        self.win_cb.setMinimumWidth(220)
        layout.addWidget(self.win_cb)

        self.refresh_btn = QPushButton("ウィンドウ一覧更新")
        self.refresh_btn.clicked.connect(self._refresh_windows)
        layout.addWidget(self.refresh_btn)

        # OCR ボタン
        self.capture_btn = QPushButton("テキスト検出（OCR）")
        self.capture_btn.setStyleSheet(
            "background:#2980b9; color:white; padding:4px 10px; border-radius:4px;"
        )
        self.capture_btn.clicked.connect(self._start_capture)
        layout.addWidget(self.capture_btn)

        # スプライト検出ボタン
        self.sprite_btn = QPushButton("相手チーム検出（スプライト）")
        self.sprite_btn.setStyleSheet(
            "background:#8e44ad; color:white; padding:4px 10px; border-radius:4px;"
        )
        self.sprite_btn.clicked.connect(self._start_sprite)
        layout.addWidget(self.sprite_btn)

        # 結果ラベル
        self.result_lbl = QLabel("")
        self.result_lbl.setMinimumWidth(200)
        layout.addWidget(self.result_lbl)

        layout.addStretch()

        if not HAS_CAPTURE:
            self.capture_btn.setEnabled(False)
            self.result_lbl.setText(
                "⚠ pip install mss easyocr pygetwindow Pillow が必要です"
            )
            self.result_lbl.setStyleSheet("color: #c0392b; font-size: 11px;")
        else:
            self._refresh_windows()

    def _refresh_windows(self):
        if not HAS_CAPTURE:
            return
        self._windows = list_windows()
        self.win_cb.clear()
        self.win_cb.addItem("（全画面プライマリ）", userData=None)
        for w in self._windows:
            label = w.title[:50] + ("…" if len(w.title) > 50 else "")
            self.win_cb.addItem(label, userData=w)

    def _start_capture(self):
        if not HAS_CAPTURE:
            return
        self.capture_btn.setEnabled(False)
        self.result_lbl.setText("OCR 実行中...")
        self.result_lbl.setStyleSheet("color: #2980b9;")

        win = self.win_cb.currentData()
        self._worker = OCRWorker(window_info=win)
        self._worker.detected.connect(self._on_detected)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self.capture_btn.setEnabled(True))
        self._worker.start()

    @pyqtSlot(list)
    def _on_detected(self, results):
        if not results:
            self.result_lbl.setText("ポケモンが検出されませんでした")
            self.result_lbl.setStyleSheet("color: #e67e22;")
            return
        best = results[0]
        self.result_lbl.setText(
            f"検出: {best.name_ja} ({best.confidence*100:.0f}%)"
        )
        self.result_lbl.setStyleSheet("color: #27ae60; font-weight: bold;")
        self.pokemon_detected.emit(best.key)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self.result_lbl.setText(f"エラー: {msg}")
        self.result_lbl.setStyleSheet("color: #c0392b;")

    def _start_sprite(self):
        if not HAS_CAPTURE:
            return
        self.sprite_btn.setEnabled(False)
        self.result_lbl.setText("スプライト照合中...")
        self.result_lbl.setStyleSheet("color: #8e44ad;")
        win = self.win_cb.currentData()
        self._sprite_worker = SpriteWorker(window_info=win)
        self._sprite_worker.detected.connect(self._on_sprites)
        self._sprite_worker.error.connect(self._on_error)
        self._sprite_worker.finished.connect(lambda: self.sprite_btn.setEnabled(True))
        self._sprite_worker.start()

    @pyqtSlot(list)
    def _on_sprites(self, results: list):
        count = len(results)
        self.result_lbl.setText(f"スプライト検出: {count} 体")
        self.result_lbl.setStyleSheet("color: #8e44ad; font-weight: bold;")
        self.sprites_detected.emit(results)


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
        self.setWindowTitle("ポケモンチャンピオンズ ダメージ計算ツール v2.0")
        self.setMinimumSize(1060, 900)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._calculate)
        self.atk_panel.changed.connect(self._timer.start)
        self.def_panel.changed.connect(self._timer.start)
        self.state_panel.changed.connect(self._timer.start)
        # 相手ポケモン変更 → 使用率取得
        self.def_panel.pokemon_cb.currentIndexChanged.connect(self._on_def_pokemon_changed)
        QTimer.singleShot(400, self._calculate)

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

        # 対戦中リアルタイム監視パネル
        self.battle_monitor_widget = BattleMonitorWidget()
        self.battle_monitor_widget.opponent_detected.connect(self._on_battle_detected)
        vbox.addWidget(self.battle_monitor_widget)

        # Phase 2 キャプチャパネル
        self.capture_panel = CapturePanel()
        self.capture_panel.pokemon_detected.connect(self._on_pokemon_detected)
        self.capture_panel.sprites_detected.connect(self._on_sprites_detected)
        vbox.addWidget(self.capture_panel)

        # 相手チーム検出結果（スプライト）
        self.opponent_team_widget = OpponentTeamWidget()
        self.opponent_team_widget.pokemon_selected.connect(self._on_pokemon_detected)
        vbox.addWidget(self.opponent_team_widget)

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

        # 結果テーブル＋使用率
        result_row = QHBoxLayout()
        result_row.setSpacing(10)

        atk_grp = QGroupBox("⚔   自分 → 相手（与えるダメージ）")
        atk_lay = QVBoxLayout(atk_grp)
        self.atk_table = ResultTable()
        atk_lay.addWidget(self.atk_table)

        # 相手側：ダメージ表 + 使用率
        def_col = QVBoxLayout()
        def_grp = QGroupBox("🛡   相手 → 自分（受けるダメージ）")
        def_lay = QVBoxLayout(def_grp)
        self.def_table = ResultTable()
        def_lay.addWidget(self.def_table)
        def_col.addWidget(def_grp)

        self.usage_widget = UsageRateWidget()
        self.usage_widget.setMaximumHeight(200)
        def_col.addWidget(self.usage_widget)

        result_row.addWidget(atk_grp)
        result_row.addLayout(def_col)
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

    def _on_def_pokemon_changed(self):
        """相手ポケモン変更時 → 使用率を自動取得"""
        key = self.def_panel.pokemon_cb.current_key()
        if key and HAS_SCRAPER:
            self.usage_widget.fetch(key)

    @pyqtSlot(str, str)
    def _on_battle_detected(self, key: str, name_ja: str):
        """対戦監視による自動検出 → 相手パネルと使用率を更新"""
        self.def_panel.pokemon_cb.set_key(key)
        self.statusBar().showMessage(f"自動検出: {name_ja} を相手に設定しました")
        if HAS_SCRAPER:
            self.usage_widget.fetch(key)

    @pyqtSlot(str)
    def _on_pokemon_detected(self, pokemon_key: str):
        """OCR / ボタン選択結果を相手パネルに反映"""
        self.def_panel.pokemon_cb.set_key(pokemon_key)
        pd = _POKEMON.get(pokemon_key, {})
        name = pd.get("name_ja", pokemon_key)
        self.statusBar().showMessage(f"検出: {name} を相手に設定しました")

    @pyqtSlot(list)
    def _on_sprites_detected(self, results: list):
        """スプライト検出結果を OpponentTeamWidget に渡す"""
        self.opponent_team_widget.show_team(results)


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
