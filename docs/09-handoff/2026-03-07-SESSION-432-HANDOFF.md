# Session 432 Handoff — Auto-Demote Filters + MLB Pre-Season

**Date:** 2026-03-07
**Status:** All changes committed and pushed.

---

## What Was Done

### 1. NBA: Auto-Demote Filter System (Priority 1 from Session 431b)
- **Cloud Function**: `filter-counterfactual-evaluator` deployed + scheduled (11:30 AM ET daily)
- **How it works**: Computes daily counterfactual HR per filter from `best_bets_filtered_picks`. If CF HR >= 55% for 7 consecutive days at N >= 20, auto-demotes filter to observation via `filter_overrides` table. Max 2 demotions/run. Core filters excluded.
- **Aggregator integration**: `runtime_demoted_filters` parameter — demoted filters still record but don't block picks
- **Exporter integration**: `_query_filter_overrides()` reads active overrides at export time
- **BQ tables**: `filter_counterfactual_daily` (tracking), `filter_overrides` (runtime demotions)
- **Backfilled**: 4 days of CF HR data (Mar 3-6). Full 7-day window by ~Mar 10.

### 2. MLB: Complete Pre-Season Prep
- **Model retrained**: CatBoost V1 (train May 17 - Sep 14, 2025), **68.5% HR edge 1+ (N=54)**, all 5 governance gates passed
- **Model deployed**: Uploaded to GCS, registered in BQ (production=TRUE), worker env var updated
- **Batter backfill COMPLETE**: 367 dates through Sep 28, 2025
- **Statcast backfill COMPLETE**: 82 dates through Sep 28, 2025
- **Training query improved**: COALESCE statcast features with season averages — recovers 487/492 null rows (30% → ~3% NaN drop rate)
- **Scheduler resume script**: `./bin/mlb-season-resume.sh`
- **CRITICAL FIX**: Worker env var `MLB_CATBOOST_V1_MODEL_PATH` was overriding code default with old model — fixed

---

## What to Do Next

### IMMEDIATE: Retrain MLB with Fixed Training Query
The COALESCE fix was committed but model hasn't been retrained with it yet. This adds ~487 more training samples.

```bash
# Retrain with fixed query (NaN drop should be ~3% instead of 30%)
PYTHONPATH=. .venv/bin/python ml/training/mlb/quick_retrain_mlb.py \
  --model-type catboost --training-window 120 --train-end 2025-09-14 --eval-days 14

# If gates pass, upload and register
PYTHONPATH=. .venv/bin/python ml/training/mlb/quick_retrain_mlb.py \
  --model-type catboost --training-window 120 --train-end 2025-09-14 --eval-days 14 \
  --upload --register --notes "COALESCE fix, ~97% feature coverage"

# Update worker env var to new model
gcloud run services update mlb-prediction-worker --region=us-west2 --project=nba-props-platform \
  --update-env-vars="MLB_CATBOOST_V1_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/<NEW_MODEL_FILE>"
```

### IMMEDIATE: Update pitcher_loader.py with same COALESCE logic
The training query was fixed but `predictions/mlb/pitcher_loader.py` (production feature extraction) needs the same fix so production predictions don't drop players missing statcast data. Check `load_batch_features()` and apply same fallback pattern.

### Performance Experiments
```bash
# Experiment 1: Already done — compare NaN drop rates
# Before: ~30% dropped, ~1507 clean samples. After: ~3% dropped, ~2100+ samples

# Experiment 2: Training window sweep
for W in 90 120 150; do
  PYTHONPATH=. .venv/bin/python ml/training/mlb/quick_retrain_mlb.py \
    --training-window $W --train-end 2025-09-14
done

# Experiment 3: XGBoost comparison
PYTHONPATH=. .venv/bin/python ml/training/mlb/quick_retrain_mlb.py \
  --model-type xgboost --training-window 120 --train-end 2025-09-14
```

### Feature Store Gaps to Fill
```sql
-- Historical statcast gap: only 2025-07-01 to 2025-09-28
-- Backfill 2024 season for better pitcher_rolling_statcast coverage:
PYTHONPATH=. .venv/bin/python scripts/mlb/backfill_statcast.py --start 2024-03-28 --end 2025-06-30
```

### Mar 24-25: Season Launch
```bash
./bin/mlb-season-resume.sh  # Resume all 24 scheduler jobs
```

---

## Key Files Changed
```
ml/training/mlb/quick_retrain_mlb.py          # COALESCE fix for statcast features
ml/signals/aggregator.py                       # Runtime filter demote support
data_processors/publishing/signal_best_bets_exporter.py  # filter_overrides query
orchestration/cloud_functions/filter_counterfactual_evaluator/  # New CF
predictions/mlb/config.py                      # New model path
predictions/mlb/prediction_systems/catboost_v1_predictor.py  # New model path
bin/mlb-season-resume.sh                       # Scheduler resume script
```
