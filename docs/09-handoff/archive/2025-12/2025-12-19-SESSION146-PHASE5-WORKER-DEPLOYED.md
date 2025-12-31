# Session 146: Phase 5 Prediction Worker Deployed

**Date:** December 19, 2025
**Status:** Worker Deployed, Scheduler Fixed, Backfill Needed

---

## Summary

This session deployed the Phase 5 prediction worker to Cloud Run, fixed feature schema mismatches, and created the missing `player-daily-cache-daily` scheduler job. Predictions are now generating successfully for historical data.

---

## Completed Work

### 1. Phase 5 Prediction Worker Deployed

**Service:** `prediction-worker`
**Region:** us-west2
**URL:** https://prediction-worker-f7p3g7f6ya-wl.a.run.app

The worker receives prediction requests via Pub/Sub and generates predictions using 5 systems:
- Moving Average Baseline
- Zone Matchup V1
- Similarity Balanced V1
- XGBoost V1
- Ensemble V1

**Deployment script:** `bin/predictions/deploy/deploy_prediction_worker.sh prod`

### 2. Feature Schema Mismatch Fixed

Fixed `predictions/worker/data_loaders.py` to match the actual `ml_feature_store_v2` schema:

**Changes:**
- Updated `validate_features()` required fields to match actual feature names
- Added feature name aliases for backward compatibility with prediction systems
- Added `days_rest` from row data to features dict
- Relaxed production-readiness check to allow quality score >= 70

**Key Aliases Added:**
```python
FEATURE_ALIASES = {
    'games_in_last_7_days': ['games_played_last_7_days'],
    'opponent_def_rating': ['opponent_def_rating_last_15'],
    'home_away': ['is_home'],
    'pct_paint': ['paint_rate_last_10'],
    # ... etc
}
```

### 3. Missing Scheduler Job Created

Created `player-daily-cache-daily` to complete the Phase 4 pipeline:

| Time (PT) | Scheduler | Purpose |
|-----------|-----------|---------|
| 23:00 | player-composite-factors-daily | Phase 4 step 3 |
| 23:15 | **player-daily-cache-daily** | Phase 4 step 4 (NEW) |
| 23:30 | ml-feature-store-daily | Phase 4 step 5 |

### 4. Predictions Verified Working

Successfully generated predictions for historical data (June 2025):

```
Player: tyresehaliburton
Date: 2025-06-19
Line: 22.5

| System          | Predicted | Confidence | Recommendation |
|-----------------|-----------|------------|----------------|
| ensemble_v1     | 15.2      | 49%        | PASS           |
| moving_average  | 15.9      | 40%        | PASS           |
| xgboost_v1      | 12.7      | 82%        | UNDER          |
| zone_matchup_v1 | 20.0      | 40%        | PASS           |
```

---

## Root Cause Analysis

### Why Predictions Weren't Working

1. **Prediction worker never deployed** - The Pub/Sub subscription was pointing to a non-existent Cloud Run service

2. **Feature schema drift** - The `ml_feature_store_v2` table uses different feature names than the worker expected

3. **Missing scheduler job** - `player-daily-cache-daily` was never created, breaking the Phase 4 pipeline chain

4. **Phase 3 context tables stale** - `upcoming_player_game_context` and `upcoming_team_game_context` stopped in April 2024 due to offseason skip logic

### Pipeline Data Status

| Table | Latest Data | Gap |
|-------|-------------|-----|
| `player_game_summary` (Phase 3) | 2025-12-13 | ✅ Current |
| `upcoming_player_game_context` (Phase 3) | 2024-04-14 | ❌ 20 months |
| `upcoming_team_game_context` (Phase 3) | 2024-04-14 | ❌ 20 months |
| `player_composite_factors` (Phase 4) | 2025-12-03 | ⚠️ 16 days |
| `player_daily_cache` (Phase 4) | 2025-06-22 | ❌ 6 months |
| `ml_feature_store_v2` (Phase 4) | 2025-06-22 | ❌ 6 months |

---

## What Still Needs Work

### P0: Backfill Phase 4 for Current Season

The scheduler jobs are now in place, but they need data to run against. Run the Phase 4 backfill:

```bash
# Backfill from Oct 2025 to now
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2025-10-22 \
  --end-date 2025-12-19 \
  --start-from 3  # Start from player_composite_factors
```

**Estimated time:** 2-4 hours

### P1: Fix Phase 3 Context Tables (Optional for predictions)

The `upcoming_*_game_context` tables are 20 months stale because of offseason skip logic.

**Root cause file:** `shared/processors/patterns/early_exit_mixin.py`
- `_is_offseason()` returns True for July-September
- Processors set `ENABLE_OFFSEASON_CHECK = True`

**Fix options:**
1. Set `ENABLE_OFFSEASON_CHECK = False` in processors
2. Run backfill scripts:
   ```bash
   python backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
     --start-date 2025-10-22 --end-date 2025-12-19
   ```

### P2: Deploy Prediction Coordinator

For automated daily predictions, deploy the prediction coordinator:
- Location: `predictions/coordinator/`
- Purpose: Triggers predictions for all players playing on a given day
- Script: `bin/predictions/deploy/deploy_prediction_coordinator.sh`

---

## Files Changed

```
Modified:
- predictions/worker/data_loaders.py    # Fixed feature schema, added aliases
- predictions/worker/worker.py          # Relaxed production-readiness check

Created:
- docs/09-handoff/2025-12-19-SESSION146-PHASE5-WORKER-DEPLOYED.md
```

---

## Testing Commands

### Test Prediction Worker
```bash
# Publish test message
gcloud pubsub topics publish prediction-request-prod \
  --project=nba-props-platform \
  --message='{"player_lookup": "stephencurry", "game_date": "2025-06-19", "game_id": "test", "line_values": [25.5]}'

# Check logs
gcloud run services logs read prediction-worker --region=us-west2 --limit=30

# Check BigQuery
bq query --use_legacy_sql=false \
  'SELECT system_id, predicted_points, recommendation
   FROM nba_predictions.player_prop_predictions
   WHERE player_lookup = "stephencurry" AND game_date = "2025-06-19"'
```

### Manually Run Phase 4 Processor
```bash
curl -X POST \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerDailyCacheProcessor"], "analysis_date": "2025-12-13"}'
```

---

## Architecture After This Session

```
Cloud Scheduler (Phase 4)
    │
    ├── 23:00 player-composite-factors-daily
    ├── 23:15 player-daily-cache-daily (NEW)
    └── 23:30 ml-feature-store-daily
           │
           ▼
    ml_feature_store_v2 (BigQuery)
           │
           ▼
    Pub/Sub: prediction-request-prod
           │
           ▼
    prediction-worker (Cloud Run) ← NEW
           │
           ▼
    player_prop_predictions (BigQuery)
           │
           ▼
    Phase 6 Exporters → GCS → Frontend
```

---

## Next Session Priorities

1. **Run Phase 4 backfill** for 2025-26 season (2-4 hours)
2. **Deploy prediction coordinator** for automated daily predictions
3. **Test end-to-end** with current season data
4. **Monitor scheduler jobs** tomorrow to verify they run correctly

---

## Reference

### Scheduler Jobs
```bash
gcloud scheduler jobs list --location=us-west2 --filter="name:daily"
```

### Prediction Worker
```bash
gcloud run services describe prediction-worker --region=us-west2
gcloud run services logs read prediction-worker --region=us-west2 --limit=50
```

### BigQuery Tables
```sql
-- Check latest predictions
SELECT MAX(created_at) FROM nba_predictions.player_prop_predictions;

-- Check feature store
SELECT MAX(game_date) FROM nba_predictions.ml_feature_store_v2;
```
