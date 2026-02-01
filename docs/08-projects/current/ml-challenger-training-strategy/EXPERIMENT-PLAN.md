# ML Experiment Plan

**Created:** 2026-02-01 (Session 68)
**Status:** Ready for Review
**Purpose:** Define specific experiments to run for model improvement

---

## Executive Summary

This document outlines a systematic experiment plan to improve our CatBoost model. The current V9 model achieves **79.4% high-edge hit rate** on production data. Our goal is to find configurations that maintain or improve this while being more robust.

**Key Variables to Test:**
1. Training window size (30, 60, 90 days vs full season)
2. Recency weighting (none vs exponential decay)
3. Feature subsets (all 33 vs Vegas-only samples vs reduced features)
4. Hyperparameters (depth, learning rate, regularization)

---

## Current Baseline: V9

| Property | Value |
|----------|-------|
| Training Window | Nov 2, 2025 - Jan 8, 2026 (68 days) |
| Training Samples | 9,993 |
| Features | 33 |
| High-Edge Hit Rate | 79.4% (148 bets) |
| Premium Hit Rate | 65.6% (392 bets) |
| MAE | ~4.8 |

---

## Experiment Batches

### Batch 1: Training Window Size (PRIORITY: HIGH)

**Question:** What's the optimal training window size?

**Hypothesis:**
- Too short (30d) = not enough samples, overfits to recent noise
- Too long (full season) = includes stale patterns
- Sweet spot likely 60-90 days

**Experiments:**

| ID | Name | Train Start | Train End | Eval Period | Command |
|----|------|-------------|-----------|-------------|---------|
| W1 | 30-day window | 2025-12-25 | 2026-01-24 | Jan 25-31 | See below |
| W2 | 45-day window | 2025-12-10 | 2026-01-24 | Jan 25-31 | See below |
| W3 | 60-day window | 2025-11-25 | 2026-01-24 | Jan 25-31 | See below |
| W4 | 90-day window | 2025-10-26 | 2026-01-24 | Jan 25-31 | See below |
| W5 | Full season | 2025-11-02 | 2026-01-24 | Jan 25-31 | See below |

**Commands:**

```bash
# W1: 30-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W1_30DAY" \
    --train-start 2025-12-25 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "30-day rolling window"

# W2: 45-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W2_45DAY" \
    --train-start 2025-12-10 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "45-day rolling window"

# W3: 60-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W3_60DAY" \
    --train-start 2025-11-25 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "60-day rolling window"

# W4: 90-day window (extends before season start - will have less data)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W4_90DAY" \
    --train-start 2025-10-26 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "90-day rolling window"

# W5: Full season
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W5_FULL_SEASON" \
    --train-start 2025-11-02 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "Full season training"
```

**Success Criteria:**
- High-edge hit rate >= 65% (statistically significant improvement needs 50+ bets)
- MAE <= 5.0
- Compare sample sizes - may need longer eval period for reliability

**Note:** Jan 25-31 eval period may have few high-edge bets. Consider extending eval or running multiple eval windows.

---

### Batch 2: Extended Evaluation Periods

**Question:** Are our eval results statistically reliable?

**Problem:** 7-day eval windows often have <30 high-edge bets, making results unreliable.

**Solution:** Run same experiments with longer eval periods.

| ID | Name | Train End | Eval Period | Expected Bets |
|----|------|-----------|-------------|---------------|
| E1 | 14-day eval | Jan 17 | Jan 18-31 | ~60 high-edge |
| E2 | 21-day eval | Jan 10 | Jan 11-31 | ~90 high-edge |

**Commands:**

```bash
# E1: 14-day eval with 60-day training
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_E1_60DAY_14EVAL" \
    --train-start 2025-11-18 --train-end 2026-01-17 \
    --eval-start 2026-01-18 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "60-day train, 14-day eval for statistical reliability"

# E2: 21-day eval with 60-day training
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_E2_60DAY_21EVAL" \
    --train-start 2025-11-11 --train-end 2026-01-10 \
    --eval-start 2026-01-11 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "60-day train, 21-day eval for statistical reliability"
```

---

### Batch 3: Recency Weighting (PRIORITY: MEDIUM)

**Question:** Does weighting recent games more heavily improve performance?

**Hypothesis:** Recent games better reflect current player form, injuries, and team dynamics.

**Implementation Required:** Add sample weighting to `quick_retrain.py`

```python
# Proposed implementation
def compute_sample_weights(dates, half_life_days=90):
    """Exponential decay weighting - recent games weighted higher."""
    max_date = dates.max()
    days_ago = (max_date - dates).dt.days
    weights = np.exp(-days_ago / half_life_days)
    return weights

# In training:
weights = compute_sample_weights(df_train['game_date'], half_life_days=args.half_life)
model.fit(X_train, y_train, sample_weight=weights)
```

**Experiments (after implementation):**

| ID | Name | Half-Life | Effect |
|----|------|-----------|--------|
| R1 | No weighting | None | Baseline (current) |
| R2 | 30-day half-life | 30 | Very aggressive recency |
| R3 | 60-day half-life | 60 | Moderate recency |
| R4 | 90-day half-life | 90 | Mild recency |

**Implementation Steps:**
1. Add `--half-life` argument to `quick_retrain.py`
2. Implement `compute_sample_weights()` function
3. Pass weights to `model.fit()`
4. Run experiments R1-R4

---

### Batch 4: Feature Subsets (PRIORITY: MEDIUM)

**Question:** Do all 33 features help, or do some cause overfitting?

**Experiments:**

| ID | Name | Features | Hypothesis |
|----|------|----------|------------|
| F1 | All features | 33 | Baseline |
| F2 | No Vegas | 29 (remove 4 Vegas) | Model works without lines |
| F3 | Core only | 15 most important | Reduce overfitting |
| F4 | Stats only | 13 player stats | Pure statistical model |

**Feature Groups:**

```python
# Current 33 features
ALL_FEATURES = [
    # Player Stats (13)
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    "minutes_avg_last_10", "ppm_avg_last_10",
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    "avg_points_vs_opponent", "games_vs_opponent",

    # Derived Scores (6)
    "fatigue_score", "shot_zone_mismatch_score", "pace_score",
    "usage_spike_score", "rest_advantage", "recent_trend",

    # Team Context (5)
    "team_pace", "team_off_rating", "team_win_pct",
    "opponent_def_rating", "opponent_pace",

    # Game Context (5)
    "home_away", "back_to_back", "playoff_game",
    "injury_risk", "minutes_change",

    # Vegas Lines (4)
    "vegas_points_line", "vegas_opening_line",
    "vegas_line_move", "has_vegas_line",
]

# F2: No Vegas (29 features)
NO_VEGAS_FEATURES = [f for f in ALL_FEATURES if not f.startswith('vegas') and f != 'has_vegas_line']

# F3: Core only (15 features) - based on typical feature importance
CORE_FEATURES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "minutes_avg_last_10",
    "vegas_points_line", "has_vegas_line",
    "opponent_def_rating", "team_off_rating",
    "fatigue_score", "rest_advantage",
    "home_away", "back_to_back",
    "recent_trend", "games_in_last_7_days",
]

# F4: Stats only (13 features)
STATS_ONLY_FEATURES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    "minutes_avg_last_10", "ppm_avg_last_10",
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    "avg_points_vs_opponent", "games_vs_opponent",
]
```

**Implementation Required:** Add `--feature-set` argument to `quick_retrain.py`

---

### Batch 5: Hyperparameter Tuning (PRIORITY: LOW)

**Question:** Are the default CatBoost parameters optimal?

**Current Settings:**
```python
model = cb.CatBoostRegressor(
    iterations=1000,
    learning_rate=0.05,
    depth=6,
    l2_leaf_reg=3,
    random_seed=42,
    early_stopping_rounds=50
)
```

**Experiments:**

| ID | Name | Changes | Hypothesis |
|----|------|---------|------------|
| H1 | Baseline | Default | Current settings |
| H2 | Deeper trees | depth=8 | Capture complex patterns |
| H3 | Shallower trees | depth=4 | Reduce overfitting |
| H4 | More regularization | l2_leaf_reg=10 | Prevent overfitting |
| H5 | Slower learning | lr=0.02, iter=2000 | Better convergence |
| H6 | Faster learning | lr=0.1, iter=500 | Quicker training |

**Implementation Required:** Add hyperparameter arguments to `quick_retrain.py`

---

### Batch 6: Player/Game Filtering (PRIORITY: LOW)

**Question:** Should we filter training data to higher-quality samples?

**Experiments:**

| ID | Name | Filter | Hypothesis |
|----|------|--------|------------|
| P1 | All players | minutes > 0 | Baseline |
| P2 | Starters only | minutes >= 20 | Focus on predictable players |
| P3 | Vegas only | has_vegas_line = 1 | Higher quality samples |
| P4 | Experienced | games_played >= 10 | Exclude early-season noise |

**Implementation Required:** Add filtering logic to data loading

---

## Recommended Experiment Sequence

### Phase 1: Quick Wins (Run Now)

Run Batch 1 (training windows) with current code - no implementation needed:

```bash
# Run all 5 window experiments
for exp in W1 W2 W3 W4 W5; do
    echo "Running $exp..."
    # Commands from Batch 1 above
done
```

### Phase 2: Statistical Reliability

Run Batch 2 (extended eval) to get reliable numbers:

```bash
# Run extended eval experiments
# Commands from Batch 2 above
```

### Phase 3: Code Enhancements

Implement and run:
1. Recency weighting (Batch 3)
2. Feature subsets (Batch 4)
3. Hyperparameter arguments (Batch 5)

### Phase 4: Final Optimization

Based on Phase 1-3 results:
1. Combine best training window + best recency weighting
2. Test feature subsets with winning configuration
3. Fine-tune hyperparameters

---

## Experiment Tracking

All experiments are automatically logged to BigQuery:

```sql
-- View recent experiments
SELECT
    experiment_name,
    JSON_VALUE(config_json, '$.train_days') as train_days,
    JSON_VALUE(config_json, '$.line_source') as line_source,
    JSON_VALUE(results_json, '$.mae') as mae,
    JSON_VALUE(results_json, '$.hit_rate_all') as hit_rate_all,
    JSON_VALUE(results_json, '$.hit_rate_high_edge') as hit_rate_high_edge,
    JSON_VALUE(results_json, '$.bets_high_edge') as high_edge_bets,
    created_at
FROM nba_predictions.ml_experiments
WHERE experiment_type = 'monthly_retrain'
ORDER BY created_at DESC
LIMIT 20;
```

---

## Success Criteria

An experiment is considered successful if:

1. **Statistical Significance:** >= 50 high-edge bets in eval period
2. **Hit Rate Improvement:** High-edge hit rate >= 70% (vs 79.4% baseline)
3. **MAE Improvement:** MAE <= 5.0 (lower is better)
4. **Consistency:** Results hold across multiple eval periods

---

## Decision Framework

After running experiments:

| Scenario | Action |
|----------|--------|
| Clear winner (>5% improvement, reliable sample) | Promote to production |
| Marginal improvement (<5%, reliable sample) | Run shadow mode for 1 week |
| Mixed results | Run more experiments with different eval periods |
| Worse than baseline | Document learnings, try different approach |

---

## Implementation Checklist

Before running experiments, verify:

- [x] `--line-source` argument works (Session 68)
- [ ] Experiments register in `ml_experiments` table
- [ ] Eval periods don't overlap with training
- [ ] Sufficient high-edge bets for statistical reliability

Enhancements needed for future batches:

- [ ] Add `--half-life` for recency weighting (Batch 3)
- [ ] Add `--feature-set` for feature subsets (Batch 4)
- [ ] Add `--depth`, `--learning-rate`, `--l2-reg` for hyperparameters (Batch 5)
- [ ] Add `--min-minutes`, `--require-vegas` for filtering (Batch 6)

---

## Questions for Review

1. **Training window:** Should we prioritize 60-day or full-season as default?
2. **Eval reliability:** Is 50 high-edge bets sufficient, or should we require 100+?
3. **Recency weighting:** Worth implementing before more experiments?
4. **Feature selection:** Should we run feature importance analysis first?
5. **Hyperparameters:** Worth tuning, or stick with CatBoost defaults?

---

## Appendix: Quick Reference Commands

```bash
# Dry run any experiment
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "TEST" --dry-run

# Run with custom dates
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "CUSTOM" \
    --train-start YYYY-MM-DD --train-end YYYY-MM-DD \
    --eval-start YYYY-MM-DD --eval-end YYYY-MM-DD \
    --line-source draftkings

# View experiment results
bq query --use_legacy_sql=false "
SELECT experiment_name,
       JSON_VALUE(results_json, '$.hit_rate_high_edge') as hr,
       JSON_VALUE(results_json, '$.bets_high_edge') as bets
FROM nba_predictions.ml_experiments
ORDER BY created_at DESC LIMIT 10"

# Check current V9 production performance
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 'High Edge' ELSE 'Other' END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.system_id = 'catboost_v9' AND p.game_date >= '2026-01-09'
GROUP BY 1"
```

---

*Created: Session 68, 2026-02-01*
*Status: Ready for review by next session*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
