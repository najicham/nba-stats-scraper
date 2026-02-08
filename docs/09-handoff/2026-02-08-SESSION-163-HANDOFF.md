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
- `1a05ee76` — docs: Session 163 — model governance project docs, handoff, CLAUDE.md update

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
- Feb 8: Regeneration batch triggered (67 expected). Was at 6/67 when prediction-worker redeploy started — likely stalled during deploy. May need re-trigger.
- Feb 1-7: Background script `/tmp/backfill_feb_v2.sh` (PID bfc5b40) was waiting for Feb 8 batch to finish before starting. **May not have completed** — verify on next session.
- Phase 4 past-seasons backfill: Killed (was at 12% after 43h, running with old validator code). Needs restart with corrected validator.

### Cloud Build Status (as of session end)
- prediction-worker: BUILDING (Cloud Build 5e0810fa). Downloading model from GCS monthly/, building new Docker image with fixed glob pattern, deploying.
- Other services (coordinator, phase4, phase2): Deployed earlier this session (SUCCESS).

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

## Investigation Details: Why the Retrain Was Worse

The original V9 (trained Nov 2 - Jan 8, 9,993 samples) had near-neutral Vegas alignment:
- avg(predicted - vegas_line) = **-0.13** → balanced OVER/UNDER recommendations
- High-edge (3+) hit rate: **71.2%** (Jan 12 week)

The Feb 2 retrain (expanded to Nov 2 - Jan 31, ~15K samples) developed UNDER bias:
- avg(predicted - vegas_line) = **-2.26** → 87% UNDER recommendations
- High-edge (3+) hit rate: **51.2%** (Feb 2 week)

**Key insight:** MAE improved (4.12 vs 4.82) because the model got better at guessing the right ballpark. But it systematically under-predicted relative to Vegas lines. Since we bet OVER/UNDER against Vegas, what matters is `pred_vs_vegas` accuracy, not raw MAE.

**Possible root causes for the next session to investigate:**
1. Late January training data may have had quality issues (lower vegas_quality_pct ~39-60%)
2. Adding more data may have diluted early-season patterns that were accurate
3. The training pipeline may not properly weight recent games vs older ones
4. Feature distributions may have shifted (All-Star break, trade deadline effects)

**All Jan catboost_v9 predictions in prediction_accuracy were backfilled on Feb 1 at 10:10 AM** using the original model — they were NOT real-time predictions. This is important context for interpreting the historical hit rate numbers.

## Data for Next Session: Model Performance by Week

```
Week        | Model              | 3+ edge HR | pred_vs_vegas | OVER/UNDER
------------|--------------------|-----------:|---------------|------------
Jan 5-11    | original V9        |     62.3%  |  +0.34        | 27/26
Jan 12-18   | original V9        |     71.2%  |  +3.87        | 95/44
Jan 19-25   | original V9        |     66.4%  |  -0.40        | 52/61
Jan 26-Feb 1| mixed (transition) |     56.3%  |  -1.03        | 41/62
Feb 2-8     | Feb 2 retrain      |     53.4%  |  -5.30        | 17/116
```

## Copy-Paste Prompt for Session 164

```
Session 164 — Continue from Session 163

Read the handoff: docs/09-handoff/2026-02-08-SESSION-163-HANDOFF.md

What happened in Session 163:
- Discovered Feb 2 V9 retrain crashed hit rate from 71.2% to 51.2% (UNDER bias)
- Rolled back to original V9 model (catboost_v9_33features_20260201_011018.cbm)
- Implemented model governance: dynamic versioning, SHA256 tracking, promotion gates
- Fixed 7 more unprotected next() calls and 2 validator unit mismatches
- Backfills for Feb 1-8 were triggered but may not have completed

Priorities:
1. Check if prediction-worker deploy finished: gcloud builds list --region=us-west2 --limit=3
2. Check if Feb 1-8 backfills completed:
   SELECT game_date, model_version, COUNT(*) as n, COUNTIF(is_active) as active
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-01'
   GROUP BY 1, 2 ORDER BY 1
3. If backfills didn't complete, re-trigger them
4. Verify dynamic model_version shows "v9_20260201_011018" in new predictions
5. Deploy stale services: nba-grading-service (2d), nba-phase1-scrapers (6d)
6. Run daily validation: /validate-daily
7. Investigate why expanded training window degraded model performance
8. Restart Phase 4 past-seasons backfill (killed at 12% in Session 163)
```
