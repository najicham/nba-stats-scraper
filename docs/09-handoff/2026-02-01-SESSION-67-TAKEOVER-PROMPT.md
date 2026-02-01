# Session 67 Takeover Prompt

**Date:** 2026-02-01
**Priority:** Run ML experiments to find a model that actually works

---

## Start Here

```bash
# Read the experiment plan first
cat docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md
```

---

## Critical Context

### Session 66 Discovery: Data Leakage Bug

The V8 model's reported 84% hit rate was **FAKE**. A data leakage bug in `player_daily_cache_processor.py` included the current game's stats in rolling averages:

```python
# BUG (before Jan 26): Included current game (cheating!)
WHERE game_date <= '{analysis_date}'

# FIX (after Jan 26): Correctly excludes current game
WHERE game_date < '{analysis_date}'
```

**Impact:** ALL historical predictions (2021 - Jan 8, 2026) used leaked data.

### True Model Performance (Post-Fix, No Leakage)

| Filter | Predictions | Hit Rate |
|--------|-------------|----------|
| Premium (92+ conf, 3+ edge) | 59 | **52.5%** |
| High Conf (92+) | 136 | **58.1%** |
| High Edge (5+) | 437 | **57.0%** |
| Standard | 1,156 | **51.1%** |

The model is barely better than random. We need experiments to find a better approach.

---

## Your Task: Run Experiments

Use the `/model-experiment` skill to train and evaluate challenger models. We need to find training configurations that produce a model with TRUE hit rate > 55%.

### Priority Order

```bash
# PRIORITY 1: Current season only (avoids all distribution issues)
/model-experiment exp_20260201_current_szn

# PRIORITY 2: Different recency weightings
/model-experiment exp_20260201_recency_90d
/model-experiment exp_20260201_recency_180d

# PRIORITY 3: Different data sources
/model-experiment exp_20260201_dk_only
/model-experiment exp_20260201_dk_bettingpros
/model-experiment exp_20260201_multi_book
```

### Why Current Season First?

The experiment plan (read it!) identifies multiple issues with historical data:
1. **team_win_pct bug** - was always 0.5 before Nov 2025
2. **Vegas imputation mismatch** - training vs inference handled differently
3. **Distribution shift** - NBA patterns change year-to-year

Training on **Nov 2025+ data only** avoids all these issues.

---

## Backfill Requirements

### Feature Store: Already Backfilled ✓
ML feature store was backfilled Nov 13 - Jan 30 with v37 features (Session 65).
No additional feature backfill needed.

### After Training a New Model

1. **Save the model** to `models/` directory
2. **Update model path** in prediction worker or backfill script
3. **Regenerate predictions** for evaluation:

```bash
# Regenerate Jan 9-31 predictions with new model
PYTHONPATH=. python ml/backfill_v8_predictions.py --start-date 2026-01-09 --end-date 2026-01-31
```

4. **Wait for grading** (runs automatically) or run manually:

```bash
# Check hit rate of new predictions
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3
    THEN 'Premium' ELSE 'Standard'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'YOUR_NEW_SYSTEM_ID'
  AND game_date >= '2026-01-09'
  AND prediction_correct IS NOT NULL
GROUP BY 1"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md` | **READ THIS FIRST** - Full experiment definitions |
| `ml/train_catboost_v8.py` | Model training script |
| `ml/backfill_v8_predictions.py` | Prediction backfill |
| `ml/experiments/` | Experiment framework |
| `models/` | Trained model files |

---

## Success Criteria

1. **Train multiple models** with different configurations
2. **Evaluate each on Jan 9-31, 2026** (post-fix data only!)
3. **Find configuration with premium hit rate > 55%**
4. **Document results** in experiment plan

### Minimum Bar to Beat

| Metric | V8 (Current) | Target |
|--------|--------------|--------|
| Premium Hit Rate | 52.5% | >55% |
| High Conf Hit Rate | 58.1% | >60% |
| MAE | 5.3 | <5.0 |

---

## Known Issues to Work Around

1. **Broken features**:
   - `pace_score`: 100% zeros (opponent_pace_last_10 NULL upstream)
   - `team_win_pct`: Was always 0.5 before Nov 2025

2. **Vegas coverage**: Only 44% of players in feature store have Vegas lines

3. **Small evaluation sample**: Only 59 premium picks in post-fix period
   - May need to use lower confidence threshold for larger sample
   - Or use full Jan 9-31 sample (1,788 predictions)

4. **Training data quality**: Historical data (before Nov 2025) has broken features
   - Recommend training on Nov 2025+ only

---

## Quick Start Checklist

```bash
# 1. Read the experiment plan (REQUIRED)
cat docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md

# 2. Check what experiments exist
ls -la ml/experiments/

# 3. Run the priority experiment
/model-experiment exp_20260201_current_szn

# 4. The skill will guide you through training and evaluation
```

---

## Session 66 Commits (Context)

```
dc354967 feat: Add features_snapshot field to predictions for debugging
6cd59f9f docs: Add Session 66 handoff - Data leakage root cause discovery
```

---

*Created: Session 66, 2026-02-01*
