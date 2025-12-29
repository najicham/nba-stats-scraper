# Session 183: ML Feature Store Same-Day Fix

**Date**: 2025-12-28 (evening)
**Focus**: Fix prediction pipeline generating predictions for only 27/192 players

## Problem Identified

ML Feature Store was failing for same-day predictions because:
1. When `backfill_mode=True`, it queries `player_game_summary` (who actually played)
2. For same-day games, those games haven't been played yet
3. So it returned 0 players, causing predictions to fail

The self-heal function and other orchestrators were calling Phase 4 with `backfill_mode=True`, which is correct for historical backfills but breaks same-day predictions.

## Solution Implemented

### Fix 1: feature_extractor.py (v3.4)
Added date check that forces use of `upcoming_player_game_context` for same-day/future dates:

```python
# v3.4: Determine if this is a same-day/future date
today_et = datetime.now(ZoneInfo('America/New_York')).date()
is_future_or_today = game_date >= today_et

# For future/same-day dates, ALWAYS use upcoming_player_game_context
use_backfill_query = backfill_mode and not is_future_or_today
```

### Fix 2: self_heal/main.py
Changed Phase 3 trigger from `backfill_mode=True` to `backfill_mode=False` since self-heal generates predictions for tomorrow.

## Results

| Metric | Before | After |
|--------|--------|-------|
| Players with ML features | 27 | 192 |
| Unique players with predictions | 27 | 56 |
| Total prediction rows | 165 | 1,920 |

Note: 56 unique players (not 192) is expected - the prediction coordinator only generates predictions for players meeting the `min_minutes=15` threshold.

## Deployments

1. **Phase 4 Precompute Processors**
   - Revision: `nba-phase4-precompute-processors-00025-th6`
   - Commit: `15aa27f`
   - Verified working with `[SAME-DAY FIX]` log message

2. **Self-Heal Cloud Function**
   - Revision: `self-heal-check-00004-him`
   - Now uses `backfill_mode=False` for Phase 3

## Verification Commands

```bash
# Check if same-day fix is working
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase4-precompute-processors" AND "SAME-DAY"' --limit=5 --format="table(timestamp,textPayload)" --freshness=1h

# Check ML feature store count
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE('America/New_York')"

# Check prediction count
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE('America/New_York') AND is_active = TRUE"
```

## Known Issue: Live Grading Player Matching

A **separate issue** was discovered during verification:
- Live grading shows `team: null` and `actual: null` for predictions
- This causes predictions to show as "pending" even for completed games
- Root cause: Player matching between predictions and BDL live stats is failing

This is NOT related to the same-day fix - it's a pre-existing bug in `live_grading_exporter.py` that should be investigated in a future session.

## Files Changed

1. `data_processors/precompute/ml_feature_store/feature_extractor.py`
   - Added v3.4 same-day fix with date comparison

2. `orchestration/cloud_functions/self_heal/main.py`
   - Changed `backfill_mode=True` to `backfill_mode=False` in `trigger_phase3()`
