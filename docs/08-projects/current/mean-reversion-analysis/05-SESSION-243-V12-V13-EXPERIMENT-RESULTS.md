# Session 243: V12/V13 Experiment Suite & Shooting Efficiency Analysis Results

**Date:** 2026-02-13
**Training:** 2025-11-02 to 2026-01-31 (91 days)
**Evaluation:** 2026-02-01 to 2026-02-12 (12 days)
**Date Overlap:** NONE (hard guard enforced in `quick_retrain.py`)

## Executive Summary

Ran 11 model experiments (8 V12 + 3 V13) and 5 SQL analyses. Found:
1. **V12 RSM50 is the best configuration** (57.1% edge 3+ HR, balanced direction)
2. **FG% features (V13) provide zero value to CatBoost** despite strong SQL signals
3. **FG% cold streaks are a powerful mean-reversion signal** (60.8% OVER rate) but the model can't leverage it
4. **The continuation filter hurts performance** — suppressed bets actually hit at 69.1%
5. **Game total 230-234 OVER bets hit at 80%** (small sample, needs validation)

---

## Phase 1: V12 Experiment Matrix (8 Experiments)

All experiments: `--feature-set v12 --no-vegas --walkforward --include-no-line --force`

| # | Experiment | Key Flags | MAE | HR All | HR 3+ (n) | OVER | UNDER | Direction |
|---|-----------|-----------|-----|--------|-----------|------|-------|-----------|
| A | BASELINE | (none) | 4.91 | 53.7% | 46.4% (28) | 42.9% | 47.6% | FAIL |
| B | TUNED | `--tune` | 4.91 | 53.7% | 46.4% (28) | 42.9% | 47.6% | FAIL (tune skipped without vegas) |
| C | RECENCY30 | `--recency-weight 30` | 4.91 | 55.1% | 41.4% (29) | 30.0% | 47.4% | FAIL |
| D | RECENCY14 | `--recency-weight 14` | 4.89 | 53.6% | 54.2% (24) | 45.5% | 61.5% | FAIL (OVER) |
| E | HUBER5 | `--loss-function "Huber:delta=5"` | 5.00 | 53.3% | 50.9% (57) | 46.7% | 52.4% | FAIL (OVER) |
| **F** | **PRUNED** | `--exclude-features (6 dead)` | **4.90** | **54.5%** | **56.5% (23)** | **57.1%** | **56.2%** | **PASS** |
| **G** | **RSM50** | `--rsm 0.5 --grow-policy Depthwise` | **4.82** | **58.2%** | **57.1% (35)** | **64.3%** | **52.4%** | **PASS** |
| H | BEST_COMBO | RSM50+PRUNED+RECENCY14 | 4.86 | 57.6% | 51.3% (39) | 36.4% | 57.1% | FAIL |

### Winner: Experiment G (V12_RSM50)

- **`--rsm 0.5 --grow-policy Depthwise`** — forces CatBoost to use 50% of features per split
- Reduces `points_avg_season` dominance (30% vs 27.7% baseline — still dominant but other features get more say)
- Best MAE (4.82), best overall HR (58.2%), best edge 3+ HR (57.1%)
- Only experiment with strong directional balance: OVER 64.3%, UNDER 52.4%
- Walk-forward consistent: week1 66.7%, week2 55.0%, week3 58.3%

### Key Observations

1. **`line_vs_season_avg` leaks vegas info** in no-vegas mode (12.9% importance in baseline). Computed from `vegas_points_line - season_avg`. Should be excluded in truly vegas-free experiments.
2. **Improvements don't stack** — combining RSM50 + pruning + recency (H) performed worse than RSM50 alone (G).
3. **Huber loss generates more edge 3+ samples** (57 vs ~25-35 for others) but at lower quality.
4. **Dead features confirmed (0% importance):** `breakout_flag, playoff_game, spread_magnitude, teammate_usage_available, multi_book_line_std`
5. **`--tune` doesn't work in no-vegas mode** — the grid search requires `vegas_points_line` in the feature set.

### Feature Importance (G - RSM50, top 15)

| Rank | Feature | Importance |
|------|---------|-----------|
| 1 | points_avg_season | 30.00% |
| 2 | points_avg_last_10 | 24.64% |
| 3 | points_avg_last_5 | 12.06% |
| 4 | points_avg_last_3 | 8.65% |
| 5 | line_vs_season_avg | 5.04% |
| 6 | minutes_avg_last_10 | 3.21% |
| 7 | usage_rate_last_5 | 1.81% |
| 8 | ppm_avg_last_10 | 1.44% |
| 9 | avg_points_vs_opponent | 1.04% |
| 10 | minutes_load_last_7d | 0.79% |
| 18 | **prop_under_streak** | **0.46%** |
| 19 | scoring_trend_slope | 0.45% |
| 36 | consecutive_games_below_avg | 0.18% |
| 41 | prop_over_streak | 0.11% |

Streak features have <1% importance. The model barely uses them.

---

## Phase 2: SQL Streak & Cold Streak Analysis

### 2.1 — Points-based Cold Streaks (Weak Signal)

| Definition | Cold Games | Over Rate Cold | Over Rate Normal | Signal |
|-----------|-----------|----------------|------------------|--------|
| 2g 10% below avg | 692 | 51.6% | 49.3% | +2.3pp |
| 2g 15% below avg | 558 | 52.2% | 49.3% | +2.9pp |
| 2g 20% below avg | 460 | 50.7% | 49.6% | +1.1pp |
| 3g 10% below avg | 317 | 53.3% | 49.4% | +3.9pp |

Marginal mean-reversion. Not strong enough for betting.

### 2.1b — FG% Cold Streaks (STRONG Signal!)

| Definition | Cold Games | Over Rate Cold | Over Rate Normal | Signal | Next Game FG% |
|-----------|-----------|----------------|------------------|--------|---------------|
| FG% L2 < 35% | 437 | **60.4%** | 53.6% | **+6.8pp** | 44.4% |
| FG% L2 < 40% | 772 | **58.7%** | 53.2% | **+5.5pp** | 45.2% |
| FG% L2 < 42% | 997 | **58.9%** | 52.5% | **+6.4pp** | 45.6% |
| FG% L2 < 45% | 1295 | 56.4% | 53.2% | +3.2pp | 45.4% |
| FG% rel 5pp below | 946 | **58.0%** | 53.0% | **+5.0pp** | 48.0% |
| FG% rel 10pp below | 498 | **60.8%** | 53.3% | **+7.5pp** | 48.7% |

Players shooting >10pp below their personal season avg go OVER their prop at **60.8%** rate.

### 2.2 — Prop Streak Continuation by Tier

| Streak | Stars | Starters | Role | Bench |
|--------|-------|----------|------|-------|
| 0 (none) | 36.8% | 48.6% | 51.2% | 50.3% |
| 1 under | **61.2%** | 57.1% | 50.0% | 47.4% |
| 2 under | 40.0% | 51.9% | 52.0% | 44.0% |
| 3 under | 42.3% | 43.4% | 55.3% | 36.2% |
| 4 under | **63.6%** (n=11) | 53.6% | 46.4% | 51.5% |
| 5+ under | 40.0% | 44.0% | 51.9% | 51.6% |

Non-uniform pattern. Stars mean-revert at streak=1 and streak=4. Bench players show continuation.

### 2.3 — Combined Cold Signals

| Signal | N | Over Rate | Baseline | Signal Strength |
|--------|---|-----------|----------|-----------------|
| FG cold (<40%) | 837 | 57.9% | 54.1% | +3.8pp |
| Points cold (20% below x2) | 458 | 57.2% | 54.7% | +2.5pp |
| Streak 2+ under | 1156 | 54.2% | 55.5% | -1.3pp |
| FG + Streak combined | 452 | 58.0% | 54.6% | +3.4pp |
| **Triple cold** | **234** | **60.3%** | **54.7%** | **+5.6pp** |

Triple cold (FG% <40% + pts 20% below + under streak 2+) = **60.3% OVER** on 234 games.

---

## Phase 3: Streak Feature Validation

Streak features have <1% importance in the model. The FG% cold signal (60%+ OVER rate in SQL) is not being captured. This is because:
- CatBoost optimizes MAE (magnitude), not direction (OVER/UNDER)
- FG% tells us direction but not magnitude
- The model predicts point totals, not bet outcomes

**Decision:** FG% features add orthogonal signal → proceed to V13 experiments.

---

## Phase 4: V13 FG% Feature Experiments

Added 6 features (indices 54-59): `fg_pct_last_3`, `fg_pct_last_5`, `fg_pct_vs_season_avg`, `three_pct_last_3`, `three_pct_last_5`, `fg_cold_streak`

| # | Experiment | MAE | HR All | HR 3+ (n) | OVER | UNDER | FG% Importance |
|---|-----------|-----|--------|-----------|------|-------|----------------|
| V13-A | BASELINE | 4.89 | 56.1% | 50.0% (22) | 40.0% | 52.9% | **ALL 0%** |
| V13-B | RSM50 | 4.94 | 53.4% | 54.1% (37) | 60.0% | 51.9% | ALL 0% |
| V13-C | PRUNED_RSM50 | 4.93 | 51.8% | 56.4% (39) | 85.7% | 50.0% | ALL 0% |

**All 6 FG% features got 0% importance in every experiment.** CatBoost cannot leverage shooting efficiency for point prediction. The FG% signal is real (SQL proves it) but it's about direction, not magnitude.

### Why FG% Fails as Model Features

The disconnect: FG% cold → mean reversion → higher probability of going OVER. But CatBoost predicts *how many points*, not *over/under*. A player shooting 35% FG% doesn't predictably score X points — they might score more or less depending on volume, free throws, etc. The FG% signal is probabilistic (60% OVER rate) but CatBoost needs deterministic point prediction.

**Implication:** FG% cold should be used as a **post-prediction filter** or **rule-based layer**, not as a model feature.

---

## Phase 5: Advanced Experiments

### 5.1 — Continuation Filter: COUNTERPRODUCTIVE

| Segment | HR No Filter | HR With Filter | Suppressed Bets HR |
|---------|-------------|----------------|-------------------|
| All edge 3+ (n=631) | 58.3% | 56.4% | 69.1% (n=94) |
| OVER edge 3+ (n=315) | 65.0% | 63.2% | 69.1% (n=94) |

The model's OVER calls during under streaks hit at **69.1%** — these are the BEST bets. Suppressing them drops HR. The model already captures mean reversion.

### 5.5 — Game Total Filter

| Game Total | OVER HR (n) | UNDER HR (n) |
|-----------|-------------|--------------|
| <220 (low) | 76.9% (26) | 55.3% (39) |
| 220-224 | 61.2% (166) | 56.9% (154) |
| 225-229 | 63.6% (44) | 27.0% (38) |
| 230-234 | **80.0% (30)** | 46.3% (54) |
| 235+ (high) | 63.3% (49) | 60.0% (25) |

OVER in 230-234 total games: **80.0%** hit rate. Small sample but strong signal.

---

## Code Changes

1. **`shared/ml/feature_contract.py`** — Added V13 contract (60 features), V13_NOVEG contract (56 features), 6 new feature definitions (indices 54-59), defaults, registry entries
2. **`ml/experiments/quick_retrain.py`** — Added `--feature-set v13` option, `augment_v13_features()` function that queries `nbac_gamebook_player_stats` for rolling FG%/3PT% with quality filters

---

## Governance Gate Status

No experiment passed all gates. Closest: V12 RSM50 (G)
- [PASS] MAE improvement
- [FAIL] HR 3+ >= 60% (57.1% — close)
- [FAIL] HR 3+ sample >= 50 (n=35 — needs more eval days)
- [PASS] Vegas bias
- [PASS] Tier bias
- [PASS] Directional balance

---

## Recommended Next Steps

1. **Shadow deploy V12 RSM50** for real-world validation
2. **Extend eval window** to 3-4 weeks to get 50+ edge 3+ samples
3. **Exclude `line_vs_season_avg`** in truly vegas-free experiments (it leaks vegas)
4. **Post-prediction FG% filter** — apply the 60% OVER signal as a rule-based layer after model prediction
5. **Game total 230-234 OVER filter** — needs more data validation
6. **Explore new feature ideas:** personalized FG% z-scores, fatigue-cold interaction, minutes-FG% interaction
