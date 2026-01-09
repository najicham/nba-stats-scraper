# Shadow Mode Implementation Guide

## Overview

Shadow mode runs the v8 model alongside the existing mock model without affecting production predictions. This allows real-world validation before full deployment.

## Components Created

### 1. Injury Filter (`predictions/shared/injury_filter.py`)

Checks injury status before generating predictions.

```python
from predictions.shared.injury_filter import InjuryFilter, check_injury_status

# Single player check
filter = InjuryFilter()
status = filter.check_player("lebron-james", date.today())

if status.should_skip:
    print(f"Skip: {status.message}")  # Player listed as OUT
elif status.has_warning:
    print(f"Warning: {status.message}")  # QUESTIONABLE/DOUBTFUL
else:
    # Generate prediction normally
    pass

# Batch check (more efficient)
statuses = filter.check_players_batch(
    ["lebron-james", "kevin-durant"],
    date.today()
)
```

### 2. CatBoost V8 System (`predictions/worker/prediction_systems/catboost_v8.py`)

Production ML model with 33 features achieving 3.40 MAE.

```python
from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8

system = CatBoostV8(use_local=True)

result = system.predict(
    player_lookup="lebron-james",
    features=features_dict,  # 25 base features
    betting_line=25.5,
    vegas_line=25.5,
    vegas_opening=24.5,
    minutes_avg_last_10=35.2,
    ppm_avg_last_10=0.65,
)

print(result)
# {
#   'system_id': 'catboost_v8',
#   'predicted_points': 27.3,
#   'confidence_score': 82.0,
#   'recommendation': 'OVER',
#   'model_type': 'catboost_v8_real'
# }
```

### 3. Shadow Mode Runner (`predictions/shadow_mode_runner.py`)

Runs both models and logs results.

```bash
# Run for today
PYTHONPATH=. python predictions/shadow_mode_runner.py

# Run for specific date
PYTHONPATH=. python predictions/shadow_mode_runner.py --date 2026-01-10

# Dry run (no BigQuery writes)
PYTHONPATH=. python predictions/shadow_mode_runner.py --dry-run
```

Output:
```
======================================================================
SHADOW MODE SUMMARY
======================================================================

Total predictions: 423

Prediction Differences (v8 - mock):
  Mean: +1.23 points
  Min:  -8.45 points
  Max:  +12.33 points

Recommendation Agreement:
  Same: 356 (84.2%)
  Different: 67 (15.8%)

Injury Warnings: 12 players flagged as QUESTIONABLE/DOUBTFUL

Edge Analysis (389 players with Vegas lines):
  v8 OVER signals (>1pt edge):  145
  v8 UNDER signals (>1pt edge): 132
======================================================================
```

### 4. Comparison Report (`predictions/shadow_mode_report.py`)

Compares predictions to actual results after games complete.

```bash
# Single date
PYTHONPATH=. python predictions/shadow_mode_report.py --date 2026-01-08

# Date range
PYTHONPATH=. python predictions/shadow_mode_report.py --start 2026-01-01 --end 2026-01-08

# JSON output
PYTHONPATH=. python predictions/shadow_mode_report.py --date 2026-01-08 --json
```

Output:
```
======================================================================
SHADOW MODE COMPARISON REPORT: 2026-01-08 to 2026-01-08
======================================================================

Total Predictions: 423
Predictions with Vegas Lines: 389

----------------------------------------------------------------------
MODEL ACCURACY
----------------------------------------------------------------------

Metric                    Mock            V8              Winner
-----------------------------------------------------------------
MAE                       4.82            3.51            v8
Median Error              3.45            2.67            v8
P90 Error                 10.23           8.12            v8
Within 3 pts              42.3%           51.2%           v8
Within 5 pts              68.1%           76.4%           v8
Betting Accuracy          58.2%           69.4%           v8

----------------------------------------------------------------------
HEAD-TO-HEAD COMPARISON
----------------------------------------------------------------------

Closer to Actual:
  Mock wins:  134 (31.7%)
  V8 wins:    267 (63.1%)
  Ties:       22 (5.2%)

V8 Win Rate: 66.6%
MAE Improvement: +27.2%

======================================================================

VERDICT: V8 significantly outperforms mock
======================================================================
```

## Data Flow

```
1. Shadow Mode Runner (daily)
   ├── Load players for today's games
   ├── Check injury status (filter OUT, flag QUESTIONABLE)
   ├── Run mock prediction (XGBoostV1)
   ├── Run v8 prediction (CatBoostV8)
   └── Write to: nba_predictions.shadow_mode_predictions

2. After Games Complete
   └── Comparison Report
       ├── Join predictions with actual results
       ├── Calculate MAE, accuracy metrics
       └── Determine which model performed better
```

## BigQuery Table

Predictions stored in `nba_predictions.shadow_mode_predictions`:

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Player identifier |
| game_date | DATE | Game date (partition key) |
| mock_predicted | FLOAT64 | Mock model prediction |
| mock_confidence | FLOAT64 | Mock confidence score |
| mock_recommendation | STRING | OVER/UNDER/PASS |
| v8_predicted | FLOAT64 | V8 model prediction |
| v8_confidence | FLOAT64 | V8 confidence score |
| v8_recommendation | STRING | OVER/UNDER/PASS |
| betting_line | FLOAT64 | Vegas prop line |
| injury_status | STRING | Player's injury status |
| injury_warning | BOOLEAN | True if QUESTIONABLE/DOUBTFUL |
| prediction_diff | FLOAT64 | v8 - mock |

## Deployment Schedule

### Week 1-2: Shadow Mode
```bash
# Daily cron job (run before games start)
0 10 * * * cd /path/to/repo && PYTHONPATH=. python predictions/shadow_mode_runner.py

# Daily report (run morning after games)
0 8 * * * cd /path/to/repo && PYTHONPATH=. python predictions/shadow_mode_report.py --date $(date -d "yesterday" +%Y-%m-%d)
```

### Week 3+: Gradual Rollout

If shadow mode shows v8 outperforming mock:
1. Update `predictions/worker/prediction_systems/xgboost_v1.py` to use v8 model
2. Or create new `xgboost_v8.py` and add to ensemble

## Success Criteria

Before full deployment, verify:

| Metric | Target | Shadow Mode Result |
|--------|--------|-------------------|
| MAE | < 3.5 | TBD |
| vs Mock | > 15% better | TBD |
| Betting Accuracy | > 65% | TBD |
| V8 Win Rate | > 55% | TBD |
| No errors | 100% success | TBD |

## Troubleshooting

### CatBoost model not loading
```bash
# Check model files exist
ls -la models/catboost_v8_*.cbm

# Verify catboost installed
pip install catboost
```

### No predictions generated
```bash
# Check players exist for date
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
result = client.query('''
  SELECT COUNT(*) as cnt
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = CURRENT_DATE()
''').result()
print(list(result)[0].cnt)
"
```

### Injury filter returning no data
```bash
# Check injury report table
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
result = client.query('''
  SELECT COUNT(*) as cnt, MAX(game_date) as latest
  FROM nba_raw.nbac_injury_report
''').result()
for row in result:
    print(f'Records: {row.cnt}, Latest: {row.latest}')
"
```
