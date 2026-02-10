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
- `/compare-models`

## What This Skill Does

1. Lists all active challengers from `catboost_monthly.py` MONTHLY_MODELS config
2. For each enabled challenger, queries production graded results from `prediction_accuracy`
3. Compares production performance vs backtest metrics (from config and `ml_experiments`)
4. Compares each challenger vs the champion (`catboost_v9`) over the same period
5. Flags any models underperforming their backtest expectations

## How to Run

### Quick: Compare all challengers

```bash
# List all challenger models and their backtest metrics
PYTHONPATH=. python bin/compare-model-performance.py --list

# Compare a specific challenger (default: last 7 days)
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108

# Compare with more history
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 14

# Via model-registry wrapper
./bin/model-registry.sh compare catboost_v9_train1102_0108
```

### Full comparison of all challengers

Run comparison for each enabled challenger:

```bash
for sid in catboost_v9_train1102_0108 catboost_v9_train1102_0208 catboost_v9_train1102_0208_tuned; do
    echo ""; echo "========================================";
    PYTHONPATH=. python bin/compare-model-performance.py $sid --days 7
done
```

### BQ queries for deeper analysis

```sql
-- All challengers: daily hit rates
SELECT system_id, game_date,
    COUNT(*) as n,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
    ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE 'catboost_v9_train%'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY 2 DESC, 1;

-- Champion vs challengers side by side
SELECT system_id,
    COUNT(*) as n_graded,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate_all,
    ROUND(100.0 * COUNTIF(prediction_correct AND ABS(edge) >= 3)
        / NULLIF(COUNTIF(ABS(edge) >= 3), 0), 1) as hit_rate_3plus,
    COUNTIF(ABS(edge) >= 3) as n_edge_3plus,
    ROUND(AVG(ABS(predicted_points - actual_points)), 3) as mae,
    ROUND(AVG(predicted_points - line_value), 2) as vegas_bias
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v9_train1102_0108',
                     'catboost_v9_train1102_0208', 'catboost_v9_train1102_0208_tuned')
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY hit_rate_all DESC;

-- Check experiment backtest metrics for comparison
SELECT experiment_name, experiment_id,
    JSON_EXTRACT_SCALAR(results_json, '$.mae') as backtest_mae,
    JSON_EXTRACT_SCALAR(results_json, '$.hit_rate_all') as backtest_hr_all,
    JSON_EXTRACT_SCALAR(results_json, '$.hit_rate_edge_3plus') as backtest_hr_3plus,
    JSON_EXTRACT_SCALAR(results_json, '$.bets_edge_3plus') as backtest_n_3plus
FROM nba_predictions.ml_experiments
WHERE experiment_name IN ('V9_BASELINE_CLEAN', 'V9_FULL_FEB', 'V9_TUNED_FEB')
ORDER BY experiment_name;
```

## Interpreting Results

### Expected Gaps

Backtest metrics are always higher than production because:
- Backtest uses pre-computed features (no timing drift)
- Production predicts at 2:30 AM before all lines settle
- No line movement between prediction and game in backtest

**Expect 3-5pp lower hit rate in production vs backtest.** A challenger showing 58% HR All when backtest showed 62.4% is performing as expected.

### Decision Framework

| Production HR All | vs Champion | Action |
|-------------------|-------------|--------|
| 3+ pp better | Consistently better | Consider promotion |
| Within 3pp | Similar | Keep monitoring, need more data |
| 3+ pp worse | Consistently worse | Retire the challenger |

**Minimum data:** 2+ game days with graded results before drawing conclusions. Ideally 5+ game days.

### Red Flags

- **Vegas bias > +/- 1.5**: Model is miscalibrated vs market
- **Directional imbalance**: One direction (OVER or UNDER) below 52.4%
- **MAE much higher than backtest** (> 1.0 higher): Feature pipeline issue
- **Zero predictions**: Model failed to load — check worker logs

## Active Challengers (Session 177)

| system_id | Experiment | Backtest HR All | Backtest HR 3+ |
|---|---|---|---|
| `catboost_v9_train1102_0108` | V9_BASELINE_CLEAN | 62.4% | 87.0% (n=131) |
| `catboost_v9_train1102_0208` | V9_FULL_FEB | 75.4%* | 91.8%* (n=159) |
| `catboost_v9_train1102_0208_tuned` | V9_TUNED_FEB | 74.8%* | 93.0%* (n=157) |

*Contaminated backtest (train/eval overlap). Real performance will be much lower.

## Files

| File | Purpose |
|------|---------|
| `bin/compare-model-performance.py` | Main comparison script |
| `bin/model-registry.sh compare` | Wrapper for comparison script |
| `predictions/worker/prediction_systems/catboost_monthly.py` | MONTHLY_MODELS config |
| `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md` | Full guide |

---
*Created: Session 177*
*Part of: Retrain Infrastructure / Parallel Models*
