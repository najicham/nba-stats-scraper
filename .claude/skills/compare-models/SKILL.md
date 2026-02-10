---
name: compare-models
description: Compare challenger models vs champion and experiment backtest results
---

# Compare Models Skill

Compare shadow challenger models against the production champion and their original experiment backtest metrics. Shows whether models are performing as expected in real production conditions.

## Trigger
- User wants to check how challenger models are doing
- "How are the shadow models performing?"
- "Compare models", "model comparison", "challenger performance"
- "Model landscape", "all models"
- `/compare-models`

## What This Skill Does

1. Lists all active challengers from `catboost_monthly.py` MONTHLY_MODELS config
2. For each enabled challenger, queries production graded results from `prediction_accuracy`
3. Compares production performance vs backtest metrics (from config and `ml_experiments`)
4. Compares each challenger vs the champion (`catboost_v9`) over the same period
5. Shows segment breakdowns (direction, tier, line range) with auto-detected strengths
6. Flags any models underperforming their backtest expectations

## How to Run

### Landscape view (all models at once)

```bash
# Compare all enabled models + champion in one table
PYTHONPATH=. python bin/compare-model-performance.py --all --days 7

# With segment breakdowns for each model
PYTHONPATH=. python bin/compare-model-performance.py --all --segments --days 7
```

### Single model comparison

```bash
# Compare a specific challenger (default: last 7 days)
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108

# With segment breakdowns
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --segments --days 7

# Compare with more history
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 14
```

### List models with strength profiles

```bash
# List all challenger models, backtest metrics, and strength profiles
PYTHONPATH=. python bin/compare-model-performance.py --list
```

### BQ queries for deeper analysis

```sql
-- All challengers: daily hit rates
SELECT system_id, game_date,
    COUNT(*) as n,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
    ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE 'catboost_v9_%'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY 2 DESC, 1;

-- Champion vs challengers side by side
SELECT system_id,
    COUNT(*) as n_graded,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate_all,
    ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_margin) >= 3)
        / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hit_rate_3plus,
    COUNTIF(ABS(predicted_margin) >= 3) as n_edge_3plus,
    ROUND(AVG(ABS(predicted_points - actual_points)), 3) as mae,
    ROUND(AVG(predicted_points - line_value), 2) as vegas_bias
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v9_train1102_0108',
                     'catboost_v9_train1102_0131_tuned',
                     'catboost_v9_q43_train1102_0131',
                     'catboost_v9_q45_train1102_0131')
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY hit_rate_all DESC;
```

## Interpreting Results

### Expected Gaps

Backtest metrics are always higher than production because:
- Backtest uses pre-computed features (no timing drift)
- Production predicts at 2:30 AM before all lines settle
- No line movement between prediction and game in backtest

**Expect 3-5pp lower hit rate in production vs backtest.** A challenger showing 58% HR All when backtest showed 62.4% is performing as expected.

### Segment Breakdowns

The `--segments` flag shows performance across:
- **Direction:** OVER HR, UNDER HR
- **Player Tier (by line):** Stars (25+), Starters (15-24), Role (5-14), Bench (<5)
- **Line Range:** Low (<12.5), Mid (12.5-20.5), High (>20.5)
- **Cross-segments:** Direction x Tier (UNDER variants)

Segments with HR >= 58% and N >= 5 are auto-detected as **strengths** (marked with `***`).

### Decision Framework

| Model Type | Key Metric | Promotion Threshold |
|------------|-----------|-------------------|
| RMSE (standard) | HR Edge 3+ | 3+ pp better than champion, 5+ game days |
| Quantile (alpha < 0.5) | UNDER HR + HR Edge 3+ | 55%+ HR in production, UNDER-heavy expected |

**Minimum data:** 2+ game days with graded results before drawing conclusions. Ideally 5+ game days.

### Red Flags

- **Vegas bias > +/- 1.5**: Model is miscalibrated vs market (expected for quantile models — Q43 targets ~-1.6)
- **Directional imbalance (RMSE models)**: One direction below 52.4%
- **Directional imbalance (quantile models)**: UNDER HR below 55% — quantile edge not working
- **MAE much higher than backtest** (> 1.0 higher): Feature pipeline issue
- **Zero predictions**: Model failed to load — check worker logs

## Active Challengers (Session 187)

| system_id | Type | Strengths | Watch For |
|-----------|------|-----------|-----------|
| `catboost_v9` (champion) | RMSE, Jan 8 | All-around but decaying | HR 3+ below breakeven (47.9%) |
| `catboost_v9_train1102_0108` | RMSE, Jan 8, clean | Best edge 3+ HR (58.3%), balanced | Sustained edge vs champion |
| `catboost_v9_train1102_0131_tuned` | RMSE, Jan 31, tuned | RMSE baseline | Few edge picks (n=6) |
| `catboost_v9_q43_train1102_0131` | Quantile 0.43 | UNDER specialist: Starters UNDER 85.7%, High Lines 76.5% | UNDER HR, staleness stability |
| `catboost_v9_q45_train1102_0131` | Quantile 0.45 | Less aggressive: Role UNDER 78.6% | UNDER HR, fewer edge picks |

## Monitoring Strategy (Per-Model)

| Model | Monitor These Segments | Strength Threshold |
|-------|----------------------|-------------------|
| Champion | HR 3+ (overall) | Above 52.4% (breakeven) |
| _0108 | HR 3+ (overall), OVER/UNDER balance | HR 3+ >= 55% |
| Q43 | UNDER HR, Starters UNDER, High Lines | UNDER HR >= 60%, HR 3+ >= 55% |
| Q45 | UNDER HR, Role UNDER, Mid Lines | UNDER HR >= 58%, HR 3+ >= 55% |
| _0131_tuned | HR All (baseline comparison only) | N/A — RMSE baseline |

## Files

| File | Purpose |
|------|---------|
| `bin/compare-model-performance.py` | Main comparison script (--all, --segments, --list) |
| `bin/model-registry.sh compare` | Wrapper for comparison script |
| `predictions/worker/prediction_systems/catboost_monthly.py` | MONTHLY_MODELS config with strengths |
| `docs/08-projects/current/session-179-validation-and-retrain/06-MODEL-MONITORING-STRATEGY.md` | Full monitoring guide |
| `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md` | Parallel models guide |

---
*Created: Session 177*
*Updated: Session 187 — added --all, --segments, strength profiles, quantile models*
*Part of: Retrain Infrastructure / Parallel Models*
