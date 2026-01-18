# Setting Up NBA Prediction Grading Scheduled Query

## Overview
This scheduled query runs daily at **12:00 PM PT** to grade yesterday's NBA predictions.

## Option 1: BigQuery UI (Recommended)

1. **Open BigQuery Console**: https://console.cloud.google.com/bigquery

2. **Navigate to Scheduled Queries**:
   - Click on "Scheduled queries" in the left navigation
   - Click "CREATE SCHEDULED QUERY"

3. **Configure the Query**:
   - Name: `nba-prediction-grading-daily`
   - Query:
     ```sql
     DECLARE game_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

     INSERT INTO `nba-props-platform.nba_predictions.prediction_grades` (
       prediction_id,
       player_lookup,
       game_id,
       game_date,
       system_id,
       predicted_points,
       confidence_score,
       recommendation,
       points_line,
       actual_points,
       actual_vs_line,
       prediction_correct,
       margin_of_error,
       line_margin,
       graded_at,
       grading_version,
       data_quality_tier,
       has_issues,
       issues,
       minutes_played,
       player_dnp
     )
     SELECT
       p.prediction_id,
       p.player_lookup,
       p.game_id,
       p.game_date,
       p.system_id,
       CAST(p.predicted_points AS NUMERIC) as predicted_points,
       CAST(p.confidence_score AS NUMERIC) as confidence_score,
       p.recommendation,
       CAST(p.current_points_line AS NUMERIC) as points_line,
       a.points as actual_points,
       CASE
         WHEN a.points > p.current_points_line THEN 'OVER'
         WHEN a.points < p.current_points_line THEN 'UNDER'
         WHEN a.points = p.current_points_line THEN 'PUSH'
         ELSE NULL
       END as actual_vs_line,
       CASE
         WHEN p.recommendation = 'PASS' THEN NULL
         WHEN p.recommendation = 'NO_LINE' THEN NULL
         WHEN a.minutes_played = 0 THEN NULL
         WHEN a.points = p.current_points_line THEN NULL
         WHEN p.recommendation = 'OVER' AND a.points > p.current_points_line THEN TRUE
         WHEN p.recommendation = 'OVER' AND a.points < p.current_points_line THEN FALSE
         WHEN p.recommendation = 'UNDER' AND a.points < p.current_points_line THEN TRUE
         WHEN p.recommendation = 'UNDER' AND a.points > p.current_points_line THEN FALSE
         ELSE NULL
       END as prediction_correct,
       CAST(ABS(p.predicted_points - a.points) AS NUMERIC) as margin_of_error,
       CAST(a.points - p.current_points_line AS NUMERIC) as line_margin,
       CURRENT_TIMESTAMP() as graded_at,
       'v1' as grading_version,
       a.data_quality_tier,
       CASE
         WHEN a.points IS NULL THEN TRUE
         WHEN a.minutes_played = 0 THEN TRUE
         WHEN a.data_quality_tier != 'gold' THEN TRUE
         WHEN p.current_points_line IS NULL THEN TRUE
         ELSE FALSE
       END as has_issues,
       ARRAY(
         SELECT issue FROM UNNEST([
           IF(a.points IS NULL, 'missing_actual_points', NULL),
           IF(a.minutes_played = 0, 'player_dnp', NULL),
           IF(a.data_quality_tier != 'gold', CONCAT('quality_tier_', COALESCE(a.data_quality_tier, 'unknown')), NULL),
           IF(p.current_points_line IS NULL, 'missing_betting_line', NULL)
         ]) AS issue
         WHERE issue IS NOT NULL
       ) as issues,
       CAST(a.minutes_played AS INT64) as minutes_played,
       a.minutes_played = 0 as player_dnp
     FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
     INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` a
       ON p.player_lookup = a.player_lookup
       AND p.game_date = a.game_date
     WHERE
       p.game_date = game_date
       AND p.is_active = TRUE
       AND p.prediction_id NOT IN (
         SELECT prediction_id
         FROM `nba-props-platform.nba_predictions.prediction_grades`
         WHERE game_date = game_date
       );
     ```

4. **Set Schedule**:
   - Repeats: `Daily`
   - Start time: `12:00 PM`
   - Timezone: `America/Los_Angeles` (Pacific Time)
   - Start date: Today's date

5. **Destination**:
   - Leave as "No destination table" (query handles INSERT itself)

6. **Advanced Options** (optional):
   - Email notifications: Add your email for failures
   - Retry on failure: 3 retries

7. **Click "SAVE"**

## Option 2: gcloud CLI

Run the setup script:
```bash
./bin/schedulers/setup_nba_grading_scheduler.sh
```

## Verification

After setup, verify the scheduled query is working:

1. **Check scheduled queries**:
   ```bash
   bq ls --transfer_config --transfer_location=us --project_id=nba-props-platform
   ```

2. **Manually trigger a test run**:
   - Go to BigQuery Console → Scheduled queries
   - Find "nba-prediction-grading-daily"
   - Click "SCHEDULE BACKFILL" or "RUN NOW"

3. **Verify results**:
   ```sql
   SELECT
     game_date,
     COUNT(*) as graded_count,
     COUNTIF(prediction_correct) as correct,
     ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as accuracy_pct
   FROM `nba-props-platform.nba_predictions.prediction_grades`
   GROUP BY game_date
   ORDER BY game_date DESC
   LIMIT 7;
   ```

## Monitoring

- **Scheduled query runs**: Check in BigQuery Console → Scheduled queries → "nba-prediction-grading-daily"
- **Execution history**: View past runs, errors, and duration
- **Email alerts**: Configure to receive notifications on failures

## Troubleshooting

**Query fails**: Check the error message in the scheduled query execution history.

Common issues:
- No predictions for the date (expected if no games)
- Missing actuals (boxscores not yet ingested)
- Permission errors (ensure service account has BigQuery Data Editor role)

**No grades inserted**:
- Check if predictions already exist for that date
- Verify predictions exist in `player_prop_predictions` for the target date
- Verify actuals exist in `player_game_summary` for the target date
