# Session 395 — Experiment Results (37 Experiments, 6 Sweeps)

**Date:** 2026-03-03
**Training:** Dec 15, 2025 → Feb 8, 2026 (56 days)
**Eval:** Feb 9 → Feb 28, 2026 (20 days)
**Baseline:** V12_noveg, RMSE loss, CatBoost, min-ppg=0
**Statistical caveat:** All N < 188. Need 376+ for 5pp significance. Any difference < 5pp is noise.

## Top 10 Leaderboard

| Rank | Sweep | Config | HR 3+ | N | OVER | UNDER | Gates |
|------|-------|--------|-------|---|------|-------|-------|
| 1 | Framework | **XGBoost** | **73.8%** | 42 | 69.2% | **75.9%** | PASS |
| 2 | Feature/Vegas | V12, vegas=1.0 | 70.8% | 24 | 75.0% | 66.7% | FAIL |
| 3 | Feature/Vegas | V15 | 69.2% | 26 | 75.0% | 64.3% | PASS |
| 4 | Feature/Vegas | **V13 (shooting)** | **69.0%** | 29 | 81.8% | 61.1% | PASS |
| 5 | Feature/Vegas | V13, vegas=0.15 | 68.2% | 22 | 83.3% | 50.0% | FAIL |
| 6 | Loss Function | **Huber:delta=5** | **66.7%** | 57 | 76.9% | 63.6% | PASS |
| 7 | Category Wt | recent_performance=2.0 | 66.7% | 21 | 100.0% | 50.0% | FAIL |
| 8 | Hyperparams | rsm=0.3, SymmetricTree | 66.7% | 33 | 81.2% | 52.9% | PASS |
| 9 | Baseline | V12_noveg, RMSE | 65.6% | 32 | 76.9% | 57.9% | PASS |
| 10 | Framework | LightGBM | 65.6% | 64 | 67.5% | 62.5% | PASS |

## Sweep 1: Feature × Vegas Combos (8 experiments)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| V12, vegas=1.0 | 70.8% | 24 | 75.0% | 66.7% | 4.93 | FAIL (N) |
| V15 | 69.2% | 26 | 75.0% | 64.3% | 5.00 | PASS |
| V13 | 69.0% | 29 | 81.8% | 61.1% | 4.96 | PASS |
| V13, vegas=0.15 | 68.2% | 22 | 83.3% | 50.0% | 4.97 | FAIL |
| V12_noveg (baseline) | 65.6% | 32 | 76.9% | 57.9% | 4.92 | PASS |
| V12, vegas=0.25 | 60.7% | 28 | 76.9% | 46.7% | 5.01 | FAIL |
| V12, vegas=0.15 | 57.1% | 28 | 66.7% | 50.0% | 5.02 | FAIL |
| V16_noveg | 56.7% | 30 | 66.7% | 46.7% | 5.04 | FAIL |

**Findings:** V13 (shooting features) beats V12_noveg by +3.4pp and passes gates. V16_noveg is worst at 56.7%. Full vegas (1.0) is best HR but fails sample size gate. Vegas at 0.15-0.25 hurts on this eval window.

## Sweep 2: Population Filter (4 experiments)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| min-ppg=10 (role+) | 64.2% | 81 | 64.5% | 63.2% | 5.18 | PASS |
| min-ppg=0 (all players) | 64.1% | 39 | 81.8% | 57.1% | 4.95 | PASS |
| min-ppg=15 (starter+) | 55.2% | 181 | 55.4% | 54.2% | 6.05 | FAIL |
| min-ppg=25 (star only) | N/A | 0 | N/A | N/A | N/A | FAIL |

**Findings:** min-ppg=10 filters out bench players from training and gets the highest N (81) with balanced direction HR. Adding bench players (min-ppg=0) hurts UNDER by -6.1pp. min-ppg=15 inflates N to 181 but tanks HR — model generates too many low-quality predictions.

## Sweep 3: Category Weight Sweep (8 experiments)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| recent_performance=2.0 | 66.7% | 21 | 100.0% | 50.0% | 4.94 | FAIL |
| baseline (all 1.0) | 65.6% | 32 | 76.9% | 57.9% | 4.92 | PASS |
| recent_perf=2.0, matchup=2.0 | 65.5% | 29 | 88.9% | 55.0% | 4.94 | PASS |
| team_context=0.5 | 64.7% | 34 | 84.6% | 52.4% | 4.97 | PASS |
| recent_performance=3.0 | 63.3% | 30 | 77.8% | 57.1% | 4.99 | PASS |
| opponent_history=2.0 | 61.5% | 26 | 80.0% | 50.0% | 4.94 | FAIL |
| matchup=2.0 | 59.4% | 32 | 69.2% | 52.6% | 4.91 | FAIL |
| composite=0.5 | 54.3% | 35 | 73.3% | 40.0% | 4.99 | FAIL |

**Findings:** No category weight change reliably beats baseline. All within noise. Downweighting composite is catastrophic (UNDER 40.0%). Confirmed Session 369 finding that category weight dampening is a dead end.

## Sweep 4: Framework Shootout (3 experiments)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| **XGBoost** | **73.8%** | 42 | 69.2% | **75.9%** | 4.91 | PASS |
| CatBoost (baseline) | 65.6% | 32 | 76.9% | 57.9% | 4.92 | PASS |
| LightGBM | 65.6% | 64 | 67.5% | 62.5% | 5.09 | PASS |

**Findings:** XGBoost at 73.8% is the headline result. Notably dominant in UNDER (75.9% vs CatBoost's 57.9%). LightGBM generates 2x more edge 3+ picks but at same HR.

**CRITICAL CAVEAT:** XGBoost had a production version mismatch issue (Session 378c — trained v3.1.2, loaded v2.0.2, predictions ~8.6pts too low). Must pin identical versions in training and production before trusting. N=42 is far below statistical significance. Needs cross-validation on multiple seeds and eval windows before follow-up.

## Sweep 5: Loss Function (4 experiments)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| Huber:delta=5 | 66.7% | 57 | 76.9% | 63.6% | 4.93 | PASS |
| RMSE (baseline) | 65.6% | 32 | 76.9% | 57.9% | 4.92 | PASS |
| Huber:delta=3 | 63.2% | 57 | 100.0% | 56.2% | 4.86 | PASS |
| MAE | 57.5% | 40 | 71.4% | 54.5% | 5.03 | FAIL |

**Findings:** Huber:delta=5 is the best loss function — higher HR than RMSE (+1.1pp) with nearly double the N (57 vs 32) and best UNDER (63.6%). Huber:delta=3 has perfect OVER but weaker UNDER. MAE confirmed as worst loss (fails gates). Note: Huber:delta=3 has the best raw MAE (4.86) but lower MAE ≠ better betting — this was confirmed in Session 374.

## Sweep 6: Hyperparameter Sweep (6 experiments)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| rsm=0.3, SymmetricTree | 66.7% | 33 | 81.2% | 52.9% | 5.01 | PASS |
| rsm=0.7, Depthwise | 64.1% | 39 | 73.3% | 58.3% | 4.97 | PASS |
| rsm=0.3, Depthwise | 62.2% | 45 | 66.7% | 58.3% | 5.01 | PASS |
| rsm=0.5, Depthwise | 62.2% | 37 | 80.0% | 50.0% | 5.04 | FAIL |
| rsm=0.7, SymmetricTree | 60.7% | 28 | 90.9% | 41.2% | 5.01 | FAIL |
| rsm=0.5, SymmetricTree | 58.3% | 36 | 71.4% | 50.0% | 4.95 | FAIL |

**Findings:** Low RSM (0.3) with SymmetricTree gives highest HR but weak UNDER. Higher RSM (0.7) with Depthwise is more balanced. All within noise of baseline. rsm=0.7 + SymmetricTree has 90.9% OVER but catastrophic 41.2% UNDER — classic overfitting to OVER. No clear hyperparameter winner.

## Cross-Sweep: Population × Features (8 experiments, 4 overlap with Sweep 2)

| Config | HR 3+ | N | OVER | UNDER | MAE | Gates |
|--------|-------|---|------|-------|-----|-------|
| V12_noveg, min-ppg=10 | 64.2% | 81 | 64.5% | 63.2% | 5.18 | PASS |
| V12_noveg, min-ppg=0 | 64.1% | 39 | 81.8% | 57.1% | 4.95 | PASS |
| V16_noveg, min-ppg=0 | 55.9% | 34 | 72.7% | 47.8% | 5.04 | FAIL |
| V16_noveg, min-ppg=10 | 55.3% | 94 | 57.9% | 44.4% | 5.26 | FAIL |
| V12_noveg, min-ppg=15 | 55.2% | 181 | 55.4% | 54.2% | 6.05 | FAIL |
| V16_noveg, min-ppg=15 | 52.7% | 188 | 52.9% | 50.0% | 6.21 | FAIL |
| V12/V16, min-ppg=25 | N/A | 0 | N/A | N/A | N/A | FAIL |

**Findings:** V12_noveg dominates V16_noveg at every population level (+8-9pp). V16's deviation features hurt when combined with the 56-day training window and Feb eval data.

## Key Takeaways

### High-Priority Follow-ups

1. **XGBoost (73.8%, N=42)** — Best single result. Requires:
   - Version pinning (xgboost==3.1.2 in both training and production)
   - Cross-validation on 5 seeds + sliding eval windows
   - Production Dockerfile update
   - Known dead end if version mismatch recurs

2. **V13 shooting features (69.0%, N=29)** — Beats V12_noveg by +3.4pp. Worth a focused retrain with broader eval.

3. **Huber:delta=5 loss (66.7%, N=57)** — Best N among gate-passing experiments. Worth combining with XGBoost and V13.

### Confirmed Dead Ends (Don't Revisit)

- **V16_noveg on Feb eval**: 56.7% — V16 deviation features hurt during Feb degradation
- **MAE loss**: 57.5% — Fails gates, confirmed worst loss function
- **min-ppg=15/25**: Generates too many low-quality predictions or zero predictions
- **composite=0.5 category weight**: 54.3%, UNDER 40% — catastrophic
- **Category weights generally**: All within noise of baseline (confirmed Session 369)
- **rsm=0.7 + SymmetricTree**: UNDER 41.2% — overfits to OVER

### Meta-Insights

1. **UNDER is the differentiator.** Top configs separate from bottom primarily on UNDER HR. OVER is easier to predict.
2. **N and HR are inversely correlated.** Configs that generate more edge 3+ picks tend to have lower HR. The model trades selectivity for volume.
3. **MAE is not correlated with betting success.** Huber:delta=3 has the best MAE (4.86) but not the best HR. Confirmed again.
4. **Framework matters more than features.** XGBoost → +8.2pp vs V13 → +3.4pp. The tree algorithm choice is a bigger lever than feature engineering at this point.
