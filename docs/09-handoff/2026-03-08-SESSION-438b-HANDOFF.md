# Session 438b Handoff — MLB Feature Backfill + Best Bets Strategy Overhaul

**Date:** 2026-03-08
**Focus:** MLB f15/f16/is_day_game backfill, walk-forward validation, best bets probability cap

## What Was Done

### 1. Feature Backfill (COMPLETE)
Backfilled 3 new pitcher_game_summary columns for the full historical period (2024-04-01 to 2025-09-28):
- **f15 opponent_team_k_rate**: Rolling 15-game team K rate (92-97% coverage)
- **f16 ballpark_k_factor**: Historical venue K/IP ratio (92-99% coverage)
- **is_day_game**: From mlb_schedule.day_night field (88-98% coverage)

Total: 10,057 rows updated. Ran via:
```
SPORT=mlb PYTHONPATH=. .venv/bin/python data_processors/analytics/mlb/pitcher_game_summary_processor.py \
  --start-date 2024-04-01 --end-date 2025-09-28
```

### 2. Walk-Forward with Real Data (NOISE)
Ran walk-forward with real f15/f16 + new f25_is_day_game feature:
- **Result: 57.58% HR at edge 1.0 (N=2235) vs 57.70% baseline** — no improvement
- Same lesson as NBA: adding features doesn't help. Rolling K avgs + vegas lines already capture what these features would add.
- Results saved: `results/mlb_walkforward_v3_with_f15f16/`

### 3. Best Bets Strategy Overhaul (KEY DELIVERABLE)
Deep analysis of the walk-forward prediction data revealed the model has an overconfidence problem. Picks where the model is >70% confident actually perform WORSE.

**Probability calibration discovery:**
| Prob Range | HR | N | Action |
|---|---|---|---|
| 0.60-0.65 | 60.2% | 550 | Keep |
| 0.65-0.70 | **64.4%** | 365 | **SWEET SPOT** |
| 0.70-0.75 | 58.7% | 230 | Block |
| 0.75-0.80 | 58.3% | 132 | Block |
| 0.80+ | **48.2%** | 110 | **Losing money** |

**Winning strategy (S7): Top-3 OVER, prob 0.60-0.70 only**
- 63.1% HR (N=696), +20.4% ROI
- **Zero losing months** across 13 months (Apr 2024 - Sep 2025)
- Cross-season: 62.6% (2024) vs 63.4% (2025)
- Bootstrap 95% CI: [59.5%, 66.7%]
- z=5.64 vs breakeven (p<0.000001)
- Sensitivity: robust across 9 prob windows (3.1pp range)

**Changes to `ml/signals/mlb/best_bets_exporter.py`:**

| Parameter | Before | After | Env Var |
|---|---|---|---|
| MAX_EDGE | 2.5 | **2.0** | `MLB_MAX_EDGE` |
| MAX_PROB_OVER | *none* | **0.70** | `MLB_MAX_PROB_OVER` |
| MAX_PICKS_PER_DAY | 2 | **3** | `MLB_MAX_PICKS_PER_DAY` |

New `probability_cap` filter added as step 1c (after edge cap, before negative filters). Blocks OVER picks where `p_over > 0.70`. Audit-logged. Algorithm version bumped to `mlb_v3`.

### 4. Infrastructure
- Created `docker/mlb-analytics-processor.Dockerfile` (was missing from repo — needed for MLB Phase 3 deploy)
- Fixed duplicate f15 column in walk-forward SQL
- Added f25_is_day_game to walk-forward feature list

## Changed Files (Uncommitted)

```
M  ml/signals/mlb/best_bets_exporter.py           # Prob cap + threshold changes
M  scripts/mlb/training/walk_forward_simulation.py # f25_is_day_game + dedup fix
?? docker/mlb-analytics-processor.Dockerfile       # New — MLB Phase 3 Dockerfile
?? results/mlb_walkforward_v3_with_f15f16/         # Walk-forward results
```

## What Needs To Be Done Next

### Before Mar 24 Season Start (Priority Order)

1. **Commit and push the changes** — auto-deploys NBA services; MLB worker/Phase 3 need manual deploy
2. **Deploy MLB Phase 3 analytics** — pitcher_game_summary processor with new f15/f16/is_day_game CTEs:
   ```bash
   ./bin/analytics/deploy/mlb/deploy_mlb_analytics.sh
   ```
   Last deployed: Jan 16. Dockerfile: `docker/mlb-analytics-processor.Dockerfile`
3. **Resume MLB scheduler jobs** (24 paused):
   ```bash
   ./bin/mlb-season-resume.sh
   ```
4. **E2E smoke test** after first game day (Mar 27+):
   - Verify pitcher_game_summary populates with real f15/f16/is_day_game
   - Verify best bets exporter applies prob cap (check filter audit for `probability_cap` entries)
   - Verify `algorithm_version` shows `mlb_v3_phase*_top3_prob0.7`

### Monitor After Launch

- **Probability cap audit**: `SELECT * FROM mlb_predictions.best_bets_filter_audit WHERE filter_name = 'probability_cap' AND game_date >= '2026-03-27'`
- **Pick quality**: Compare pre/post prob cap HR at edge 1.0+ after 2 weeks
- **Volume check**: Should see ~3 picks/day (up from 2) but only from prob 0.60-0.70 sweet spot
- If too few picks surface, can widen to 0.72-0.75 via `MLB_MAX_PROB_OVER` env var

### Data Notes

- `p_over` field is already in prediction dicts from `catboost_v1_predictor.py` (line 324) — no worker changes needed
- Probability cap handles `p_over=None` gracefully (passes through)
- All thresholds configurable via env vars without redeploy
- Walk-forward data at `results/mlb_walkforward_v3_with_f15f16/predictions_catboost_120d_fixed_edge1.0.csv` — 2,235 rows for further analysis

### Longer Term

- **No model retrain needed** — f15/f16 features are NOISE, model performance unchanged
- Consider raising `PHASE_2_EDGE_FLOOR` from 1.0 to 1.2 (walk-forward shows 1.0-1.2 = 57% vs 1.2-2.0 = 63%)
- UNDER stays disabled — only profitable pocket is prob 0.35-0.40 at 57.2% HR, not worth the complexity
- NBA side: P9 (z-score) and P10 (sanity check) are observation signals, promote after validation
