# Session 382 Handoff — Remove Hardcoded catboost_v12 from All Publishing Exporters

**Date:** 2026-03-01
**Commits:** `41eaed8a`, `832a6035`
**Status:** Deployed, verified in production.

## Problem

When catboost_v12 stopped winning the multi-model aggregator's selection (0 active `is_active=TRUE` predictions on Mar 1), the tonight and predictions endpoints returned 0 results despite 1,350 active predictions from other models. Root cause: ~30 hardcoded `system_id = 'catboost_v12'` references across 11 publishing exporter files.

The pre-commit hook (`validate_model_references.py`) was supposed to catch these, but it treated ALL triple-quoted strings as "docstrings" and skipped them — so SQL queries like `WHERE system_id = 'catboost_v12'` inside triple-quoted strings passed undetected.

## What Was Done

### Commit `41eaed8a`: Tonight Exporter Fix (emergency)
- Fixed `tonight_exporter.py` and `tonight_players_exporter.py` to use `is_active = TRUE` instead of `system_id = 'catboost_v12'`

### Commit `832a6035`: Systematic Fix (11 files)

**Step 1 — Forward-looking prediction queries (CRITICAL):**
Queries against `player_prop_predictions` now use `is_active = TRUE` instead of filtering by system_id. The multi-model aggregator already selects the winning model, so `is_active` is the correct filter.

| File | Change |
|------|--------|
| `predictions_exporter.py` | `system_id` → `is_active = TRUE`, PA join parameterized |
| `player_profile_exporter.py` | Next-game query: `system_id` → `is_active = TRUE` |
| `live_grading_exporter.py` | Removed redundant `system_id` (already had `is_active = TRUE`) |
| `best_bets_exporter.py` | Predictions branch: removed `system_id` (has `is_active = TRUE`) |

**Step 2 — Backward-looking grading queries (15 references):**
Queries against `prediction_accuracy` now use `@champion_model_id` SQL parameter populated by `get_champion_model_id()` from `shared/config/model_selection.py`. Output identical today (returns `'catboost_v12'`), but changing the champion in one file updates all exporters.

| File | # References |
|------|-------------|
| `player_profile_exporter.py` | 5 |
| `best_bets_exporter.py` | 3 |
| `predictions_exporter.py` | 1 (PA join) |
| `player_game_report_exporter.py` | 1 |
| `streaks_exporter.py` | 1 |
| `player_season_exporter.py` | 1 |
| `trends_tonight_exporter.py` | 1 |
| `results_exporter.py` | 1 |
| `daily_signals_exporter.py` | 1 |

**Step 3 — Python config/metadata:**
- `best_bets_exporter.py`: Removed `system_id` keys from `TIER_CONFIG` dict (unused in code, only documentation)
- `daily_signals_exporter.py`: `get_model_codename('catboost_v12')` → `get_model_codename(get_champion_model_id())`

**Step 4 — Pre-commit hook enhancement:**
- `is_in_docstring()` replaced with `is_in_module_docstring()` — only skips the file's very first triple-quoted block (true module docstring), not SQL queries in triple-quoted strings
- Added `model_health_exporter.py` and `system_performance_exporter.py` to `EXCLUDE_FILES` (legitimate display metadata)

## Verification

- **Pre-commit hook:** 0 violations in publishing exporters (1 pre-existing `catboost_v9` in enrichment processor — separate issue)
- **Cloud Build:** All 3 triggers passed
- **Deployment drift:** Zero drift across all 16 services
- **Production re-export for 2026-03-01:**
  - `predictions/2026-03-01.json`: **1,350 predictions across 11 games** (was 0 before fix)
  - `tonight/2026-03-01.json`: **400 players, 134 with prop lines**

## Known Remaining Issues

### Pre-existing: `catboost_v9` in enrichment processor
- **File:** `data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py:357`
- **Status:** Legacy dead code. V9 is blocked at the aggregator layer (Session 382 `LEGACY_MODEL_BLOCKLIST`). The re-prediction trigger fires but results are discarded. Non-fatal, harmless.
- **Action:** Low-priority cleanup for a future session.

### Pre-existing: model_health_exporter / system_performance_exporter
- These legitimately display `catboost_v12` as metadata labels (not query filters). Excluded from hook.

## Architecture Note

The fix establishes a clean separation:
- **Forward-looking queries** (what to show users tonight): Use `is_active = TRUE` — model-agnostic, follows multi-model aggregator's selection
- **Backward-looking queries** (historical grading): Use `get_champion_model_id()` — parameterized, single point of change in `shared/config/model_selection.py`

Changing the champion model now requires editing only `CHAMPION_MODEL_ID` in `shared/config/model_selection.py`. All 11 publishing exporters will follow automatically.
