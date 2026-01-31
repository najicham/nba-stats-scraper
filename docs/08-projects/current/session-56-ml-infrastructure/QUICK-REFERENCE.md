# Session 56 Quick Reference

## Run Performance Diagnostics

```bash
# Full analysis with persistence
PYTHONPATH=. python -c "
from datetime import date
from shared.utils.performance_diagnostics import run_diagnostics
results = run_diagnostics(date.today(), persist=True)
print(f'Root Cause: {results[\"primary_cause\"]} ({results[\"cause_confidence\"]:.0%})')
print(f'Alert: {results[\"alert_level\"]}')
"

# Quick alert check
PYTHONPATH=. python -c "
from shared.utils.performance_diagnostics import get_alert
alert = get_alert()
print(f'{alert[\"level\"]}: {alert[\"message\"]}')"
```

## Run Experiments with Registry

```bash
# New way: YAML config
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --config ml/experiments/configs/example_experiment.yaml

# Old way: CLI args (still works)
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 \
    --train-end 2026-01-15 \
    --experiment-id MY_EXP

# Without registry tracking
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 \
    --no-registry
```

## Query Experiment Registry

```sql
-- Recent experiments
SELECT experiment_name, status,
       JSON_VALUE(results_json, '$.hit_rate') as hit_rate,
       created_at
FROM nba_predictions.ml_experiments
ORDER BY created_at DESC
LIMIT 10;

-- Best performing
SELECT experiment_name,
       CAST(JSON_VALUE(results_json, '$.hit_rate') AS FLOAT64) as hit_rate
FROM nba_predictions.ml_experiments
WHERE status = 'completed'
ORDER BY hit_rate DESC
LIMIT 5;

-- Experiments with tag
SELECT * FROM nba_predictions.ml_experiments
WHERE 'recency-test' IN UNNEST(tags);
```

## Query Performance Diagnostics

```sql
-- Recent diagnostics
SELECT game_date,
       alert_level,
       primary_cause,
       hit_rate_7d,
       model_beats_vegas_pct,
       sharpness_status
FROM nba_orchestration.performance_diagnostics_daily
ORDER BY game_date DESC
LIMIT 7;

-- Alert history
SELECT game_date, alert_level, alert_message
FROM nba_orchestration.performance_diagnostics_daily
WHERE alert_triggered = TRUE
ORDER BY game_date DESC;

-- Trend analysis
SELECT
  FORMAT_DATE('%Y-%W', game_date) as week,
  AVG(hit_rate_7d) as avg_hit_rate,
  AVG(model_beats_vegas_pct) as avg_beats_vegas,
  COUNTIF(alert_level = 'critical') as critical_days
FROM nba_orchestration.performance_diagnostics_daily
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY 1;
```

## Deploy Schemas

```bash
# Performance diagnostics
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/performance_diagnostics_daily.sql

# Experiment registry
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/ml_experiments.sql
```

## Key Files

| Purpose | File |
|---------|------|
| Performance diagnostics schema | `schemas/bigquery/nba_orchestration/performance_diagnostics_daily.sql` |
| Experiment registry schema | `schemas/bigquery/nba_predictions/ml_experiments.sql` |
| Diagnostics class | `shared/utils/performance_diagnostics.py` |
| Registry class | `ml/experiment_registry.py` |
| Example YAML config | `ml/experiments/configs/example_experiment.yaml` |
| Config schema | `ml/experiments/configs/experiment_config_schema.yaml` |

## Alert Thresholds

| Level | Condition |
|-------|-----------|
| CRITICAL | model_beats_vegas < 42% AND hit_rate_7d < 50% |
| WARNING | drift_score >= 40 OR model_beats_vegas < 45% |
| INFO | Notable baseline deviation |
| OK | Normal operation |

## Root Cause Categories

| Cause | Meaning |
|-------|---------|
| VEGAS_SHARP | Market is unusually efficient |
| MODEL_DRIFT | Model performance degrading |
| DATA_QUALITY | Pipeline/feature issues |
| NORMAL_VARIANCE | Expected fluctuation |
