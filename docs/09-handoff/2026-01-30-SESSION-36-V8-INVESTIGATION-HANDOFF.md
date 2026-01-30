# Session 36 Handoff - V8 Investigation Complete

**Date:** 2026-01-30
**Status:** Investigation complete, fixes applied, follow-up needed

---

## Session 36 Accomplishments

### 1. Root Cause Analysis Complete
- **Data is valid** - Actual points match source data 100%
- **Grading bug found and fixed** - 2026-01-12 had wrong line values
- **Confidence calibration issue identified** - Decile 9 is miscalibrated

### 2. Bug Fix Applied
**Root cause**: `bettingpros_player_points_props` table contains ALL prop types (points, assists, rebounds, blocks, steals, threes) but queries weren't filtering by `market_type='points'`.

**Files fixed** (commit `fbd6ad3d`):
```
data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py:212
data_processors/analytics/upcoming_player_game_context/betting_data.py:185
predictions/coordinator/player_loader.py:710,940
```

### 3. Prevention Mechanisms Added
- **Pre-commit hook**: `.pre-commit-hooks/validate_bettingpros_queries.py`
- **Validation query**: `validation/queries/predictions/line_value_validation.sql`
- **Schema docs updated**: Warning about multi-prop-type table

### 4. Data Corrected
- 2026-01-12: Updated 243 predictions with correct line values
- Re-graded with correct lines

---

## Current Performance Status

### V8 by Confidence Decile (2025-26 Season)

| Decile | Predictions | MAE | Hit Rate | Assessment |
|--------|-------------|-----|----------|------------|
| 6 | 73 | 4.92 | N/A | Low volume |
| 9 | 2,275 | 6.83 | **51.0%** | ⚠️ Coin flip |
| 10 | 2,573 | 4.58 | **67.1%** | ✅ Good |

**Key insight**: Decile 10 (confidence ≥0.90) performs well. Problem is decile 9 (0.84-0.89).

### Season Comparison

| Season | Decile 9 Hit Rate | Decile 10 Hit Rate |
|--------|-------------------|-------------------|
| 2024-25 | **57.6%** | 57.8% |
| 2025-26 | **51.0%** | 67.1% |

Decile 9 dropped from 57.6% to 51.0% this season. Decile 10 actually improved.

---

## Outstanding Issues

### 1. Duplicate Records (HIGH Priority)
**1,926 duplicate player-date-system records** in prediction_accuracy table.

```sql
-- Find duplicates
SELECT player_lookup, game_date, system_id, COUNT(*) as cnt
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-11-01'
GROUP BY 1, 2, 3
HAVING COUNT(*) > 1
ORDER BY cnt DESC
LIMIT 20;
```

**Action needed**: Investigate source, deduplicate, add prevention.

### 2. Decile 9 Calibration
The model assigns 0.84-0.89 confidence to predictions that only hit 51% of the time. This needs recalibration.

**Options** (follow challenger procedure):
1. Raise recommendation threshold from 0.84 to 0.90
2. Retrain model with 2025-26 data
3. Adjust confidence formula to penalize volatility more

**Reference**: `docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md`

### 3. Jan 21-25 Missing Predictions
~63K predictions failed due to LINE QUALITY VALIDATION blocking `line_value=20.0`.
- Feature store has data
- Betting lines exist
- Estimated lines hitting exactly 20.0 (placeholder)

---

## Quick Validation Commands

```bash
# Check confidence distribution
bq query --use_legacy_sql=false "
SELECT confidence_decile, COUNT(*), ROUND(AVG(absolute_error),2) as mae,
  ROUND(COUNTIF(prediction_correct)/NULLIF(COUNTIF(recommendation IN ('OVER','UNDER')),0)*100,1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id='catboost_v8' AND game_date >= '2025-11-01'
GROUP BY 1 ORDER BY 1"

# Check for duplicates
bq query --use_legacy_sql=false "
SELECT player_lookup, game_date, system_id, COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-11-01'
GROUP BY 1,2,3 HAVING COUNT(*) > 1"

# Run line value validation for a date
bq query --use_legacy_sql=false --parameter=game_date:DATE:2026-01-28 < validation/queries/predictions/line_value_validation.sql

# Daily validation
/validate-daily
```

---

## Files Modified This Session

```
# Bug fixes (commit fbd6ad3d)
data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py
data_processors/analytics/upcoming_player_game_context/betting_data.py
predictions/coordinator/player_loader.py

# Prevention mechanisms
.pre-commit-hooks/validate_bettingpros_queries.py (NEW)
.pre-commit-config.yaml
validation/queries/predictions/line_value_validation.sql (NEW)
schemas/bigquery/raw/bettingpros_player_props_tables.sql

# Documentation
docs/09-handoff/2026-01-30-SESSION-35-V8-DEGRADATION-INVESTIGATION.md
docs/09-handoff/2026-01-30-SESSION-36-V8-INVESTIGATION-HANDOFF.md (this file)
```

---

## Next Session Priorities

1. **Investigate 1,926 duplicate records** - Find source, deduplicate, prevent
2. **Consider raising confidence threshold** - Quick win to filter out bad decile 9
3. **Deploy fixes to production** - The code changes need deployment
4. **Run full validation** - Ensure no other data issues

---

## Key Learnings

1. **Table names can be misleading** - `bettingpros_player_points_props` has ALL prop types
2. **Pre-commit hooks work** - Add them for any discovered pattern bugs
3. **Decile 10 is reliable** - 67% hit rate, use it for recommendations
4. **Decile 9 is not reliable** - 51% hit rate, consider filtering out

---

*Session 36 complete. Bug fixed, prevention added, follow-up on duplicates needed.*
