# Skill: Experiment Tracker

Track, compare, and manage ML experiments.

## Trigger
- User asks about experiments, model comparisons, or ML tracking
- User types `/experiment-tracker`
- "What experiments have we run?", "Compare the latest models"

## Workflow

1. Query ml_experiments table for recent experiments
2. Compare results across experiments
3. Show experiment details and recommendations

## List Recent Experiments Query

```sql
SELECT
  experiment_id,
  experiment_name,
  experiment_type,
  status,
  STRUCT(train_period.start_date, train_period.end_date) as training,
  STRUCT(eval_period.start_date, eval_period.end_date) as evaluation,
  ROUND(CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64), 1) as hit_rate,
  ROUND(CAST(JSON_VALUE(results_json, '$.overall.mae') AS FLOAT64), 2) as mae,
  tags,
  created_at
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY created_at DESC
LIMIT 20
```

## Compare Experiments Query

```sql
SELECT
  experiment_name,
  status,
  JSON_VALUE(results_json, '$.overall.hit_rate') as hit_rate,
  JSON_VALUE(results_json, '$.overall.mae') as mae,
  JSON_VALUE(results_json, '$.overall.roi') as roi,
  JSON_VALUE(results_json, '$.by_tier.star.hit_rate') as star_hit_rate,
  JSON_VALUE(results_json, '$.by_tier.starter.hit_rate') as starter_hit_rate,
  JSON_VALUE(results_json, '$.by_edge.edge_3plus.hit_rate') as edge_3plus_hit_rate
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE status IN ('completed', 'promoted')
ORDER BY
  CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64) DESC
LIMIT 10
```

## Get Experiment Details Query

```sql
SELECT
  experiment_id,
  experiment_name,
  hypothesis,
  experiment_type,
  config_json,
  train_period,
  eval_period,
  results_json,
  model_path,
  git_commit,
  status,
  tags,
  created_at,
  completed_at
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE experiment_id = @experiment_id
```

## Find Best Experiment Query

```sql
SELECT
  experiment_name,
  experiment_id,
  CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64) as hit_rate,
  CAST(JSON_VALUE(results_json, '$.overall.mae') AS FLOAT64) as mae,
  model_path,
  eval_period.start_date as eval_start,
  eval_period.end_date as eval_end
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE status = 'completed'
  AND eval_period.end_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
ORDER BY CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64) DESC
LIMIT 5
```

## Experiments by Tag Query

```sql
SELECT
  experiment_name,
  status,
  JSON_VALUE(results_json, '$.overall.hit_rate') as hit_rate,
  created_at
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE 'recency-test' IN UNNEST(tags)  -- Replace with search tag
ORDER BY created_at DESC
```

## Using Python Registry

```python
from ml.experiment_registry import ExperimentRegistry

registry = ExperimentRegistry()

# List recent experiments
experiments = registry.list_experiments(status="completed", limit=10)

# Get experiment details
exp = registry.get_experiment("550e8400-e29b-41d4-a716-446655440000")

# Find best experiment
best = registry.get_best_experiment(metric="hit_rate")

# Promote to production
registry.promote_experiment(experiment_id="...")
```

## Quality Metadata

When reviewing experiment results, also log the quality distribution of the training and evaluation data. This helps identify whether poor model performance is caused by low-quality input data rather than model issues.

```sql
-- Quality distribution for an experiment's training period
SELECT
  ROUND(100.0 * COUNTIF(is_quality_ready = TRUE) / COUNT(*), 1) as pct_quality_ready,
  ROUND(AVG(feature_quality_score), 1) as avg_feature_quality_score,
  COUNTIF(quality_alert_level = 'red') as red_alert_count,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN @train_start AND @train_end
```

Include `pct_quality_ready` and `avg_feature_quality_score` alongside hit rate and MAE when comparing experiments. A model trained on 90%+ quality-ready data is more trustworthy than one trained on 60%.

## Output Format

```
Recent Experiments (Last 30 Days)
=================================

| Name              | Type        | Status    | Hit Rate | MAE  | Tags                |
|-------------------|-------------|-----------|----------|------|---------------------|
| JAN_DEC_ONLY      | walk_forward| completed | 54.7%    | 4.53 | recency, jan-2026   |
| REC_60_HALFLIFE   | walk_forward| completed | 52.1%    | 4.78 | recency-test        |
| V8_BASELINE       | walk_forward| promoted  | 49.4%    | 4.89 | production, v8      |

Best Performing (Last 60 Days):
  1. JAN_DEC_ONLY: 54.7% hit rate (Dec training)
  2. REC_60_HALFLIFE: 52.1% hit rate (60-day recency)
  3. V8_BASELINE: 49.4% hit rate (current production)

Experiment Details: JAN_DEC_ONLY
--------------------------------
ID: 550e8400-e29b-41d4-a716-446655440000
Hypothesis: Training on recent December data improves January predictions
Training: 2025-12-01 to 2025-12-31 (4,415 samples)
Evaluation: 2026-01-01 to 2026-01-30

Results by Tier:
| Tier     | Hit Rate | MAE  |
|----------|----------|------|
| Star     | 53.5%    | 5.21 |
| Starter  | 55.8%    | 4.12 |
| Rotation | 52.1%    | 4.45 |

Model Path: ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131.cbm
Git Commit: abc123
```

## Commands

- `/experiment-tracker` - List recent experiments
- `/experiment-tracker compare` - Compare top experiments
- `/experiment-tracker <name>` - Get details for specific experiment
- `/experiment-tracker best` - Show best performing experiments
- `/experiment-tracker tags <tag>` - Find by tag
