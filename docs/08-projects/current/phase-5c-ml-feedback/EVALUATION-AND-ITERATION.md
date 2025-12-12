# Prediction System Evaluation & Iteration Guide

**Created:** 2025-12-11
**Last Updated:** 2025-12-11

---

## Overview

This document explains:
1. How the ML feedback loop works (and doesn't work)
2. How to evaluate prediction performance
3. How to make improvements and iterate

---

## How the Learning System Works

### Current Architecture: Static Adjustments

The tier adjustment system uses **pre-computed, static adjustments** - NOT real-time learning.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ADJUSTMENT COMPUTATION (Offline)                      │
│                                                                              │
│   1. Query historical prediction_accuracy data                              │
│   2. Group by scoring tier (based on season_avg)                            │
│   3. Compute average bias per tier                                          │
│   4. Store in scoring_tier_adjustments table                                │
│                                                                              │
│   This runs MANUALLY when you call:                                         │
│   processor = ScoringTierProcessor()                                        │
│   processor.process('2022-01-07')  # Compute adjustments as of this date   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ADJUSTMENT APPLICATION (During Prediction)            │
│                                                                              │
│   1. For each prediction, get player's season_avg                           │
│   2. Classify into tier (BENCH, ROTATION, STARTER, STAR)                    │
│   3. Look up adjustment from table WHERE as_of_date <= game_date            │
│   4. Apply: adjusted_points = predicted_points + adjustment                 │
│                                                                              │
│   This runs AUTOMATICALLY during predictions backfill                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What This Means for Backfills

**During backfill, the system does NOT dynamically learn from each day's results.**

Example:
```
Backfilling predictions for Dec 15, 2021:
  → System looks up adjustment WHERE as_of_date <= '2021-12-15'
  → Finds adjustment from Dec 12 (as_of_date = '2021-12-12')
  → Uses that static adjustment
  → Does NOT incorporate Dec 13-14 results
```

### When Learning Happens

Learning (adjustment recomputation) happens ONLY when you explicitly run:

```python
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

processor = ScoringTierProcessor(lookback_days=30)
processor.process('2022-01-15')  # Recompute adjustments using last 30 days
```

### Recommended Learning Schedule

| Scenario | When to Recompute Adjustments |
|----------|-------------------------------|
| **Initial backfill** | Compute for key dates (weekly intervals) before running predictions |
| **Daily production** | Weekly recomputation (e.g., every Monday) |
| **After model changes** | Immediately recompute for all dates |
| **After bug fixes** | Recompute and re-run affected predictions |

---

## Evaluation Metrics

### Primary Metrics

| Metric | Formula | Target | Interpretation |
|--------|---------|--------|----------------|
| **MAE** | avg(\|predicted - actual\|) | < 5.0 | Lower = more accurate |
| **Bias** | avg(predicted - actual) | ~ 0 | Positive = over-predict, Negative = under-predict |
| **Win Rate** | % of correct over/under calls | > 52% | Higher = more profitable |

### Secondary Metrics

| Metric | Purpose |
|--------|---------|
| MAE by Tier | Identify weak spots by player type |
| MAE by System | Compare prediction systems |
| MAE by Context | Home/away, back-to-back, etc. |
| Within 3pt % | Predictions within 3 points of actual |
| Within 5pt % | Predictions within 5 points of actual |

---

## Evaluation Queries

### Overall System Performance

```sql
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as MAE,
  ROUND(AVG(signed_error), 2) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct,
  ROUND(AVG(CASE WHEN absolute_error <= 3 THEN 1 ELSE 0 END) * 100, 1) as within_3pt_pct,
  ROUND(AVG(CASE WHEN absolute_error <= 5 THEN 1 ELSE 0 END) * 100, 1) as within_5pt_pct
FROM `nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2021-12-01' AND '2022-01-07'
GROUP BY 1
ORDER BY MAE;
```

### Performance by Tier (Ensemble Only)

```sql
WITH predictions_with_tier AS (
  SELECT
    p.scoring_tier,
    pa.absolute_error,
    pa.signed_error,
    pa.prediction_correct
  FROM `nba_predictions.player_prop_predictions` p
  JOIN `nba_predictions.prediction_accuracy` pa
    USING (player_lookup, game_date, system_id)
  WHERE p.system_id = 'ensemble_v1'
    AND p.scoring_tier IS NOT NULL
)
SELECT
  scoring_tier,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 2) as MAE,
  ROUND(AVG(signed_error), 2) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct
FROM predictions_with_tier
GROUP BY 1
ORDER BY 1;
```

### Performance Over Time (Weekly)

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as MAE,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

### Worst Performing Players

```sql
SELECT
  player_lookup,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as MAE,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
HAVING COUNT(*) >= 10
ORDER BY MAE DESC
LIMIT 20;
```

---

## Iteration Workflow

### Step 1: Identify Problem Areas

After backfill, run evaluation queries to find:
- Which tiers have highest MAE?
- Which players are we worst at predicting?
- Is there a bias pattern (consistently over/under)?
- Are certain contexts harder (back-to-back, road games)?

### Step 2: Hypothesize Improvements

| Problem | Possible Solution |
|---------|-------------------|
| High bias for a tier | Adjust tier correction factors |
| Specific players always wrong | Add per-player adjustments |
| Back-to-back games have higher MAE | Add fatigue features |
| Road games have different bias | Add home/away context |

### Step 3: Test on Historical Data

```python
# Pseudo-code for testing a change
def test_improvement(change_description, new_predictions, historical_actuals):
    """
    Test a proposed change against historical data.

    1. Generate predictions with the change
    2. Compare MAE vs baseline
    3. Only deploy if MAE improves
    """
    baseline_mae = get_current_mae()
    new_mae = calculate_mae(new_predictions, historical_actuals)

    improvement = baseline_mae - new_mae

    if improvement > 0:
        print(f"✓ {change_description}: MAE improved by {improvement:.3f}")
        return True
    else:
        print(f"✗ {change_description}: MAE worsened by {-improvement:.3f}")
        return False
```

### Step 4: Deploy and Monitor

1. Update the relevant code/configuration
2. Re-run predictions for affected dates
3. Re-run grading
4. Validate with `validate_adjustments_improve_mae()`
5. Monitor daily metrics

---

## Available Adjustment Levers

### Tier Adjustment Factors

Located in `scoring_tier_adjuster.py`:

```python
DEFAULT_ADJUSTMENT_FACTORS = {
    'BENCH_0_9': 0.5,        # Apply 50% of computed adjustment
    'ROTATION_10_19': 0.5,   # Apply 50% of computed adjustment
    'STARTER_20_29': 0.75,   # Apply 75% of computed adjustment
    'STAR_30PLUS': 1.0,      # Apply 100% of computed adjustment
}
```

**To tune:** Change these factors and re-run predictions.

### Lookback Window

Located in `scoring_tier_processor.py`:

```python
processor = ScoringTierProcessor(
    lookback_days=30,      # How many days of history to use
    min_sample_size=20     # Minimum predictions per tier
)
```

**To tune:**
- Longer lookback = more stable but slower to adapt
- Shorter lookback = more responsive but noisier

### Ensemble Weights

Located in prediction system configuration:

```python
# Current: Equal weights
ensemble_weights = {
    'xgboost_v1': 0.25,
    'moving_average_baseline_v1': 0.25,
    'similarity_balanced_v1': 0.25,
    'zone_matchup_v1': 0.25,
}

# Could tune based on historical performance
```

---

## Future Improvements (Roadmap)

### Phase 1: Current (Tier Adjustments)
- [x] Compute tier-based bias corrections
- [x] Apply adjustments during prediction
- [x] Validate adjustments improve MAE

### Phase 2: Per-Player Adjustments
- [ ] Identify players with consistent bias
- [ ] Store per-player correction factors
- [ ] Apply on top of tier adjustments

### Phase 3: Context-Aware Adjustments
- [ ] Track performance by context (home/away, rest days, opponent)
- [ ] Add context features to models
- [ ] Apply context-specific corrections

### Phase 4: Automated Retraining
- [ ] Weekly automated adjustment recomputation
- [ ] Automated model retraining pipeline
- [ ] A/B testing infrastructure

---

## Validation Checklist

Before deploying any change:

- [ ] Run `validate_adjustments_improve_mae()` - must pass
- [ ] Check MAE improved (not just bias)
- [ ] Check all tiers improved (or at least didn't get worse)
- [ ] Test on multiple date ranges (not just one period)
- [ ] Document the change and rationale

---

## Related Files

| File | Purpose |
|------|---------|
| `data_processors/ml_feedback/scoring_tier_processor.py` | Compute adjustments |
| `data_processors/ml_feedback/scoring_tier_adjuster.py` | Apply adjustments |
| `backfill_jobs/grading/` | Grade predictions |
| `docs/09-handoff/2025-12-11-SESSION124-TIER-ADJUSTMENT-FIX.md` | Bug fix details |

---

## Quick Reference Commands

```bash
# Compute new tier adjustments
PYTHONPATH=. .venv/bin/python -c "
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor
processor = ScoringTierProcessor()
processor.process('2022-01-07')
"

# Validate adjustments help
PYTHONPATH=. .venv/bin/python -c "
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor
processor = ScoringTierProcessor()
processor.validate_adjustments_improve_mae('2021-12-05', '2022-01-07')
"

# Re-run predictions for a date range
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07 --no-resume

# Re-grade predictions
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07
```
