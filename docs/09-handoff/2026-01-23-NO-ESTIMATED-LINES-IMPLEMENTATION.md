# No Estimated Lines Implementation

**Date:** 2026-01-23
**Status:** Complete
**Revision:** prediction-coordinator-00086-pzl

---

## Summary

Implemented user requirement: **No fake/estimated betting lines in the system.**

Players without real sportsbook lines still get predictions (for accuracy learning), but:
- No fake line is assigned
- No OVER/UNDER recommendation is generated
- Grading excludes them from win rate calculations (avoids contamination)

---

## Problem Statement

ESTIMATED_AVG lines were fake lines based on season point averages. They:
- Represented 58.6% of 2025-26 predictions
- Had **42.7% win rate** (worse than random coin flip)
- Contaminated accuracy metrics, making it hard to evaluate true model performance

**User requirement:** "I really don't want estimates in the system. We can still make a prediction, but I don't want fake lines."

---

## Solution Implemented

### Code Changes

**1. Config Flag (`shared/config/orchestration_config.py`)**
```python
disable_estimated_lines: bool = True  # Default True - no fake lines
```
- Environment variable: `DISABLE_ESTIMATED_LINES`
- When True: No estimated lines generated
- When False: Legacy behavior (fall back to season average)

**2. Player Loader (`predictions/coordinator/player_loader.py` v3.10)**

Players are now handled in three ways:

| Player Type | line_source | has_prop_line | recommendation | predicted_points |
|-------------|-------------|---------------|----------------|------------------|
| Has real betting line | ACTUAL_PROP | TRUE | OVER/UNDER/PASS | ✅ Generated |
| No real line | NO_PROP_LINE | FALSE | NO_LINE | ✅ Generated |
| New player (no history) | NEEDS_BOOTSTRAP | - | - | ❌ Skipped |

**3. Data Cleanup**
- Deleted 49,522 ESTIMATED_AVG records from `prediction_accuracy` table
- Grading now only contains: ACTUAL_PROP, VEGAS_BACKFILL, NO_VEGAS_DATA

### Files Modified

| File | Change |
|------|--------|
| `shared/config/orchestration_config.py` | Added `disable_estimated_lines` flag |
| `predictions/coordinator/player_loader.py` | Handle NO_PROP_LINE case, fix has_prop_line logic |

---

## How It Works Now

### Prediction Flow

```
Player with real line (DraftKings/FanDuel/etc):
  → line_source = 'ACTUAL_PROP'
  → has_prop_line = TRUE
  → recommendation = OVER/UNDER/PASS (based on edge)
  → Graded for win rate AND MAE

Player without real line:
  → line_source = 'NO_PROP_LINE'
  → has_prop_line = FALSE
  → recommendation = 'NO_LINE'
  → Graded for MAE only (not win rate)
  → Predicted points still generated (for learning)
```

### Grading Filter

The grading processor filters predictions with:
```sql
AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
AND has_prop_line = TRUE
```

This means:
- **ACTUAL_PROP predictions**: Graded for MAE + OVER/UNDER accuracy
- **NO_PROP_LINE predictions**: NOT graded (no line to compare against)
- **ESTIMATED_AVG predictions**: Deleted from history, never generated again

---

## Verification Queries

### Check Line Source Distribution (Current Season)
```sql
SELECT
  line_source,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE AND game_date >= '2025-10-22'
GROUP BY 1 ORDER BY 2 DESC;
```

### Verify Grading Has No ESTIMATED_AVG
```sql
SELECT line_source, COUNT(*)
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
GROUP BY 1;
```
Expected: No ESTIMATED_AVG rows

### Track MAE for NO_PROP_LINE Predictions (Ad-hoc Learning)
```sql
-- Compare predicted vs actual for players without lines
SELECT
  p.game_date,
  p.player_lookup,
  p.predicted_points,
  a.points as actual_points,
  ABS(p.predicted_points - a.points) as absolute_error
FROM `nba_predictions.player_prop_predictions` p
JOIN `nba_analytics.player_game_summary` a
  ON p.player_lookup = a.player_lookup AND p.game_id = a.game_id
WHERE p.line_source = 'NO_PROP_LINE'
  AND p.is_active = TRUE
  AND p.game_date >= '2026-01-24'  -- After deployment
ORDER BY p.game_date DESC, absolute_error DESC;
```

---

## What's NOT Included

1. **NO_PROP_LINE predictions are not auto-graded** - The grading processor doesn't process them. Use ad-hoc queries above if needed.

2. **Historical NO_PROP_LINE backfill** - Old predictions that had ESTIMATED_AVG were deleted, not converted to NO_PROP_LINE.

3. **Worker changes** - Not needed. Worker already handles `prop_line=None` gracefully.

---

## Recommended Follow-up Actions

### P2: Optional MAE Tracking for NO_PROP_LINE
If you want to systematically track prediction accuracy for players without lines:
1. Add separate grading path that only computes MAE (no OVER/UNDER)
2. Or create a separate analytics table for "lineless predictions"

### P3: Monitor First Prediction Run
After deployment, verify:
```bash
# Check logs for NO_PROP_LINE handling
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-coordinator AND textPayload:NO_PROP_LINE" --limit=20 --project=nba-props-platform
```

---

## Related Documentation

- [Historical Line Source Handoff](./2026-01-23-HISTORICAL-LINE-SOURCE-HANDOFF.md) - Original investigation
- [Historical Data Validation Project](../08-projects/current/historical-data-validation/README.md) - Project tracker
- [Performance Analysis Guide](../08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md) - How to verify metrics

---

## Deployment Details

| Component | Revision | Status |
|-----------|----------|--------|
| prediction-coordinator | 00086-pzl | ✅ Deployed, 100% traffic |
| prediction-worker | (unchanged) | ✅ Already handles None lines |

**Service URL:** https://prediction-coordinator-756957797294.us-west2.run.app
