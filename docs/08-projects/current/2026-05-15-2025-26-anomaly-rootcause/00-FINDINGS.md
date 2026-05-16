# 2025-26 NBA Anomaly — Root Cause Investigation

**Date:** 2026-05-15
**Status:** Investigation complete
**TL;DR:** The 2025-26 collapse was a **regime-shift + stale-models** failure, not a model bug. Scoring environment rose ~1 K per player between seasons; our fleet entered Nov 2025 carrying 2024-25 training data with no auto-retrain mechanism (weekly-retrain CF didn't ship until 2026-03-09). The model's chronic under-prediction bias (always present) became catastrophic when paired with Vegas's tightest MAE in 2 years.

## The numbers

### Raw model HR by season (all directions, all edges)

| Season | n_graded | HR all | HR edge3+ | HR edge5+ |
|---|---|---|---|---|
| 2021-2022 | 28,983 | 64.6% | 67.7% | 71.4% |
| 2022-2023 | 28,084 | 64.2% | 66.6% | 70.2% |
| 2023-2024 | 30,732 | 63.1% | 65.3% | 67.6% |
| 2024-2025 | 35,982 | 63.1% | 65.4% | 68.0% |
| **2025-2026** | **32,312** | **53.9%** | **57.8%** | **59.4%** |

10pp deficit at the raw model level, across all edges. Bigger absolute drop at edge 5+ (71→59) than at HR-all (64→54), confirming high-conviction picks degraded most.

### Monthly trajectory — story isn't "broken from day one"

| Month | n | HR all | model_mae | vegas_mae | mae_gap | avg_pred | avg_actual | pred_bias |
|---|---|---|---|---|---|---|---|---|
| 2024-11 | 3,392 | 67.4% | 4.49 | 5.00 | **-0.51** | 12.18 | 13.07 | -0.89 |
| 2024-12 | 5,683 | 64.1% | 4.74 | 4.77 | -0.03 | 11.18 | 12.36 | -1.18 |
| 2025-01 | 7,552 | 62.7% | 4.71 | 4.67 | +0.04 | 11.17 | 12.47 | -1.30 |
| 2025-02 | 5,539 | 61.5% | 5.00 | 4.68 | +0.32 | 10.67 | 12.39 | -1.71 |
| 2025-03 | 7,913 | 62.2% | 5.05 | 4.61 | +0.45 | 10.19 | 12.21 | -2.02 |
| 2025-04 | 4,969 | 61.5% | 5.15 | 4.67 | +0.48 | 10.18 | 12.03 | -1.84 |
| **2025-11** | **2,921** | **55.9%** | **5.42** | **4.33** | **+1.10** | **11.04** | **13.27** | **-2.23** |
| 2025-12 | 5,413 | 61.0% | 5.33 | 4.97 | +0.36 | 12.28 | 13.24 | -0.96 |
| 2026-01 | 10,998 | 52.9% | 5.06 | 4.71 | +0.36 | 12.74 | 13.42 | -0.68 |
| 2026-02 | 10,242 | 51.5% | 5.38 | 4.88 | +0.50 | 12.66 | 13.76 | -1.10 |

Three distinct phases:
1. **Nov 2025 — bias spike.** Model predicted players would score 11.0 K when actuals were 13.3 K (pred_bias -2.23, the worst month in the dataset). Vegas (line_bias -0.03) was perfectly calibrated. mae_gap +1.10 — model was 1.10 K worse than Vegas.
2. **Dec 2025 — partial recovery.** Catboost_v8 became the volume leader, hit 66.9% HR on 1,554 predictions. pred_bias improved to -0.96. Likely a manual retrain landed somewhere in late Nov / early Dec.
3. **Jan-Feb 2026 — full collapse.** Fleet expanded (7 → 12 → 51 models), volume doubled (5K → 11K/month). Every model fell to 49-55% HR simultaneously. pred_bias improved Dec → Jan (-0.96 → -0.68, the best of the season) then worsened back to -1.10 in Feb — never recovered to pre-Nov 2025 levels. The HR collapse despite improving bias suggests a second mechanism beyond regime drift: fleet diversity collapse + edge compression (consistent with MEMORY notes on LGBM clones).

### Per-model HR — Dec → Jan collapse is uniform

`catboost_v8` (static model, no retrain):
- Dec 2025: 66.9% HR (n=1,554)
- Jan 2026: 55.3% HR (n=2,546)
- Feb 2026: 47.8% HR (n=1,077)

Same code, same weights — HR dropped 19pp in 2 months. **The actuals/lines changed, not the model.** Every other model in the fleet shows the same pattern. This rules out a per-model bug.

## Root cause

### Primary: stale models entering a regime shift

The 2024-25 → 2025-26 transition shifted league scoring up by ~1 K per player:
- 2024-25 avg_actual: 12.0–12.5 K
- 2025-26 avg_actual: 13.2–13.8 K
- (March 2026 jumped further to 17.1 K, but n=2,372 is dominated by the halt-mode filter selecting only star players)

Vegas adjusted lines accordingly (avg_line tracked avg_actual within ±0.2 K every month). **Our model did not.** The Nov 2025 fleet (catboost_v8, ensemble_v1, moving_average_baseline_v1, similarity_balanced_v1, xgboost_v1, zone_matchup_v1) was carrying 2024-25 training data into a higher-scoring 2025-26 regime.

The model under-predicts chronically (pred_bias has been negative every month of the dataset), but the magnitude is amplified when actuals shift upward. Nov 2025 was the perfect storm.

### Secondary: Vegas got significantly sharper

vegas_mae dropped to its 2-year low in Nov 2025 (4.33). Throughout 2025-26 it ran 4.33–4.97, vs 4.67–5.15 for 2024-25. Even if our model had been correctly calibrated, beating Vegas would have been harder.

mae_gap (model_mae − vegas_mae) decomposition for Nov 2024 → Nov 2025:
- Nov 2024 gap: -0.51 (model better than Vegas by 0.51)
- Nov 2025 gap: +1.10 (model worse than Vegas by 1.10)
- Total swing: +1.61
  - ~0.93 from model degrading (4.49 → 5.42)
  - ~0.67 from Vegas tightening (5.00 → 4.33)
- **~58% of the deficit is model degradation; ~42% is Vegas market efficiency**

### Enabling cause: no auto-retrain in Oct-Nov 2025

Per the explore-agent report:
- `weekly-retrain` CF first deployed 2026-03-09 (commit `17d57a5b`)
- `monthly-retrain` CF was deprecated before that — no replacement
- No automated weekly refresh during Oct-Nov 2025 season start
- Fleet trained once at season start and went stale immediately

The November 2025 architecture work (predictions coordinator, Phase 5 split, orchestration migration) consumed the team's focus during the period when retrains should have been happening.

### Not a cause: feature drift

Feature store quality (`ml_feature_store_v2.default_feature_count`) by month shows:
- Nov 2025: avg_defaults 9.71 (elevated, but n=7,130 rows)
- Dec 2025+: avg_defaults 4.56–7.05 (normal range)

The Nov spike correlates with HR but isn't the dominant driver — Dec defaults returned to normal but HR collapse only intensified in Jan-Feb. V16 features (55, 56) didn't ship until Feb 27, 2026, so they're not implicated in the Nov-Jan collapse.

## What the MEMORY had wrong

> "2025-26 was uniquely broken from day one — Early season 55.9% vs historical 68-70%. Model quality issue, not seasonal dynamics."

Half right. The 55.9% in Nov is real, and stale model quality was the proximate cause. But **it WAS partly seasonal dynamics** — the scoring environment shifted up ~1 K. The model failed because it didn't adapt to the new regime, not because it was suddenly inferior in absolute terms.

> Hypotheses worth testing: feature drift early-season, fleet over-indexed on LGBM clones, training-window contamination, specific feature collapse.

None of these are the primary cause. The fleet wasn't LGBM clones in Nov 2025 (that came later). V16 features weren't even live. Training windows weren't contaminated by 2024-25 playoffs because there was no rolling retrain at all.

## Prevention for 2026-27

### Highest leverage

1. **Pre-season cold-boot retrain.** Add a one-shot retrain trigger that fires Oct 15, 2026 using preseason + first-week regular season data. Don't let the fleet enter October on April 2026 training data.

2. **Verify `weekly-retrain` fires from Oct 1, 2026.** The CF is deployed; confirm its cron is `0 10 * * 1` year-round (not limited to in-season months). The fleet needs to refresh weekly through the season-transition period.

3. **Bias monitoring with auto-alert.** Add `pred_bias_7d` to `model_performance_daily`. Alert to `#nba-betting-signals` if `|pred_bias_7d| > 1.5 K` for any model with N ≥ 20 picks in 7 days. The Nov 2025 fleet would have tripped this on Nov 7 (5 days into the season).

### Medium leverage

4. **mae_gap monitoring.** Alert if `model_mae_7d − vegas_mae_7d > 0.5 K` for 7 consecutive days. This is a generalization of the existing edge-based auto-halt and would catch the regime shift earlier.

5. **Daily calibration layer.** Bayesian shift correction: for each model, learn a bias correction from the last N=10 days of (predicted, actual) pairs and apply it post-prediction. Re-fit nightly. Won't fix variance, but neutralizes drift while waiting for retrains. ~1 day of work.

6. **Auto-disable threshold tightening.** Currently models auto-disable on HR < 52.4% in `decay-detection`. The 2025-26 collapse showed 8-15pp drops over 4 weeks; the decay state machine (HEALTHY→WATCH→DEGRADING→BLOCKED) caught this but slowly. Consider faster transitions if pred_bias trends are also negative.

### Already done (kept for completeness)

- **Edge-based auto-halt** (Session 515) — caught the Feb-Mar 2026 collapse. Currently active.
- **Late-season training cap** (Session 514) — prevents training on March data that contaminates April predictions.

## What this means for the rest of the season

NBA is halted (Apr 7 → June 3). No action needed on the fleet right now. But before June 3:
1. Run a pre-resumption retrain with data through June 2 (~3 weeks of summer league + playoff data).
2. Verify `weekly-retrain` will fire June 8 (first Monday after resumption).
3. Add pred_bias monitoring before predictions resume.

## Files referenced

- BQ source: `nba_predictions.prediction_accuracy` (raw HR, MAE, bias)
- BQ source: `nba_predictions.ml_feature_store_v2` (feature quality)
- Code: `orchestration/cloud_functions/weekly_retrain/main.py` (deployed 2026-03-09)
- Docs: `docs/08-projects/current/model-management/MONTHLY-RETRAINING.md`
- Session learnings: Sessions 454, 458, 487, 514, 515
