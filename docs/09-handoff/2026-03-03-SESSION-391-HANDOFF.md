# Session 391 Handoff — Legacy Model Selection Drain Fix

**Date:** 2026-03-03
**Status:** Fixes committed, pending push + auto-deploy

## Root Cause

Zero best bets on a 10-game slate (Mar 1-3). Legacy models (`catboost_v12`/`catboost_v9`) hardcoded in worker.py bypass the model registry. They won per-player selection for 77% of candidates (47/61) via `ROW_NUMBER() OVER(PARTITION BY player)` in `supplemental_data.py`, but were then blocked by `LEGACY_MODEL_BLOCKLIST` in the aggregator. Result: 0 picks.

**Why now?** All Session 383B models are new (Feb 28+). Legacy models had months of predictions, higher edge scores from stale training data, and won selection despite being unsuitable.

## Fixes Applied

### BigQuery (done, live)
- Added `catboost_v12` and `catboost_v9` to `model_registry` as `disabled`
- Fixed 18 models with inconsistent enabled/status combinations

### Code (committed, pending push)
1. **`ml/signals/supplemental_data.py`** — Defense-in-depth: disabled_models CTE now explicitly includes `['catboost_v12', 'catboost_v9']` via UNION DISTINCT
2. **`ml/signals/aggregator.py`** — Filter dominance WARNING when any filter rejects >50% of candidates
3. **`ml/signals/player_blacklist.py`** — Excludes disabled/blocked models from multi-model blacklist HR calculation (was inflating blacklist from 30→113 players)
4. **`predictions/worker/worker.py`** — `ENABLE_LEGACY_V9`/`ENABLE_LEGACY_V12` env vars (default false) gate legacy model loading. Saves ~200 wasted predictions/day.

### Monitoring (committed, pending push)
5. **`orchestration/cloud_functions/decay_detection/main.py`** — Consecutive best bets drought detection (escalates severity for 2+ zero-pick days)
6. **`data_processors/publishing/signal_best_bets_exporter.py`** — Filter audit trail to `nba_predictions.best_bets_filter_audit` (MERGE per game_date)
7. **`orchestration/cloud_functions/daily_health_check/main.py`** — Model registry consistency check (detects unregistered system_ids producing predictions)

## Deployment Path

The signal-best-bets export runs via `phase6-export` CF, NOT the prediction-coordinator. Code changes auto-deploy when pushed to main via `cloudbuild-functions.yaml`.

```bash
git push origin main    # Auto-deploys phase6-export CF + others
```

After push, trigger re-export:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "2026-03-03"}'
```

**Verify:** Blacklist should drop from 113 to ~30-50. Filter dominance warning should appear in logs.

## AWAY Block Assessment

Queried new fleet AWAY performance (Feb 20+):
- **v12_noveg: AWAY 48.0% (N=125) vs HOME 58.3% (N=108)** — block confirmed
- lgbm: AWAY 62.5% (N=16) vs HOME 64.3% (N=14) — no block needed
- v16_noveg: AWAY 75.0% (N=12) — too sparse (N<15)

**Decision:** Keep AWAY block as-is. Revisit v16_noveg when N≥15.

## Known State After This Session

- Worker legacy model prevention is code-only (not deployed). Will take effect on next worker deploy.
- `best_bets_filter_audit` BQ table created but empty — populates on next export run.
- Today (Mar 3) will still show 0 picks until push + auto-deploy completes.

## Follow-Up Items (Next Session)

1. **Verify post-deploy:** Check blacklist reduction and filter dominance warnings
2. **Fleet ramp-up:** Monitor which models reach N=50 governance gate first
3. **AWAY block v16:** Revisit when N≥15 AWAY picks accumulated (~5-7 days)
4. **Worker deploy:** When next deploying worker, legacy models auto-disabled via env vars
5. **Signal count coverage:** Only 4/55 edge 3+ picks had SC≥3 today — structurally limited
