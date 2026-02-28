# Session 365 Handoff — Filter Improvements, Shadow Fleet Expansion, Strategic Direction

**Date:** 2026-02-28
**Previous:** Session 363 (infrastructure fixes), Session 364 (Firestore/auto-retry)

## What Session 365 Did

Addressed the Feb best bets collapse (70.3% Jan → 44.9% Feb) with three filter improvements and four new shadow models. Also fixed V15 feature bug and added V13/V15 model families.

### 1. Filter Improvements (Deployed)

**Model HR-Weighted Selection** (`supplemental_data.py`):
- Per-model 14-day rolling HR computed inline from `prediction_accuracy` (edge 3+)
- Applied as `effective_edge = ABS(edge) * min(1.0, hr_14d / 55.0)` in per-player ROW_NUMBER
- Models at 55%+ HR get full weight. V9 at 44% HR → 0.80x weight.
- New/unproven models (<10 graded picks) default to 50% HR → 0.91x weight.
- **Impact:** Better-performing shadow models now win per-player selection over stale/degraded ones.

**AWAY Block Expanded** (`aggregator.py`):
- v9 AWAY: 48.1% HR (N=449) vs 58.8% HOME — now blocked alongside v12_noveg (43.8% AWAY).
- Research showed v12_vegas (54.1% AWAY) and "other" models (53.0%) do NOT have significant gaps — correctly left unblocked.

**Multi-Model Blacklist** (`player_blacklist.py`):
- Default changed from `multi_model=False` to `multi_model=True`.
- Now aggregates HR across ALL models' edge 3+ predictions, not just champion.
- Players who can't beat the line on ANY model get blacklisted.

### 2. Shadow Fleet Expansion (4 New Models)

| Model | HR (edge 3+) | N | OVER | UNDER | Innovation |
|-------|-------------|---|------|-------|-----------|
| `catboost_v12_noveg_tw_vw025_train0109_0219` | **70.7%** | 41 | 90.9% | 63.3% | Tier-weighted (star=2.0, starter=1.2, role=0.8, bench=0.5) |
| `catboost_v15_noveg_vw025_train0109_0219` | **69.7%** | 33 | 100% | 61.5% | Player profile (ft_rate + starter_rate) |
| `catboost_v13_vw025_train0109_0219` | **65.8%** | 38 | 84.6% | 56.0% | 6 shooting efficiency features |
| `catboost_v12_noveg_60d_vw025_train1222_0219` | 60.9% | 23 | 70.0% | 53.8% | 60-day training window |

All registered with `enabled=TRUE`. Worker will generate predictions on next game day.

**Dead ends confirmed:** LightGBM+vw025 (54.9% HR, UNDER 50%), V16 Q55 (48.9% HR).

### 3. Bug Fixes

**V15 augment_v15_features crash** (`quick_retrain.py`):
- Was: `FEATURE_STORE_NAMES.index('ft_rate_season')` → ValueError (V15 features not in store)
- Fix: Write as named columns + fallback in `prepare_features()` for direct column names.

**V13/V15 model families** (`cross_model_subsets.py`):
- Added `v13_mae` and `v15_noveg_mae` patterns so Phase 6 exporter discovers their predictions.

### 4. Research Findings

| Finding | Data | Implication |
|---------|------|-------------|
| V9 generates LOWER edges than other models (4.43 vs 5.40 avg) | 3A query | Plan assumption was wrong — V9 doesn't inflate edges |
| Bench OVER: 60.7% HR (N=1274, profitable) | 3C query | Do NOT expand bench block to OVER |
| Bench UNDER: 51.9% HR (N=2397, below breakeven) | 3C query | Existing block is correct |
| v9 AWAY: 48.1% (N=449), v12_vegas AWAY: 54.1% (N=242) | HOME/AWAY query | Only v9 and v12_noveg have structural AWAY weakness |

---

## Strategic Direction — What's Next

### Key Question: What Are We Actually Measuring?

Our experiment eval (`quick_retrain.py`) measures **raw model HR** — the hit rate if we bet every edge 3+ prediction the model makes. But production best bets pass through **16 negative filters** in `BestBetsAggregator` that reshape which picks actually get published.

**The gap:**
- Experiment eval: Raw model, all edge 3+ picks → 60-75% HR
- Production best bets: Filtered, signal-gated, 5-8 picks/day → 45-70% HR
- Ultra bets (highest confidence): Extreme edge + multi-signal → 75-90% HR

A model with 75% raw HR might produce only 60% HR after filters strip out its best-performing segments. Or a model with 60% raw HR might produce 70% filtered HR because its edge 3+ picks happen to pass all filters cleanly.

**We should focus experiments on "does this model produce good high-confidence picks after filters?"** — not just overall HR.

### How to Test High-Confidence Picks

**Tool:** `bin/backfill_dry_run.py` runs the FULL production pipeline:
```bash
# After training, simulate what production picks would look like
python bin/backfill_dry_run.py --start 2026-02-20 --end 2026-02-27
```
This applies all 16 filters, signal evaluation, player blacklist, and shows:
- How many predictions survived filters (coverage)
- Which players were selected (the actual "best bets")
- Actual HR on those filtered picks
- Filter rejection breakdown (which filters killed the most picks)

**Gap to close:** Currently `backfill_dry_run.py` runs against already-published predictions. It doesn't let you swap in a NEW model and see "what would picks look like with Model X instead?" We'd need to extend it to accept a model_id parameter and query that model's predictions specifically.

### How Filters Work Today — and What We Don't Track

**16 filters in the aggregator, applied in order:**

| Filter | Direction? | What It Blocks | HR That Triggered It |
|--------|-----------|----------------|---------------------|
| Player blacklist | Both | <40% HR on 8+ picks | Data-driven |
| Edge floor (3.0) | Both | Low-conviction predictions | <57% |
| UNDER edge 7+ | UNDER only | V9 UNDER at extreme edge | 40.7% |
| Model-direction affinity | Both | Model+direction+edge combos | <45% |
| AWAY block | Both | v12_noveg/v9 on AWAY games | 43-48% |
| Feature quality floor | Both | quality < 85 | 24.0% |
| Bench UNDER | UNDER only | line < 12 | 35.1% |
| Star UNDER | UNDER only | season_avg >= 25 | 51.3% |
| Med usage UNDER | UNDER only | teammate_usage 15-30 | 32.0% |
| Starter V12 UNDER | UNDER only | 15-20 line range for V12 | 46.7% |
| Line jumped UNDER | UNDER only | prop_line_delta >= 2.0 | 38.2% |
| Line dropped UNDER | UNDER only | prop_line_delta <= -2.0 | 35.2% |
| Neg +/- streak UNDER | UNDER only | 3+ negative games | 13.1% |
| Signal count floor | Both | < 2 qualifying signals | — |
| Signal density | Both | Only base signals + edge < 7 | 57.1% |
| Anti-pattern combos | Both | Known bad signal combos | — |

**What we track:**
- `signal_best_bets_picks.filter_summary`: JSON with per-filter rejection counts per day
- `prediction_accuracy`: Raw prediction HR per model (OVER/UNDER separately)
- `system_daily_performance`: Over/under win rate per model per day
- `model_performance_daily`: Rolling 7/14/30d HR per model (overall only, NOT directional)

**What we DON'T track:**
- Per-filter HR verification ("is bench UNDER still 35%?")
- Post-filter directional HR per model ("V12 OVER after filters = ?%")
- Filter overlap (how many picks hit multiple filters)
- Whether filter thresholds are still correct (they were set months ago on different data)

### Should We Run Thousands of Feature Weight Experiments?

**Current infrastructure:**
- 9 feature categories, each could have 5-10 weight values
- Single experiment: ~15-20 min (BQ query + train + eval)
- No automated grid search for feature weights (only `--tune` for hyperparams)

**Feasibility matrix:**

| Approach | Experiments | Time | Feasible? |
|----------|------------|------|-----------|
| Single-parameter sweep (vegas weight) | 7-10 | 2-3h | Done (Session 359) |
| 2D grid (vegas × recency) | 16-24 | 5-8h | Yes |
| 3D grid (vegas × feature_set × quantile) | 36-48 | 12-16h | Yes (overnight) |
| Full exhaustive | 1B+ | Years | No |

**Recommendation: Phased, not exhaustive.** Session 359 showed that a 12-experiment systematic matrix (vegas weight sweep) yielded the breakthrough finding (0.25x optimal). We don't need thousands — we need **focused sweeps on the right dimensions**.

**High-value next sweeps:**
1. **Tier-weight sweep**: star=1.5-3.0, starter=0.8-1.5, bench=0.3-0.8 (12 combos, 3-4h)
2. **Recency × tier-weight**: Best tier weights + recency half-life 7-21d (8 combos, 2-3h)
3. **Feature set shootout**: V12/V13/V15/V16 all with same optimal weights (4 combos, 1h)

A wrapper script (`ml/experiments/grid_search_weights.py`) could automate these by generating combinations and collecting results.

### What We Should Build Next

**Priority 1: Post-filter evaluation in experiments**
- Extend `quick_retrain.py` or `backfill_dry_run.py` to answer: "Given this model's predictions, how many pass production filters and what's their HR?"
- This closes the gap between experiment eval and production performance.

**Priority 2: Filter health monitoring**
- Periodic audit: Is each filter's claimed HR still accurate?
- Track directional HR per model in `model_performance_daily` (currently only overall)
- Add filter-effectiveness report to `/validate-daily`

**Priority 3: Focused experiment grid**
- Build `grid_search_weights.py` for tier-weight and recency sweeps
- Run the tier-weight grid (most promising based on 2E results: 70.7% HR)
- Evaluate with `backfill_dry_run.py` for post-filter HR

**Priority 4: Smarter model selection in aggregator**
- Currently: highest HR-weighted edge wins per player
- Consider: track which model families produce the best post-filter picks
- Weight by post-filter HR, not raw HR

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | AWAY block expanded to v9, algorithm version bumped |
| `ml/signals/player_blacklist.py` | Multi-model default, `multi_model` parameter |
| `ml/signals/supplemental_data.py` | Model HR-weighted selection via inline CTE |
| `ml/experiments/quick_retrain.py` | V15 augment fix, prepare_features fallback |
| `shared/config/cross_model_subsets.py` | V13 + V15 model families added |
| `tests/unit/signals/test_aggregator.py` | V9 AWAY test updated |
| `tests/unit/signals/test_player_blacklist.py` | Multi-model test, version test |
| `CLAUDE.md` | Session 365 results, dead ends, filter updates |

## Shadow Fleet Status (18 + 1 production)

```
PRODUCTION: catboost_v9_33f_train20260106-20260205 (42% Feb HR — degrading)

SESSION 365 (NEW):
  catboost_v12_noveg_tw_vw025_train0109_0219  — 70.7% HR (tier-weighted)
  catboost_v15_noveg_vw025_train0109_0219     — 69.7% HR (player profile)
  catboost_v13_vw025_train0109_0219           — 65.8% HR (shooting features)
  catboost_v12_noveg_60d_vw025_train1222_0219 — 60.9% HR (60-day window)

PRIOR SHADOW:
  catboost_v12_train1201_0215                 — 75.0% HR (vegas=0.25, best backtest)
  catboost_v16_noveg_train1201_0215           — 70.8% HR (V16 deviation features)
  catboost_v16_noveg_rec14_train1201_0215     — 69.0% HR (V16 + recency)
  catboost_v12_noveg_q55_tw_train0105_0215    — 68.0% HR (Q55 + trend weights)
  lgbm_v12_noveg_train1102_0209               — 73.3% HR (LightGBM)
  lgbm_v12_noveg_train1201_0209               — 67.7% HR (LightGBM)
  + 8 more shadow models
```

## Verification Checklist

- [x] All unit tests pass (74/74)
- [x] Pre-commit hooks pass
- [x] All Cloud Build triggers succeeded
- [x] 4 new models uploaded to GCS and registered in `model_registry`
- [x] Deployment drift: builds queued/completing for latest push
- [ ] **Tomorrow:** Verify new shadow models generate predictions
- [ ] **Tomorrow:** Verify filter changes reduce V9 share in best bets
- [ ] **Tomorrow:** Verify AWAY picks eliminated for v9/v12_noveg
