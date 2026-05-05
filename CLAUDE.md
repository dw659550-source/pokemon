# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ユーザーへの対応方針

- ユーザーは非エンジニアです。専門用語は使わず、わかりやすい言葉で説明してください。
- 返答は必ず日本語でしてください。

## What This Project Is

Pokemon Champions damage calculator with automatic opponent detection. The GUI monitors the selection screen, identifies the opponent's 6 Pokemon via sprite pHash matching, and calculates damage for every move.

## Running the App

```bash
# Main GUI (Phase 2 - requires opencv, PyQt6, etc.)
python gui.py

# CLI calculator (Phase 1 - no extra dependencies)
python cli.py

# Install Phase 2 dependencies
pip install -r requirements_phase2.txt
# Also requires: pip install PyQt6
```

## Data Setup (one-time)

The `data/` directory must be populated before use. Scripts in `scripts/` fetch from PokeAPI/Smogon:

```bash
python scripts/fetch_pokemon_data.py      # pokemon.json, moves.json, etc.
python scripts/download_sprites.py        # data/sprites/ (PNG per Pokemon)
python scripts/download_abilities.py      # abilities.json
python scripts/download_moves.py          # moves.json
python scripts/download_pokemon_moves.py  # pokemon_moves.json
python scripts/download_champions_pokemon.py  # Champions-specific roster
```

Required JSON files: `pokemon.json`, `moves.json`, `natures.json`, `items.json`, `type_chart.json`, `abilities.json`.

## Diagnostics & Calibration

```bash
# Capture selection screen and diagnose type icon detection
python scripts/diagnose_type_icons.py

# Extract new type icon templates from a live capture
python scripts/extract_type_icons_from_game.py

# Calibrate slot regions for a different screen layout
python scripts/calibrate_battle.py
python scripts/calibrate_slots.py

# Visualize current region config overlaid on a screenshot
python scripts/visualize_regions.py
```

## Architecture

### Damage Calculation (`calculator/`)

- `models.py` — `PokemonBuild` (species, EVs 0–32 each per Champions rules, mega), `BattleState` (ranks, weather, terrain), `DamageResult`
- `stats.py` — stat calculation; reads `data/pokemon.json`
- `damage.py` — full damage formula: STAB, type chart, item/ability/weather/terrain modifiers, multi-hit, special cases (Gyro Ball, Eruption, Low Kick, etc.)
- `__init__.py` — exports `DamageCalculator`

Note: EVs are 0–32 per stat (Champions-specific, not standard 0–252).

### Screen Capture Pipeline (`capture/`)

**Selection screen flow:**
1. `SelectionMonitor` (QThread) polls at ~1 fps, detects "選出してください" via OCR
2. On trigger → calls `detect_opponent_team()` from `sprite_detector.py`
3. Result emitted via `teams_detected` signal to GUI

**`sprite_detector.py`** — core detection module:
- `REGION_CONFIG` — hardcoded ratios for 1920×1080 (panel_x1=0.807, panel_x2=0.960, 6 slot_tops, slot_height=0.118)
- `detect_slot_types(type_area_bgr)` — template matching (`TM_CCOEFF_NORMED`, scales 0.65–1.05) in two fixed zones (Zone1: x=62.2–79.9%, Zone2: x=79.9–97.2% of slot width); returns list of canonical type names
- `_ZONE_VARIANT_MAP` — maps zone-specific template names (e.g. `steel_z1`, `steel_z2`) back to canonical type names
- `SpriteDatabase` — loads pHash for all sprites, `find_best_match_typed(icon_bgr, detected_types)` filters candidates by type before pHash comparison
- `detect_opponent_team(image, db)` — full pipeline: crop slots → detect types → pHash match

**Type icon templates** (`data/type_icons/`):
- PNG files named by type (e.g. `fire.png`, `steel.png`, `steel_z1.png`, `steel_z2.png`, `dragon.png`)
- Zone-variant templates exist for types that look visually different depending on which icon position (Zone1 vs Zone2) they appear in
- Extract new templates with `scripts/extract_type_icons_from_game.py` — reads `diagnose_full.png`, specify `ICON_SPECS` with (slot_idx, zone_idx, name, y_offset)
- `ICON_H_PX = 42` is the extraction height; y_offset is pixels from slot top where the icon starts (varies: Slot1≈28, Slot2≈17, Slot3≈8, Slot4–6≈0)

**Battle monitor** (`capture/battle_monitor.py`):
- `BattleMonitor` (QThread) monitors the battle screen, detects opponent Pokemon name via EasyOCR
- Config stored in `data/battle_config.json` (screen region ratios); calibrated via `scripts/calibrate_battle.py`

### GUI (`gui.py`)

PyQt6 single-file application. Key components:
- Party registration tab — input own team, saved to `data/my_builds.json`
- Auto-detection tab — starts `SelectionMonitor`, shows detected opponent team, triggers damage calculation
- Damage table — shows all moves with min/max damage %, effectiveness, KO chance
- Optional usage rate overlay via `scraper/usage_scraper.py` (Smogon usage stats)

All optional capture/scraper imports are guarded by try/except so the GUI launches even without Phase 2 deps.

### Data Files (`data/`)

| File | Contents |
|------|----------|
| `pokemon.json` | Per-species: base stats, types, weight, forms, name_ja |
| `moves.json` | Per-move: power, type, category, name_ja, special flags |
| `type_chart.json` | Nested dict `[attacking][defending]` → multiplier |
| `natures.json` | boosted/reduced stat per nature |
| `items.json` | Item effects relevant to damage calc |
| `sprites/` | `{pokemon_key}.png` at 80×80 px (grayscale pHash source) |
| `type_icons/` | Type badge templates for template matching |
| `region_config.json` | Manual calibration override for REGION_CONFIG |
| `sprite_hists.pkl` | pHash cache (auto-regenerated if stale, version=3) |

## Key Implementation Notes

**pHash matching**: 64-bit DCT-based perceptual hash. `SpriteDatabase.find_best_match_typed()` filters the ~272-sprite database down to ~10–30 candidates matching the detected types, then ranks by Hamming distance.

**Type detection scale range**: `np.arange(0.65, 1.05, 0.05)` in `detect_slot_types()`. Minimum scale 0.65 is critical — smaller scales cause all badge shapes to look identical (false positives). Scale 1.0 is included so templates match at extraction resolution.

**Zone-variant templates**: Some types (steel, dragon) look visually different in Zone1 vs Zone2 position. Templates named `steel_z1`, `steel_z2` etc. are matched normally but canonicalized via `_ZONE_VARIANT_MAP` before returning.

**COLOR_TIEBREAK_MARGIN = 0.0**: The HSV color tiebreak is currently disabled because Pokemon sprite backgrounds contaminate zone column color measurements (~50% of non-crimson pixels are background sprite colors, not badge colors).
