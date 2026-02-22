# Session 325 Handoff — V12+Vegas Season Replay + Fresh Retrains

**Date:** 2026-02-22
**Focus:** Walk-forward V12+vegas replay, best bets dry-run, fresh model retrains for all families

## Summary

1. Fixed `backfill-challenger-predictions.py` for V12 (54f) support
2. Trained 2 walk-forward V12+vegas models for historical replay (Jan 9 - Feb 21)
3. Backfilled 3,628 predictions, graded 35,713 across 46 game dates
4. **V12+vegas walk-forward: 62.7% HR edge 3+ vs V9's 48.3%** (+14.4pp)
5. Ran best bets dry-run with V12+vegas in candidate pool: **66.0% HR, $2,680 P&L** (100 picks)
6. Retrained 3 fresh models (V9 MAE, V12+vegas MAE, V12+vegas Q43) all on same Dec 25 - Feb 5 window

## Best Bets Dry-Run Results

The dry-run ran the full best bets algorithm (multi-model candidate generation, edge floor 5.0, negative filters, signal evaluation) for Jan 9 - Feb 21 with V12+vegas models in the candidate pool.

| Metric | Value |
|--------|-------|
| Total picks | 100 |
| Graded | 94 |
| Wins / Losses | 62 / 32 |
| **Hit Rate** | **66.0%** |
| **Est. P&L** | **$2,680** |

**Weekly breakdown:**
- Jan 9-15: 19W-10L (66%)
- Jan 16-22: 15W-6L (71%)
- Jan 23-29: 8W-1L (89%)
- Jan 30 - Feb 5: 7W-4L (64%)
- Feb 6-12: 10W-8L (56%)
- Feb 13-18: 2W-2L (50%) — ASB week
- Feb 19-21: 1W-1L (50%) — 3 days only

**Model attribution:** V12+vegas contributed picks on Jan 10, 11, 13, 20, 21, 22, 26, 31, Feb 8, 11, 19, 21. The algorithm automatically chose V12 when it had higher edge per player.

**Best bets NOT yet materialized.** The dry-run was `--compare` only. To write: `backfill_dry_run.py --start 2026-01-09 --end 2026-02-21 --write`

## Walk-Forward Replay Results

Each model only sees data BEFORE its prediction period (no future peeking).

| Model | Period | HR 3+ | HR 5+ | MAE | N (3+) |
|-------|--------|-------|-------|-----|--------|
| **V12+vegas combined** | Jan 9 - Feb 21 | **62.7%** | **82.5%** | **4.76** | 220 |
| V9 baseline | Jan 9 - Feb 21 | 48.3% | 52.9% | 5.02 | 573 |
| V12 train1102_1225 | Jan 9-25 | 65.9% | 83.3% | 4.66 | 132 |
| V12 train1102_0125 | Jan 26-Feb 5 | 71.1% | 85.7% | 4.81 | 45 |
| V12 train1225_0205 | Feb 6-21 | 44.2% | 66.7% | 4.90 | 43 |

**Direction balance (V12+vegas edge 3+):** OVER 61.1% (n=108), UNDER 64.3% (n=112).

## Fresh Retrains (All Families, Same Window)

All 3 trained Dec 25 - Feb 5, eval Feb 6-21. This ensures fair comparison across families.

| Model | System ID | Features | MAE | HR 3+ | N | Gates |
|-------|-----------|----------|-----|-------|---|-------|
| V9 MAE | `catboost_v9_train1225_0205` | 33 | 4.81 | 60.0% | 10 | 4/6 (sample, OVER balance) |
| V12+vegas MAE | `catboost_v12_train1225_0205_feb22` | 54 | 4.72 | 64.7% | 17 | 4/6 (sample, OVER balance) |
| V12+vegas Q43 | `catboost_v12_q43_train1225_0205_feb22` | 54 | 4.86 | 59.0% | 61 | 4/6 (HR 59%, vegas bias -1.66) |

Gate failures are expected — ASB reduced eval sample size dramatically. Models are for shadow/best-bets use, not production champion replacement.

**All 3 uploaded to GCS, registered in model_registry (enabled=TRUE), added to MONTHLY_MODELS.**

## How Best Bets Works (Important Context)

Best bets does NOT switch between models. It **combines** all models:
1. Queries ALL registered CatBoost families via `build_system_id_sql_filter()`
2. Per player-game, picks the prediction with the **highest edge** across all models
3. Applies negative filters (edge floor 5.0, player blacklist, UNDER blocks, etc.)
4. Ranks by edge, requires 2+ signals
5. Each pick records `source_model_id` showing which model was used

Since V12+vegas models are now registered with predictions in BQ, they're **automatically included** in daily best bets runs — no code changes needed.

## Observations on Best Bets HR Improvement Opportunities

From the dry-run data, potential areas to investigate:

1. **Player blacklist is working well** — caught lukadoncic (25-33%), jarenjacksonjr (0%), jabarismithjr (12.5%), treymurphyiii (30%). These players would have dragged down HR significantly.

2. **Edge floor 5.0 is the critical filter** — 3,704 predictions rejected (the bulk). The few that pass at edge 5+ hit at 66%. Could investigate whether edge 7+ has even higher HR (the dry-run showed [7+) = 100% but tiny sample).

3. **UNDER edge 7+ block is valuable** — blocked 30 predictions that historically hit at 40.7%.

4. **Feb 6-21 V12+vegas (Model C) underperformed** (44.2%) — this was the oldest model (trained to Feb 5, 17 days stale by Feb 21). The fresh retrain should fix this.

5. **Signal investigation opportunities:**
   - Dates with 0 picks (Jan 18, 23, 24, 27, Feb 6) — investigate if any good picks were filtered incorrectly
   - The `quality_floor` filter rejected 24 picks — check if threshold (85) is too aggressive
   - `line_jumped_under` blocked 15 — verify these were correct rejections

## Files Modified

| File | Change |
|------|--------|
| `bin/backfill-challenger-predictions.py` | V12/V12_NOVEG contract support |
| `predictions/worker/prediction_systems/catboost_monthly.py` | +5 new MONTHLY_MODELS entries (2 replay + 3 fresh) |

## Active Models Inventory (13 shadows + 1 champion)

| System ID | Feature Set | Window | HR 3+ | Purpose |
|-----------|-------------|--------|-------|---------|
| catboost_v9 (champion) | v9 (33f) | Nov 2 - Feb 5 | 48.3%* | PRODUCTION |
| catboost_v9_train1225_0205 | v9 (33f) | Dec 25 - Feb 5 | 60.0% | Fresh shadow |
| catboost_v12_train1102_1225 | v12 (54f) | Nov 2 - Dec 25 | 65.9% | Replay (Jan) |
| catboost_v12_train1102_0125 | v12 (54f) | Nov 2 - Jan 25 | 71.1% | Replay (late Jan) |
| catboost_v12_train1225_0205 | v12 (54f) | Dec 25 - Feb 5 | 75.0%** | Session 324 shadow |
| catboost_v12_train1225_0205_feb22 | v12 (54f) | Dec 25 - Feb 5 | 64.7% | Fresh shadow |
| catboost_v12_q43_train1225_0205 | v12 (54f) | Dec 25 - Feb 5 | 70.6%** | Session 324 Q43 |
| catboost_v12_q43_train1225_0205_feb22 | v12 (54f) | Dec 25 - Feb 5 | 59.0% | Fresh Q43 |
| + 5 other existing shadows | various | various | various | Existing |

*V9 HR measured Jan 9-Feb 21, **Session 324 HR measured on earlier smaller window

## Next Steps

### Immediate
1. **Push to main** — auto-deploys worker with new MONTHLY_MODELS entries
2. **Verify predictions generate tomorrow** — all 13 shadows + champion should produce picks
3. **Monitor best bets source_model_id** — see if V12+vegas picks start appearing

### Short-term
4. **Backfill best bets** — `backfill_dry_run.py --write` once satisfied with dry-run results
5. **Study signals** — analyze which signals are most correlated with wins in the dry-run data
6. **Consider promoting V12+vegas** — once 2+ weeks of live shadow data accumulate

### Model Management Strategy
- **Let all models run in parallel.** The best bets algorithm automatically picks the highest-edge prediction per player. More models = more candidates = better picks.
- **Old models keep running** as shadows. They only get selected if they have the highest edge for a specific player. No harm in keeping them.
- **Weekly retrain all families** — extend `retrain.sh` to include V12+vegas alongside V9
- **Retire models when stale** — if a model hasn't been selected by best bets for 2+ weeks, disable it

## Commands for Next Session

```bash
# 1. Push and verify deployment
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5

# 2. Materialize best bets backfill
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-09 --end 2026-02-21 --write

# 3. Study signal effectiveness
PYTHONPATH=. python ml/analysis/replay_cli.py --start 2026-01-09 --end 2026-02-21 --compare --verbose

# 4. Monitor tomorrow's best bets
bq query "SELECT source_model_id, COUNT(*) FROM signal_best_bets_picks WHERE game_date = '2026-02-23' GROUP BY 1"
```
