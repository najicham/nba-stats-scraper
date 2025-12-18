# Phase 5B Prediction Grading Backfill Runbook

**Created:** 2025-12-17
**Last Updated:** 2025-12-18
**Status:** Current
**Purpose:** Backfill prediction_accuracy and related grading tables

---

## Overview

Phase 5B grades predictions against actual results. This runbook covers:
- `prediction_accuracy` - Per-prediction grading
- `system_daily_performance` - Daily aggregates by system
- `prediction_performance_summary` - Multi-dimensional aggregates (NEW)

### Key Discovery (December 2025)

**The Phase 5B infrastructure exists but the tables are EMPTY.**
- Schema: Exists
- Processor code: Exists
- Data: **Empty - needs backfill**

---

## Prerequisites

Before running Phase 5B backfill:

1. **Phase 5A predictions must exist** - Check `player_prop_predictions` has data
2. **Phase 3 game results must exist** - Check `player_game_summary` has actual points

```bash
# Verify predictions exist
bq query --use_legacy_sql=false '
SELECT COUNT(*) as predictions, MIN(game_date) as earliest, MAX(game_date) as latest
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE'

# Verify game results exist
bq query --use_legacy_sql=false '
SELECT COUNT(*) as games, MIN(game_date) as earliest, MAX(game_date) as latest
FROM nba_analytics.player_game_summary
WHERE points IS NOT NULL'
```

---

## Quick Start

### One-Command Backfill (Current Season)

```bash
# Backfill prediction accuracy for 2025-26 season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-10-21 \
  --end-date 2025-12-17
```

### Verify Success

```bash
# Check data was populated
bq query --use_legacy_sql=false '
SELECT
  system_id,
  COUNT(*) as predictions,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as hit_rate,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM nba_predictions.prediction_accuracy
GROUP BY system_id
ORDER BY predictions DESC'
```

---

## Detailed Steps

### Step 1: Check Current State

```bash
# Are the grading tables empty?
bq query --use_legacy_sql=false '
SELECT
  "prediction_accuracy" as table_name,
  COUNT(*) as row_count
FROM nba_predictions.prediction_accuracy
UNION ALL
SELECT "system_daily_performance", COUNT(*)
FROM nba_predictions.system_daily_performance'
```

Expected output for empty tables:
```
+---------------------------+-----------+
| table_name                | row_count |
+---------------------------+-----------+
| prediction_accuracy       |         0 |
| system_daily_performance  |         0 |
+---------------------------+-----------+
```

### Step 2: Determine Date Range

```bash
# Find the date range with predictions
bq query --use_legacy_sql=false '
SELECT
  MIN(game_date) as first_prediction,
  MAX(game_date) as last_prediction,
  COUNT(DISTINCT game_date) as days_with_predictions
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE
  AND game_date < CURRENT_DATE()'  # Only past games (have results)
```

### Step 3: Run Prediction Accuracy Backfill

```bash
# Full season backfill
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-10-21 \
  --end-date 2025-12-17

# Or single date (for testing)
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --date 2025-12-15
```

**Expected output:**
```
Processing 2024-10-22...
  Graded 156 predictions
  Correct: 112 (71.8%)
Processing 2024-10-23...
  ...
Backfill complete: 55 dates, 8,540 predictions graded
```

### Step 4: Verify Prediction Accuracy

```bash
# Check coverage
bq query --use_legacy_sql=false '
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct) as correct,
  ROUND(COUNTIF(prediction_correct) / COUNT(*), 3) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= "2025-10-21"
GROUP BY game_date, system_id
ORDER BY game_date DESC
LIMIT 20'
```

### Step 5: Run System Daily Performance Aggregation

Aggregate prediction accuracy into daily system-level metrics (required for Phase 6 `SystemPerformanceExporter`):

```bash
# Run for the full date range
PYTHONPATH=. .venv/bin/python data_processors/grading/system_daily_performance/system_daily_performance_processor.py \
  --start-date 2025-10-21 --end-date 2025-12-17
```

### Step 6: Run Performance Summary Aggregation (Optional)

If you need multi-dimensional aggregates (by player, archetype, etc.):

```bash
# Create the table first (if not exists)
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/prediction_performance_summary.sql

# Run the aggregation processor
PYTHONPATH=. .venv/bin/python data_processors/grading/performance_summary/performance_summary_processor.py \
  --date 2025-12-17
```

### Step 7: Verify Daily Performance

```bash
# Check system_daily_performance
bq query --use_legacy_sql=false '
SELECT
  system_id,
  COUNT(*) as days_tracked,
  AVG(win_rate) as avg_win_rate,
  SUM(predictions_count) as total_predictions
FROM nba_predictions.system_daily_performance
GROUP BY system_id
ORDER BY total_predictions DESC'
```

---

## Troubleshooting

### No predictions found for date

**Symptom:** Backfill reports "No predictions found for 2024-XX-XX"

**Cause:** Phase 5A predictions weren't generated for that date

**Solution:**
```bash
# Check if predictions exist
bq query --use_legacy_sql=false '
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = "2024-XX-XX" AND is_active = TRUE'

# If 0, run Phase 5A first
PYTHONPATH=. .venv/bin/python backfill_jobs/predictions/prediction_backfill.py \
  --date 2024-XX-XX
```

### No game results found

**Symptom:** Backfill reports "No game results for player X on date Y"

**Cause:** Phase 3 `player_game_summary` missing data

**Solution:**
```bash
# Check if game results exist
bq query --use_legacy_sql=false '
SELECT COUNT(*) FROM nba_analytics.player_game_summary
WHERE game_date = "2024-XX-XX" AND points IS NOT NULL'

# If 0, run Phase 3 first
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --date 2024-XX-XX
```

### prediction_correct is NULL

**Symptom:** Many records have `prediction_correct = NULL`

**Cause:** Prediction was PASS or NO_LINE (no recommendation)

**Expected:** PASS recommendations don't have hit/miss, NULL is correct

```sql
-- Check distribution
SELECT
  recommendation,
  COUNT(*) as count,
  COUNTIF(prediction_correct IS NULL) as null_count
FROM nba_predictions.prediction_accuracy
GROUP BY recommendation
```

---

## Phase 5B Tables Reference

### prediction_accuracy

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Player identifier |
| game_id | STRING | Game identifier |
| game_date | DATE | Game date |
| system_id | STRING | Prediction system |
| predicted_points | NUMERIC | What we predicted |
| actual_points | INTEGER | What happened |
| prediction_correct | BOOLEAN | Was OVER/UNDER correct? |
| absolute_error | NUMERIC | \|predicted - actual\| |
| signed_error | NUMERIC | predicted - actual (bias) |
| within_3_points | BOOLEAN | Error <= 3 |
| within_5_points | BOOLEAN | Error <= 5 |

### system_daily_performance

| Field | Type | Description |
|-------|------|-------------|
| game_date | DATE | Game date |
| system_id | STRING | Prediction system |
| predictions_count | INTEGER | Total predictions |
| win_rate | NUMERIC | Correct / total |
| mae | NUMERIC | Mean absolute error |
| high_confidence_win_rate | NUMERIC | Win rate for confidence >= 0.70 |

### prediction_performance_summary (NEW)

| Field | Type | Description |
|-------|------|-------------|
| summary_key | STRING | Unique identifier |
| system_id | STRING | Prediction system |
| period_type | STRING | rolling_7d, rolling_30d, month, season |
| player_lookup | STRING | Specific player (NULL = all) |
| archetype | STRING | Player archetype (NULL = all) |
| hit_rate | FLOAT64 | Correct / total |

---

## Scheduling

After backfill, schedule daily jobs:

| Job | Schedule | Purpose |
|-----|----------|---------|
| prediction_accuracy_grading | 6:00 AM ET daily | Grade yesterday's predictions |
| performance_summary_aggregation | 6:30 AM ET daily | Update aggregates |

```bash
# Example Cloud Scheduler
gcloud scheduler jobs create http prediction-accuracy-grading \
  --schedule="0 6 * * *" \
  --time-zone="America/New_York" \
  --uri="https://prediction-accuracy-grading-xxxxx.run.app" \
  --http-method=POST
```

---

## Related Documentation

- **Schema:** `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- **Processor:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- **Backfill Job:** `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`
- **Performance Summary:** `data_processors/grading/performance_summary/performance_summary_processor.py`
- **Frontend Project:** `docs/08-projects/current/frontend-api-backend/README.md`
