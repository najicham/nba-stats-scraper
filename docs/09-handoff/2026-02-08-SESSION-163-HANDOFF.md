# Session 163 Handoff — Model Governance After Performance Crash

**Date:** 2026-02-08
**Focus:** Model rollback, governance system, validator fixes, backfills

## What Happened

### Critical Discovery: V9 Model Performance Crash
The Feb 2 retrained CatBoost V9 model caused high-edge hit rate to crash from **71.2% to 51.2%** over 7 days. Root cause: the retrain had lower MAE (4.12 vs 4.82) which looked better, but was systematically under-predicting vs Vegas lines (-2.26 avg bias), creating 87% UNDER recommendation skew.

### Actions Taken

1. **Rolled back model** — Changed `CATBOOST_V9_MODEL_PATH` env var to original V9 model (`catboost_v9_33features_20260201_011018.cbm`). Confirmed healthy.

2. **Fixed 7 more unprotected next() calls** (continuing Session 162 audit):
   - `bigquery_save_ops.py` (2 calls — Session 162 missed these)
   - `quality_gate.py` (1 call)
   - `batch_staging_writer.py` (2 calls)
   - `database_reader.py` (2 calls)

3. **Fixed 2 more pre_write_validator unit mismatches**:
   - `pace_score_range`: 70-130 -> -8 to +8 (was using wrong units)
   - `matchup_difficulty_range` -> `shot_zone_mismatch_range` (was validating non-existent field)

4. **Implemented model governance system**:
   - Dynamic `MODEL_VERSION` derived from filename (not hardcoded)
   - SHA256 hash computed at load time, written to every prediction
   - Model registry in BQ + GCS manifest with all 3 V9 models registered
   - Governance gates in `quick_retrain.py`: Vegas bias check, tier bias, sample size
   - Fixed Dockerfile glob mismatch (monthly model was unused in Docker image)

5. **Triggered backfills**:
   - Feb 8: Regenerated (67 predictions with correct model)
   - Feb 1-7: Backfill running in background

## Commits
- `b3dd5586` — fix: Validator unit mismatches and 7 more unprotected next() calls
- `d74b8614` — feat: Model governance — dynamic versioning, SHA256 tracking, promotion gates

## Current State

### Model Status
| Model | Status | Hit Rate (3+ edge) |
|-------|--------|-------------------|
| catboost_v9_33features_20260201_011018.cbm | **PRODUCTION** | 71.2% |
| catboost_v9_feb_02_retrain.cbm | Deprecated | 51.2% |
| catboost_v9_2026_02.cbm (monthly) | Untested | ~53.7% |

### Deployment Status
- prediction-worker: Rolled back to original V9 (env var change + code push)
- Auto-deploy triggered for: prediction-worker, prediction-coordinator, phase4-precompute, phase2-raw
- nba-grading-service: Still 2 days stale (unchanged this session)
- nba-phase1-scrapers: Still 6 days stale (unchanged this session)

### Backfill Status
- Feb 8: Regeneration triggered, 67 predictions expected
- Feb 1-7: Running in background (`/tmp/backfill_feb_predictions.sh`)
- Phase 4 past-seasons backfill: Killed (was at 12% after 43h). Needs restart.

## Priorities for Next Session

### High
1. **Verify backfill completed** — Check that Feb 1-7 predictions were regenerated with original model. Query:
   ```sql
   SELECT game_date, model_version, COUNT(*) as n, COUNTIF(is_active) as active
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-01'
   GROUP BY 1, 2 ORDER BY 1
   ```

2. **Verify new model_version tracking** — After auto-deploy, predictions should show `v9_20260201_011018` instead of `v9_current_season`. Check:
   ```sql
   SELECT model_version, COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09'
   GROUP BY 1
   ```

3. **Deploy stale services** — nba-grading-service (2d) and nba-phase1-scrapers (6d)

4. **Restart Phase 4 backfill** — Was killed this session. Defense zone records need the corrected validator from Session 162. Consider running just `team_defense_zone_analysis` processor:
   ```bash
   ./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 \
     --end-date 2025-06-22 --processor team_defense_zone_analysis
   ```

### Medium
5. **Evaluate model retraining strategy** — The Feb 2 retrain (Nov 2 - Jan 31) was worse than the original (Nov 2 - Jan 8). Investigate why expanding the training window degraded performance. Possible causes:
   - Overfitting to recent data patterns
   - Training data quality issues in late January
   - Need for feature recalibration with more data

6. **Fix remaining ~42 unprotected next() calls** — Session 163 audit found 49 total, fixed 7. Priority list in Session 163 audit results.

7. **Fix Phase 2→3 trigger tracking** — Firestore shows `_triggered=False` for Feb 7 despite Phase 3 running. The orchestrator may not be updating Firestore correctly.

### Low
8. **Shadow testing infrastructure** — The governance process recommends 2+ days of shadow testing before model promotion. This requires running a second model with a different `system_id` (e.g., `catboost_v9_shadow`). Not yet implemented.

## Key Files
- `docs/08-projects/current/model-governance/00-PROJECT-OVERVIEW.md` — Full project docs
- `predictions/worker/prediction_systems/catboost_v9.py` — Dynamic versioning
- `ml/experiments/quick_retrain.py` — Governance gates
- `bin/model-registry.sh` — Registry CLI
- `gs://nba-props-platform-models/catboost/v9/manifest.json` — Model manifest

## Quick Reference

```bash
# Check model registry
./bin/model-registry.sh list
./bin/model-registry.sh validate  # Verifies SHA256 integrity

# Rollback a model
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/MODEL_FILE.cbm"

# Retrain with governance gates
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "MAR_MONTHLY" \
  --train-start 2025-11-02 --train-end 2026-02-28
```
