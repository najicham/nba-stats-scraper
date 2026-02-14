# Session 243 Handoff: V12/V13 Experiment Suite & Shooting Efficiency

**Date:** 2026-02-13
**Focus:** V12 experiment matrix (8 configs), V13 FG% features, cold streak SQL analysis, post-prediction filters
**Status:** All experiments complete, analysis documented, code changes committed

---

## What Was Done

### 1. V12 Experiment Matrix (8 experiments)

Trained 8 V12 no-vegas models (train: Nov 2 - Jan 31, eval: Feb 1-12, no overlap):

| # | Name | Key Config | HR 3+ (n) | Direction |
|---|------|-----------|-----------|-----------|
| A | V12_BASELINE | defaults | 46.4% (28) | FAIL |
| B | V12_TUNED | `--tune` (skipped in no-vegas) | 46.4% (28) | FAIL |
| C | V12_RECENCY30 | `--recency-weight 30` | 41.4% (29) | FAIL |
| D | V12_RECENCY14 | `--recency-weight 14` | 54.2% (24) | FAIL |
| E | V12_HUBER5 | `--loss-function "Huber:delta=5"` | 50.9% (57) | FAIL |
| F | V12_PRUNED | exclude 6 dead features | 56.5% (23) | PASS |
| **G** | **V12_RSM50** | **`--rsm 0.5 --grow-policy Depthwise`** | **57.1% (35)** | **PASS** |
| H | V12_BEST_COMBO | RSM50+PRUNED+RECENCY14 | 51.3% (39) | FAIL |

**Winner: G (V12_RSM50)** — 57.1% edge 3+ HR, 58.2% overall HR, MAE 4.82, OVER 64.3%, UNDER 52.4%

### 2. SQL Cold Streak Analysis

- **FG% cold is a powerful mean-reversion signal:** players shooting >10pp below personal avg go OVER at **60.8%** (n=498)
- **Triple cold signal** (FG%<40% + points 20% below + under streak 2+) = **60.3% OVER** (n=234)
- **Points-based cold streaks are weak** (+2-4pp, marginal)
- **Prop streak continuation varies by tier:** stars mean-revert, bench players continue

### 3. V13 FG% Features (NEW)

Added 6 FG% features to feature contract and `quick_retrain.py`:
- `fg_pct_last_3`, `fg_pct_last_5`, `fg_pct_vs_season_avg`
- `three_pct_last_3`, `three_pct_last_5`, `fg_cold_streak`

**Result: All 6 features got 0% importance in every V13 experiment.** CatBoost can't use FG% for MAE point prediction. The signal is about direction (OVER/UNDER), not magnitude.

### 4. Post-Prediction Filters

- **Continuation filter (suppress OVER on under streaks): HURTS.** Suppressed bets hit at 69.1% — removing the best bets.
- **Game total 230-234 OVER: 80.0% HR** (n=30, needs more data)

### 5. Dead Features Confirmed

Zero importance in every experiment: `breakout_flag, playoff_game, spread_magnitude, teammate_usage_available, multi_book_line_std`

---

## Key Findings

1. **RSM (feature subsampling) is the single most impactful training technique.** It forces CatBoost to use diverse features instead of over-relying on `points_avg_season` (which is 30% importance by default).

2. **FG% signal is real but orthogonal to model features.** SQL shows 60%+ OVER rate after cold shooting. But CatBoost optimizes MAE (magnitude), not direction. FG% should be a post-prediction rule/filter, not a model feature.

3. **`line_vs_season_avg` leaks vegas info** in no-vegas mode (5-13% importance). Computed from `vegas_points_line - season_avg`. Should be excluded or recomputed from prop lines.

4. **Improvements don't stack** — combining multiple winning techniques (H) performed worse than the single best (G).

5. **Model already captures mean reversion** — OVER calls during under streaks hit at 69.1%. Don't suppress them.

6. **12-day eval window is too short** for governance (max 57 edge 3+ samples). Need 3-4 weeks.

---

## Code Changes

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | Added V13/V13_NOVEG contracts (60/56 features), 6 new feature defs (54-59), defaults |
| `ml/experiments/quick_retrain.py` | Added `--feature-set v13`, `augment_v13_features()` function |

Models saved in `models/` directory (not deployed, experiment-only).

---

## What the Next Session Should Do

### Priority 1: Continue Feature Exploration

The FG% signal is real but CatBoost ignores it as a feature. Try these approaches:

**A. Personalized FG% Z-Score Feature**
```
fg_cold_z_score = (fg_pct_last_3 - player_season_fg_pct) / player_season_fg_std
```
This captures "cold for THIS player" vs absolute thresholds. Jokic at 52% is cold for him. A role player at 52% is hot. The z-score might give CatBoost a more usable signal.

**B. Minutes-FG% Fatigue Interaction**
```
fatigue_cold_signal = minutes_load_last_7d * (1 - fg_pct_last_3)
```
High minutes + poor shooting = strong UNDER signal. The interaction might be more predictive than either alone.

**C. Volume-Adjusted FG% Features**
Instead of just FG%, try: `expected_points_from_fg = fg_pct_last_3 * fga_last_3 * 2 + three_pct_last_3 * tpa_last_3`
This converts shooting percentages into expected points, which is closer to what CatBoost needs.

**D. FG% Change Rate**
```
fg_pct_acceleration = fg_pct_last_3 - fg_pct_last_5
```
Captures whether shooting is getting worse or better. A player declining from 50% to 35% is different from one steady at 40%.

**E. 3PT% Variance Feature**
Three-point shooting is high-variance. A feature like `three_pct_std_last_5` captures inconsistency.

### Priority 2: More V12 RSM50 Variants

The RSM50 config won. Try these combinations:

```bash
# RSM50 + exclude line_vs_season_avg (remove vegas leak)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM50_NOVEG_CLEAN" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --exclude-features "line_vs_season_avg,multi_book_line_std,teammate_usage_available,spread_magnitude,breakout_flag,playoff_game" \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register

# RSM50 + Huber loss (more edge 3+ samples + feature diversity)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM50_HUBER" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --loss-function "Huber:delta=5" \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register

# RSM50 + quantile 0.47 (slight UNDER bias for continuation)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM50_Q47" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --quantile-alpha 0.47 \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register

# RSM with different values (0.3, 0.7) to find optimal
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM30" \
  --feature-set v12 --no-vegas \
  --rsm 0.3 --grow-policy Depthwise \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register
```

### Priority 3: Post-Prediction Rule Layer Analysis

Since FG% can't be a model feature, test rule-based filters applied AFTER model prediction:

```sql
-- Test: boost confidence for OVER predictions when player is FG% cold
-- (since model's OVER calls on cold players hit 69.1%)
WITH model_preds AS (
  SELECT pa.*,
    fg_data.fg_pct_last_2,
    fg_data.season_fg_pct,
    COALESCE(upcg.prop_under_streak, 0) as under_streak
  FROM prediction_accuracy pa
  JOIN fg_rolling_data fg_data ON ...
  JOIN upcoming_player_game_context upcg ON ...
  WHERE edge >= 3
)
-- Rules to test:
-- Rule 1: OVER + FG% cold (<40% L2) → boost edge by 1 point
-- Rule 2: OVER + triple cold → flag as "high conviction"
-- Rule 3: UNDER + FG% hot (>50% L2) → boost edge
-- Measure: what's the HR for each rule-filtered subset?
```

### Priority 4: Extended Eval Window

V12 RSM50 only had 35 edge 3+ samples (needs 50 for governance). Options:
- Wait for more days of eval data
- Run with eval window Feb 1-20+ (after ASB break ends)
- Use walk-forward with 4-week eval periods from historical data

### Priority 5: Game Total Filter Deep Dive

The 230-234 OVER at 80% signal needs validation:
- Is it stable across months? (not just one hot week)
- What's the mechanism? (pace, shooting, competitive games?)
- Can it be a post-prediction filter?

---

## Schema Notes for SQL Queries

Queries against these tables need these column names:
- `prediction_accuracy`: `line_value` (not prop_line), `actual_points` (not actual_stat), NO `stat_type` column (all points)
- `nbac_gamebook_player_stats`: `minutes_decimal` (not minutes_played), `field_goals_made/attempted`, `three_pointers_made/attempted`
- `player_game_summary`: `minutes_played` (has it), `points`, `usage_rate`

---

## Documentation

- **Full results:** `docs/08-projects/current/mean-reversion-analysis/05-SESSION-243-V12-V13-EXPERIMENT-RESULTS.md`
- **Prior context:** `docs/08-projects/current/mean-reversion-analysis/01-04-*.md`
- **Model improvement context:** `docs/08-projects/current/model-improvement-analysis/`
- **Feature contract:** `shared/ml/feature_contract.py` (V13 added)
- **Experiment runner:** `ml/experiments/quick_retrain.py` (V13 augmentation added)

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-13-SESSION-243-HANDOFF.md

# 2. See prior results
cat docs/08-projects/current/mean-reversion-analysis/05-SESSION-243-V12-V13-EXPERIMENT-RESULTS.md

# 3. Run a new experiment (example: RSM50 + clean vegas exclusion)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM50_NOVEG_CLEAN" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --exclude-features "line_vs_season_avg,multi_book_line_std,teammate_usage_available,spread_magnitude,breakout_flag,playoff_game" \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register

# 4. To add new V13/V14 features, edit:
#    - shared/ml/feature_contract.py (add contract)
#    - ml/experiments/quick_retrain.py (add augment_vXX_features function + wiring)
```
