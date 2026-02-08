# Session 164 Handoff — Model Governance Hardening & Backfill

**Date:** 2026-02-08
**Previous Session:** 163 (model retrain disaster, rollback, governance gates)

## What Was Accomplished

### 1. Coordinator /reset Bug Fix
- `ProgressTracker.reset()` set `is_complete=False` which prevented new batches from starting
- Fixed: set `current_tracker = None` in `/reset` endpoint
- File: `predictions/coordinator/coordinator.py:2869`

### 2. Fixed 42+ Unprotected `next()` Calls
- 24 files changed across scrapers, analytics, precompute, monitoring, validation
- All production `next(result).field` patterns now use `next(result, None)` with proper null handling
- Commit: `f4fcb6a3`

### 3. Stale Service Deploys
- `nba-grading-service` — deployed (was 2 days stale)
- `nba-phase1-scrapers` — deployed (was 6 days stale)
- All other services auto-deployed via Cloud Build on push

### 4. Model Governance Documentation
- Updated `/model-experiment` SKILL.md with:
  - "Training Is NOT Deployment" warning
  - 5-step Model Promotion Checklist (each requires user approval)
  - "What Constitutes a Different Model" definition
- Updated CLAUDE.md model governance section
- Commit: `9622c706`

### 5. Fixed BQ Model Registry
- `training_end_date` for production V9 was WRONG (showed Jan 31, should be Jan 8)
- Fixed to match GCS manifest (source of truth)

### 6. Training Date Overlap Check — CLEAN
- Zero predictions exist on or before Jan 8, 2026 (training cutoff)
- Zero subset picks exist on or before Jan 8, 2026
- Predictions correctly start Jan 9, 2026

## Current State

### Model Configuration
| Property | Value |
|----------|-------|
| Production model | `catboost_v9_33features_20260201_011018.cbm` |
| Training range | Nov 2, 2025 - Jan 8, 2026 |
| SHA256 | `5b3a187b1b6d` (prefix) |
| Worker env var | `CATBOOST_V9_MODEL_PATH` correctly set |
| Dynamic versioning | Deployed but no new predictions since deploy |

### Feb Prediction Status
| Date | Total | Active | Model Version |
|------|-------|--------|---------------|
| Feb 1 | 143 | 143 | v9_current_season |
| Feb 2 | 111 | 69 | v9_current_season |
| Feb 3 | 243 | 155 | v9_current_season |
| Feb 4 | 99 | 99 | v9_current_season |
| Feb 5 | 127 | 119 | v9_current_season |
| Feb 6 | 86 | 86 | v9_current_season |
| Feb 7 | 474 | 148 | v9_current_season |
| Feb 8 | 87 | 53 | v9_current_season |

### Deployment Status
- All Cloud Run services: up to date (deployed 2026-02-08)
- All stale services fixed

## UNRESOLVED: Backfill Pub/Sub Stalling

**Problem:** Manual backfills via `/start` create batches correctly, but workers never process them. Batch stays at 0/N for minutes then stalls.

**What we know:**
- Coordinator publishes to `prediction-request-prod` topic (default env var)
- Push subscription targets `https://prediction-worker-f7p3g7f6ya-wl.a.run.app/predict`
- Worker OIDC auth configured with `prediction-worker@nba-props-platform.iam.gserviceaccount.com`
- Worker `/health` and `/health/deep` both pass
- No error logs in either coordinator or worker during stall period
- Earlier in Session 164, backfills DID work (Feb 1 got 143/181) — possibly before deploys disrupted Pub/Sub push delivery

**Investigation needed:**
1. Check if coordinator is actually calling `publish_prediction_requests()` after creating the batch
2. Check Pub/Sub delivery metrics in Cloud Console
3. Try a pull-based test: temporarily switch subscription to pull and verify messages exist
4. Check if Cloud Run min-instances=0 is causing Pub/Sub push to fail on cold starts

## UNRESOLVED: Model Governance Sync

**Problem:** 4 places describe model metadata and they drift:
1. GCS manifest.json (source of truth)
2. BQ model_registry (was wrong, fixed this session)
3. CLAUDE.md (manually maintained)
4. Model filenames (use creation timestamp, not training dates)

**Proposed solutions (for next focused session):**
1. `./bin/model-registry.sh sync` — reads manifest → updates BQ registry
2. New filename convention: `catboost_v9_33f_train20251102-20260108_{timestamp}.cbm`
3. Pre-training duplicate check in `quick_retrain.py`
4. Auto-generate CLAUDE.md model section from registry
5. Validate sync on deploy (drift detection for model metadata)

## Next Session Priorities

### Priority 1: Fix Backfill Stalling (Opus)
The morning prediction run may work fine (triggered by scheduler, not manual `/start`), but manual backfills are broken. Need to investigate Pub/Sub delivery.

### Priority 2: Model Governance Sync (Sonnet)
Focused implementation session to build the sync infrastructure. See "Proposed solutions" above.

### Priority 3: Subset Backfill
After predictions are stable, run subset materialization for Feb 1-8:
```bash
PYTHONPATH=. python /tmp/backfill_subsets_feb.py
```
Or use the SubsetMaterializer directly.

### Priority 4: Verify Dynamic model_version
After the next morning prediction run (Feb 9), verify new predictions show `v9_20260201_011018` instead of `v9_current_season`.

## Key Files Changed
- `predictions/coordinator/coordinator.py` — /reset bug fix
- `scrapers/nbacom/nbac_scoreboard_v2.py` — 6 next() fixes
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` — 6 next() fixes
- `data_processors/analytics/analytics_base.py` — 1 next() fix
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` — 1 next() fix
- `data_processors/raw/bigdataball/bigdataball_pbp_processor.py` — 1 next() fix
- `shared/validation/validators/feature_validator.py` — 1 next() fix
- `shared/validation/validators/regression_detector.py` — 2 next() fixes
- `validation/base_validator.py` — 2 next() fixes
- `bin/monitoring/*.py` — 16 next() fixes (via agent)
- `scrapers/balldontlie/bdl_*.py` — 3 next() fixes
- `monitoring/mlb/mlb_gap_detection.py` — 1 next() fix
- `.claude/skills/model-experiment/SKILL.md` — governance hardening
- `CLAUDE.md` — model governance section strengthened
- `docs/08-projects/current/model-governance/00-PROJECT-OVERVIEW.md` — Session 164 updates
