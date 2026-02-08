# Session 165 Handoff — Fix Pub/Sub Retry Storm (Backfill Stalling)

**Date:** 2026-02-08
**Previous Session:** 164 (model governance hardening, backfill investigation prompts)

## What Was Accomplished

### 1. Root Cause: Pub/Sub Retry Storm (FIXED)

**Problem:** Manual backfills via `/start` created batches, but workers never processed them. Batch stalled at 0/N or 15/181 for minutes before timeout.

**Root Cause:** Worker returned HTTP 400 for malformed Pub/Sub messages (missing `player_lookup`, `game_id`). For Pub/Sub push subscriptions, **ANY non-2xx response triggers retry**. This created a cascading retry storm:

| Response Code | Count (24h pre-fix) | Cause |
|---|---|---|
| 204 (success) | 1,043 (31%) | Legitimate predictions |
| 500 (server error) | 1,213 (36%) | Worker overloaded by retries |
| 429 (rate limit) | 949 (28%) | Cloud Run throttling |
| 400 (bad request) | 179 (5%) | Malformed "poison" messages — root trigger |

A **3-day-old stuck message** kept retrying with exponential backoff, consuming worker capacity and blocking legitimate new messages.

**Fix (3 parts):**

1. **Worker code fix** (`predictions/worker/worker.py`): Return 204 (ACK) instead of 400 for permanent failures:
   - No Pub/Sub envelope (line 692)
   - No message field in envelope (line 698)
   - Missing required fields (line 716)
   - KeyError on field access (line 916)
   - Kept 500 returns for transient failures (BQ write, staging) that should legitimately retry

2. **Coordinator fix** (`predictions/coordinator/coordinator.py`):
   - Update `expected_players` in Firestore after quality gate filtering (was set to initial request count, not filtered count)
   - Mark batch complete immediately if 0 players published (prevents infinite stall)
   - New `update_expected_players()` method in `batch_state_manager.py`

3. **Infrastructure:**
   - Seeked `prediction-request-prod` subscription to current time (purged all stuck messages)
   - Set `min-instances=1` on prediction-worker (prevents cold start 503s on Pub/Sub push)

**Commit:** `2b35b9e8` — auto-deployed via Cloud Build

### 2. Subset Backfill (Feb 1-8)

Ran subset materialization for Feb 1-8:
- Feb 1-5: Existing or newly materialized
- Feb 6: 112 picks across 8 subsets
- Feb 7: 211 picks across 8 subsets
- Feb 8: 0 picks (no qualifying predictions for today's games)
- All exported to GCS API

### 3. Verification

- Worker health check passing (200)
- Pub/Sub push endpoint matches Cloud Run service URL
- No POISON_MESSAGE logs after fix (stuck messages purged)
- Manual backfill for Feb 7 processed end-to-end (camspencer — was OUT, correctly skipped)
- Both coordinator and worker deployed with commit `2b35b9e8`

## Key Lesson

**Pub/Sub Push = ONLY 2xx is success.** Any 4xx or 5xx response causes retries with exponential backoff. A single malformed "poison" message returning 400 creates an ever-growing retry storm that crowds out legitimate traffic. Always return 2xx for permanent failures in push subscription handlers.

## Current State

### Prediction Status (Feb 7-8)
| Date | Total | Active | Model Version |
|------|-------|--------|---------------|
| Feb 7 | 474 | 148 | v9_current_season |
| Feb 8 | 87 | 53 | v9_current_season |

### Deployment Status
- prediction-worker: `2b35b9e8`, min-instances=1
- prediction-coordinator: `2b35b9e8`
- Pub/Sub `prediction-request-prod`: clean (no stuck messages)

## Still Pending

### 1. Dynamic model_version Verification
All predictions still show `v9_current_season` instead of `v9_20260201_011018`. The dynamic versioning code was deployed but hasn't generated new predictions yet. Check after the Feb 9 morning run.

### 2. Model Governance Sync (from Session 164)
4 places describe model metadata and drift. See Session 164 handoff for proposed solutions.

### 3. Feature Mismatch Warnings
Worker logs show CatBoost V8 and breakout classifier feature mismatches:
- CatBoost V8: `teammate_injury_count` present in model but not in pool
- Breakout V1: `points_avg_season` present in model but not in pool
These fall back to PASS recommendations — not blocking, but degrading V8/breakout quality.

## Key Files Changed
- `predictions/worker/worker.py` — Return 204 for poison messages instead of 400
- `predictions/coordinator/coordinator.py` — Update expected_players after quality gate, mark empty batches complete
- `predictions/coordinator/batch_state_manager.py` — New `update_expected_players()` method
