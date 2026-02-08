# Session 159 Handoff — Robustness Improvements + Prediction Recovery

**Date:** 2026-02-08
**Focus:** Four prevention mechanisms, prediction recovery for Feb 7-8, deployment audit
**Status:** All code pushed + deployed. Phase 4 backfill still running (background).

## What Was Done

### Part A: Prediction Recovery (Fire)
- **Feb 7** (10 games): Triggered BACKFILL, 3,441 predictions landed (1,215 actionable)
- **Feb 8** (4 games): Triggered BACKFILL, 343 predictions landed (67 actionable)
- Both batches stalled at ~70% completion; force-completed via `/check-stalled` with relaxed thresholds
- Old orphaned Feb 8 batch (from Session 158 fix attempt) also force-completed in Firestore

### Part B: Four Robustness Improvements

#### 1. Worker Startup Schema Validation
**Files:** `predictions/shared/batch_staging_writer.py`, `predictions/worker/health_checks.py`

- `validate_output_schema(record_keys)` compares worker output fields against BQ table columns
- On first `write_to_staging()` call: fail-fast if fields missing from BQ (CRITICAL log + immediate failure)
- Added to `/health/deep` endpoint: checks 14 critical fields including `vegas_line_source`, `required_default_count`
- **Prevents:** Schema mismatch silently breaking all writes (Feb 7-8 root cause)

#### 2. Coordinator Batch Timeout (30 min) + /reset Endpoint
**Files:** `predictions/coordinator/coordinator.py`, `predictions/coordinator/batch_state_manager.py`

- `check_and_complete_stalled_batch()` now has `max_batch_age_minutes=30`: force-completes batches running > 30 min regardless of completion %
- Stall detection in `/start` reduced from 600s to 300s (5 min)
- New `/reset` endpoint: unconditionally clears stuck batch (Firestore + in-memory). Accepts `batch_id` or `game_date`
- **Prevents:** Stuck batches blocking new predictions for 4+ hours

#### 3. Prediction Gap Alerting
**File:** `bin/monitoring/pipeline_canary_queries.py`

- New "Phase 5 - Prediction Gap" canary check
- Cross-references `nba_schedule` (games today) vs `player_prop_predictions` (predictions today)
- FAIL if `games_today > 0 AND prediction_count = 0`
- Alerts to `#canary-alerts` via existing 30-min canary schedule
- **Prevents:** Zero-prediction days going unnoticed (Feb 7 had 10 games, no predictions, no alert)

#### 4. Phase 4 Cascade Fix (Retry with Backoff)
**File:** `data_processors/precompute/base/precompute_base.py`

- When critical dependencies missing (Phase 3 not done): retry up to 3 times with 60s/120s/180s backoff
- Only in non-backfill mode (backfill skips dependency checks)
- Configurable via `dependency_retries` and `dependency_retry_base_seconds` opts
- **Prevents:** DailyCache -> CompositeFactors -> FeatureStore -> Predictions cascade from Phase 3 timing

### Part C: Season Subset Export
- Exported season subset picks: 379KB, 8 groups, 151 dates to `gs://nba-props-platform-api/v1/subsets/season.json`
- Deployed Phase 5→6 Cloud Function (`phase5-to-phase6-orchestrator`) to include `season-subsets` in auto-exports

### Part D: Deployment Audit

Audited all services to understand what auto-deploys on push to main vs what needs manual deploy.

### Part E: Deployment Status (All Successful)
- `deploy-prediction-coordinator` — SUCCESS
- `deploy-prediction-worker` — SUCCESS
- `deploy-nba-phase4-precompute-processors` — SUCCESS
- `phase5-to-phase6-orchestrator` Cloud Function — deployed manually

---

## Deployment Architecture Investigation

### Current State: What Auto-Deploys

**7 services have Cloud Build triggers** that fire on push to `main`:

| Service | Type | Trigger | Watches |
|---|---|---|---|
| `nba-scrapers` | Cloud Run | `deploy-nba-scrapers` | `scrapers/**`, `shared/**` |
| `nba-phase2-raw-processors` | Cloud Run | `deploy-nba-phase2-raw-processors` | `data_processors/raw/**`, `shared/**` |
| `nba-phase3-analytics-processors` | Cloud Run | `deploy-nba-phase3-analytics-processors` | `data_processors/analytics/**`, `shared/**` |
| `nba-phase4-precompute-processors` | Cloud Run | `deploy-nba-phase4-precompute-processors` | `data_processors/precompute/**`, `shared/**` |
| `prediction-coordinator` | Cloud Run | `deploy-prediction-coordinator` | `predictions/coordinator/**`, `predictions/shared/**`, `shared/**` |
| `prediction-worker` | Cloud Run | `deploy-prediction-worker` | `predictions/worker/**`, `predictions/shared/**`, `shared/**` |
| `phase5b-grading` | Cloud Function | `deploy-phase5b-grading` | `orchestration/cloud_functions/grading/**`, `shared/**` |

Cloud Run services use `cloudbuild.yaml`. The grading Cloud Function uses `cloudbuild-functions.yaml`.

### The Gap: 66 Cloud Functions Need Manual Deploy

**All orchestrators** (connect pipeline phases via Pub/Sub):
- `phase2-to-phase3-orchestrator`
- `phase3-to-phase4-orchestrator`
- `phase4-to-phase5-orchestrator`
- `phase5-to-phase6-orchestrator`

**All monitoring/alerting** (~30 functions):
- `deployment-drift-monitor`, `daily-health-check`, `pipeline-health-monitor`, `stale-processor-monitor`, `prediction-health-alert`, etc.

**All self-healing** (~10 functions):
- `self-heal-check`, `self-heal-predictions`, `auto-backfill-orchestrator`, etc.

### Why This Matters

Session 158 added `season-subsets` to the Phase 5→6 orchestrator code. The code was committed and pushed, but the Cloud Function wasn't redeployed until Session 159 manually deployed it. Any time orchestrator code changes, there's a risk of code drift.

### Recommendation: Add Triggers for 4 Critical Orchestrators

**Priority 1 — Pipeline orchestrators (high impact, change occasionally):**

These are the most critical because they control the flow between pipeline phases. When code changes (like adding `season-subsets`), they MUST be redeployed.

| Function | Watches | Why Critical |
|---|---|---|
| `phase2-to-phase3-orchestrator` | `orchestration/cloud_functions/phase2_to_phase3/**`, `shared/**` | Controls Phase 2→3 transition |
| `phase3-to-phase4-orchestrator` | `orchestration/cloud_functions/phase3_to_phase4/**`, `shared/**` | Controls Phase 3→4 transition |
| `phase4-to-phase5-orchestrator` | `orchestration/cloud_functions/phase4_to_phase5/**`, `shared/**` | Controls Phase 4→5 transition (quality gates!) |
| `phase5-to-phase6-orchestrator` | `orchestration/cloud_functions/phase5_to_phase6/**`, `shared/**` | Controls Phase 5→6 exports |

**Implementation:** Create 4 new Cloud Build triggers using the existing `cloudbuild-functions.yaml` template. Each trigger watches the function's source directory + `shared/`.

**Priority 2 — Everything else (low impact, rarely changes):**

Monitoring, alerting, and self-healing functions rarely change and are lower risk. These can stay manual deploy. If one is forgotten, the worst case is a monitoring gap — not a pipeline failure.

### How to Create a New Cloud Build Trigger

```bash
# Example for phase5-to-phase6-orchestrator:
gcloud builds triggers create github \
  --name="deploy-phase5-to-phase6-orchestrator" \
  --repo-name=nba-stats-scraper \
  --repo-owner=najicham \
  --branch-pattern="^main$" \
  --build-config=cloudbuild-functions.yaml \
  --included-files="orchestration/cloud_functions/phase5_to_phase6/**,shared/**" \
  --substitutions=_FUNCTION_NAME=phase5-to-phase6-orchestrator,_FUNCTION_SOURCE=orchestration/cloud_functions/phase5_to_phase6,_ENTRY_POINT=handle_phase5_completion,_TRIGGER_TOPIC=nba-phase5-predictions-complete \
  --region=us-west2 \
  --project=nba-props-platform
```

**Note:** The `cloudbuild-functions.yaml` template needs to support substitution variables (`_FUNCTION_NAME`, `_FUNCTION_SOURCE`, `_ENTRY_POINT`, `_TRIGGER_TOPIC`) for this to work generically. Check its current format before creating triggers.

---

## Background: Phase 4 Backfill Status

- PID 3453211 still running (processors 3-5, started Session 158)
- At date 54/96 (Dec 27, 2025) — ~56% complete after 5.5 hours
- Estimated ~4 more hours to completion
- Current contamination: 24.6% required-feature defaults (last 14 days)
- After backfill completes, contamination should drop significantly

## Files Changed

| File | Change |
|------|--------|
| `predictions/shared/batch_staging_writer.py` | `validate_output_schema()` + first-write validation |
| `predictions/worker/health_checks.py` | `check_output_schema()` in `/health/deep` |
| `predictions/coordinator/coordinator.py` | `/reset` endpoint + stall threshold reduction |
| `predictions/coordinator/batch_state_manager.py` | `max_batch_age_minutes` timeout |
| `bin/monitoring/pipeline_canary_queries.py` | Prediction gap canary check |
| `data_processors/precompute/base/precompute_base.py` | Dependency retry with backoff |
| `docs/08-projects/current/robustness-improvements/SESSION-159-PREVENTION-MECHANISMS.md` | **NEW** |
| `docs/08-projects/current/training-data-quality-prevention/00-PROJECT-OVERVIEW.md` | Updated |
| `docs/09-handoff/2026-02-08-SESSION-159-HANDOFF.md` | **NEW** |

## Next Session Priorities

### 1. Create Auto-Deploy Triggers for Orchestrators
Create 4 Cloud Build triggers for the pipeline orchestrators (phase2→3, phase3→4, phase4→5, phase5→6). See "Recommendation" section above. Check `cloudbuild-functions.yaml` format first.

### 2. Verify Backfill Completion
```bash
ps -p 3453211 -o pid,etime --no-headers 2>/dev/null || echo "Finished"
./bin/monitoring/check_training_data_quality.sh --recent
```

### 3. Start Past-Seasons Backfill (2021-2025)
After current-season backfill completes (~853 game dates, 7-9 hours).

### 4. Clean Up Orphaned Staging Tables
Many orphaned staging tables from Feb 4-5 batches:
```bash
python3 -c "
from predictions.shared.batch_staging_writer import BatchConsolidator
from google.cloud import bigquery
c = BatchConsolidator(bigquery.Client('nba-props-platform'), 'nba-props-platform')
result = c.cleanup_orphaned_staging_tables(max_age_hours=24, dry_run=True)
print(result)
"
```

### 5. Post-Deploy Verification
```bash
# Verify schema validation in /health/deep
curl -s "https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health/deep" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | python3 -m json.tool | grep output_schema

# Test /reset endpoint exists
curl -s "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

---
*Session 159 — Co-Authored-By: Claude Opus 4.6*
