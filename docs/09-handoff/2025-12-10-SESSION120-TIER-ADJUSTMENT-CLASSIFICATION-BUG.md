# Session 120 Handoff - Tier Adjustment Classification Bug Discovery

**Date:** 2025-12-10
**Focus:** Discovered critical bug in scoring tier adjustment logic

---

## Executive Summary

Implemented scoring tier adjustments into the prediction backfill (Phase 5C integration), but discovered a **fundamental design flaw**: tier classification is based on predicted points instead of player's historical average. This causes adjustments to make predictions **worse**, not better.

**Key Finding:** Adjusted MAE (4.92) is worse than raw MAE (4.74) because we're applying wrong adjustments.

---

## What Was Done This Session

### 1. Integrated Tier Adjustments into Prediction Backfill

Modified `backfill_jobs/prediction/player_prop_predictions_backfill.py`:
- Added import for `ScoringTierAdjuster`
- Added `_init_tier_adjuster()` lazy initialization
- For ensemble predictions, applies tier adjustment and stores:
  - `scoring_tier` - The tier classification
  - `tier_adjustment` - The adjustment amount applied
  - `adjusted_points` - predicted_points + tier_adjustment

### 2. Fixed Date Lookup Bug

Fixed `data_processors/ml_feedback/scoring_tier_processor.py`:
- Changed `as_of_date = '{as_of_date}'` to `as_of_date <= '{as_of_date}'`
- Now correctly finds the most recent adjustment at or before query date

### 3. Added Schema Columns

Added to `nba_predictions.player_prop_predictions`:
```sql
ALTER TABLE ADD COLUMN scoring_tier STRING,
ALTER TABLE ADD COLUMN tier_adjustment FLOAT,
ALTER TABLE ADD COLUMN adjusted_points FLOAT;
```

### 4. Ran Prediction Backfill

Backfill status: **22/33 dates completed** (Dec 5 - Dec 27)
- Dec 5: Has adjustments ✓
- Dec 6-11: Streaming buffer prevented updates (no adjustments)
- Dec 12-27: Has adjustments ✓
- Dec 28 - Jan 7: Still processing

---

## Critical Bug Discovered

### The Problem

Tier classification uses **predicted points** to determine tier, but bias adjustments were calculated based on **actual scoring tiers**. This creates a mismatch:

| Predicted Tier | Actual Tier | Count | Avg Predicted | Avg Actual | Issue |
|----------------|-------------|-------|---------------|------------|-------|
| BENCH_0_9 | ROTATION_10_19 | 293 | 5.4 | 13.1 | Underestimated |
| BENCH_0_9 | STARTER_20_29 | 30 | 5.3 | 23.1 | Severely underestimated |
| ROTATION_10_19 | STARTER_20_29 | 198 | 13.7 | 23.1 | Underestimated |

**Example:** Player predicted at 5 pts scores 23 pts:
- Current: Apply BENCH adjustment (-0.8) → 4.2 pts (worse!)
- Should: Apply STARTER adjustment (+5.85) → 10.85 pts (better)

### Why It Happens

The `classify_tier()` method in `ScoringTierAdjuster`:
```python
def classify_tier(self, predicted_points: float) -> str:
    if predicted_points >= 30:
        return 'STAR_30PLUS'
    # ... etc
```

This classifies based on the prediction value, not the player's typical scoring level.

### The Fix Required

Modify tier classification to use **player's historical season average** from ML feature store:

```python
def classify_tier_by_player(self, player_lookup: str, game_date: str) -> str:
    # Get player's season_ppg from ml_feature_store_v2
    query = f"""
    SELECT season_ppg
    FROM nba_predictions.ml_feature_store_v2
    WHERE player_lookup = '{player_lookup}'
      AND game_date = '{game_date}'
    """
    season_ppg = run_query(query)
    return self.classify_tier(season_ppg)  # Classify based on historical average
```

---

## Current Data State

### Predictions Table
- **With adjustments:** Dec 5, Dec 12-27 (and continuing)
- **Without adjustments:** Dec 6-11 (streaming buffer issue)
- **Not yet processed:** Dec 28 - Jan 7

### MAE Analysis (preliminary)
| Status | Predictions | Raw MAE | Adjusted MAE |
|--------|-------------|---------|--------------|
| With adjustment | 993 | 4.74 | 4.92 |
| Without adjustment | 969 | 4.17 | 4.17 |

Adjustments are making predictions **worse** due to tier classification bug.

---

## Background Processes

The prediction backfill is still running:
- Shell ID: `1fbe70`
- Progress: 22/33 dates completed
- Command: `backfill_jobs/prediction/player_prop_predictions_backfill.py --start-date 2021-12-05 --end-date 2022-01-07`

**Note:** There are many stale background shell references from previous sessions. The actual Python process may have completed or be near completion.

---

## Files Modified This Session

### Modified
1. `backfill_jobs/prediction/player_prop_predictions_backfill.py`
   - Added tier adjustment integration (lines 51-53, 86-93, 483-500)

2. `data_processors/ml_feedback/scoring_tier_processor.py`
   - Fixed date lookup bug (line 201: `<=` instead of `=`)

3. `docs/08-projects/current/phase-5c-ml-feedback/DESIGN.md`
   - Added integration design section with Option B decision

---

## Next Steps (Prioritized)

### 1. Kill/Let Complete Current Backfill
The current backfill will populate data with the buggy tier classification. Let it complete for comparison purposes, or kill it.

### 2. Fix Tier Classification Logic
Update `ScoringTierAdjuster` to classify based on player's historical average:

```python
# In scoring_tier_processor.py
def classify_tier_for_player(self, player_lookup: str, game_date: str) -> str:
    """Classify tier based on player's season average, not prediction."""
    # Query ML feature store for season_ppg
    query = f"""
    SELECT season_ppg
    FROM nba_predictions.ml_feature_store_v2
    WHERE player_lookup = '{player_lookup}' AND game_date = '{game_date}'
    """
    result = self.bq_client.query(query).result()
    for row in result:
        return self._processor.classify_tier(float(row.season_ppg))
    return None  # Player not found
```

### 3. Update Backfill to Pass Player Info
Modify prediction backfill to pass `player_lookup` and `game_date` to tier adjuster:
```python
# Instead of:
tier = adjuster.classify_tier(float(predicted_value))
adjustment = adjuster.get_scaled_adjustment(float(predicted_value), as_of_date=game_date)

# Use:
tier = adjuster.classify_tier_for_player(player_lookup, game_date)
adjustment = adjuster.get_adjustment_for_tier(tier, as_of_date=game_date)
```

### 4. Re-backfill Predictions
After fixing the logic, re-run:
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07 --skip-preflight
```

### 5. Validate MAE Improvement
```sql
SELECT
  scoring_tier,
  COUNT(*) as predictions,
  AVG(ABS(actual_points - predicted_points)) as raw_mae,
  AVG(ABS(actual_points - adjusted_points)) as adjusted_mae
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy a USING (player_lookup, game_date, system_id)
WHERE p.system_id = 'ensemble_v1' AND p.adjusted_points IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

---

## Key Design Decision Made

**Option B selected** for storing adjustments: Add columns to existing predictions table rather than creating separate system_id records.

Benefits:
- Easy comparison of raw vs adjusted in same row
- No duplicate storage
- Simple queries

---

## Tests

All 32 unit tests passing:
```bash
pytest tests/processors/ml_feedback/test_scoring_tier.py -v
```

Note: Tests may need updates after the tier classification fix.

---

## Related Documents

- `docs/08-projects/current/phase-5c-ml-feedback/DESIGN.md` - Full design spec
- `docs/09-handoff/2025-12-10-SESSION118-SCORING-TIER-ADJUSTER-IMPLEMENTATION.md` - Initial implementation
- `docs/09-handoff/2025-12-10-SESSION119-PHASE5C-HANDOFF-FOR-CONTINUATION.md` - Prior session

---

## Quick Start for Next Session

1. Check if backfill completed:
   ```bash
   ps aux | grep player_prop_predictions_backfill
   ```

2. If still running, check progress:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT game_date, COUNT(*) as records,
     COUNTIF(adjusted_points IS NOT NULL) as with_adj
   FROM nba_predictions.player_prop_predictions
   WHERE game_date >= '2021-12-05' AND system_id = 'ensemble_v1'
   GROUP BY 1 ORDER BY 1"
   ```

3. Fix the tier classification bug (Priority 1)

4. Re-backfill and validate MAE improvement

---

**End of Handoff**
