# Historical Line Source Cleanup - Complete Handoff

**Date:** 2026-01-23
**Status:** ✅ COMPLETE
**Sessions:** Multiple sessions over Jan 23

---

## Executive Summary

The ESTIMATED_AVG line source issue has been fully resolved. The system no longer generates fake betting lines based on player averages. All historical data has been cleaned up.

### Key Outcomes

| Metric | Before | After |
|--------|--------|-------|
| ESTIMATED_AVG records | 105,438 | **0** |
| NO_PROP_LINE records | 0 | 99,021 |
| Gradable ACTUAL_PROP | ~92K | 98,137 |
| Grading win rate | Contaminated | **77.9%** (clean) |

---

## What Was Done

### Phase 1: Stop Generating Fake Lines
- Modified `predictions/coordinator/player_loader.py` (v3.10)
- Added `disable_estimated_lines` config flag (default: True)
- Players without real betting lines now get `line_source='NO_PROP_LINE'`
- Still generates predictions (for MAE tracking) but no OVER/UNDER recommendation

### Phase 2: Data Migration
1. **ESTIMATED_AVG → NO_PROP_LINE** (105,438 rows)
   - Set `current_points_line = NULL`
   - Set `has_prop_line = FALSE`
   - Set `recommendation = 'NO_LINE'`
   - Preserved value in `estimated_line_value` for reference

2. **Backfill estimated_line_value** (85,502 rows)
   - Populated player's L5 average for ACTUAL_PROP records
   - Allows "beat the baseline" analysis

3. **Convert fixable predictions** (6,417 rows)
   - Found NO_PROP_LINE predictions that had BettingPros lines available
   - Converted to ACTUAL_PROP with real lines

### Phase 3: Deduplication & Grading Fix
1. **Predictions table**: Deactivated 49,341 duplicate predictions
2. **Grading table**: Deleted 2,580 duplicate graded records
3. **Grading query fix**: Added `is_active = TRUE` filter to prevent grading deactivated predictions

---

## Current Data State

### Predictions Table (2025-26 Season)
```
ACTUAL_PROP:    26,777  ✅ Gradable
NO_PROP_LINE:   15,232  ❌ Not gradable (no line)
VEGAS_BACKFILL:  5,763  ✅ Gradable
NO_VEGAS_DATA:   2,941  ❌ Not gradable
─────────────────────────
Total:          50,713 active predictions
```

### Grading Table (2025-26, CatBoost V8)
```
ACTUAL_PROP: 7,177 graded
Win Rate:    77.9%
MAE:         6.75
```

### Column Semantics (CORRECTED)

| Column | Meaning |
|--------|---------|
| `current_points_line` | Real Vegas line ONLY (NULL if none) |
| `estimated_line_value` | Player's L5 average (always populated) |
| `has_prop_line` | TRUE only for real lines |
| `line_source` | ACTUAL_PROP, NO_PROP_LINE, VEGAS_BACKFILL, NO_VEGAS_DATA |

---

## Code Changes Made

### 1. predictions/coordinator/player_loader.py (v3.10)
- Added `_get_player_baseline()` method
- Modified `_get_betting_lines()` to return NO_PROP_LINE when no real line found
- Always populates `estimated_line_value` for reference

### 2. shared/config/orchestration_config.py
- Added `disable_estimated_lines` flag (default: True)
- Environment variable: `DISABLE_ESTIMATED_LINES`

### 3. data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py
- Added `is_active = TRUE` filter to grading query
- Prevents grading deactivated duplicate predictions

---

## Deployments

| Service | Revision | Status |
|---------|----------|--------|
| prediction-coordinator | 00088-2rq | ✅ Healthy |

---

## Documentation Created

1. `docs/09-handoff/2026-01-23-NO-ESTIMATED-LINES-IMPLEMENTATION.md` - Implementation details
2. `docs/09-handoff/2026-01-23-ESTIMATED-LINE-DESIGN-FLAW.md` - Root cause analysis
3. `docs/09-handoff/2026-01-23-COMPREHENSIVE-CLEANUP-PLAN.md` - Full execution plan
4. `docs/09-handoff/2026-01-23-HISTORICAL-CLEANUP-PLAN.md` - Data analysis

---

## What's Working Now

1. **No more fake lines** - System only uses real betting lines from OddsAPI or BettingPros
2. **Clean grading** - Only ACTUAL_PROP predictions are graded (77.9% win rate)
3. **Baseline tracking** - `estimated_line_value` always populated for analysis
4. **No duplicates** - Both predictions and grading tables are deduplicated

---

## Potential Follow-ups (Optional)

### P2: Historical Seasons
- 2021-2024 seasons have NO_PROP_LINE records that cannot be converted (BettingPros didn't cover those players)
- These are correctly marked and won't affect grading

### P2: MAE-only grading for NO_PROP_LINE
- Could add separate MAE tracking for predictions without lines
- Would measure point prediction accuracy regardless of line availability

### P3: Daily monitoring
- Add alert if ESTIMATED_AVG reappears (shouldn't happen)
- Monitor NO_PROP_LINE percentage

---

## Quick Verification Commands

```bash
# Check line source distribution
bq query --use_legacy_sql=false "
SELECT line_source, COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE AND game_date >= '2025-10-01'
GROUP BY 1 ORDER BY 2 DESC"

# Check grading health
bq query --use_legacy_sql=false "
SELECT line_source, COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-10-01' AND system_id = 'catboost_v8'
GROUP BY 1"

# Verify no ESTIMATED_AVG
bq query --use_legacy_sql=false "
SELECT COUNT(*) as estimated_avg_count
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE AND line_source = 'ESTIMATED_AVG'"
# Expected: 0
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `predictions/coordinator/player_loader.py` | Line source fallback logic |
| `shared/config/orchestration_config.py` | Config flags |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Grading logic |
| `docs/09-handoff/2026-01-23-ESTIMATED-LINE-DESIGN-FLAW.md` | Why ESTIMATED_AVG was broken |

---

## Summary

The ESTIMATED_AVG issue is fully resolved:
- ✅ No more fake lines generated
- ✅ Historical data cleaned up
- ✅ Grading only uses real lines
- ✅ 77.9% win rate on clean data
- ✅ Code deployed and working

**No immediate action required.** The system is clean and working correctly.
