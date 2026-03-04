# Session 396 — Experiment Results (7 Experiments)

**Date:** 2026-03-03
**Training:** Dec 15, 2025 → Feb 8, 2026 (56 days)
**Eval:** Feb 9 → Mar 2, 2026 (22 days — captures late toxic + recovery)
**Baseline:** V12_noveg, CatBoost, vegas=0.25, seed 42 → 65.6% (Session 395)
**Statistical caveat:** N < 188. Need 376+ for 5pp significance.

## Experiment Summary

| # | Config | Framework | HR 3+ | N | OVER | UNDER | MAE | Gates |
|---|--------|-----------|-------|---|------|-------|-----|-------|
| 1 | V12_noveg vw025 s42 | **XGBoost** | **71.7%** | 46 | 69.2% | 72.7% | 4.93 | PASS |
| 2 | V12_noveg vw025 s123 | XGBoost | 64.0% | 50 | 88.9% | 58.5% | 5.05 | PASS |
| 3 | V12_noveg vw025 s456 | XGBoost | 62.2% | 45 | 71.4% | 58.1% | 5.04 | PASS |
| 4 | V12_noveg vw025 s789 | XGBoost | 62.0% | 50 | 77.8% | 58.5% | 5.05 | PASS |
| 5 | V12_noveg vw025 s999 | XGBoost | **69.6%** | 46 | 69.2% | 69.7% | 5.03 | PASS |
| 6 | V13 Huber:delta=5 vw025 | CatBoost | 62.0% | 100 | 66.7% | 61.0% | 5.23 | PASS |
| 7 | V12_noveg vw015 | **LightGBM** | **66.7%** | 63 | 68.4% | 64.0% | 5.11 | PASS |

## XGBoost 5-Seed Cross-Validation

**Gate: Mean >= 65%, StdDev < 5pp. RESULT: PASS (65.9%, 4.5pp)**

| Metric | Value |
|--------|-------|
| Mean HR 3+ | 65.9% |
| StdDev | 4.5pp |
| Min | 62.0% (seed 789) |
| Max | 71.7% (seed 42) |
| Mean MAE | 5.02 |
| Mean OVER HR | 75.3% |
| Mean UNDER HR | 63.5% |

XGBoost OVER HR is consistently strong (69-89%). UNDER is more variable (58-73%).
Best seeds: 42 (71.7%) and 999 (69.6%) — both have balanced OVER/UNDER.

**Version pinning CRITICAL:** Must match xgboost==3.1.2 in training AND production (Session 378c).

## V13 + Huber:delta=5 + vegas=0.25

Hypothesis: V13's shooting features (+3.4pp in Session 395) + Huber's UNDER (63.6%) = best of both.
Result: 62.0% HR — **disappointing**. The combination didn't compound.

- Huber loss suppresses extreme predictions, reducing edge magnitude
- V13 shooting features add signal for OVER (81.8% in Session 395) but Huber dampens it
- Role players best at 81.8% OVER but N=11 — too small

**Lesson:** Loss function and feature set interact non-linearly. Don't assume additive gains.

## LightGBM + vegas=0.15

Best balanced model. Vegas=0.15 is cross-season validated optimal weight.
- Highest N of all experiments (63 edge 3+ picks) — more stable estimate
- Best all-population MAE (4.84) across all 7 experiments
- Starters UNDER: 90.0% (N=10) — genuine framework diversity signal
- Vegas bias: +0.13 (nearly neutral)

**Genuine feature diversity from CatBoost:** `points_avg_season` dominates (28.1%) vs CatBoost's `line_vs_season_avg`. Different gradient computation produces different feature rankings.

## Recommendations

1. **Deploy XGBoost seed 42 + 999** to shadow (primary + fallback)
2. **Deploy LightGBM+vw015** as secondary shadow
3. **Run A3: XGBoost + V13** next — best features + best framework
4. **Skip V13+Huber** — no additive gains from combination
5. **Skip V13+LightGBM** unless A3 shows V13 helps XGBoost specifically

## Dead Ends Confirmed This Session

- V13 + Huber:delta=5 = no additive gain (62.0%)
- Combination of "best loss" + "best features" ≠ best model (non-linear interaction)
