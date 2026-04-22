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
    QPushButton, QSizePolicy, QFrame, QProgressBar, QTabWidget,
    QSplitter, QListWidget, QListWidgetItem, QTextEdit, QInputDialog,
    QMessageBox,
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
with open(_DATA / "type_chart.json", encoding="utf-8") as f:
    _TYPE_CHART: dict = json.load(f)

_ABILITIES: dict = {}
def _load_abilities() -> dict:
    global _ABILITIES
    if not _ABILITIES:
        p = _DATA / "abilities.json"
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    _ABILITIES = json.load(f)
            except Exception:
                pass
    return _ABILITIES

_ALL_TYPES = [
    "normal","fire","water","electric","grass","ice","fighting","poison",
    "ground","flying","psychic","bug","rock","ghost","dragon","dark","steel","fairy",
]

def compute_type_matchup(def_types: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"x4": [], "x2": [], "x0.5": [], "x0.25": [], "x0": []}
    for atk in _ALL_TYPES:
        eff = 1.0
        for d in def_types:
            eff *= _TYPE_CHART.get(atk, {}).get(d, 1.0)
        if   eff >= 4.0: result["x4"].append(atk)
        elif eff >= 2.0: result["x2"].append(atk)
        elif eff == 0.0: result["x0"].append(atk)
        elif eff <= 0.25: result["x0.25"].append(atk)
        elif eff <= 0.5:  result["x0.5"].append(atk)
    return result

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
# 日本語名 → キー（使用率データの技名を解決するため）
_MOVE_JA_TO_KEY: dict[str, str] = {
    v["name_ja"]: k for k, v in _MOVES.items()
    if not k.startswith("_") and "name_ja" in v
}
ITEM_LIST = sorted(
    [(k, v["name_ja"]) for k, v in _ITEMS.items() if not k.startswith("_")],
    key=lambda x: x[1],
)

# ポケモンごとの覚え技マップ（遅延ロード）
_POKEMON_MOVES: dict[str, list[str]] = {}
_POKEMON_MOVES_PATH = _DATA / "pokemon_moves.json"

def _get_learnable_moves(pokemon_key: str) -> list[tuple]:
    """ポケモンが覚えられるダメージ技リストを返す。データなければ全技。"""
    global _POKEMON_MOVES
    if not _POKEMON_MOVES and _POKEMON_MOVES_PATH.exists():
        try:
            with open(_POKEMON_MOVES_PATH, encoding="utf-8") as f:
                _POKEMON_MOVES = json.load(f)
        except Exception:
            pass
    if not pokemon_key or not _POKEMON_MOVES:
        return DAMAGE_MOVE_LIST
    learnable = set(_POKEMON_MOVES.get(pokemon_key, []))
    if not learnable:
        return DAMAGE_MOVE_LIST
    return [("", "（なし）")] + sorted(
        [(k, v) for k, v in DAMAGE_MOVE_LIST[1:] if k in learnable],
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

    def update_items(self, items: list[tuple]):
        """アイテムを入れ替え、以前の選択を可能な限り維持する"""
        prev_key = self.current_key()
        self.blockSignals(True)
        self.clear()
        for key, name in items:
            self.addItem(name, userData=key)
        completer = QCompleter([name for _, name in items], self)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(completer)
        self.set_key(prev_key)  # 覚えない技なら index 0（なし）に戻る
        self.blockSignals(False)


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


class PokemonTypeInfoWidget(QGroupBox):
    """相手ポケモンのタイプ相性・特性を縦リストで表示するパネル"""

    # effectiveness → (バー幅px, バー色)
    _BAR = {
        4.0:  (80, "#c0392b"),
        2.0:  (50, "#e67e22"),
        0.5:  (30, "#2980b9"),
        0.25: (15, "#1a5276"),
    }

    def __init__(self, parent=None):
        super().__init__("タイプ相性・特性", parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        self._vbox = QVBoxLayout(self)
        self._vbox.setSpacing(2)
        self._vbox.setContentsMargins(6, 6, 6, 6)
        self._vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._rows: list[QWidget] = []
        self._hint = QLabel("ポケモンを選ぶと表示されます")
        self._hint.setStyleSheet("color:#888; font-size:11px;")
        self._vbox.addWidget(self._hint)

    def _add(self, w: QWidget):
        self._vbox.addWidget(w)
        self._rows.append(w)

    def refresh(self, pokemon_key: str):
        for w in self._rows:
            self._vbox.removeWidget(w)
            w.deleteLater()
        self._rows.clear()

        pd = _POKEMON.get(pokemon_key, {})
        if not pd:
            return
        self._hint.setText("")

        def_types = pd.get("types", [])

        # ── タイプ相性を縦リスト ──
        rows: list[tuple[float, str]] = []
        for atk in _ALL_TYPES:
            eff = 1.0
            for d in def_types:
                eff *= _TYPE_CHART.get(atk, {}).get(d, 1.0)
            if eff != 1.0:
                rows.append((eff, atk))
        rows.sort(key=lambda x: x[0], reverse=True)

        for eff, atk in rows:
            row = QWidget()
            hl  = QHBoxLayout(row)
            hl.setContentsMargins(2, 1, 2, 1)
            hl.setSpacing(6)

            # タイプバッジ
            badge = QLabel(TYPE_JA.get(atk, atk))
            badge.setFixedWidth(58)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"background:{TYPE_COLOR.get(atk,'#888')}; color:white;"
                f" padding:1px 4px; border-radius:3px; font-size:11px;"
            )
            hl.addWidget(badge)

            if eff == 0.0:
                note = QLabel("×0　（全く効かない）")
                note.setStyleSheet("color:#999; font-size:11px;")
                hl.addWidget(note)
            else:
                bar_w, bar_col = self._BAR.get(eff, (int(eff * 25), "#888"))
                bar = QLabel("")
                bar.setFixedSize(bar_w, 12)
                bar.setStyleSheet(f"background:{bar_col}; border-radius:2px;")
                hl.addWidget(bar)
                mult = QLabel(f"×{eff:g}")
                mult.setStyleSheet("font-size:11px; font-weight:bold;")
                hl.addWidget(mult)

            hl.addStretch()
            self._add(row)

        # ── 区切り線 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#ddd; margin:3px 0;")
        self._add(sep)

        # ── 特性 ──
        ab_data = _load_abilities()
        for ab_key in pd.get("abilities", []):
            ab   = ab_data.get(ab_key, {})
            name = ab.get("name_ja", ab_key)
            desc = ab.get("description_ja") or ab.get("description_en", "")
            w    = QWidget()
            vl   = QVBoxLayout(w)
            vl.setContentsMargins(2, 2, 2, 2)
            vl.setSpacing(1)
            vl.addWidget(QLabel(f"◆ {name}",
                                styleSheet="font-weight:bold; font-size:11px;"))
            if desc:
                dl = QLabel(desc)
                dl.setWordWrap(True)
                dl.setStyleSheet("color:#555; font-size:10px;")
                vl.addWidget(dl)
            self._add(w)


class UsageRateWidget(QGroupBox):
    """相手ポケモンの使用率（技・持ち物）を表示するパネル"""
    data_ready = pyqtSignal(str, dict)   # (pokemon_key, data) — 取得完了時

    _BAR_STYLE = (
        "QProgressBar{border:1px solid #ccc;border-radius:3px;font-size:10px;text-align:right;}"
        "QProgressBar::chunk{background:#5dade2;border-radius:2px;}"
    )

    def __init__(self, parent=None):
        super().__init__("使用率データ（pokechamdb.com）", parent)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(2)
        self._layout.setContentsMargins(6, 6, 6, 6)

        hdr = QHBoxLayout()
        self._status = QLabel("ポケモンを選ぶと自動取得します")
        self._status.setStyleSheet("color: #888; font-size: 11px;")
        hdr.addWidget(self._status, 1)
        self._refresh_btn = QPushButton("更新")
        self._refresh_btn.setFixedSize(40, 20)
        self._refresh_btn.setStyleSheet("font-size:10px; padding:0;")
        self._refresh_btn.clicked.connect(self._on_refresh)
        hdr.addWidget(self._refresh_btn)
        self._layout.addLayout(hdr)

        self._widgets: list[QWidget] = []
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
        self._clear_widgets()

        self._worker = UsageFetcher(pokemon_key, force)
        self._worker.finished.connect(self._on_data)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_refresh(self):
        if self._current_key:
            self.fetch(self._current_key, force=True)

    def _clear_widgets(self):
        for w in self._widgets:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

    def _add_section(self, label: str, entries: list):
        hdr = QLabel(label)
        hdr.setStyleSheet("font-weight:bold; font-size:11px; color:#444; margin-top:4px;")
        self._layout.addWidget(hdr)
        self._widgets.append(hdr)
        for name, pct in entries:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 0, 2, 0)
            rl.setSpacing(4)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(110)
            name_lbl.setStyleSheet("font-size:11px;")
            rl.addWidget(name_lbl)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(pct))
            bar.setFixedHeight(14)
            bar.setFormat(f"{pct:.1f}%")
            bar.setTextVisible(True)
            bar.setStyleSheet(self._BAR_STYLE)
            rl.addWidget(bar, stretch=1)
            self._layout.addWidget(row)
            self._widgets.append(row)

    @pyqtSlot(str, dict)
    def _on_data(self, key: str, data: dict):
        if key != self._current_key:
            return
        self._clear_widgets()
        self.data_ready.emit(key, data)
        moves = data.get("moves", [])
        items = data.get("items", [])

        if not moves and not items:
            self._status.setText("このポケモンの使用率データはありません")
            self._status.setStyleSheet("color:#aaa; font-size:11px;")
            return

        self._status.setText("")
        if moves:
            self._add_section("技", moves[:8])
        if items:
            self._add_section("持ち物", items[:5])

    @pyqtSlot(str, str)
    def _on_fail(self, key: str, msg: str):
        if key == self._current_key:
            self._status.setText(f"取得失敗: {msg}")


class EVWidget(QWidget):
    """EV 6ステータス入力（H/A/B/C/D/S 横一列）"""
    changed = pyqtSignal()

    _STATS = [("H","hp"), ("A","attack"), ("B","defense"),
              ("C","sp_attack"), ("D","sp_defense"), ("S","speed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._spins: dict[str, QSpinBox] = {}
        for label, key in self._STATS:
            col = QVBoxLayout()
            col.setSpacing(1)
            col.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size:10px; color:#555;")
            spin = QSpinBox()
            spin.setRange(0, 32)
            spin.setFixedWidth(52)
            spin.valueChanged.connect(self.changed.emit)
            col.addWidget(lbl)
            col.addWidget(spin)
            layout.addLayout(col)
            self._spins[key] = spin

    def get_evs(self) -> dict:
        return {k: s.value() for k, s in self._spins.items()}

    def set_evs(self, evs: dict):
        for k, s in self._spins.items():
            s.setValue(evs.get(k, 0))


class StatsDisplay(QWidget):
    """計算済みステータス表示（H/A/B/C/D/S 横一列）"""

    _STATS = [("H","hp"), ("A","attack"), ("B","defense"),
              ("C","sp_attack"), ("D","sp_defense"), ("S","speed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._vals: dict[str, QLabel] = {}
        for name, key in self._STATS:
            col = QVBoxLayout()
            col.setSpacing(1)
            col.setContentsMargins(0, 0, 0, 0)
            hdr = QLabel(name)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setStyleSheet("font-size:10px; color:#777;")
            val = QLabel("—")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val.setStyleSheet("font-weight:bold; font-size:12px;")
            col.addWidget(hdr)
            col.addWidget(val)
            layout.addLayout(col)
            self._vals[key] = val

    def update(self, stats: dict):
        for key, lbl in self._vals.items():
            lbl.setText(str(stats.get(key, "—")))


# ─────────────────────────────────────────────────────────────────────────────
# ポケモン入力パネル
# ─────────────────────────────────────────────────────────────────────────────

class PokemonPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, title: str, filter_by_learnset: bool = True, parent=None):
        super().__init__(title, parent)
        self._filter_by_learnset = filter_by_learnset
        self._build_ui()
        self._connect()
        QTimer.singleShot(0, self._on_pokemon_changed)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(3)
        root.setContentsMargins(4, 6, 4, 4)

        # ── ポケモン名 ──
        r = QHBoxLayout()
        r.setSpacing(4)
        self.pokemon_cb = SearchableComboBox(POKEMON_LIST)
        r.addWidget(self.pokemon_cb, 1)
        root.addLayout(r)

        # ── タイプ表示 ──
        self.type_label = QLabel()
        self.type_label.setTextFormat(Qt.TextFormat.RichText)
        self.type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.type_label)

        # ── 性格 + 持ち物 ──
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        r2.addWidget(QLabel("性格"))
        self.nature_cb = QComboBox()
        for k, v in _NATURES.items():
            if not k.startswith("_"):
                nd = v
                boost  = nd["boosted"] or "-"
                reduce = nd["reduced"] or "-"
                self.nature_cb.addItem(f"{nd['name_ja']} ↑{boost} ↓{reduce}", userData=k)
        r2.addWidget(self.nature_cb, 3)
        r2.addWidget(QLabel("持物"))
        self.item_cb = SearchableComboBox(ITEM_LIST)
        r2.addWidget(self.item_cb, 3)
        root.addLayout(r2)

        # ── 特性 + メガシンカ ──
        r3 = QHBoxLayout()
        r3.setSpacing(4)
        r3.addWidget(QLabel("特性"))
        self.ability_edit = QLineEdit()
        self.ability_edit.setPlaceholderText("特性キー")
        r3.addWidget(self.ability_edit, 3)
        self.mega_cb = QCheckBox("メガ")
        self.mega_cb.setVisible(False)
        r3.addWidget(self.mega_cb)
        root.addLayout(r3)

        # ── 技（2列×2行）──
        move_grp = QGroupBox("技")
        mg = QGridLayout(move_grp)
        mg.setSpacing(3)
        mg.setContentsMargins(4, 4, 4, 4)
        self.move_cbs: list[SearchableComboBox] = []
        for i in range(4):
            row, col = divmod(i, 2)
            cb = SearchableComboBox(DAMAGE_MOVE_LIST)
            mg.addWidget(cb, row, col)
            self.move_cbs.append(cb)
        root.addWidget(move_grp)

        # ── 能力ポイント (AP 0-32) ──
        ev_grp = QGroupBox("能力ポイント (0〜32)")
        ev_lay = QVBoxLayout(ev_grp)
        ev_lay.setContentsMargins(4, 4, 4, 4)
        self.ev_widget = EVWidget()
        ev_lay.addWidget(self.ev_widget)
        root.addWidget(ev_grp)

        # ── ステータス表示 ──
        stat_grp = QGroupBox("実数値")
        sl = QVBoxLayout(stat_grp)
        sl.setContentsMargins(4, 4, 4, 4)
        self.stats_disp = StatsDisplay()
        sl.addWidget(self.stats_disp)
        root.addWidget(stat_grp)

        root.addStretch()

    def _connect(self):
        self.pokemon_cb.currentIndexChanged.connect(self._on_pokemon_changed)
        self.nature_cb.currentIndexChanged.connect(self._fire)
        self.item_cb.currentIndexChanged.connect(self._fire)
        self.ability_edit.textChanged.connect(self._fire)
        self.mega_cb.stateChanged.connect(self._fire)
        for cb in self.move_cbs:
            cb.currentIndexChanged.connect(self._fire)
        self.ev_widget.changed.connect(self._fire)

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
        # 覚え技で技ドロップダウンを絞り込む
        move_list = _get_learnable_moves(key) if self._filter_by_learnset else DAMAGE_MOVE_LIST
        for cb in self.move_cbs:
            cb.update_items(move_list)
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
        is_mega = self.mega_cb.isVisible() and self.mega_cb.isChecked()
        mega_form = (self.mega_cb.property("mega_form") or "") if is_mega else ""
        return PokemonBuild(
            species=species,
            nature=nature, item=item, ability=ability, moves=moves,
            ev_hp=evs["hp"],       ev_attack=evs["attack"],
            ev_defense=evs["defense"], ev_sp_attack=evs["sp_attack"],
            ev_sp_defense=evs["sp_defense"], ev_speed=evs["speed"],
            is_mega=is_mega, mega_form=mega_form,
        )

    def set_build(self, build: "PokemonBuild"):
        """保存済みビルドをパネルに反映する"""
        self.pokemon_cb.set_key(build.species)
        for i in range(self.nature_cb.count()):
            if self.nature_cb.itemData(i) == build.nature:
                self.nature_cb.setCurrentIndex(i)
                break
        self.item_cb.set_key(build.item or "none")
        self.ability_edit.setText(build.ability)
        move_keys = (build.moves + ["", "", "", ""])[:4]
        for cb, key in zip(self.move_cbs, move_keys):
            cb.set_key(key)
        self.ev_widget.set_evs({
            "hp": build.ev_hp, "attack": build.ev_attack,
            "defense": build.ev_defense, "sp_attack": build.ev_sp_attack,
            "sp_defense": build.ev_sp_defense, "speed": build.ev_speed,
        })
        if self.mega_cb.isVisible():
            self.mega_cb.setChecked(build.is_mega)


# ─────────────────────────────────────────────────────────────────────────────
# 対戦状態パネル
# ─────────────────────────────────────────────────────────────────────────────

class BattleStatePanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("⚙  対戦状態", parent)
        layout = QHBoxLayout(self)

        # ── バトル形式 ──
        layout.addWidget(QLabel("形式"))
        self.format_cb = QComboBox()
        self.format_cb.addItem("シングル", userData="single")
        self.format_cb.addItem("ダブル",   userData="double")
        self.format_cb.setFixedWidth(80)
        layout.addWidget(self.format_cb)

        # ダブル時のみ表示：全体技チェック
        self.spread_cb = QCheckBox("全体技（×0.75）")
        self.spread_cb.setVisible(False)
        layout.addWidget(self.spread_cb)
        self.format_cb.currentIndexChanged.connect(self._on_format_changed)

        layout.addSpacing(12)
        layout.addWidget(QLabel("天気"))
        self.weather_cb = QComboBox()
        for k, lbl in [("none","なし"),("sun","晴れ"),("rain","雨"),
                        ("sand","砂嵐"),("snow","雪")]:
            self.weather_cb.addItem(lbl, userData=k)
        layout.addWidget(self.weather_cb)

        layout.addSpacing(12)
        layout.addWidget(QLabel("フィールド"))
        self.terrain_cb = QComboBox()
        for k, lbl in [("none","なし"),("electric","エレキ"),("grassy","グラス"),
                        ("misty","ミスト"),("psychic","サイコ")]:
            self.terrain_cb.addItem(lbl, userData=k)
        layout.addWidget(self.terrain_cb)

        layout.addSpacing(12)
        layout.addWidget(QLabel("【自分】"))
        self.burn_atk  = QCheckBox("やけど")
        self.crit_cb   = QCheckBox("急所")
        layout.addWidget(self.burn_atk)
        layout.addWidget(self.crit_cb)

        layout.addSpacing(12)
        layout.addWidget(QLabel("【相手】"))
        self.burn_def = QCheckBox("やけど")
        layout.addWidget(self.burn_def)

        layout.addStretch()

        for w in [self.format_cb, self.weather_cb, self.terrain_cb,
                  self.burn_atk, self.crit_cb, self.burn_def, self.spread_cb]:
            (w.currentIndexChanged if isinstance(w, QComboBox)
             else w.stateChanged).connect(self.changed.emit)

    def _on_format_changed(self):
        is_double = self.format_cb.currentData() == "double"
        self.spread_cb.setVisible(is_double)
        if not is_double:
            self.spread_cb.setChecked(False)

    def is_double(self) -> bool:
        return self.format_cb.currentData() == "double"

    def atk_state(self) -> BattleState:
        return BattleState(
            weather=self.weather_cb.currentData(),
            terrain=self.terrain_cb.currentData(),
            burned=self.burn_atk.isChecked(),
            is_critical=self.crit_cb.isChecked(),
            is_spread=self.spread_cb.isChecked(),
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
    """対戦画面を常時監視し、相手・自分のポケモン名を自動検出するパネル"""
    opponent_detected = pyqtSignal(str, str)  # (key, name_ja)
    own_detected      = pyqtSignal(str, str)  # (key, name_ja)

    def __init__(self, parent=None):
        super().__init__("対戦中 — 相手ポケモン自動検出（リアルタイム）", parent)
        self._monitor: "BattleMonitor | None" = None
        self._windows: list = []

        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("キャプチャ対象:"))
        self.win_cb = QComboBox()
        self.win_cb.setMinimumWidth(220)
        layout.addWidget(self.win_cb)

        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.setFixedWidth(48)
        self.refresh_btn.clicked.connect(self._refresh_windows)
        layout.addWidget(self.refresh_btn)

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

        if HAS_CAPTURE:
            self._refresh_windows()

        if not HAS_BATTLE_MONITOR:
            self.toggle_btn.setEnabled(False)
            self.status_lbl.setText("⚠ pip install mss easyocr が必要です")
            self.status_lbl.setStyleSheet("color:#c0392b; font-size:11px;")

    def _refresh_windows(self):
        if not HAS_CAPTURE:
            return
        self._windows = list_windows()
        self.win_cb.clear()
        self.win_cb.addItem("（モニター全体）", userData=None)
        for w in self._windows:
            self.win_cb.addItem(w.title, userData=w)

    def _on_toggle(self, checked: bool):
        if checked:
            self._start()
        else:
            self._stop()

    def _start(self):
        cfg = load_battle_config()
        win_info = self.win_cb.currentData()
        window_title = win_info.title if win_info else ""
        self._monitor = BattleMonitor(config=cfg, window_title=window_title)
        self._monitor.opponent_changed.connect(self._on_detected)
        self._monitor.own_changed.connect(self._on_own_detected)
        self._monitor.status_changed.connect(self._on_status)
        self._monitor.start()
        self.toggle_btn.setText("監視停止")
        self.win_cb.setEnabled(False)
        self.refresh_btn.setEnabled(False)
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
        self.win_cb.setEnabled(True)
        self.refresh_btn.setEnabled(True)

    @pyqtSlot(str, str)
    def _on_detected(self, key: str, name_ja: str):
        self.opponent_detected.emit(key, name_ja)

    @pyqtSlot(str, str)
    def _on_own_detected(self, key: str, name_ja: str):
        self.own_detected.emit(key, name_ja)

    @pyqtSlot(str)
    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)
        if "相手:" in msg:
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
        hh = self.horizontalHeader()
        # 技名・判定はStretch、威力・タイプ相性・ダメージ・割合は固定
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)         # 技名
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)           # 威力
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)           # タイプ相性
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)           # ダメージ
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)           # 割合
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)         # 判定
        self.setColumnWidth(1, 70)
        self.setColumnWidth(2, 75)
        self.setColumnWidth(3, 110)
        self.setColumnWidth(4, 150)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(100)

    def show_results(self, results):
        self.setRowCount(0)
        for r in results:
            row = self.rowCount()
            self.insertRow(row)
            name = r.move_name_ja + ("◎" if r.is_stab else "")
            power_str = str(r.base_power) if r.base_power else "可変"
            if r.hit_count:
                power_str += " " + r.hit_count
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
# ─────────────────────────────────────────────────────────────────────────────
# マイビルド永続化
# ─────────────────────────────────────────────────────────────────────────────

_MY_BUILDS_PATH = Path("data/my_builds.json")


def _load_my_builds() -> dict:
    if _MY_BUILDS_PATH.exists():
        try:
            with open(_MY_BUILDS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"builds": {}, "parties": {}}


def _save_my_builds(data: dict):
    _MY_BUILDS_PATH.parent.mkdir(exist_ok=True)
    with open(_MY_BUILDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _build_to_dict(build: "PokemonBuild", memo: str = "") -> dict:
    return {
        "nature": build.nature, "item": build.item, "ability": build.ability,
        "moves": build.moves,
        "ev_hp": build.ev_hp, "ev_attack": build.ev_attack,
        "ev_defense": build.ev_defense, "ev_sp_attack": build.ev_sp_attack,
        "ev_sp_defense": build.ev_sp_defense, "ev_speed": build.ev_speed,
        "is_mega": build.is_mega, "mega_form": build.mega_form,
        "memo": memo,
    }


def _dict_to_build(species: str, d: dict) -> "PokemonBuild":
    return PokemonBuild(
        species=species,
        nature=d.get("nature", "hardy"),
        item=d.get("item", "none"),
        ability=d.get("ability", ""),
        moves=d.get("moves", []),
        ev_hp=d.get("ev_hp", 0), ev_attack=d.get("ev_attack", 0),
        ev_defense=d.get("ev_defense", 0), ev_sp_attack=d.get("ev_sp_attack", 0),
        ev_sp_defense=d.get("ev_sp_defense", 0), ev_speed=d.get("ev_speed", 0),
        is_mega=d.get("is_mega", False), mega_form=d.get("mega_form", ""),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ポケモン登録タブ
# ─────────────────────────────────────────────────────────────────────────────

class BuildRegistrationTab(QWidget):
    """マイポケモン型登録・パーティ管理タブ"""
    send_to_atk = pyqtSignal(object)  # PokemonBuild

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = _load_my_builds()
        self._current_species: str | None = None
        self._setup_ui()
        self._refresh_all()

    # ── UI構築 ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        # ── パーティ ──
        party_grp = QGroupBox("パーティ")
        party_lay = QVBoxLayout(party_grp)
        party_lay.setSpacing(4)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("パーティ名:"))
        self.party_cb = QComboBox()
        self.party_cb.setMinimumWidth(150)
        self.party_cb.currentTextChanged.connect(self._on_party_changed)
        name_row.addWidget(self.party_cb)
        add_p = QPushButton("新規")
        add_p.setFixedWidth(48)
        add_p.clicked.connect(self._add_party)
        name_row.addWidget(add_p)
        del_p = QPushButton("削除")
        del_p.setFixedWidth(48)
        del_p.clicked.connect(self._del_party)
        name_row.addWidget(del_p)
        save_p = QPushButton("保存")
        save_p.setFixedWidth(48)
        save_p.clicked.connect(self._save_party)
        name_row.addWidget(save_p)
        name_row.addStretch()
        party_lay.addLayout(name_row)

        # 6スロット (2行×3列)
        self._slot_cbs: list[QComboBox] = []
        grid = QGridLayout()
        grid.setSpacing(4)
        for i in range(6):
            row, col = divmod(i, 3)
            lbl = QLabel(f"{i + 1}.")
            lbl.setFixedWidth(18)
            cb = QComboBox()
            cb.setMinimumWidth(130)
            self._slot_cbs.append(cb)
            send_btn = QPushButton("→送る")
            send_btn.setFixedWidth(58)
            send_btn.clicked.connect(lambda _, idx=i: self._send_slot(idx))
            grid.addWidget(lbl,      row, col * 3)
            grid.addWidget(cb,       row, col * 3 + 1)
            grid.addWidget(send_btn, row, col * 3 + 2)
        party_lay.addLayout(grid)
        root.addWidget(party_grp)

        # ── ポケモン登録エリア (スプリッタ) ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左: 登録済みリスト
        left_w = QWidget()
        ll = QVBoxLayout(left_w)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("登録済みポケモン:"))
        self.poke_list = QListWidget()
        self.poke_list.currentRowChanged.connect(self._on_list_select)
        ll.addWidget(self.poke_list)
        splitter.addWidget(left_w)

        # 右: 編集フォーム
        right_w = QWidget()
        rl = QVBoxLayout(right_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        scroll = QScrollArea()
        self.build_panel = PokemonPanel("ポケモン登録")
        scroll.setWidget(self.build_panel)
        scroll.setWidgetResizable(True)
        rl.addWidget(scroll)

        memo_grp = QGroupBox("メモ")
        memo_lay = QVBoxLayout(memo_grp)
        memo_lay.setContentsMargins(4, 4, 4, 4)
        self.memo_edit = QTextEdit()
        self.memo_edit.setFixedHeight(70)
        self.memo_edit.setPlaceholderText("型の説明など自由に...")
        memo_lay.addWidget(self.memo_edit)
        rl.addWidget(memo_grp)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_build)
        send_btn = QPushButton("攻撃パネルに送る")
        send_btn.clicked.connect(self._send_current)
        del_btn = QPushButton("削除")
        del_btn.clicked.connect(self._delete_build)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(send_btn)
        btn_row.addStretch()
        btn_row.addWidget(del_btn)
        rl.addLayout(btn_row)

        splitter.addWidget(right_w)
        splitter.setSizes([160, 520])
        root.addWidget(splitter)

    # ── 更新 ──────────────────────────────────────────────────────────────────

    def _refresh_all(self):
        self._refresh_poke_list()
        self._refresh_slot_cbs()
        self._refresh_party_cb()

    def _refresh_poke_list(self):
        self.poke_list.clear()
        for key in sorted(self._data.get("builds", {}).keys()):
            name_ja = _POKEMON.get(key, {}).get("name_ja", key)
            item = QListWidgetItem(name_ja)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.poke_list.addItem(item)

    def _refresh_slot_cbs(self):
        builds = self._data.get("builds", {})
        for cb in self._slot_cbs:
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("（空）", userData="")
            for key in sorted(builds.keys()):
                name_ja = _POKEMON.get(key, {}).get("name_ja", key)
                cb.addItem(name_ja, userData=key)
            cb.blockSignals(False)

    def _refresh_party_cb(self):
        prev = self.party_cb.currentText()
        self.party_cb.blockSignals(True)
        self.party_cb.clear()
        for name in self._data.get("parties", {}):
            self.party_cb.addItem(name)
        idx = self.party_cb.findText(prev)
        self.party_cb.setCurrentIndex(max(0, idx))
        self.party_cb.blockSignals(False)
        self._on_party_changed(self.party_cb.currentText())

    # ── パーティ操作 ──────────────────────────────────────────────────────────

    def _on_party_changed(self, name: str):
        slots = self._data.get("parties", {}).get(name, [""] * 6)
        for i, cb in enumerate(self._slot_cbs):
            key = slots[i] if i < len(slots) else ""
            for j in range(cb.count()):
                if cb.itemData(j) == key:
                    cb.setCurrentIndex(j)
                    break

    def _add_party(self):
        name, ok = QInputDialog.getText(self, "パーティ新規作成", "パーティ名:")
        if not ok or not name.strip():
            return
        self._data.setdefault("parties", {})[name.strip()] = [""] * 6
        _save_my_builds(self._data)
        self._refresh_party_cb()
        idx = self.party_cb.findText(name.strip())
        if idx >= 0:
            self.party_cb.setCurrentIndex(idx)

    def _del_party(self):
        name = self.party_cb.currentText()
        if not name:
            return
        self._data.get("parties", {}).pop(name, None)
        _save_my_builds(self._data)
        self._refresh_party_cb()

    def _save_party(self):
        name = self.party_cb.currentText()
        if not name:
            return
        self._data.setdefault("parties", {})[name] = [
            cb.currentData() or "" for cb in self._slot_cbs
        ]
        _save_my_builds(self._data)

    def _send_slot(self, idx: int):
        key = self._slot_cbs[idx].currentData()
        if not key:
            return
        d = self._data.get("builds", {}).get(key)
        if d:
            self.send_to_atk.emit(_dict_to_build(key, d))

    # ── ポケモン操作 ──────────────────────────────────────────────────────────

    def _on_list_select(self, row: int):
        item = self.poke_list.item(row)
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        self._current_species = key
        d = self._data.get("builds", {}).get(key, {})
        self.build_panel.set_build(_dict_to_build(key, d))
        self.memo_edit.setPlainText(d.get("memo", ""))

    def _save_build(self):
        build = self.build_panel.get_build()
        if not build.species:
            return
        memo = self.memo_edit.toPlainText()
        self._data.setdefault("builds", {})[build.species] = _build_to_dict(build, memo)
        _save_my_builds(self._data)
        self._current_species = build.species
        self._refresh_poke_list()
        self._refresh_slot_cbs()
        self._on_party_changed(self.party_cb.currentText())
        for i in range(self.poke_list.count()):
            if self.poke_list.item(i).data(Qt.ItemDataRole.UserRole) == build.species:
                self.poke_list.setCurrentRow(i)
                break

    def _delete_build(self):
        key = self._current_species
        if not key:
            return
        name_ja = _POKEMON.get(key, {}).get("name_ja", key)
        if QMessageBox.question(self, "削除確認", f"{name_ja} の登録を削除しますか？") \
                != QMessageBox.StandardButton.Yes:
            return
        self._data.get("builds", {}).pop(key, None)
        _save_my_builds(self._data)
        self._current_species = None
        self._refresh_poke_list()
        self._refresh_slot_cbs()
        self._on_party_changed(self.party_cb.currentText())

    def _send_current(self):
        build = self.build_panel.get_build()
        if build.species:
            self.send_to_atk.emit(build)

    def load_build_for_species(self, key: str) -> bool:
        """外部から呼び出し：登録済みビルドを atk に送る。なければ False を返す。"""
        d = self._data.get("builds", {}).get(key)
        if d:
            self.send_to_atk.emit(_dict_to_build(key, d))
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# メインウィンドウ
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ポケモンチャンピオンズ ダメージ計算ツール v2.0")
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._calculate)
        self.atk_panel.changed.connect(self._timer.start)
        self.def_panel.changed.connect(self._timer.start)
        self.state_panel.changed.connect(self._timer.start)
        # 相手ポケモン変更 → 情報パネル + 使用率取得
        self.def_panel.pokemon_cb.currentIndexChanged.connect(self._on_def_pokemon_changed)
        QTimer.singleShot(400, self._calculate)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(6, 6, 6, 6)

        self._tabs = QTabWidget()
        outer.addWidget(self._tabs)

        # ── Tab 1: ダメージ計算 ──
        calc_widget = QWidget()
        self._tabs.addTab(calc_widget, "ダメージ計算")
        body = QHBoxLayout(calc_widget)
        body.setSpacing(8)
        body.setContentsMargins(0, 4, 0, 0)

        # 左：ポケモンパネル・状態・ダメージテーブル
        left = QVBoxLayout()
        left.setSpacing(4)

        panels = QHBoxLayout()
        panels.setSpacing(6)
        self.atk_panel = PokemonPanel("⚔   自分のポケモン", filter_by_learnset=True)
        self.def_panel = PokemonPanel("🛡   相手のポケモン", filter_by_learnset=True)
        for panel in (self.atk_panel, self.def_panel):
            scroll = QScrollArea()
            scroll.setWidget(panel)
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(300)
            panels.addWidget(scroll)
        left.addLayout(panels, stretch=4)

        self.state_panel = BattleStatePanel()
        left.addWidget(self.state_panel)

        result_row = QHBoxLayout()
        result_row.setSpacing(8)

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
        left.addLayout(result_row, stretch=2)

        body.addLayout(left, stretch=1)

        # 右サイドバー：タイプ相性・特性 + 使用率
        right_panel = QWidget()
        right_panel.setFixedWidth(400)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(4)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.info_widget = PokemonTypeInfoWidget()
        info_scroll = QScrollArea()
        info_scroll.setWidget(self.info_widget)
        info_scroll.setWidgetResizable(True)
        info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_layout.addWidget(info_scroll, stretch=2)

        self.usage_widget = UsageRateWidget()
        self.usage_widget.data_ready.connect(self._on_usage_ready)
        right_layout.addWidget(self.usage_widget, stretch=1)

        body.addWidget(right_panel)

        # ── Tab 2: 自動検出 ──
        capture_widget = QWidget()
        self._tabs.addTab(capture_widget, "自動検出")
        cap_layout = QVBoxLayout(capture_widget)
        cap_layout.setSpacing(8)
        cap_layout.setContentsMargins(0, 4, 0, 0)

        self.battle_monitor_widget = BattleMonitorWidget()
        self.battle_monitor_widget.opponent_detected.connect(self._on_battle_detected)
        self.battle_monitor_widget.own_detected.connect(self._on_own_battle_detected)
        cap_layout.addWidget(self.battle_monitor_widget)

        self.capture_panel = CapturePanel()
        self.capture_panel.pokemon_detected.connect(self._on_pokemon_detected)
        self.capture_panel.sprites_detected.connect(self._on_sprites_detected)
        cap_layout.addWidget(self.capture_panel)

        self.opponent_team_widget = OpponentTeamWidget()
        self.opponent_team_widget.pokemon_selected.connect(self._on_pokemon_detected)
        cap_layout.addWidget(self.opponent_team_widget)
        cap_layout.addStretch()

        # ── Tab 3: ポケモン登録 ──
        self.reg_tab = BuildRegistrationTab()
        self.reg_tab.send_to_atk.connect(self._on_reg_send_to_atk)
        self._tabs.addTab(self.reg_tab, "ポケモン登録")

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
        """相手ポケモン変更時 → 情報パネル更新 + 使用率取得"""
        key = self.def_panel.pokemon_cb.current_key()
        if key:
            self.info_widget.refresh(key)
        if key and HAS_SCRAPER:
            self.usage_widget.fetch(key)

    @pyqtSlot(str, str)
    def _on_battle_detected(self, key: str, name_ja: str):
        """対戦監視による自動検出 → 相手パネル・情報パネル・使用率を更新"""
        self.def_panel.pokemon_cb.set_key(key)
        self.info_widget.refresh(key)
        self.statusBar().showMessage(f"自動検出: {name_ja} を相手に設定しました")
        if HAS_SCRAPER:
            self.usage_widget.fetch(key)

    @pyqtSlot(str, str)
    def _on_own_battle_detected(self, key: str, name_ja: str):
        """自分のポケモン自動検出 → 登録済みビルドがあれば丸ごとロード、なければ種族だけセット"""
        if not self.reg_tab.load_build_for_species(key):
            self.atk_panel.pokemon_cb.set_key(key)
        self.statusBar().showMessage(f"自動検出: {name_ja} を自分に設定しました")

    @pyqtSlot(object)
    def _on_reg_send_to_atk(self, build):
        """登録タブ → 攻撃パネルにビルドを送る"""
        self.atk_panel.set_build(build)

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

    @pyqtSlot(str, dict)
    def _on_usage_ready(self, pokemon_key: str, data: dict):
        """使用率取得完了 → 相手パネルの技スロットを上位攻撃技で自動セット"""
        if pokemon_key != self.def_panel.pokemon_cb.current_key():
            return
        atk_keys = []
        for name_ja, _ in data.get("moves", []):
            key = _MOVE_JA_TO_KEY.get(name_ja)
            if not key:
                continue
            if _MOVES.get(key, {}).get("category") in ("physical", "special"):
                atk_keys.append(key)
            if len(atk_keys) >= 4:
                break

        if not atk_keys:
            return

        # 覚え技リストに使用率技が含まれていない場合は追加してドロップダウンを更新
        # （PokeAPIのSV覚え技データが不完全なことがあるため）
        base_list = _get_learnable_moves(pokemon_key)
        base_keys = {k for k, _ in base_list}
        extra = [
            (k, _MOVES[k]["name_ja"]) for k in atk_keys
            if k not in base_keys and k in _MOVES and "name_ja" in _MOVES[k]
        ]
        if extra:
            merged = [base_list[0]] + sorted(base_list[1:] + extra, key=lambda x: x[1])
            for cb in self.def_panel.move_cbs:
                cb.update_items(merged)

        for i, cb in enumerate(self.def_panel.move_cbs):
            if i < len(atk_keys):
                cb.set_key(atk_keys[i])


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
