# Zombie Model Decommissioning — Session 343

**Date:** 2026-02-25
**Status:** Implemented, pending deploy

---

## Problem

Session 342 identified **20 zombie/disabled models** actively producing predictions but not managed by the model registry. These:
- Wasted compute (20 extra prediction calls per player per line)
- Polluted cross-model scoring (highest-edge zombie could source a losing best bet)
- Made monitoring noisy (19 system_ids instead of 6)

## Root Cause

Two sources of zombie models:

### 1. Hardcoded Systems in `worker.py`
Four legacy systems baked into the prediction loop with no enable/disable mechanism:
- `similarity_balanced_v1` — 0 best bets picks in 30 days
- `xgboost_v1` (writes as `catboost_v8`) — 0 best bets picks in 30 days
- `ensemble_v1` — 0 best bets picks in 30 days
- `ensemble_v1_1` — 0 best bets picks in 30 days

### 2. MONTHLY_MODELS Dict Fallback in `catboost_monthly.py`
The `get_enabled_monthly_models()` function loads registry models first, then also loads dict models NOT already in the registry. The dict had **12 models with `enabled: True`** while only 1 overlapped with the 6 registry models. This loaded 11 extra stale models.

## Investigation

### Best Bets Pick Sourcing (30 days)

| System ID | Picks | Graded | Won | Status |
|-----------|-------|--------|-----|--------|
| `catboost_v9` (champion alias) | 36 | 0 | — | KEEP |
| `catboost_v12` (V12 alias) | 6 | 2 | 1W/1L | KEEP |
| `catboost_v9_low_vegas_train0106_0205` | 3 | 1 | 1W | KEEP (registry) |
| `catboost_v12_train1102_0125` | 4 | 0 | — | DISABLED |
| `catboost_v12_noveg_q45_train1102_0125` | 2 | 1 | 1W | DISABLED |
| `catboost_v12_noveg_train1102_0205` | 1 | 1 | 1W | DISABLED |
| `catboost_v12_train1225_0205` | 1 | 0 | — | DISABLED |
| `catboost_v9_q43_train1102_0125` | 1 | 0 | — | DISABLED |
| All other zombies (15 models) | 0 | 0 | — | DISABLED |

**Decision:** 9 picks in 30 days from stale models (2 graded, both correct) doesn't justify keeping them. Newer registry models (trained through Feb 15) will fill the gap.

## Changes Made

### `predictions/worker/worker.py`
- **Removed** 4 hardcoded systems from `get_prediction_systems()`: similarity, xgboost/v8, ensemble_v1, ensemble_v1_1
- **Removed** prediction loop blocks (Systems 3, 4, 6, 7)
- **Removed** metadata format blocks for removed systems
- **Updated** health check, callers, global variables
- **Kept**: moving_average, zone_matchup, catboost_v9 (champion), monthly models, catboost_v12

### `predictions/worker/prediction_systems/catboost_monthly.py`
- Set `enabled: False` for all 12 MONTHLY_MODELS dict entries except `catboost_v9_low_vegas_train0106_0205` (which is deduplicated with registry anyway)
- Added `# DISABLED Session 343` comments with reason for each

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| System IDs per prediction | ~20 | ~8 (3 hardcoded + ~5 registry + V12) |
| Predictions per player per line | ~20 | ~8 |
| Compute per prediction batch | 100% | ~40% |
| Best bets accuracy | Unchanged — zombies contributed <2% of picks |

## Also Fixed This Session

- **signal-health.json / model-health.json**: Stale since Feb 22. Added `signal-health` and `model-health` to Cloud Scheduler `phase6-daily-results` export_types. Manually triggered catch-up export.

## Rollback

If predictions break after deploy:
1. Revert the worker.py changes (re-add hardcoded systems)
2. Set `enabled: True` in catboost_monthly.py dict entries
3. Redeploy: `./bin/deploy-service.sh prediction-worker`
