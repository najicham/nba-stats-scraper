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

### Tier 3: Future Experiments (Feature Interactions & Combinations)

| # | Experiment | Features | Hypothesis | Prior Evidence | Expected Signal | Prerequisite |
|---|-----------|----------|-----------|----------------|-----------------|--------------|
| 6 | `pace_x_tracking_v1` | pace_ratio_tr * tracking_usage_pct, pace_ratio_tr * tracking_drives | Interaction: high-usage players in fast-paced games score more. | Neither interaction tested. Individual features may be wash but interaction could capture conditional effect. | **SKIP** — both pace and tracking are dead ends individually | Tier 1 results |
| 7 | `projection_x_sharp_v1` | projection_consensus_delta * sharp_money_divergence | When projections AND sharp money agree on direction, signal is stronger. | No prior. Both sources independent. | MEDIUM | Tier 2 data |
| 8 | `multi_source_v1` | Best features from Tier 1 + Tier 2 combined | Combined model with cherry-picked features from individual experiments. | No prior. Risk of overfitting to eval period. | MEDIUM (with overfitting risk) | Tier 1+2 results |

## Execution Protocol

For each experiment:

```bash
# 1. Backfill
PYTHONPATH=. python bin/backfill_experiment_features.py --experiment EXPERIMENT_ID

# 2. Verify data
bq query --use_legacy_sql=false "
SELECT feature_name, COUNT(*), AVG(feature_value), STDDEV(feature_value)
FROM nba_predictions.ml_feature_store_experiment
WHERE experiment_id = 'EXPERIMENT_ID'
GROUP BY 1"

# 3. Run 5-seed experiment
for seed in 42 123 456 789 999; do
  PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_${EXPERIMENT_ID}_s${seed}" \
    --feature-set v12_noveg \
    --experiment-features EXPERIMENT_ID \
    --train-days 56 \
    --random-seed $seed \
    --machine-output results/experiment_grid/${EXPERIMENT_ID}_s${seed}.json
done

# 4. Compare: aggregate 5-seed HR/MAE vs baseline
# Baseline: V12_noveg 5-seed from Session 407
```

## Baseline (V12_noveg 5-seed, Session 407)

| Metric | Value |
|--------|-------|
| HR (edge 3+) | ~65.9% (post-filter) |
| HR (unfiltered) | ~52.2% |
| MAE | ~5.3 |

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

## What's Already Dead (Don't Re-Test)

From `docs/06-reference/model-dead-ends.md`:
- TeamRankings pace features (team_pace_tr, opp_pace_tr, pace_ratio_tr) — Session 408, redundant with existing f7/f14/f22
- Static tracking stats as individual features (usg, ppg, pct_pts, fga) — Session 407
- V17 opponent_pace_mismatch — <1% importance
- Expected_scoring_possessions (pace * usage) — 62.8% vs 68.6% baseline
- Rolling_zscore_5v10 — <1% importance
- Percentile-transformed features — all 7 <2% importance, -2.76pp
- Scoring skewness as model feature — works better as filter
