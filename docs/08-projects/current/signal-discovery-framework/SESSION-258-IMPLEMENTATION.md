# Session 258: Production Combo Signals + Anti-Pattern Warning System

**Date:** 2026-02-15
**Session:** 258 (implements findings from Sessions 256-257)
**Changes:** 2 new files, 7 modified files

---

## What Was Done

Implemented the top findings from the comprehensive 9-dimension signal testing (Sessions 256-257) as production code.

### New Combo Signals

| Signal | Tag | Criteria | HR | Confidence |
|--------|-----|----------|-----|-----------|
| **HighEdgeMinutesSurgeCombo** | `combo_he_ms` | Edge >= 5 + minutes surge >= 3 + OVER | 68.8% (16 picks) | 0.85 |
| **ThreeWayCombo** | `combo_3way` | Edge >= 5 + surge >= 3 + ESO quality gate | 88.9% (17 picks) | 0.95 |

Both check their conditions internally (no dependency on other signal instances firing).

### Signal Filters Added

| Signal | Filter | Impact |
|--------|--------|--------|
| `cold_snap` | HOME-ONLY | 93.3% home vs 31.3% away (+62pt split) |
| `blowout_recovery` | Exclude Centers | 20.0% HR for centers (vs ~58% others) |
| `blowout_recovery` | Exclude B2B (rest_days < 2) | 46.2% HR on B2B (below breakeven) |

### Anti-Pattern Warning System

The aggregator now applies combo-aware scoring adjustments:

| Pattern | Detection | Action |
|---------|-----------|--------|
| `combo_3way` present | Tags check | +2.5 composite bonus |
| `combo_he_ms` present | Tags check | +2.0 composite bonus |
| HE + ESO without MS | `redundancy_trap` | -2.0 penalty |
| MS + blowout_recovery | `contradictory_signals` | Neutralize bonus (cap at 0) |

Warnings surface as `warning_tags` in:
- JSON export (`v1/signal-best-bets/{date}.json`)
- BigQuery `signal_best_bets_picks` table
- BigQuery `current_subset_picks` table (via signal annotator bridge)

### Data Pipeline Changes

`supplemental_data.py` now provides:
- `is_home` — derived from `game_id` format (`YYYYMMDD_AWAY_HOME`)
- `player_context.position` — from `player_game_summary`

### Registry Update

23 signals registered (was 20):
- +2 combo signals (`combo_he_ms`, `combo_3way`)
- +1 re-registered (`edge_spread_optimal`) for anti-pattern detection in aggregator

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/combo_he_ms.py` | NEW — HighEdgeMinutesSurgeComboSignal |
| `ml/signals/combo_3way.py` | NEW — ThreeWayComboSignal |
| `ml/signals/supplemental_data.py` | Added `position` to SQL, `is_home` derivation, `player_context` |
| `ml/signals/cold_snap.py` | HOME-ONLY filter |
| `ml/signals/blowout_recovery.py` | Center + B2B exclusions |
| `ml/signals/registry.py` | Registered combo signals + ESO |
| `ml/signals/aggregator.py` | Combo bonuses, anti-pattern penalties, `warning_tags` |
| `data_processors/publishing/signal_best_bets_exporter.py` | `warnings` in JSON, `warning_tags` in BQ |
| `data_processors/publishing/signal_annotator.py` | `warning_tags` in subset bridge |

---

## Verification

All tests pass:
- Python syntax: 9/9 files OK
- Registry import: 23 signals registered, all 3 new ones present
- Aggregator unit tests: combo bonuses, anti-pattern penalties, warning_tags all correct
- Signal evaluate tests: combo signals fire correctly, filters block correctly (home/away, Center, B2B, PF-C hybrids)

---

## Pre-Deploy Checklist

- [ ] `ALTER TABLE nba_predictions.signal_best_bets_picks ADD COLUMN warning_tags ARRAY<STRING>`
- [ ] `ALTER TABLE nba_predictions.current_subset_picks ADD COLUMN warning_tags ARRAY<STRING>`
- [ ] Push to main (auto-deploys via Cloud Build)
- [ ] Verify builds succeed
- [ ] Check drift
