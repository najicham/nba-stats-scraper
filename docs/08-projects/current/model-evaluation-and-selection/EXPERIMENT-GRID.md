# Experiment Feature Grid

**Created:** Session 408 (Mar 5, 2026)
**Infrastructure:** `ml_feature_store_experiment` table + `bin/backfill_experiment_features.py` + `--experiment-features` flag

## Overview

All experiments use V12_noveg baseline (50 features), 56-day training, 5-seed evaluation.
Experiment features are injected at training time via the experiment table — zero production risk.

## Grid

### Tier 1: Run Now (Static Features — Full Historical Coverage)

| # | Experiment | Features | Hypothesis | Prior Evidence | Expected Signal |
|---|-----------|----------|-----------|----------------|-----------------|
| 1 | `pace_v1` | team_pace_tr, opp_pace_tr, pace_ratio_tr, opp_off_eff_tr, opp_def_eff_tr | TeamRankings pace/efficiency add context beyond existing team_pace/opp_pace features (which are from Phase 3 analytics). External source may capture different signal. | `predicted_pace_over` shadow signal fires. `fast_pace_over` production signal has 81.5% HR. V17 opponent_pace_mismatch was tested but as single-feature addition. | **DEAD END.** Pace-only: -3.4pp HR. Full (5 feat): +0.0pp same-seed, <1% importance. See Results. |
| 2 | `tracking_v1` | tracking_touches, tracking_drives, tracking_catch_shoot_pct, tracking_pull_up_pct, tracking_paint_touches, tracking_usage_pct | Different tracking features than Session 407 (which tested usg, ppg, pct_pts, fga). Touches/drives/paint_touches capture play style. | Session 407: usg/ppg/pct_pts/fga = WASH (+0.3pp). These are different features. But all are static (season-level). | LOW. Same static problem. Most values are 0.0 in current scrape. Likely WASH again. |

### Tier 2: Run After ~30 Days Accumulation (Daily-Varying Features)

| # | Experiment | Features | Hypothesis | Prior Evidence | Expected Signal | Ready Date |
|---|-----------|----------|-----------|----------------|-----------------|------------|
| 3 | `projections_v1` | projection_consensus_pts, projection_consensus_delta, projection_n_sources | External projections capture information the model misses. Delta (projection - line) is directional. | `projection_consensus` shadow signal is single-source (NumberFire only). Dimers data quality uncertain. No prior feature experiment. | **HIGH**. projection_delta is daily-varying, directional, and from an independent source. Best candidate. | ~Apr 5 |
| 4 | `sharp_money_v1` | sharp_money_divergence, over_ticket_pct, over_money_pct | Sharp vs public money divergence predicts outcomes. Money% - ticket% captures where sharps disagree with public. | `sharp_money_over/under` shadow signal exists but NOT FIRING. VSiN data is game-level (total O/U), not player-level. | **MEDIUM**. Game-level feature applied to all players in same game. Signal may be diluted. But sharp money is proven concept in sports betting. | ~Apr 5 |
| 5 | `dvp_v1` | dvp_points_rank_norm, dvp_points_allowed | Opponent defense vs position is a classic DFS feature. Weak defense = more points opportunity. | `dvp_favorable_over` shadow signal exists, status unknown. No prior feature experiment. Feature is semi-static (ranks change slowly). | **MEDIUM**. Classic feature. But DVP ranks change slowly — may be near-static in practice. Points_allowed has more variance. | ~Apr 5 |

### Tier 3: Derived Features (Computed from Existing Data — Full Season)

| # | Experiment | Features | Hypothesis | Result |
|---|-----------|----------|-----------|--------|
| 6 | `derived_v1` | pts_std_last_5, pts_std_last_10, form_ratio, over_rate_weighted | Player volatility and momentum signals | **NOISE** (+4.2pp, N=14) |
| 7 | `interactions_v1` | fatigue*minutes, pace*usage, rest*b2b, spread*home | Cross-feature interaction terms | **DEAD_END** (+0.5pp) |
| 8 | `line_history_v1` | line_vs_avg, opening_vs_current, line_range | Line-derived CLV proxy features | **DEAD_END** (-3.5pp) |
| 9 | `derived_all` | All 11 derived+interaction+line features | Combined derived features | **DEAD_END** (-0.6pp) |
| 10 | `kitchen_sink` | All 22 experiment features | Everything combined | **NOISE** (+3.2pp, N=12) |

### Tier 4: Future Experiments (Pending Data Accumulation)

| # | Experiment | Features | Hypothesis | Ready Date |
|---|-----------|----------|-----------|------------|
| 11 | `projections_v1` | projection_consensus_pts/delta, n_sources | External projections — best remaining candidate | ~Apr 5 |
| 12 | `sharp_money_v1` | sharp_money_divergence, ticket/money pct | Sharp vs public money | ~Apr 5 |
| 13 | `projection_x_sharp_v1` | projection_delta * sharp_divergence | When independent sources agree | ~Apr 5 |

## Execution Protocol

**Preferred: Use experiment harness** (automates baseline + multi-seed + z-test + verdict):

```bash
# 1. Backfill
PYTHONPATH=. python bin/backfill_experiment_features.py --experiment EXPERIMENT_ID

# 2. Run harness (baseline + experiment, 5 seeds each, auto-verdict)
PYTHONPATH=. python ml/experiments/experiment_harness.py \
    --name EXPERIMENT_ID \
    --experiment-features EXPERIMENT_ID \
    --hypothesis "Why we are testing this" \
    --persist  # writes to BQ experiment_grid_results

# Combo experiment (comma-separated IDs):
PYTHONPATH=. python ml/experiments/experiment_harness.py \
    --name derived_all \
    --experiment-features "derived_v1,interactions_v1,line_history_v1" \
    --hypothesis "All derived combined" --persist
```

## Baseline (V12_noveg, auto-generated per harness run)

Harness runs fresh baseline with same eval window for fair comparison.
Typical baseline: HR(3+) ~76% (small eval N), MAE ~5.40.

## Results

### Experiment 1: `pace_v1` (pace-only, no efficiency) — Session 408

**Date:** Mar 5, 2026 | **Features:** team_pace_tr, opp_pace_tr, pace_ratio_tr (3 of 5; efficiency NULL due to scraper bug)
**Eval window:** Feb 25 - Mar 3, 2026 | **Training:** 56 days (Dec 31 - Feb 24)

| Seed | HR(all) | HR(3+) | N(3+) | MAE |
|------|---------|--------|-------|-----|
| 42 | 56.9% | 72.7% | 11 | 5.404 |
| 123 | 60.7% | 73.3% | 15 | 5.354 |
| 456 | 55.9% | 86.7% | 15 | 5.371 |
| 789 | 64.2% | 78.6% | 14 | 5.282 |
| 999 | 60.6% | 62.5% | 16 | 5.483 |
| **AVG** | **59.6%** | **74.8%** | **14.2** | **5.379** |

**Same-seed baseline (seed 42, same eval window):**

| | Baseline (50f) | PACE_V1 (53f) | Delta |
|--|----------------|---------------|-------|
| HR(all) | 60.3% | 56.9% | **-3.4pp** |
| HR(3+) | 90.9% | 72.7% | **-18.2pp** |
| MAE | 5.379 | 5.404 | **+0.025** |

**Feature importance:** Pace features (team_pace_tr, opp_pace_tr, pace_ratio_tr) not in top 10 in any seed. Model ignores them — redundant with existing team_pace (f22) and opponent_pace (f14).

**Verdict: DEAD END (pace-only).** Adding TeamRankings pace features to V12_noveg adds noise. Expected: model already has 4 pace features from Phase 3 analytics. TeamRankings seasonal averages are highly correlated with rolling 10-game Phase 3 values.

### Experiment 1b: `pace_v1` full (5 features incl. efficiency) — Session 408

**Date:** Mar 5, 2026 | **Features:** all 5 (team_pace_tr, opp_pace_tr, pace_ratio_tr, opp_off_eff_tr, opp_def_eff_tr)
**Eval window:** Feb 25 - Mar 3, 2026 | **Training:** 56 days

| Seed | HR(all) | HR(3+) | N(3+) | MAE |
|------|---------|--------|-------|-----|
| 42 | 56.5% | 90.9% | 11 | 5.472 |
| 123 | 61.3% | 69.2% | 13 | 5.470 |
| 456 | 58.7% | 90.9% | 11 | 5.440 |
| 789 | 58.6% | 76.9% | 13 | 5.392 |
| 999 | 57.8% | 70.6% | 17 | 5.445 |
| **AVG** | **58.6%** | **79.7%** | **13.0** | **5.444** |

**Same-seed (s42) vs baseline:** HR(3+) 90.9% → 90.9% (+0.0pp), HR(all) -3.8pp, MAE +0.09.

**Efficiency features (opp_off_eff_tr, opp_def_eff_tr):** Not in top 10 importance in any seed. Adding efficiency to pace-only: +5.0pp HR(3+) avg, but stdev=10.6% with N≈13 — noise, not signal.

**Verdict: DEAD END (full pace_v1).** All 5 TeamRankings features are noise. Both pace (redundant with f7/f14/f22) and efficiency (seasonal averages, static) fail to add signal. Skip Tier 3 `pace_x_tracking_v1` experiment.

### Session 409: Full Grid Results (Experiment Harness, 5-seed)

**Date:** Mar 5, 2026 | **Harness:** `ml/experiments/experiment_harness.py`
**Baseline:** V12_noveg, 56d training | **Eval:** Auto (last 7 days)
**Schema fix:** Recreated table from WIDE to LONG format. Fixed derived_v1 data leakage (window included CURRENT ROW).

| # | Experiment | Features | Delta HR(3+) | N(3+) | Delta MAE | z-score | Verdict |
|---|-----------|----------|-------------|-------|-----------|---------|---------|
| 1 | `tracking_v1` | 6 tracking stats | **-1.3pp** | 13 | +0.012 | -0.08 | DEAD_END |
| 2 | `pace_v1` | 5 pace/efficiency | **+8.2pp** | 12 | -0.014 | +0.52 | NOISE (N too small) |
| 3 | `interactions_v1` | 4 cross-feature products | **+0.5pp** | 12 | +0.022 | +0.03 | DEAD_END |
| 4 | `line_history_v1` | 3 line-derived features | **-3.5pp** | 12 | +0.022 | -0.20 | DEAD_END |
| 5 | `derived_v1` | 4 volatility/form | **+4.2pp** | 14 | -0.049 | +0.27 | NOISE (N too small) |
| 6 | `derived_all` | derived+interactions+line (11 features) | **-0.6pp** | 13 | +0.046 | -0.04 | DEAD_END |
| 7 | `kitchen_sink` | All 22 experiment features | **+3.2pp** | 12 | +0.022 | +0.19 | NOISE (N too small) |

**Key findings:**
- **No experiment reached significance** — all N(3+) are 9-18 per seed (too small for p<0.05)
- **derived_v1 is most promising** (+4.2pp HR, -0.05 MAE) but needs more data
- **Combining features hurts** — derived_all worse than derived_v1 alone (curse of dimensionality)
- **Kitchen sink** = slight positive (+3.2pp) but MAE worse — model confused by noise features
- **V12_noveg remains best** — consistent with prior findings (adding features hurts)

**BQ table:** `nba_predictions.experiment_grid_results` — all results persisted with `--persist`

### Session 410: Feature Exclusion + Training Window + RSM Experiments

**Date:** Mar 4, 2026 | **Harness:** Fixed (extra_args only apply to experiment runs, not baseline)
**Baseline:** V12_noveg, 56d training | **Eval:** 14 days (doubled from 7 — harness fix)
**N(3+):** 25-46 per seed (up from 12-18) — much better statistical power

| # | Experiment | Change | Delta HR(3+) | N(3+) avg | Delta MAE | Verdict |
|---|-----------|--------|-------------|-----------|-----------|---------|
| 1 | `exclude_noise_v2` | Remove playoff_game, breakout_flag, injury_risk, games_since_structural_change | **-1.2pp** | 32 | +0.006 | DEAD_END |
| 2 | `exclude_shot_zones_v2` | Remove pct_paint, pct_mid_range, pct_three, pct_free_throw | **+1.4pp** | 35 | +0.002 | NOISE |
| 3 | `window_63d_v2` | 63-day training window (vs 56d) | **+0.1pp** | 31 | -0.010 | DEAD_END |
| 4 | `window_70d_v2` | 70-day training window (vs 56d) | **+1.4pp** | 28 | -0.005 | NOISE |
| 5 | `rsm03_v2` | RSM 0.3 (subsample 30% features per split) | **-3.8pp** | 38 | +0.030 | DEAD_END |

**Key findings:**
- **CatBoost self-optimizes feature selection** — removing "noise" features either hurts or makes no difference
- **RSM 0.3 is harmful** (-3.8pp) — random subsampling removes features the model needs
- **56d remains sweet spot** — 63d identical, 70d is slight noise-level positive
- **Shot zone exclusion closest to signal** (+1.4pp) but not actionable at noise level
- **Harness bug found & fixed:** Prior runs (Session 409) applied extra_args to both baseline and experiment, producing +0.0pp. Fixed: baseline_train_days separate from experiment train_days; extra_args only for experiment runs.

## Decision Criteria

- **Promote to signal:** HR improvement >= 2pp at edge 3+ across 5 seeds, N >= 50
- **Promote to production feature:** HR improvement >= 3pp, confirmed across 2+ eval windows
- **Dead end:** < 1pp improvement or negative = add to model-dead-ends.md
- **Noise zone:** 1-2pp improvement = need more data, don't act

## Known Constraints

1. **All scraper data starts Mar 4, 2026** — only 1 day exists
2. **Static features** (tracking, pace) can be replicated across history but don't capture daily variance
3. **Daily features** (projections, sharp money, DVP) need ~30 days to accumulate
4. **player_lookup format mismatch**: Scraper tables use `jalen-johnson`, feature store uses `jalenjohnson`. Backfill script handles normalization.
5. **Tracking data quality**: touches, drives, paint_touches mostly 0.0. Only usage_pct has real values.
6. **VSiN is game-level**: sharp money splits are per-game total (not player-level). Applied uniformly to all players in a game.
7. **Dimers projections questionable**: May be generic, not game-date-specific (Session 407 finding)
8. **Data leakage risk in derived features**: Window functions MUST use `1 PRECEDING` not `CURRENT ROW` to exclude target game. Initial derived_v1 showed +21.6pp (fake) before fix.

## What's Already Dead (Don't Re-Test)

From `docs/06-reference/model-dead-ends.md` + Session 409:
- TeamRankings pace features (team_pace_tr, opp_pace_tr, pace_ratio_tr) — Session 408, redundant with existing f7/f14/f22
- Static tracking stats — Session 407 (usg/ppg/pct_pts/fga) + Session 409 (touches/drives/paint_touches/catch_shoot/pull_up/usage). Mostly 0.0 values.
- Cross-feature interaction terms (fatigue*minutes, pace*usage, rest*b2b, spread*home) — Session 409, DEAD_END
- Line-derived features (line_vs_avg, opening_vs_current, line_range) — Session 409, DEAD_END (-3.5pp)
- Combined derived features (11 features) — Session 409, DEAD_END. Curse of dimensionality.
- Feature exclusion (playoff_game, breakout_flag, injury_risk, structural_change) — Session 410, -1.2pp. CatBoost already ignores them.
- Feature exclusion (shot zones: pct_paint/mid_range/three/free_throw) — Session 410, +1.4pp NOISE
- RSM 0.3 (random subspace 30%) — Session 410, -3.8pp DEAD_END. Removes needed features.
- Training window 63d — Session 410, +0.1pp DEAD_END. Identical to 56d.
- Training window 70d — Session 410, +1.4pp NOISE. 56d confirmed as sweet spot.
- V17 opponent_pace_mismatch — <1% importance
- Expected_scoring_possessions (pace * usage) — 62.8% vs 68.6% baseline
- Rolling_zscore_5v10 — <1% importance
- Percentile-transformed features — all 7 <2% importance, -2.76pp
- Scoring skewness as model feature — works better as filter
