# Session 159: Prevention Mechanisms for Schema/Timing Failures

**Date:** 2026-02-08
**Context:** Feb 7-8 predictions broken by schema mismatch + cascade failures
**Status:** Implemented, pending deploy

## Problem Statement

Three failure modes caused predictions to be broken for 24+ hours:

1. **Schema mismatch** - Worker code added `vegas_line_source` and `required_default_count` fields but BQ table didn't have matching columns. 100% write failure.
2. **Coordinator stuck batches** - Workers failed, coordinator stayed in "running" state for 4+ hours blocking new runs.
3. **Phase 4 cascade failure** - Phase 3 timing caused PlayerDailyCacheProcessor to fail, cascading to CompositeFactors, FeatureStore, and Predictions.
4. **No prediction gap alerting** - Zero predictions for Feb 7 (10 games) with no alert.

## Solutions Implemented

### 1. Worker Startup Schema Validation

**Files:** `predictions/shared/batch_staging_writer.py`, `predictions/worker/health_checks.py`

- Added `validate_output_schema()` method to `BatchStagingWriter`
- On first `write_to_staging()` call, compares prediction record keys against BQ table columns
- If mismatch found: logs CRITICAL error, returns failure immediately (fail-fast)
- Added `check_output_schema()` to health check suite (`/health/deep`)
- Checks 14 critical fields that have caused production issues

**Detection time:** First prediction attempt (~seconds after deploy) vs previous hours of cryptic errors.

### 2. Coordinator Batch Timeout + /reset Endpoint

**Files:** `predictions/coordinator/coordinator.py`, `predictions/coordinator/batch_state_manager.py`

- **Absolute batch timeout (30 min):** `check_and_complete_stalled_batch()` now has `max_batch_age_minutes` param. Batches running > 30 min are force-completed regardless of completion percentage.
- **Stall detection reduced:** `/start` endpoint stall threshold reduced from 600s (10 min) to 300s (5 min).
- **New `/reset` endpoint:** Force-resets any stuck batch. Clears both Firestore and in-memory tracker. Accepts `batch_id` or `game_date`.

**Impact:** Max time a stuck batch blocks new predictions: 30 min (was 4+ hours).

### 3. Prediction Gap Alerting

**File:** `bin/monitoring/pipeline_canary_queries.py`

- New "Phase 5 - Prediction Gap" canary check
- Cross-references `nba_reference.nba_schedule` (games today) with `player_prop_predictions` (predictions today)
- FAIL if `games_today > 0 AND prediction_count = 0`
- Alerts to `#canary-alerts` via existing canary infrastructure (runs every 30 min)

### 4. Phase 4 Cascade Fix (Retry with Backoff)

**File:** `data_processors/precompute/base/precompute_base.py`

- When critical dependencies are missing (Phase 3 not done), retry up to 3 times with linear backoff (60s, 120s, 180s) before failing
- Only applies to non-backfill mode (backfill skips dependency checks)
- Configurable via `dependency_retries` and `dependency_retry_base_seconds` opts
- Prevents DailyCache -> CompositeFactors -> FeatureStore -> Predictions cascade failure

**Impact:** Handles Phase 3 taking up to 6 extra minutes without failing Phase 4.

## Testing Notes

- Schema validation: Will catch mismatches on first write attempt
- Batch timeout: Testable via `/check-stalled` with `max_batch_age_minutes` param
- Prediction gap: Testable via `python bin/monitoring/pipeline_canary_queries.py`
- Retry logic: Will log retry attempts; verify with Phase 4 processor logs

## Deployment

Push to main triggers auto-deploy for all affected services:
- `prediction-worker` (schema validation + health check)
- `prediction-coordinator` (/reset endpoint + batch timeout)
- `nba-phase4-precompute-processors` (retry logic)
- Canary queries: Runs as scheduled job (no deploy needed)
