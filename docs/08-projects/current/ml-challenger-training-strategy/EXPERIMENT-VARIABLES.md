# ML Experiment Variables

**Created:** 2026-02-01 (Session 68)
**Purpose:** Document all configurable variables for ML training experiments

---

## Overview

This document outlines the main variables to manipulate when running training experiments. Understanding these helps design systematic experiments to improve model performance.

---

## 1. Training Window

The most impactful variable - determines what data the model learns from.

| Variable | Description | Options |
|----------|-------------|---------|
| `train_start` | First date of training data | Season start, N days ago, specific date |
| `train_end` | Last date of training data | Must be before eval period |
| `window_type` | Fixed vs rolling | Fixed (all data), Rolling (last N days) |
| `train_days` | Number of days (if rolling) | 30, 60, 90, 120 |

### Current V9 Settings
- Start: Nov 2, 2025
- End: Jan 8, 2026
- Type: Fixed
- Days: 68

### Experiments to Run

| Experiment | Window | Hypothesis |
|------------|--------|------------|
| `EXP_WINDOW_30D` | Last 30 days | Recent trends dominate |
| `EXP_WINDOW_60D` | Last 60 days | Balance recency/stability |
| `EXP_WINDOW_90D` | Last 90 days | More samples improve accuracy |
| `EXP_FULL_SEASON` | Nov - current | Maximum data available |

---

## 2. Evaluation Window

Determines how we measure model performance.

| Variable | Description | Options |
|----------|-------------|---------|
| `eval_start` | First date of evaluation | Must be after train_end |
| `eval_end` | Last date of evaluation | Recent enough for actuals |
| `line_source` | Sportsbook for lines | `draftkings`, `bettingpros`, `fanduel` |
| `min_samples` | Minimum for reliability | 50+ for filtered metrics |

### Current Settings
- Line source: `draftkings` (matches production)
- Minimum high-edge samples: 50 for statistical reliability

### Key Insight
**Line source matters!** Session 67 found:
- BettingPros eval: 72.2% high-edge
- DraftKings eval: 79.4% high-edge (same model!)

Always use `draftkings` to match production betting.

---

## 3. Sample Weighting

Weight recent games more heavily than older games.

| Variable | Description | Options |
|----------|-------------|---------|
| `weighting` | Enable/disable | `none`, `exponential`, `linear` |
| `half_life` | Decay rate (if exponential) | 30, 60, 90, 180 days |
| `min_weight` | Floor for old samples | 0.1, 0.2, 0.5 |

### Current Settings
- Weighting: None (all samples equal)

### Experiments to Run

| Experiment | Half-Life | Hypothesis |
|------------|-----------|------------|
| `EXP_RECENCY_30D` | 30 days | Very recent data most predictive |
| `EXP_RECENCY_90D` | 90 days | Moderate recency bias |
| `EXP_RECENCY_180D` | 180 days | Slight recency preference |

### Implementation Note
Not yet implemented in `quick_retrain.py`. Would require:
```python
# Add to training
weights = np.exp(-days_ago / half_life)
model.fit(X_train, y_train, sample_weight=weights)
```

---

## 4. Feature Selection

Which of the 33 features to include.

| Variable | Description | Current |
|----------|-------------|---------|
| `feature_count` | Total features | 33 |
| `rolling_windows` | Lookback periods | 5-game, 10-game, season |
| `vegas_required` | Require Vegas lines | No (impute if missing) |

### Current 33 Features

**Player Stats (13)**
- `points_avg_last_5`, `points_avg_last_10`, `points_avg_season`
- `points_std_last_10`, `games_in_last_7_days`
- `minutes_avg_last_10`, `ppm_avg_last_10`
- Shot zones: `pct_paint`, `pct_mid_range`, `pct_three`, `pct_free_throw`
- `avg_points_vs_opponent`, `games_vs_opponent`

**Derived Scores (6)**
- `fatigue_score`, `shot_zone_mismatch_score`, `pace_score`
- `usage_spike_score`, `rest_advantage`, `recent_trend`

**Team Context (5)**
- `team_pace`, `team_off_rating`, `team_win_pct`
- `opponent_def_rating`, `opponent_pace`

**Game Context (5)**
- `home_away`, `back_to_back`, `playoff_game`
- `injury_risk`, `minutes_change`

**Vegas Lines (4)**
- `vegas_points_line`, `vegas_opening_line`
- `vegas_line_move`, `has_vegas_line`

### Experiments to Run

| Experiment | Change | Hypothesis |
|------------|--------|------------|
| `EXP_NO_VEGAS` | Remove 4 Vegas features | Model works without lines |
| `EXP_VEGAS_ONLY` | Train only on samples with Vegas | Higher quality samples |
| `EXP_ADD_MOMENTUM` | Add win_streak, pts_trend | Momentum is predictive |
| `EXP_FEWER_FEATURES` | Top 20 by importance | Reduce overfitting |

---

## 5. Model Hyperparameters

CatBoost configuration.

| Parameter | Description | Current | Range |
|-----------|-------------|---------|-------|
| `iterations` | Max training rounds | 1000 | 500-2000 |
| `learning_rate` | Step size | 0.05 | 0.01-0.1 |
| `depth` | Tree depth | 6 | 4-8 |
| `l2_leaf_reg` | Regularization | 3 | 1-10 |
| `early_stopping_rounds` | Patience | 50 | 30-100 |

### Experiments to Run

| Experiment | Changes | Hypothesis |
|------------|---------|------------|
| `EXP_DEEPER` | depth=8 | Capture complex patterns |
| `EXP_SHALLOWER` | depth=4 | Reduce overfitting |
| `EXP_MORE_REG` | l2=10 | More regularization helps |
| `EXP_SLOWER_LR` | lr=0.01, iter=2000 | Slower convergence is better |

---

## 6. Player/Game Filtering

Which samples to include in training.

| Variable | Description | Current |
|----------|-------------|---------|
| `min_minutes` | Minimum minutes played | >0 |
| `min_feature_count` | Features available | >=33 |
| `require_vegas` | Only samples with lines | No |
| `min_games_played` | Player experience | None |

### Experiments to Run

| Experiment | Filter | Hypothesis |
|------------|--------|------------|
| `EXP_STARTERS_ONLY` | minutes >= 20 | Focus on predictable players |
| `EXP_VEGAS_ONLY` | has_vegas_line = 1 | Higher quality samples |
| `EXP_EXPERIENCED` | player_games >= 10 | Exclude early-season noise |

---

## 7. Data Source

Which sportsbook data to train on.

| Variable | Description | Options |
|----------|-------------|---------|
| `train_line_source` | Lines for training features | `draftkings`, `bettingpros`, `consensus` |
| `eval_line_source` | Lines for evaluation | Should match production |

### Current Settings
- Training: Uses feature store (mixed sources)
- Evaluation: `draftkings` (matches production)

### Experiments to Run

| Experiment | Source | Hypothesis |
|------------|--------|------------|
| `EXP_DK_TRAIN` | Train on DK lines only | Matches production betting |
| `EXP_MULTI_BOOK` | Train with book indicator | Learn book-specific patterns |

---

## Experiment Priority Matrix

Based on expected impact and effort:

| Priority | Experiment Type | Impact | Effort |
|----------|-----------------|--------|--------|
| 1 | Training Window | High | Low |
| 2 | Recency Weighting | Medium | Medium |
| 3 | Feature Selection | Medium | Low |
| 4 | Hyperparameters | Low | Low |
| 5 | Data Source | Medium | High |
| 6 | Player Filtering | Low | Low |

---

## Running Experiments

### Using quick_retrain.py

```bash
# Basic experiment
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_WINDOW_30D" \
    --train-start 2026-01-01 \
    --train-end 2026-01-24 \
    --eval-start 2026-01-25 \
    --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "Test 30-day rolling window"

# Dry run first
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "TEST" --dry-run
```

### Tracking Results

All experiments are registered in `nba_predictions.ml_experiments`:

```sql
SELECT experiment_name,
       JSON_VALUE(results_json, '$.hit_rate_high_edge') as high_edge,
       JSON_VALUE(results_json, '$.mae') as mae
FROM nba_predictions.ml_experiments
WHERE experiment_type = 'monthly_retrain'
ORDER BY created_at DESC
LIMIT 10
```

---

## Next Steps

1. **Run Batch 1:** Training window experiments (30/60/90/full)
2. **Implement recency weighting** in quick_retrain.py
3. **Run Batch 2:** Recency experiments
4. **Document findings** in this directory

---

*Created: Session 68, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
