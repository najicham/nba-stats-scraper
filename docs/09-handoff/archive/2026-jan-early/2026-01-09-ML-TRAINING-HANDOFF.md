# ML Model Training Handoff - January 9, 2026

**Purpose**: Guide for another chat session to work on ML model training/improvement
**Status**: Ready for ML work

---

## Executive Summary

The prediction system has 470K graded predictions from 4 seasons (2021-2025) ready for ML training. The current models are baseline implementations. This session should focus on improving model accuracy.

---

## Current State

### Data Available

| Dataset | Location | Records | Notes |
|---------|----------|---------|-------|
| **Graded Predictions** | `nba_predictions.prediction_accuracy` | 470K | 4 seasons, includes actual results |
| **Daily Performance** | `nba_predictions.system_daily_performance` | - | Aggregated daily metrics |
| **ML Features** | `nba_precompute.player_composite_factors` | - | Pre-computed features |
| **Player Stats** | `nba_analytics.player_game_summary` | - | Per-game stats |
| **Team Stats** | `nba_analytics.team_offense_game_summary` | - | Team-level metrics |

### Current Models

Located in `models/`:
- `pts_model.joblib` - Points prediction model
- `base_predictor.py` - Base prediction class

### Model Architecture

```
services/prediction/
├── prediction_coordinator.py      # Orchestrates prediction generation
├── prediction_worker.py           # Cloud Run worker for predictions
└── models/
    └── base_predictor.py          # Base model class
```

---

## Quick Start

### 1. Check Current Model Performance

```bash
# Get accuracy metrics for recent predictions
bq query --use_legacy_sql=false "
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  prop_type,
  COUNT(*) as predictions,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as accuracy_pct,
  ROUND(AVG(ABS(predicted_value - actual_value)), 2) as avg_error
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-01-01'
GROUP BY 1, 2
ORDER BY 1 DESC, 2"
```

### 2. Export Training Data

```bash
# Export graded predictions for training
bq extract \
  --destination_format=CSV \
  'nba-props-platform:nba_predictions.prediction_accuracy' \
  'gs://nba-scraped-data/exports/training/prediction_accuracy_*.csv'
```

### 3. Access Feature Data

```sql
-- Get player composite factors (ML features)
SELECT
  player_id,
  game_date,
  recent_pts_avg,
  recent_usage_rate,
  opponent_def_rating,
  home_away,
  -- Many more features available
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2024-10-01'
```

---

## Training Improvement Ideas

### Priority 1: Points Model Improvements

1. **Feature Engineering**
   - Add pace adjustment features
   - Include opponent-specific defensive metrics
   - Add rest days and back-to-back indicators
   - Include injury report data (key player absences)

2. **Model Selection**
   - Try XGBoost or LightGBM instead of baseline
   - Consider ensemble approaches
   - Evaluate neural network for complex patterns

3. **Calibration**
   - Analyze prediction distribution vs actual outcomes
   - Adjust confidence thresholds

### Priority 2: Add New Prop Types

Current: Points only
Target: Add rebounds, assists, 3-pointers, steals, blocks

Each prop type needs:
1. Feature set tuning (e.g., rebounds correlate with opponent rebounding rate)
2. Separate model training
3. Calibration against historical data

### Priority 3: Real-time Updates

- Incorporate late-breaking injury news
- Adjust for lineup changes
- Consider Vegas line movements as signal

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `services/prediction/prediction_coordinator.py` | Main prediction orchestrator |
| `services/prediction/prediction_worker.py` | Worker service |
| `services/prediction/models/base_predictor.py` | Base model implementation |
| `data_processors/precompute/player_composite_factors/` | Feature computation |
| `bin/predictions/deploy/` | Deployment scripts |

---

## BigQuery Tables Schema

### prediction_accuracy (graded predictions)
```sql
SELECT column_name, data_type
FROM nba_predictions.INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'prediction_accuracy'
```

Key columns:
- `player_id`, `player_name`
- `game_date`, `game_id`
- `prop_type` (e.g., 'points')
- `predicted_value`, `actual_value`
- `prediction_correct` (boolean)
- `over_under` ('over' or 'under')
- `line_value` (Vegas line)
- `confidence` (model confidence)

### player_composite_factors (features)
Key features:
- `recent_pts_avg`, `recent_reb_avg`, `recent_ast_avg`
- `recent_usage_rate`
- `opponent_def_rating`, `opponent_pace`
- `home_away`
- `days_rest`
- Many more (~50 features)

---

## Validation Commands

```bash
# Check feature freshness
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as latest_features
FROM nba_precompute.player_composite_factors"

# Check prediction coverage
bq query --use_legacy_sql=false "
SELECT
  prop_type,
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  COUNT(*) as total
FROM nba_predictions.prediction_accuracy
GROUP BY prop_type"

# Check model accuracy trend
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as predictions,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as accuracy
FROM nba_predictions.prediction_accuracy
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY game_date
ORDER BY game_date DESC"
```

---

## Environment Setup

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
export PYTHONPATH=.

# Run local tests
pytest tests/services/prediction/ -v

# Test prediction locally
python -m services.prediction.prediction_worker --test
```

---

## Deployment After Training

```bash
# After training new models, deploy:
./bin/predictions/deploy/deploy_prediction_worker.sh

# Test the deployed service
./bin/predictions/test_prediction_service.sh
```

---

## Notes

- ESPN roster automation was just fixed (Jan 9)
- Daily pipeline is fully operational
- Schedulers are running normally
- MLB pipeline is paused (lower priority)

---

## Contact Points

- Prediction tables: `nba_predictions.*`
- Feature tables: `nba_precompute.*`
- Raw stats: `nba_analytics.*`
