# NBA Prediction Grading System

**Status**: ✅ Live in Production
**Implemented**: 2026-01-17 (Session 85)
**Grading Version**: v1

---

## Overview

The NBA prediction grading system automatically evaluates the accuracy of NBA player prop predictions by comparing them against actual game results.

**Key Features**:
- Automated daily grading at noon PT
- Supports all prediction systems (rule-based and ML)
- Tracks accuracy, margin of error, and confidence calibration
- Handles edge cases (DNP, pushes, missing data)
- Provides real-time performance reporting views

---

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  1. Predictions Generated (Phase 5)                         │
│     nba_predictions.player_prop_predictions                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Next day at 12:00 PM PT
                     │
┌────────────────────▼────────────────────────────────────────┐
│  2. Boxscores Ingested (Phase 4)                            │
│     nba_analytics.player_game_summary                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Scheduled Query (Daily @ Noon PT)
                     │
┌────────────────────▼────────────────────────────────────────┐
│  3. Grading Query Executes                                  │
│     - Joins predictions + actuals                           │
│     - Calculates correctness                                │
│     - Handles edge cases                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ INSERT results
                     │
┌────────────────────▼────────────────────────────────────────┐
│  4. Grades Stored                                           │
│     nba_predictions.prediction_grades                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Queried by reporting views
                     │
┌────────────────────▼────────────────────────────────────────┐
│  5. Reporting Views                                         │
│     - prediction_accuracy_summary                           │
│     - confidence_calibration                                │
│     - player_prediction_performance                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Tables and Views

### `nba_predictions.prediction_grades` (Table)

Primary grading results table. Stores one row per graded prediction.

**Key Fields**:
- `prediction_id` - FK to player_prop_predictions
- `player_lookup` - Player identifier
- `game_date` - Game date (partition key)
- `system_id` - Prediction system (e.g., 'ensemble_v1')
- `predicted_points` - What was predicted
- `actual_points` - What actually happened
- `prediction_correct` - TRUE/FALSE/NULL
- `margin_of_error` - |predicted - actual|
- `confidence_score` - Prediction confidence (0-1)
- `has_issues` - Data quality flag
- `issues` - Array of issue codes

**Partitioning**: By `game_date` for efficient queries
**Clustering**: By `player_lookup`, `prediction_correct`, `confidence_score`

### `prediction_accuracy_summary` (View)

Daily accuracy rollup by system.

**Example Query**:
```sql
SELECT * FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC, accuracy_pct DESC;
```

**Key Metrics**:
- `accuracy_pct` - % of correct predictions
- `avg_margin_of_error` - Average points off
- `avg_confidence` - Average confidence score

### `confidence_calibration` (View)

Checks if confidence scores are well-calibrated.

**Example**: If a system reports 90% confidence, do those predictions actually hit 90%?

**Example Query**:
```sql
SELECT * FROM `nba-props-platform.nba_predictions.confidence_calibration`
WHERE system_id = 'ensemble_v1'
ORDER BY confidence_bucket DESC;
```

**Key Metrics**:
- `confidence_bucket` - Confidence range (e.g., 85-89%)
- `actual_accuracy_pct` - Actual accuracy in this bucket
- `calibration_error` - Difference (positive = overconfident)

### `player_prediction_performance` (View)

Per-player accuracy across all systems.

**Example Query**:
```sql
SELECT * FROM `nba-props-platform.nba_predictions.player_prediction_performance`
WHERE total_predictions >= 10
ORDER BY accuracy_pct DESC
LIMIT 20;
```

**Use Cases**:
- Find which players are most predictable
- Identify players where models struggle
- Analyze OVER vs UNDER split accuracy

---

## Grading Logic

### Correctness Determination

```sql
CASE
  -- Don't grade PASS recommendations
  WHEN recommendation = 'PASS' THEN NULL

  -- Don't grade NO_LINE recommendations
  WHEN recommendation = 'NO_LINE' THEN NULL

  -- Don't grade if player didn't play
  WHEN minutes_played = 0 THEN NULL

  -- PUSH = no win/loss
  WHEN actual_points = betting_line THEN NULL

  -- OVER predictions
  WHEN recommendation = 'OVER' AND actual_points > betting_line THEN TRUE
  WHEN recommendation = 'OVER' AND actual_points < betting_line THEN FALSE

  -- UNDER predictions
  WHEN recommendation = 'UNDER' AND actual_points < betting_line THEN TRUE
  WHEN recommendation = 'UNDER' AND actual_points > betting_line THEN FALSE

  ELSE NULL
END
```

### Edge Cases

| Scenario | Grading Behavior | `prediction_correct` | `has_issues` |
|----------|------------------|---------------------|--------------|
| Player DNP (0 minutes) | Not graded | NULL | TRUE |
| Exact push (actual = line) | Not graded | NULL | FALSE |
| PASS recommendation | Not graded | NULL | FALSE |
| NO_LINE recommendation | Not graded | NULL | FALSE |
| Missing actual result | Not graded | NULL | TRUE |
| Non-gold data quality | Graded, flagged | TRUE/FALSE | TRUE |
| Missing betting line | Not graded | NULL | TRUE |

---

## Scheduled Query

**Name**: `nba-prediction-grading-daily`
**Schedule**: Daily at 12:00 PM PT (20:00 UTC)
**Location**: us (multi-region)
**Target**: `nba_predictions.prediction_grades`

### Why Noon PT?

- **Boxscores ingested**: By ~9-11 AM PT (games end late night)
- **Grading runs**: 12:00 PM PT (safe buffer)
- **Results available**: By ~12:05 PM PT for afternoon analysis

### Query Logic

1. **Declares parameter**: `game_date = CURRENT_DATE - 1 day`
2. **Joins**: `player_prop_predictions` + `player_game_summary`
3. **Filters**: Only active predictions, not already graded
4. **Calculates**: Correctness, margin of error, issues
5. **Inserts**: Into `prediction_grades` table

### Idempotency

The query uses a `NOT IN` clause to skip already-graded predictions:
```sql
AND p.prediction_id NOT IN (
  SELECT prediction_id FROM prediction_grades
  WHERE game_date = @game_date
)
```

This means:
- Safe to re-run manually
- No duplicate grades created
- Can backfill specific dates

---

## Usage Examples

### Check Recent Accuracy

```sql
-- Last 7 days accuracy by system
SELECT
  game_date,
  system_id,
  accuracy_pct,
  total_predictions,
  avg_margin_of_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC, accuracy_pct DESC;
```

### Check Confidence Calibration

```sql
-- Is ensemble_v1 well-calibrated?
SELECT
  confidence_bucket,
  total_predictions,
  actual_accuracy_pct,
  avg_confidence,
  calibration_error
FROM `nba-props-platform.nba_predictions.confidence_calibration`
WHERE system_id = 'ensemble_v1'
ORDER BY confidence_bucket DESC;
```

**Expected**: Low calibration error (< 5 points)
**Red flag**: High calibration error (> 15 points) = model overconfident

### Find Most Predictable Players

```sql
-- Top 10 most predictable players (ensemble_v1)
SELECT
  player_lookup,
  total_predictions,
  accuracy_pct,
  avg_margin_of_error
FROM `nba-props-platform.nba_predictions.player_prediction_performance`
WHERE system_id = 'ensemble_v1'
  AND total_predictions >= 10
ORDER BY accuracy_pct DESC
LIMIT 10;
```

### Grade Specific Date (Manual)

```sql
-- Grade Jan 15, 2026 (if not already graded)
-- Use the query from: schemas/bigquery/nba_predictions/grade_predictions_query.sql
-- Set parameter: @game_date = '2026-01-15'
```

---

## Performance Metrics (Baseline)

Based on Jan 14-16, 2026 grading results:

| System | Avg Accuracy | Avg Margin | Predictions Graded |
|--------|--------------|------------|-------------------|
| moving_average | 64.8% | 5.64 pts | 1,139 |
| similarity_balanced_v1 | 60.6% | 6.07 pts | 988 |
| ensemble_v1 | 61.8% | 6.07 pts | 1,139 |
| zone_matchup_v1 | 57.4% | 6.62 pts | 1,139 |

**Observations**:
- `moving_average` has highest accuracy but moderate confidence
- `similarity_balanced_v1` has high confidence but lower accuracy (may be overconfident)
- `ensemble_v1` balanced performance
- `zone_matchup_v1` lowest accuracy (needs improvement)

---

## Monitoring

### Daily Checks

1. **Scheduled query ran successfully**:
   - BigQuery Console → Scheduled queries → "nba-prediction-grading-daily"
   - Check execution history for errors

2. **Grades inserted**:
   ```sql
   SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.prediction_grades`
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
   ```
   - Expected: 150-300 grades per day (varies by game schedule)

3. **Accuracy trends**:
   - Use `prediction_accuracy_summary` view
   - Alert if 7-day accuracy drops below 55%

### Alerts (Future Enhancement)

Recommended alerts:
- Grading query fails (email notification)
- 7-day accuracy < 55% (performance degradation)
- Confidence calibration error > 15 points (model overconfident)
- Zero grades for 2+ consecutive days (pipeline broken)

---

## Troubleshooting

### No Grades Created

**Symptoms**: Scheduled query runs but 0 rows inserted

**Causes**:
1. No games yesterday (check NBA schedule)
2. No predictions exist for yesterday
3. Boxscores not yet ingested
4. All predictions already graded

**Diagnosis**:
```sql
-- Check predictions exist
SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND is_active = TRUE;

-- Check actuals exist
SELECT COUNT(*) FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

-- Check not already graded
SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
```

### Low Accuracy (<50%)

**Symptoms**: accuracy_pct consistently below 50%

**Causes**:
1. Model bug (recommendation logic inverted?)
2. Poor data quality
3. Betting lines inaccurate
4. Model not trained on recent data

**Diagnosis**:
```sql
-- Check if OVER/UNDER logic seems inverted
SELECT
  recommendation,
  COUNT(*) as total,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as pct
FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY recommendation;
```

### Scheduled Query Fails

**Symptoms**: Query execution shows error

**Common Errors**:
- `Column not found` - Schema changed, update query
- `Insufficient permissions` - Grant BigQuery Data Editor role
- `Quota exceeded` - Increase BigQuery quota or reduce query frequency

**Fix**: Check execution history, review error message, update query/permissions

### High Calibration Error

**Symptoms**: `calibration_error > 15` in confidence_calibration view

**Interpretation**: Model is overconfident (or underconfident if negative)

**Example**: Model says 90% confidence but only 70% accurate → 20 point error

**Action**: Recalibrate confidence scores in prediction model

---

## Maintenance

### Schema Changes

If prediction or actual result schema changes:

1. Update grading query: `schemas/bigquery/nba_predictions/grade_predictions_query.sql`
2. Update reporting views if needed
3. Test query manually before updating scheduled query
4. Increment `grading_version` (e.g., 'v1' → 'v2')

### Backfilling Historical Data

To grade a specific past date:

```bash
# Run grading query for specific date
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-10 \
  < schemas/bigquery/nba_predictions/grade_predictions_query.sql
```

To grade a date range:

```bash
# Grade all dates from Jan 1 to Jan 10
for d in {1..10}; do
  bq query --use_legacy_sql=false \
    --parameter=game_date:DATE:2026-01-$(printf "%02d" $d) \
    < schemas/bigquery/nba_predictions/grade_predictions_query.sql
done
```

### Reprocessing Grades

If actual results were incorrect and later fixed:

1. Delete bad grades:
   ```sql
   DELETE FROM `nba-props-platform.nba_predictions.prediction_grades`
   WHERE game_date = '2026-01-15';
   ```

2. Re-run grading query for that date (see backfill above)

---

## Files and Locations

**Schema**:
- Table: `schemas/bigquery/nba_predictions/prediction_grades.sql`
- Grading query: `schemas/bigquery/nba_predictions/grade_predictions_query.sql`
- Views: `schemas/bigquery/nba_predictions/views/`

**Scripts**:
- Scheduler setup: `bin/schedulers/setup_nba_grading_scheduler.sh`
- Setup guide: `schemas/bigquery/nba_predictions/SETUP_SCHEDULED_QUERY.md`

**Documentation**:
- This runbook: `docs/06-grading/NBA-GRADING-SYSTEM.md`
- Implementation guide: `docs/09-handoff/SESSION-85-NBA-GRADING.md`
- Handoff: `docs/09-handoff/SESSION-85-NBA-GRADING-COMPLETE.md`

---

## Related Systems

- **MLB Grading**: `data_processors/grading/mlb/` (Python-based, updates predictions table directly)
- **NBA Predictions**: `nba_predictions.player_prop_predictions` (Phase 5)
- **NBA Boxscores**: `nba_analytics.player_game_summary` (Phase 4)

---

## Future Enhancements

1. **ROI Calculator**: Simulate betting strategy and track theoretical profit/loss
2. **Grading Dashboard**: Looker Studio dashboard with accuracy trends and charts
3. **Model Comparison**: A/B test multiple model versions side-by-side
4. **Alerting**: Email/Slack alerts for accuracy drops or grading failures
5. **Advanced Metrics**:
   - Brier score (calibration metric)
   - Sharpe ratio (risk-adjusted returns)
   - Kelly criterion optimal bet sizing

---

**Last Updated**: 2026-01-17
**Maintained By**: NBA Props Platform Team
**Contact**: See repository maintainers
