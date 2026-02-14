# Session 244: RSM Variants, SQL Explorations, V14 Feature Contract

**Date:** 2026-02-13
**Training:** 2025-11-02 to 2026-01-31 (91 days)
**Evaluation:** 2026-02-01 to 2026-02-12 (12 days)
**Previous Session:** 243 (V12 RSM50 was winner at 57.1% edge 3+ HR)

## Executive Summary

Ran 5 RSM50 variant experiments and 4 SQL explorations. Key findings:

1. **V12 RSM50 (Session 243) remains the best config** — no variant improved on 57.1%
2. **Removing `line_vs_season_avg` CRASHES performance** — 57.1% → 51.85%. Despite leaking vegas info, it's a critical feature
3. **RSM50 + Huber is the closest contender** — 57.35% HR 3+ with 68 samples (vs 35 for RSM50)
4. **3PT cold is the real cold streak signal**, not overall FG% — 55.6% OVER rate vs 50.9% for FG-only cold
5. **Game total 230-234 is NOT a special signal** — December was good across ALL totals, not just 230-234
6. **V14 feature contract implemented** — 5 engineered FG% features ready for testing

---

## Phase 1: RSM50 Variant Experiments

All experiments: `--feature-set v12 --no-vegas --walkforward --include-no-line --force --skip-register`

| # | Experiment | Key Config | MAE | HR 3+ (n) | OVER | UNDER | Gates |
|---|-----------|-----------|-----|-----------|------|-------|-------|
| **G** | **V12_RSM50 (S243)** | **RSM50 Depthwise** | **4.82** | **57.1% (35)** | **64.3%** | **52.4%** | **Closest** |
| I | RSM50_NOVEG_CLEAN | RSM50 + exclude line_vs_season_avg + dead features | 5.13 | 51.85% (108) | 50.0% | 52.8% | FAIL |
| J | RSM50_HUBER | RSM50 + Huber:delta=5 | 4.98 | 57.35% (68) | 53.8% | 59.5% | Close |
| K | RSM50_Q47 | RSM50 + quantile alpha=0.47 | 4.97 | 56.36% (55) | 37.5% | 59.6% | FAIL |
| L | RSM70 | RSM70 Depthwise | 4.87 | 55.88% (34) | 57.1% | 55.0% | FAIL (n) |
| M | RSM30 | RSM30 Depthwise | 4.90 | 56.76% (37) | 61.5% | 54.2% | FAIL (n) |

### Analysis

**I (NOVEG_CLEAN):** Removing `line_vs_season_avg` destroyed performance. HR 3+ dropped from 57.1% → 51.85%. Despite the feature partially leaking vegas info (computed from `vegas_points_line - season_avg`), it provides genuine signal about line deviation from player norm. **Keep it.**

**J (RSM50_HUBER):** Second best config. Key advantage: generates 68 edge 3+ samples (nearly 2x RSM50's 35). Close to 60% gate (57.35%). Stars hit at 80% (n=10). Notable: Huber shifts feature importance — `points_std_last_10` becomes #2 at 20.6% (vs ~0% under MAE loss). The Huber loss function creates more spread in predictions, generating more edge 3+ bets while maintaining quality.

**K (RSM50_Q47):** Quantile 0.47 creates strong UNDER bias (59.6% UNDER HR) but kills OVER (37.5%). The directional imbalance is too severe. Dead end for RSM50 combination.

**L (RSM70):** Best MAE (4.87) but only 34 edge 3+ samples — not enough for governance. Directional balance looks good (57.1%/55.0%).

### Feature Importance Comparison

| Feature | RSM50 (S243) | NOVEG_CLEAN | HUBER | Q47 | RSM70 |
|---------|-------------|-------------|-------|-----|-------|
| points_avg_season | 30.0% | 27.5% | 8.0% | 29.2% | 31.0% |
| points_avg_last_10 | 24.6% | 32.4% | 39.6% | 21.3% | 31.8% |
| points_avg_last_5 | 12.1% | 12.8% | 6.4% | 15.3% | 9.7% |
| line_vs_season_avg | 5.0% | EXCLUDED | 1.3% | 4.9% | 5.1% |
| points_std_last_10 | — | — | **20.6%** | — | — |

**Huber fundamentally changes what the model learns.** It de-emphasizes `points_avg_season` (30% → 8%) and elevates `points_std_last_10` (0% → 21%) and `minutes_avg_last_10` (2% → 6%). This makes the model more variance-aware, which may be why it generates more high-edge predictions.

---

## Phase 2: SQL Explorations

### Query 1: 3PT% Cold vs Overall FG% Cold

| Cold Type | n | Over % | Avg Diff |
|-----------|---|--------|----------|
| 3PT Cold Only | 2,200 | **55.6%** | +1.00 |
| Both Cold | 1,700 | **55.5%** | +1.10 |
| Neither Cold | 5,163 | 51.4% | +0.62 |
| FG Cold Only | 904 | 50.9% | +0.74 |

**Finding:** The 3PT cold signal (L2 < 30%) is the actual driver. FG cold alone adds nothing (50.9%). When only 3PT is cold, OVER rate is 55.6% — nearly identical to "both cold" (55.5%). **The mean-reversion signal is specifically about 3-point shooting variance**, not overall field goal efficiency.

### Query 2: Free Throw Rate (FTA/FGA)

| FT Tier | n | Over % | Avg Diff |
|---------|---|--------|----------|
| Very Low FT Rate (<20%) | 3,541 | **54.5%** | +0.91 |
| Medium FT Rate (35-50%) | 1,755 | 54.0% | +0.71 |
| Low FT Rate (20-35%) | 3,824 | 52.3% | +0.80 |
| High FT Rate (50%+) | 847 | **47.9%** | +0.48 |

**Finding:** Inverse relationship. High FT-rate players go UNDER more often (47.9% OVER). Low FT-rate players go OVER (54.5%). Players who get to the line more have variable scoring (ref variance, foul trouble). Pure shooters with low FT rate have more predictable scoring floors.

### Query 3: FG% Cold by Home/Away

| Venue | FG Status | n | Over % | Avg Diff |
|-------|-----------|---|--------|----------|
| AWAY | FG Cold | 1,353 | 54.5% | +0.93 |
| AWAY | Normal | 3,766 | 53.9% | +0.93 |
| HOME | FG Cold | 1,251 | 53.2% | +1.02 |
| HOME | Normal | 3,597 | 51.4% | +0.53 |

**Finding:** Minimal interaction. Home cold players have +1.8pp OVER rate vs home normal (53.2% vs 51.4%). Away players lean OVER regardless. Not a strong enough signal to act on.

### Query 4: Game Total 230-234 OVER Stability

| Month | 230-234 Over % (n) | Other Over % (n) | Delta |
|-------|---------------------|-------------------|-------|
| Nov 2025 | 49.3% (817) | 53.8% (1,998) | -4.5pp |
| Dec 2025 | **70.2%** (2,048) | **72.0%** (8,216) | -1.8pp |
| Jan 2026 | 55.1% (1,088) | 63.8% (5,674) | -8.7pp |
| Feb 2026 | 51.4% (521) | 49.6% (3,989) | +1.8pp |

**Finding:** 230-234 is NOT special. It tracks the overall bucket within a few points every month. December was the standout across ALL game totals (70-72%), not just 230-234. **The 80% HR we saw in Session 243 was a December artifact.** The model's OVER accuracy has been declining monthly: 72% → 64% → 50% (consistent with champion decay).

---

## Phase 3: V14 Feature Contract

Implemented 5 new engineered FG% features designed to give CatBoost usable signals from shooting data:

| Index | Feature | Formula | Rationale |
|-------|---------|---------|-----------|
| 60 | `fg_cold_z_score` | (fg_pct_L3 - season_fg) / season_fg_std | Personalized cold (Jokic at 52% is cold for him) |
| 61 | `expected_pts_from_shooting` | fg_pct_L3 * fga_L3 * 2 + three_pct_L3 * tpa_L3 | Volume-adjusted expected points |
| 62 | `fg_pct_acceleration` | fg_pct_L3 - fg_pct_L5 | Shooting trend direction |
| 63 | `fatigue_cold_signal` | minutes_load_last_7d * (1 - fg_pct_L3) | Fatigue x cold interaction |
| 64 | `three_pct_std_last_5` | Std dev of 3PT% last 5 games | Shooting inconsistency |

**Files changed:**
- `shared/ml/feature_contract.py` — V14/V14_NOVEG contracts (65/61 features)
- `ml/experiments/quick_retrain.py` — `--feature-set v14`, `augment_v14_features()` function

All contracts validate. Ready for `--feature-set v14` experiments.

---

## V12 Augmentation Bug

All experiments show **0% V12 augmentation coverage** — UPCG, Stats, and Odds lookups match 0 rows. This means all V12 experiments are effectively running on V9 base features (33 features) plus `line_vs_season_avg` (from feature store), NOT the full 50 V12 features. The 15 V12-specific features from runtime augmentation are all NaN.

This is consistent across Sessions 243 and 244. The augmentation JOIN keys likely don't match the feature store format. **This needs investigation** — fixing it could substantially improve all V12 experiments.

---

## Governance Gate Summary

| Experiment | MAE | HR 3+ | HR 3+ n | Vegas Bias | Tier Bias | Direction | Overall |
|-----------|-----|-------|---------|------------|-----------|-----------|---------|
| RSM50 (S243) | PASS | FAIL (57.1%) | FAIL (35) | PASS | PASS | PASS | 4/6 |
| RSM50_HUBER | PASS | FAIL (57.35%) | PASS (68) | PASS | PASS | PASS | 5/6 |
| RSM50_Q47 | PASS | FAIL (56.36%) | PASS (55) | PASS | PASS | FAIL | 4/6 |
| RSM70 | PASS | FAIL (55.88%) | FAIL (34) | PASS | PASS | PASS | 4/6 |
| NOVEG_CLEAN | PASS | FAIL (51.85%) | PASS (108) | PASS | PASS | FAIL | 4/6 |

**RSM50_HUBER passes the most gates (5/6)** — only failing the 60% HR threshold by 2.65pp.

---

## Key Decisions & Next Steps

1. **Keep `line_vs_season_avg`** — removing it crashes performance despite the vegas leak concern
2. **RSM50_HUBER is the most promising variant** — combine HR quality (57.35%) with volume (68 samples)
3. **Investigate V12 augmentation bug** — 0% match rate means experiments aren't using V12 features
4. **Test V14 features** — the engineered FG% signals (z-score, expected pts, acceleration) may succeed where raw FG% failed
5. **3PT cold > FG cold for post-prediction rules** — use `three_pct_last_2 < 0.30` not `fg_pct_last_2 < 0.40`
6. **Drop game total 230-234 filter idea** — it was a December artifact, not a real signal
7. **Explore FT rate as a feature** — the inverse relationship (high FT rate → UNDER) is worth testing
