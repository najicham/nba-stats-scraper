# Session 125 - Breakout Detection Implementation

**Date:** 2026-02-05
**Status:** Infrastructure Complete, Model Training Pending

---

## Executive Summary

Session 125 focused on improving role player UNDER bet performance through:
1. Enhanced filtering based on data analysis
2. Infrastructure for a breakout classifier model
3. Monitoring queries for ongoing tracking

**Key Finding:** Role player UNDER bets lose money (42-45% hit rate) unless:
- Edge >= 5 (then 55-67% hit rate)
- Player NOT on hot streak (L5 > season + 3 = only 14% hit rate)

---

## Filters Implemented

### 1. Role Player UNDER Low Edge Filter
```python
# predictions/worker/worker.py
if 8 <= season_avg <= 16 and edge < 5:
    filter_reason = 'role_player_under_low_edge'
```
**Data:** Edge 3-5 has 42.3% hit rate; Edge 5+ has 55-67%

### 2. Hot Streak UNDER Filter
```python
# predictions/worker/worker.py
if l5_avg - season_avg > 3 and recommendation == 'UNDER':
    filter_reason = 'hot_streak_under_risk'
```
**Data:** Hot streak (L5 > season + 3) UNDER has only 14.3% hit rate

### 3. Data Quality Filter
```python
# predictions/worker/worker.py
if quality_score < 80:
    filter_reason = 'low_data_quality'
```
**Data:** Quality 80+ has 60.6% hit rate vs 39.1% for 70-80

---

## Breakout Classifier Infrastructure

### Training Script
**Location:** `ml/experiments/train_breakout_classifier.py`

**Target:** `is_breakout = 1 if actual_points >= season_avg * 1.5`

**Features (10):**
| Feature | Source | Description |
|---------|--------|-------------|
| pts_vs_season_zscore | Feature store [35] | Hot streak indicator |
| points_std_last_10 | Feature store [3] | Volatility |
| explosion_ratio | Computed | max(L5) / season_avg |
| days_since_breakout | Computed | Days since last 1.5x game |
| opponent_def_rating | Feature store [13] | Defense weakness |
| home_away | Feature store [15] | Home court |
| back_to_back | Feature store [16] | Fatigue |
| points_avg_last_5 | Feature store [0] | Recent form |
| points_avg_season | Feature store [2] | Baseline |
| minutes_avg_last_10 | Feature store [31] | Playing time |

### Usage
```bash
# Train first breakout classifier
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_V1" \
    --train-start 2025-11-01 --train-end 2026-01-25 \
    --eval-start 2026-01-26 --eval-end 2026-02-02

# Dry run
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "TEST" --dry-run
```

---

## Monitoring Queries

**Location:** `validation/queries/monitoring/breakout_filter_monitoring.sql`

### Available Queries
1. **Daily Filter Performance** - Track if filters are saving money
2. **Breakout Rate by Opponent** - Identify leaky defenses
3. **Player Breakout Profiles** - High-volatility players
4. **Hot Streak Analysis** - Z-score vs breakout correlation
5. **Weekly Summary** - Filter effectiveness over time
6. **Teammate Injury Impact** - Opportunity correlation

### Quick Check
```sql
-- Filter shadow tracking
SELECT filter_reason, COUNT(*) as filtered,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as would_have_hit
FROM nba_predictions.prediction_accuracy
WHERE is_actionable = false AND filter_reason IS NOT NULL
GROUP BY 1
```

---

## Quality Propagation

### Changes to Grading
**File:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

Added:
- `feature_quality_score` - copied from prediction
- `data_quality_tier` - 'HIGH' (80+), 'MEDIUM' (70-80), 'LOW' (<70)
- `_compute_quality_tier()` helper method

This enables hit rate analysis by quality tier.

---

## Data Analysis Findings

### Role Player UNDER by Edge
| Edge | Predictions | Hit Rate |
|------|-------------|----------|
| 7+ | 3 | 66.7% |
| 5-7 | 11 | 54.5% |
| **3-5** | **52** | **42.3%** |
| <3 | 305 | 53.4% |

### Hot Streak Impact
| Filter Decision | Predictions | Hit Rate |
|-----------------|-------------|----------|
| L5 hot streak (+3+) | 7 | **14.3%** |
| KEEP | 59 | 49.2% |

### High-Breakout Opponents
- UTA: 38% breakout rate
- POR: 37%
- MEM: 37%
- LAL: 35%
- DEN: 35%

---

## Files Created/Modified

| File | Action | Purpose |
|------|--------|---------|
| `predictions/worker/worker.py` | Modified | Added 3 filters |
| `data_processors/grading/.../prediction_accuracy_processor.py` | Modified | Quality propagation |
| `ml/experiments/train_breakout_classifier.py` | Created | Breakout model training |
| `.claude/skills/model-experiment/SKILL.md` | Modified | Added breakout docs |
| `validation/queries/monitoring/breakout_filter_monitoring.sql` | Created | 6 monitoring queries |
| `docs/08-projects/current/breakout-detection-design/` | Created | Design docs |

---

## Commits

```
f59e4c37 - feat: Add quality filters and propagate quality to grading
95bcc254 - feat: Strengthen role player UNDER filter and add breakout monitoring
6e8f7079 - feat: Add hot streak UNDER filter and breakout classifier infrastructure
```

---

## Next Steps

### Immediate (Next Session)
1. **Deploy latest changes** to prediction-worker
2. **Train breakout classifier** using the new script
3. **Evaluate model** - target AUC >= 0.65

### Short-term
1. **Monitor filter performance** via shadow tracking
2. **Iterate on breakout classifier** features
3. **Add opponent-based breakout filtering** if data supports

### Long-term
1. **Integrate breakout probability** into predictions
2. **Create breakout-specific bet type** for high-probability breakouts
3. **Build player profiles** for volatility tracking

---

## Key Learnings

1. **Hot streak is the strongest predictor** - L5 > season + 3 = 14% UNDER hit rate
2. **Edge matters for role players** - Need edge >= 5 for profitable UNDERs
3. **Data quality correlates with performance** - 80+ quality = 60% hit rate
4. **breakout_flag is too rare** - Only triggers 0.4% of time (threshold too high)

---

*Session 125 - Breakout Detection Infrastructure*
