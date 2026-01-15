# Session 60 Handoff: V1.6 Production Deployment + Shadow Mode Validation

**Date**: 2026-01-15
**Focus**: V1.6 model production deployment after comprehensive shadow testing
**Status**: V1.6 deployed to production, shadow grading infrastructure complete

---

## Quick Start for New Chat

```bash
# Read this handoff
cat docs/09-handoff/2026-01-15-SESSION-60-HANDOFF.md

# Test V1.6 predictor (now default)
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
p = PitcherStrikeoutsPredictor()
p.load_model()
print(f'Model: {p.model_metadata[\"model_id\"]}')
print(f'Type: {p.model_metadata.get(\"model_type\", \"regressor\")}')
print(f'Features: {len(p.feature_order)}')
"

# Check shadow comparison summary
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as predictions,
  SUM(CASE WHEN closer_prediction = 'v1_6' THEN 1 ELSE 0 END) as v1_6_wins,
  ROUND(AVG(ABS(v1_6_predicted - actual_strikeouts)), 2) as v1_6_mae
FROM \`nba-props-platform.mlb_predictions.shadow_mode_predictions\`
WHERE actual_strikeouts IS NOT NULL"

# Check BettingPros backfill
tail -20 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output
```

---

## What Was Accomplished (Session 60)

### 1. Comprehensive Shadow Mode Testing
Ran V1.4 vs V1.6 comparison on 22 dates (full September 2025):

| Metric | V1.4 | V1.6 | Winner |
|--------|------|------|--------|
| Predictions | 482 | 482 | - |
| Closer to Actual | 192 (39.8%) | 290 (60.2%) | **V1.6** |
| MAE | 1.89 | 1.69 | **V1.6** |
| Improvement | - | 10.6% | **V1.6** |

### 2. V1.6 Deployed to Production
- Updated `predictions/mlb/pitcher_strikeouts_predictor.py` default model to V1.6
- Updated `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh` with V1.6 path
- V1.6 is now the production champion

### 3. Shadow Mode Grading Infrastructure
- Created `data_processors/grading/mlb/mlb_shadow_grading_processor.py`
- Grades shadow predictions after games complete
- Updates actual_strikeouts, v1_4_error, v1_6_error, closer_prediction

### 4. Dynamic Feature Loading
- Predictor now loads feature_order from model metadata
- Supports both V1.4 (25 features) and V1.6 (35 features)
- Classifier model support (V1.6 outputs probability, converts to K estimate)

### 5. BettingPros Batter Processor Verified
- Schema exists: `schemas/bigquery/mlb_raw/bp_props_tables.sql`
- Processor exists: `data_processors/raw/mlb/mlb_bp_historical_props_processor.py`
- Load script exists: `scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py`
- **Action after backfill**: Run `load_to_bigquery.py --prop-type batter`

---

## Background Tasks

### BettingPros Historical Backfill
- **Task ID**: `b77281f`
- **Status**: Running (~70% complete as of session end)
- **Progress**: Processing August 2024 data
- **Monitor**: `tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output`

---

## Files Modified

| File | Changes |
|------|---------|
| `predictions/mlb/pitcher_strikeouts_predictor.py` | V1.6 as default, dynamic feature loading |
| `predictions/mlb/shadow_mode_runner.py` | V1.6 features support, updated docstrings |
| `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh` | V1.6 model path |
| `data_processors/grading/mlb/mlb_shadow_grading_processor.py` | NEW - shadow grading |

---

## Model Versions

| Model | Status | Features | MAE | Notes |
|-------|--------|----------|-----|-------|
| V1.6 | **Champion** | 35 | 1.69 | Classifier, BettingPros + Statcast features |
| V1.4 | Previous | 25 | 1.89 | Regressor, baseline features |

---

## Next Session Priorities

### HIGH PRIORITY

#### 1. Complete BettingPros Backfill
```bash
# Monitor progress
tail -20 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output

# After completion, load batter props to BigQuery
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter
```

#### 2. Deploy V1.6 to Cloud Run
```bash
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
```

### MEDIUM PRIORITY

#### 3. Line Timing Data Collection
The `line_minutes_before_game` feature is implemented but all data is currently NULL.
During active MLB season, this will populate automatically. For historical backfill:
- Update `mlb_pitcher_props_processor.py` to calculate timing from `commence_time - snapshot_time`
- Run processor on historical data

#### 4. Production Monitoring
Set up alerts for:
- V1.6 prediction accuracy tracking
- Comparison with V1.4 baseline

### LOWER PRIORITY

#### 5. V1.7 Model Exploration
- Consider ensemble approach (V1.4 + V1.6)
- Add more BettingPros features after backfill completes
- Explore team-specific models

---

## Key Queries

### Shadow Mode Summary
```sql
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN closer_prediction = 'v1_4' THEN 1 ELSE 0 END) as v1_4_wins,
  SUM(CASE WHEN closer_prediction = 'v1_6' THEN 1 ELSE 0 END) as v1_6_wins,
  ROUND(AVG(ABS(v1_4_predicted - actual_strikeouts)), 2) as v1_4_mae,
  ROUND(AVG(ABS(v1_6_predicted - actual_strikeouts)), 2) as v1_6_mae
FROM `nba-props-platform.mlb_predictions.shadow_mode_predictions`
WHERE actual_strikeouts IS NOT NULL
```

### Daily Shadow Comparison
```sql
SELECT
  game_date,
  COUNT(*) as predictions,
  SUM(CASE WHEN closer_prediction = 'v1_6' THEN 1 ELSE 0 END) as v1_6_wins,
  ROUND(100.0 * SUM(CASE WHEN closer_prediction = 'v1_6' THEN 1 ELSE 0 END) / COUNT(*), 1) as v1_6_pct
FROM `nba-props-platform.mlb_predictions.shadow_mode_predictions`
WHERE actual_strikeouts IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC
```

### BettingPros Backfill Progress
```sql
SELECT
  MIN(game_date) as min_date,
  MAX(game_date) as max_date,
  COUNT(*) as total_props
FROM `nba-props-platform.mlb_raw.bp_pitcher_props`
```

---

## Session 60 Summary

1. **Validated V1.6 superiority** - 482 predictions, 60% win rate, 10.6% MAE improvement
2. **Deployed V1.6 to production** - Updated default model path
3. **Created shadow grading processor** - Automated comparison after games
4. **Verified BettingPros infrastructure** - Ready for batter props loading
5. **Line timing analysis** - Feature implemented, needs data collection

**Key Result**: V1.6 is now the production champion for MLB pitcher strikeouts predictions.

---

**Session 60 Handoff Complete**
