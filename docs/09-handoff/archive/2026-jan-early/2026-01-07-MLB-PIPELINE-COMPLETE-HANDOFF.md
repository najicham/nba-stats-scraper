# MLB Pipeline Deployment Complete - 2026-01-07

## Executive Summary

The MLB pipeline is now fully deployed with all 6 phases operational. All Cloud Run services are healthy and the infrastructure (Pub/Sub, BigQuery) was already in place.

## Deployed Services (5 Cloud Run)

| Phase | Service | URL | Status |
|-------|---------|-----|--------|
| Phase 1 | mlb-phase1-scrapers | https://mlb-phase1-scrapers-756957797294.us-west2.run.app | Healthy (28 scrapers) |
| Phase 2 | nba-phase2-raw-processors | https://nba-phase2-raw-processors-756957797294.us-west2.run.app | Healthy (shared, now MLB-aware) |
| Phase 3 | mlb-phase3-analytics-processors | https://mlb-phase3-analytics-processors-756957797294.us-west2.run.app | Healthy |
| Phase 4 | mlb-phase4-precompute-processors | https://mlb-phase4-precompute-processors-756957797294.us-west2.run.app | Healthy |
| Phase 5 | mlb-prediction-worker | https://mlb-prediction-worker-756957797294.us-west2.run.app | Healthy |
| Phase 6 | mlb-phase6-grading | https://mlb-phase6-grading-756957797294.us-west2.run.app | Healthy |

## What Was Done This Session

### 1. Phase 2 - Made Processor Service Sport-Aware
- Added MLB processor imports to `main_processor_service.py`
- Added 8 MLB processors to PROCESSOR_REGISTRY:
  - `ball-dont-lie/mlb-pitcher-stats` → MlbPitcherStatsProcessor
  - `ball-dont-lie/mlb-batter-stats` → MlbBatterStatsProcessor
  - `mlb-stats-api/schedule` → MlbScheduleProcessor
  - `mlb-stats-api/lineups` → MlbLineupsProcessor
  - `mlb-odds-api/pitcher-props` → MlbPitcherPropsProcessor
  - `mlb-odds-api/batter-props` → MlbBatterPropsProcessor
  - `mlb-odds-api/events` → MlbEventsProcessor
  - `mlb-odds-api/game-lines` → MlbGameLinesProcessor
- Added MLB path extraction logic to `extract_opts_from_path()`
- Redeployed nba-phase2-raw-processors with MLB support

### 2. Phase 3 - MLB Analytics Service (NEW)
- Created `data_processors/analytics/mlb/main_mlb_analytics_service.py`
- Processors:
  - `pitcher_game_summary` - Rolling K stats for pitchers
  - `batter_game_summary` - Rolling K stats for batters
- Created `docker/mlb-analytics-processor.Dockerfile`
- Created `bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`
- Deployed to Cloud Run

### 3. Phase 4 - MLB Precompute Service (NEW)
- Created `data_processors/precompute/mlb/main_mlb_precompute_service.py`
- Processors:
  - `pitcher_features` - 35-feature ML vector
  - `lineup_k_analysis` - Bottom-up K expectations
- Created `docker/mlb-precompute-processor.Dockerfile`
- Created `bin/precompute/deploy/mlb/deploy_mlb_precompute.sh`
- Deployed to Cloud Run

### 4. Phase 6 - MLB Grading Service (NEW)
- Created `data_processors/grading/mlb/mlb_prediction_grading_processor.py`
- Created `data_processors/grading/mlb/main_mlb_grading_service.py`
- Created `docker/mlb-grading.Dockerfile`
- Created `bin/phase6/deploy/mlb/deploy_mlb_grading.sh`
- Deployed to Cloud Run

## Files Created This Session

```
# Phase 3 - Analytics
data_processors/analytics/mlb/main_mlb_analytics_service.py
docker/mlb-analytics-processor.Dockerfile
bin/analytics/deploy/mlb/deploy_mlb_analytics.sh

# Phase 4 - Precompute
data_processors/precompute/mlb/main_mlb_precompute_service.py
docker/mlb-precompute-processor.Dockerfile
bin/precompute/deploy/mlb/deploy_mlb_precompute.sh

# Phase 6 - Grading
data_processors/grading/mlb/__init__.py
data_processors/grading/mlb/mlb_prediction_grading_processor.py
data_processors/grading/mlb/main_mlb_grading_service.py
docker/mlb-grading.Dockerfile
bin/phase6/deploy/mlb/deploy_mlb_grading.sh
```

## Infrastructure (Already Existed)

### Pub/Sub Topics (12)
```
mlb-phase1-scrapers-complete
mlb-phase1-scrapers-complete-dlq
mlb-phase2-raw-complete
mlb-phase2-raw-complete-dlq
mlb-phase3-analytics-complete
mlb-phase3-trigger
mlb-phase4-precompute-complete
mlb-phase4-trigger
mlb-phase5-predictions-complete
mlb-phase5-trigger
mlb-phase6-export-complete
mlb-phase6-trigger
```

### BigQuery Datasets
| Dataset | Tables |
|---------|--------|
| mlb_raw | 17+ tables populated |
| mlb_analytics | pitcher_game_summary, batter_game_summary |
| mlb_precompute | pitcher_ml_features, lineup_k_analysis |
| mlb_predictions | pitcher_strikeouts, pitcher_strikeout_predictions |
| mlb_orchestration | phase_completions, pipeline_runs |

## Remaining Work

### 1. Orchestrators (Not Created)
Need to create phase-to-phase orchestrators:
- Phase 2 → Phase 3
- Phase 3 → Phase 4
- Phase 4 → Phase 5
- Phase 5 → Phase 6

These trigger the next phase when the current phase completes.

### 2. Scheduler Jobs (Not Created)
Need to create Cloud Scheduler jobs for daily automation:
- Morning schedule fetch
- Lineup updates
- Props updates
- Prediction generation
- Nightly grading

MLB season starts late March, so these can wait.

## Testing Commands

```bash
# Test Phase 3 Analytics
curl -X POST https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-06-15"}'

# Test Phase 4 Precompute
curl -X POST https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-06-15"}'

# Test Phase 5 Predictions
curl -X POST https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/predict \
  -H "Content-Type: application/json" \
  -d '{"pitcher_lookup": "garrett_crochet", "game_date": "2025-09-15", "strikeouts_line": 7.5}'

# Test Phase 6 Grading
curl -X POST https://mlb-phase6-grading-f7p3g7f6ya-wl.a.run.app/grade-date \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-06-15"}'
```

## Model Performance

- **MAE**: 1.71 (11% better than 1.92 baseline)
- **Training samples**: 8,130
- **Features**: 19
- **Model path**: `gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json`

## Architecture Diagram

```
                         MLB Pipeline Architecture
                         ========================

┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Phase 1   │    │   Phase 2    │    │   Phase 3    │    │   Phase 4    │
│  Scrapers   │───▶│    Raw       │───▶│  Analytics   │───▶│  Precompute  │
│ (28 total)  │    │  Processors  │    │  Processors  │    │  Processors  │
└─────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
      │                   │                   │                   │
      ▼                   ▼                   ▼                   ▼
   GCS Files         mlb_raw.*         mlb_analytics.*    mlb_precompute.*
                                                                  │
                                                                  ▼
                    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                    │   Phase 6    │◀───│   Phase 5    │◀───│   Features   │
                    │   Grading    │    │  Predictions │    │   Ready      │
                    └──────────────┘    └──────────────┘    └──────────────┘
                          │                   │
                          ▼                   ▼
                   Accuracy Reports    mlb_predictions.*
```

## Next Steps (Priority Order)

1. **Create Orchestrators** (Optional for now)
   - Can manually trigger phases during testing
   - Automated orchestration needed before MLB season starts

2. **Create Scheduler Jobs** (Can wait until March)
   - MLB season is in off-season
   - Set up ~2 weeks before season starts

3. **End-to-End Testing**
   - Test with historical data
   - Validate predictions against actual results

---

**Status**: MLB Pipeline Fully Deployed
**Date**: January 7, 2026
**Services**: 5 Cloud Run services operational
