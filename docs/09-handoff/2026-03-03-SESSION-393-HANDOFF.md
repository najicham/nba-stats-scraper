# Session 393 Handoff — Blacklist Fix + Model Evaluation Deep Dive

**Date:** 2026-03-03
**Status:** Critical fixes deployed, documentation complete, V16 retrain pending

## What Was Done

### 1. Blacklist Fix (DEPLOYED — commit d8c393f8)

**Root cause:** `player_blacklist.py` used LEFT JOIN to exclude disabled models from registry, but 14 unregistered legacy models (ensemble_v1, catboost_v8, moving_average_baseline_v1, zone_matchup_v1, similarity_balanced_v1, etc.) had no registry entry — they bypassed the filter entirely. Blacklist was 113 players (should be 0).

**Fix:** Changed to INNER JOIN with enabled models. Only predictions from registered + enabled models count toward player HR. Verified with BQ query: 0 players blacklisted.

### 2. Zombie Model Gating (DEPLOYED — same commit)

**Root cause:** `worker.py` loaded `MovingAverageBaseline` and `ZoneMatchupV1` unconditionally. Session 391 added `ENABLE_LEGACY_V9`/`ENABLE_LEGACY_V12` gating but missed these two.

**Fix:** Added `ENABLE_LEGACY_MOVING_AVG` and `ENABLE_LEGACY_ZONE_MATCHUP` env vars (default false). Null checks added at prediction time.

### 3. Export Pipeline Verified

- Session 392's BQ correlated subquery fix confirmed working (no more errors)
- Re-export triggered for 2026-03-03
- Result: 0 best bets picks (legitimate — 16 candidates, all blocked by data-backed filters: 6 away_noveg, 4 over_edge_floor, 2 line_jumped_under, 2 signal_count, 2 star_under)
- Blacklist correctly 0 (was 113)

### 4. Model Evaluation Deep Dive (DOCUMENTATION)

Created `docs/08-projects/current/model-evaluation-and-selection/` with 7 documents:
- Full pipeline documentation, Session 393 data findings, 7 blind spots, 12 research questions, shadow monitoring design, experiment infrastructure assessment, and a prompt for the next investigation session.

Key findings: Edge is #1 predictor (7+: 81.3% HR), signal count #2 (SC=4+: 76.1%), confidence score useless (all 9.999), only 6 of 16 models ever source best bets picks, V16 (66.7% HR) never wins selection due to lower edges.

### 5. Signal & LightGBM Status

- `fast_pace_over`: Started firing Mar 2 (2 fires). Too new for signal_health_daily.
- `self_creation_over`: Not firing — conditions legitimately narrow.
- LightGBM: 2/3 already disabled/blocked. Newest (train0103_0227) has 1 graded pick — keep monitoring.

## Remaining: V16 Retrain

**V16 is the best-performing family** (66.7% HR) but is 6 days stale (trained through Feb 15). Needs fresh 56-day window retrain.

### Retrain Prompt for Next Session

```
Retrain V16 on a fresh 56-day window. V16 is our best-performing family at 66.7% HR.

Current production V16 models:
- catboost_v16_noveg_train1201_0215 (66.7% HR, 12 edge 3+ picks)
- catboost_v16_noveg_rec14_train1201_0215 (66.7% HR, 15 edge 3+ picks)

Run these retrains using /model-experiment or quick_retrain.py:

1. V16 noveg, 56-day window ending ~Mar 1:
   python bin/quick_retrain.py --feature-set v16_noveg --no-vegas \
     --train-start 2026-01-05 --train-end 2026-03-01 \
     --eval-start 2026-03-01 --eval-end 2026-03-03

2. V16 noveg rec14 (14-day recency weighting), same window:
   python bin/quick_retrain.py --feature-set v16_noveg --no-vegas \
     --train-start 2026-01-05 --train-end 2026-03-01 \
     --eval-start 2026-03-01 --eval-end 2026-03-03 \
     --recency-half-life 14

3. V12 noveg with vegas weight 0.25 (our other top config):
   python bin/quick_retrain.py --feature-set v12 --category-weight vegas=0.25 \
     --train-start 2026-01-05 --train-end 2026-03-01 \
     --eval-start 2026-03-01 --eval-end 2026-03-03

If governance gates pass, register the models. Do NOT promote to production
without reviewing results. Check edge 3+ HR, OVER/UNDER split, and MAE.

After registering, verify with: ./bin/model-registry.sh validate
```

Also consider the model evaluation investigation: `docs/08-projects/current/model-evaluation-and-selection/PROMPT.md` has a full research agenda for understanding how to better evaluate and select models.

## Deployment Status

All builds succeeded. `./bin/check-deployment-drift.sh` shows only `validation-runner` stale (non-critical). All key services at commit d8c393f8.
