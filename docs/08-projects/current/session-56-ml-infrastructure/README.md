# Session 56: ML Infrastructure Improvements

**Date:** 2026-01-31
**Status:** Implementation Complete
**Focus:** Production diagnostics, experiment tracking, backtest methodology

---

## Executive Summary

Session 56 addressed three critical infrastructure gaps:

1. **Production-Backtest Gap Investigation** - Discovered why backtest shows 49% while production hits 57%
2. **Performance Diagnostics System** - Unified monitoring for Vegas sharpness, model drift, data quality
3. **Experiment Registry System** - Centralized tracking for ML experiments with YAML configs

---

## 1. Production-Backtest Gap Investigation

### The Problem

Session 55 claimed JAN_DEC model (54.7%) beat V8 (49.4%). But production V8 actually hits **56.97-59%**.

### Root Cause Analysis

| Hypothesis | Finding | Impact |
|------------|---------|--------|
| Vegas Line Timing | NOT an issue - lines match within 0.02 pts | None |
| Sample Population | MAJOR - backtest includes 60% more player-games | ~5% |
| Missing Dates | MAJOR - 8 dates missing from production grading | ~2-3% |
| Line Type Mixing | MAJOR - 72% are estimated, not actual prop lines | Unknown |

### Key Evidence

```
Production predictions: 1,931 samples
Feature Store (has_vegas_line=1.0): 3,039 samples

Missing dates in production (but in feature store):
- 2026-01-19: 148 entries
- 2026-01-21-24: ~400 entries
- 2026-01-29-30: ~245 entries
```

### Implications

1. **Backtest results CANNOT be directly compared to production hit rates**
2. **Model A vs Model B comparisons are still valid** (same backtest population)
3. **JAN_DEC deployment NOT recommended** - would likely be a downgrade

### How to Fix

Option 1: Filter backtest to production-only samples
```sql
WHERE EXISTS (
  SELECT 1 FROM prediction_accuracy pa
  WHERE pa.player_lookup = f.player_lookup
    AND pa.game_date = f.game_date
)
```

Option 2: Accept backtest shows different absolute numbers, use for relative comparisons only.

---

## 2. Performance Diagnostics System

### Purpose

When prediction performance dips, quickly determine:
- Is Vegas getting sharper? (market issue)
- Is the model drifting? (model issue)
- Is it data quality? (pipeline issue)

### Components Created

| File | Purpose |
|------|---------|
| `schemas/bigquery/nba_orchestration/performance_diagnostics_daily.sql` | Storage schema |
| `shared/utils/performance_diagnostics.py` | Analysis class |

### Schema Fields

**Vegas Sharpness (6 fields)**
- `vegas_mae_tier1/2/3` - MAE by confidence tier
- `model_beats_vegas_pct` - % where model closer than Vegas
- `sharpness_score` - Composite 0-100 score
- `sharpness_status` - 'dull', 'normal', 'sharp', 'razor_sharp'

**Model Drift (7 fields)**
- `hit_rate_7d/14d/30d` - Rolling hit rates
- `model_mae`, `model_mean_error` - Error metrics
- `bias_direction` - 'under', 'neutral', 'over'
- `drift_score`, `drift_severity` - Composite drift tracking

**Root Cause Attribution (3 fields)**
- `primary_cause` - 'vegas_sharpness', 'model_drift', 'data_quality', 'none'
- `cause_confidence` - 0.0-1.0 confidence score
- `contributing_factors` - JSON array with factor details

**Alert Status (3 fields)**
- `alert_triggered`, `alert_level`, `alert_message`

### Usage

```python
from shared.utils.performance_diagnostics import run_diagnostics, get_alert

# Full analysis with persistence
results = run_diagnostics(game_date=date.today(), persist=True)

# Quick alert check
alert = get_alert()
print(f"Level: {alert['level']}, Message: {alert['message']}")
```

### Alert Thresholds

| Level | Condition |
|-------|-----------|
| CRITICAL | model_beats_vegas < 42% AND hit_rate_7d < 50% |
| WARNING | drift_score >= 40 OR model_beats_vegas < 45% |
| INFO | Notable changes from baseline |

---

## 3. Experiment Registry System

### Purpose

Track ML experiments in BigQuery with:
- Centralized registry (queryable)
- YAML config files (reproducible)
- Git commit tracking (auditable)
- Status lifecycle (pending → running → completed/failed → promoted)

### Components Created

| File | Purpose |
|------|---------|
| `schemas/bigquery/nba_predictions/ml_experiments.sql` | Registry table |
| `ml/experiment_registry.py` | Python interface |
| `ml/experiments/configs/experiment_config_schema.yaml` | YAML schema |
| `ml/experiments/configs/example_experiment.yaml` | Example config |
| `ml/experiments/train_walkforward.py` | Updated with registry |

### Registry Table Fields

```sql
-- Identity
experiment_id STRING,           -- UUID
experiment_name STRING,         -- Human-readable
hypothesis STRING,              -- What we're testing

-- Configuration
experiment_type STRING,         -- walk_forward, ensemble, etc.
config_json JSON,               -- Full config
tags ARRAY<STRING>,             -- Labels

-- Periods
train_period STRUCT<start_date, end_date, samples>,
eval_period STRUCT<start_date, end_date, samples>,

-- Results
results_json JSON,              -- MAE, hit_rate, ROI, etc.
model_path STRING,              -- GCS path
git_commit STRING,              -- Commit hash

-- Lifecycle
status STRING,                  -- pending, running, completed, failed, promoted
```

### Example YAML Config

```yaml
experiment_name: FEB_2026_RECENCY_60
hypothesis: "60-day half-life improves February predictions"
experiment_type: walk_forward

training:
  start_date: "2021-11-01"
  end_date: "2026-01-31"

evaluation:
  start_date: "2026-02-01"
  end_date: "2026-02-15"

model:
  type: catboost
  version: v9
  hyperparameters:
    depth: 6
    learning_rate: 0.07

recency:
  enabled: true
  half_life_days: 60

tags:
  - february-2026
  - recency-test
```

### Usage

```bash
# Train with YAML config (new way)
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --config ml/experiments/configs/my_experiment.yaml

# Train with CLI args (backward compatible)
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 --experiment-id TEST

# Disable registry tracking
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 --no-registry
```

```python
from ml.experiment_registry import ExperimentRegistry

registry = ExperimentRegistry()

# List recent experiments
experiments = registry.list_experiments(status="completed", limit=10)

# Find best performing
best = registry.get_best_experiment(metric="hit_rate")

# Promote to production
registry.promote_experiment(experiment_id="...")
```

---

## Files Created This Session

### Schemas
- `schemas/bigquery/nba_orchestration/performance_diagnostics_daily.sql`
- `schemas/bigquery/nba_predictions/ml_experiments.sql`

### Python Modules
- `shared/utils/performance_diagnostics.py`
- `ml/experiment_registry.py`

### Configs
- `ml/experiments/configs/experiment_config_schema.yaml`
- `ml/experiments/configs/example_experiment.yaml`

### Modified
- `ml/experiments/train_walkforward.py` - Added registry integration

---

## Next Steps

### Immediate (This Week)
1. Deploy BigQuery schemas
2. Run Cloud Function integration for daily diagnostics
3. Backfill experiment registry with recent experiments

### Short-Term (Next 2 Weeks)
1. Add Slack alerting for diagnostics
2. Create dashboard view for experiment comparison
3. Add shadow mode for A/B testing

### Research Questions Answered

| Question | Answer |
|----------|--------|
| Why 57% production vs 49% backtest? | Sample population difference (60% more in backtest) |
| Should we deploy JAN_DEC? | NO - production V8 is already better |
| Can we predict Vegas sharpness? | YES - 14% predictable swing identified |
| Are trajectory features useful? | Maybe - zscore shows -0.29 correlation with error |

---

## Key Learnings

1. **Always validate backtest methodology against production** - The 8% gap was a methodology issue, not a model issue.

2. **Production is the ground truth** - When backtest and production disagree, trust production and investigate why.

3. **Unified monitoring prevents finger-pointing** - When performance dips, having Vegas sharpness + model drift + data quality in one view enables quick root cause attribution.

4. **Experiment tracking enables learning** - Without a registry, we repeat experiments and lose institutional knowledge.

---

*Session 56 Complete*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
