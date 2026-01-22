# Phase Validation Monitoring Dashboard

**Part of:** Robustness Improvements - Week 7 Monitoring
**Created:** January 21, 2026
**Purpose:** Monitor phase boundary validation gates and data quality

---

## Overview

This dashboard monitors the phase validation system to ensure:
1. Validation gates are catching data quality issues
2. Game count thresholds are appropriate
3. Processor completions are tracked
4. BLOCKING mode prevents bad data from reaching Phase 4

---

## Data Source

**Primary:** BigQuery table `nba_monitoring.phase_boundary_validations`

**Schema:**
- `validation_id`: Unique ID
- `game_date`: Date of games validated
- `phase_name`: Phase transition (phase1_to_phase2, phase2_to_phase3, phase3_to_phase4)
- `is_valid`: Boolean - validation passed/failed
- `mode`: Validation mode (warning, blocking)
- `issues`: Array of validation issues
- `metrics`: JSON with counts, scores, thresholds
- `timestamp`: When validation ran

---

## Dashboard Panels

### Panel 1: Validation Success Rate

**Type:** Time Series Line Chart
**Query:**
```sql
SELECT
  DATE(game_date) as date,
  phase_name,
  COUNTIF(is_valid) as valid_count,
  COUNTIF(NOT is_valid) as invalid_count,
  ROUND(SAFE_DIVIDE(COUNTIF(is_valid), COUNT(*)) * 100, 2) as success_rate_pct
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY date, phase_name
ORDER BY date, phase_name;
```

**Visualization:**
- X-axis: Date (30-day window)
- Y-axis: Success rate percentage
- Lines: One per phase
- Target line: 95% success rate

**Alert:** Success rate < 80% for any phase

---

### Panel 2: Validation Failures by Type

**Type:** Stacked Bar Chart
**Query:**
```sql
SELECT
  DATE(game_date) as date,
  issue.validation_type,
  COUNT(*) as failure_count
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`,
  UNNEST(issues) as issue
WHERE
  game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND is_valid = FALSE
GROUP BY date, issue.validation_type
ORDER BY date, failure_count DESC;
```

**Visualization:**
- X-axis: Date
- Y-axis: Failure count
- Stacks: By validation type (game_count, processor_completion, data_quality)
- Colors: Red (game_count), Yellow (processor), Blue (quality)

---

### Panel 3: BLOCKING Events (Critical)

**Type:** Table with Alert Status
**Query:**
```sql
SELECT
  game_date,
  phase_name,
  ARRAY_LENGTH(issues) as issue_count,
  JSON_EXTRACT(metrics, '$.game_count_actual') as actual_games,
  JSON_EXTRACT(metrics, '$.game_count_expected') as expected_games,
  JSON_EXTRACT(metrics, '$.quality_score') as quality_score,
  ARRAY_TO_STRING(ARRAY(
    SELECT issue.message
    FROM UNNEST(issues) as issue
    LIMIT 3
  ), ' | ') as top_issues,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', timestamp) as validation_time
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE
  mode = 'blocking'
  AND is_valid = FALSE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY timestamp DESC
LIMIT 50;
```

**Visualization:**
- Table with conditional formatting
- Red row: BLOCKING validation failure
- Columns: Date, Phase, Issue Count, Games, Quality Score, Messages

**Alert:** Any BLOCKING validation failure (Critical severity)

---

### Panel 4: Game Count Accuracy

**Type:** Scatter Plot
**Query:**
```sql
WITH validation_metrics AS (
  SELECT
    game_date,
    phase_name,
    CAST(JSON_EXTRACT(metrics, '$.game_count_expected') AS INT64) as expected,
    CAST(JSON_EXTRACT(metrics, '$.game_count_actual') AS INT64) as actual,
    is_valid
  FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
  WHERE
    game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND JSON_EXTRACT(metrics, '$.game_count_expected') IS NOT NULL
)
SELECT
  game_date,
  phase_name,
  expected,
  actual,
  ROUND(SAFE_DIVIDE(actual, expected) * 100, 1) as accuracy_pct,
  is_valid,
  CASE
    WHEN SAFE_DIVIDE(actual, expected) >= 0.8 THEN 'Pass'
    ELSE 'Fail'
  END as threshold_status
FROM validation_metrics
ORDER BY game_date DESC;
```

**Visualization:**
- X-axis: Expected game count
- Y-axis: Actual game count
- Diagonal line: y=x (perfect match)
- Horizontal line: y = 0.8x (80% threshold)
- Points colored by: Pass (green) / Fail (red)

---

### Panel 5: Data Quality Scores Over Time

**Type:** Time Series with Band
**Query:**
```sql
SELECT
  DATE(game_date) as date,
  phase_name,
  AVG(CAST(JSON_EXTRACT(metrics, '$.quality_score') AS FLOAT64)) as avg_quality_score,
  MIN(CAST(JSON_EXTRACT(metrics, '$.quality_score') AS FLOAT64)) as min_quality_score,
  MAX(CAST(JSON_EXTRACT(metrics, '$.quality_score') AS FLOAT64)) as max_quality_score
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE
  game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND JSON_EXTRACT(metrics, '$.quality_score') IS NOT NULL
GROUP BY date, phase_name
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis: Quality score (0.0 - 1.0)
- Lines: Average quality per phase
- Shaded band: Min to Max range
- Horizontal line: 0.7 threshold

---

### Panel 6: Processor Completion Heatmap

**Type:** Heatmap
**Query:**
```sql
WITH processor_failures AS (
  SELECT
    DATE(game_date) as date,
    phase_name,
    issue.message as processor_name,
    COUNT(*) as failure_count
  FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`,
    UNNEST(issues) as issue
  WHERE
    game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND issue.validation_type = 'processor_completion'
  GROUP BY date, phase_name, processor_name
)
SELECT
  date,
  phase_name,
  processor_name,
  failure_count,
  CASE
    WHEN failure_count = 0 THEN 'Healthy'
    WHEN failure_count <= 2 THEN 'Warning'
    ELSE 'Critical'
  END as health_status
FROM processor_failures
ORDER BY date DESC, failure_count DESC;
```

**Visualization:**
- X-axis: Date
- Y-axis: Processor name
- Cell color: Failure count (green = 0, yellow = 1-2, red = 3+)
- Tooltip: Phase, Date, Failure count

---

### Panel 7: Validation Mode Distribution

**Type:** Pie Chart
**Query:**
```sql
SELECT
  phase_name,
  mode,
  COUNT(*) as validation_count,
  COUNTIF(NOT is_valid) as failure_count
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY phase_name, mode
ORDER BY phase_name, mode;
```

**Visualization:**
- Show distribution of WARNING vs BLOCKING validations
- Separate pie for each phase
- Annotation: Failure count

---

## Alerts

### Critical Alerts (Immediate Action Required)

1. **BLOCKING Validation Failure**
   ```sql
   -- Alert condition
   SELECT COUNT(*) as blocking_failures
   FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
   WHERE
     mode = 'blocking'
     AND is_valid = FALSE
     AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
   HAVING blocking_failures > 0;
   ```
   - **Severity:** Critical
   - **Notification:** PagerDuty + Slack #alerts
   - **Action:** Investigate immediately - Phase 4 pipeline is blocked

2. **Low Game Count Pattern**
   ```sql
   -- Alert if game count < 50% expected for 3+ consecutive days
   WITH daily_accuracy AS (
     SELECT
       game_date,
       AVG(
         SAFE_DIVIDE(
           CAST(JSON_EXTRACT(metrics, '$.game_count_actual') AS INT64),
           CAST(JSON_EXTRACT(metrics, '$.game_count_expected') AS INT64)
         )
       ) as accuracy_ratio
     FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
     GROUP BY game_date
   )
   SELECT COUNT(*) as low_count_days
   FROM daily_accuracy
   WHERE accuracy_ratio < 0.5
   HAVING low_count_days >= 3;
   ```
   - **Severity:** High
   - **Notification:** Slack #monitoring
   - **Action:** Check scraper health, API status

### Warning Alerts

3. **Quality Score Degradation**
   ```
   Condition: Average quality score < 0.7 for any phase in last 24 hours
   Severity: Warning
   Notification: Slack #monitoring
   ```

4. **High Validation Failure Rate**
   ```
   Condition: > 20% validation failures for any phase in last 6 hours
   Severity: Warning
   Notification: Slack #monitoring
   ```

---

## Dashboard Creation

### Using Looker Studio (Recommended)

1. **Create Data Source:**
   - Go to Looker Studio (datastudio.google.com)
   - Create new Data Source
   - Connector: BigQuery
   - Select project: `nba-props-platform`
   - Select table: `nba_monitoring.phase_boundary_validations`

2. **Create Dashboard:**
   - New Report → Blank Report
   - Name: "NBA Pipeline - Phase Validation"
   - Add data source created above

3. **Add Charts:**
   - For each panel above, create corresponding visualization
   - Use SQL queries in "Custom Query" mode for complex aggregations

4. **Configure Auto-Refresh:**
   - Dashboard settings → Auto-refresh: 5 minutes

5. **Share Dashboard:**
   - Share with data engineering team
   - Embed in internal wiki/runbook

### Using Cloud Monitoring

```yaml
# Alternative: Create charts in Cloud Monitoring using BigQuery metrics
displayName: "Phase Validation Dashboard"
mosaicLayout:
  columns: 12
  tiles:
    - width: 6
      height: 4
      widget:
        title: "Validation Success Rate"
        xyChart:
          dataSets:
            - timeSeriesQuery:
                timeSeriesFilter:
                  filter: 'metric.type="bigquery.googleapis.com/query/scanned_bytes"'
```

---

## Usage Guide

### Daily Monitoring

**Morning Checklist (9:00 AM ET):**
1. Check BLOCKING Events table - should be empty
2. Review yesterday's validation success rate - should be > 95%
3. Check Game Count Accuracy - most points should be near diagonal
4. Scan Processor Completion Heatmap for red cells

**When Validation Fails:**
1. Check BLOCKING Events table for details
2. Review specific issue messages
3. Query BigQuery for full validation record:
   ```sql
   SELECT *
   FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
   WHERE
     game_date = 'YYYY-MM-DD'
     AND phase_name = 'phase_name'
   ORDER BY timestamp DESC
   LIMIT 1;
   ```
4. Investigate root cause:
   - Low game count → Check scraper logs
   - Missing processor → Check Phase 2/3 logs
   - Low quality → Check data quality metrics
5. Trigger manual healing if needed

### Weekly Review

**Monday Review:**
1. Review 7-day success rate trend
2. Identify recurring validation failures
3. Adjust thresholds if too many false positives
4. Review and tune alert noise

**Threshold Tuning:**
- **game_count_threshold:** Default 0.8 (80%)
  - Increase if too many cancelled games trigger false alarms
  - Decrease if missing games not being caught
- **quality_threshold:** Default 0.7 (70%)
  - Adjust based on data quality patterns

---

## Query Library

### Top Validation Failure Reasons (Last 7 Days)

```sql
SELECT
  issue.validation_type,
  issue.severity,
  issue.message,
  COUNT(*) as occurrence_count,
  COUNT(DISTINCT game_date) as affected_dates
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`,
  UNNEST(issues) as issue
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY issue.validation_type, issue.severity, issue.message
ORDER BY occurrence_count DESC
LIMIT 20;
```

### Validation Performance by Phase

```sql
SELECT
  phase_name,
  COUNT(*) as total_validations,
  COUNTIF(is_valid) as passed,
  COUNTIF(NOT is_valid) as failed,
  ROUND(COUNTIF(is_valid) / COUNT(*) * 100, 2) as success_rate_pct,
  AVG(CAST(JSON_EXTRACT(metrics, '$.quality_score') AS FLOAT64)) as avg_quality_score,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY phase_name
ORDER BY phase_name;
```

### Game Count Discrepancy Details

```sql
SELECT
  game_date,
  phase_name,
  CAST(JSON_EXTRACT(metrics, '$.game_count_expected') AS INT64) as expected,
  CAST(JSON_EXTRACT(metrics, '$.game_count_actual') AS INT64) as actual,
  CAST(JSON_EXTRACT(metrics, '$.game_count_expected') AS INT64) -
    CAST(JSON_EXTRACT(metrics, '$.game_count_actual') AS INT64) as gap,
  is_valid,
  (
    SELECT STRING_AGG(issue.message, '; ')
    FROM UNNEST(issues) as issue
    WHERE issue.validation_type = 'game_count'
  ) as issue_details
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE
  game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND JSON_EXTRACT(metrics, '$.game_count_expected') IS NOT NULL
  AND CAST(JSON_EXTRACT(metrics, '$.game_count_actual') AS INT64) <
      CAST(JSON_EXTRACT(metrics, '$.game_count_expected') AS INT64)
ORDER BY gap DESC, game_date DESC;
```

### Validation Timeline for Specific Date

```sql
SELECT
  validation_id,
  phase_name,
  mode,
  is_valid,
  ARRAY_LENGTH(issues) as issue_count,
  FORMAT_TIMESTAMP('%H:%M:%S', timestamp) as time,
  JSON_EXTRACT(metrics, '$.game_count_actual') as games,
  JSON_EXTRACT(metrics, '$.quality_score') as quality
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE game_date = '2026-01-21'
ORDER BY timestamp;
```

---

## Metrics Glossary

- **Validation Success Rate:** Percentage of validations that passed
- **Game Count Accuracy:** Ratio of actual games to expected games
- **Data Quality Score:** Composite quality metric (0.0 - 1.0)
- **Processor Completion:** Whether all expected processors completed successfully
- **BLOCKING Event:** Validation failure in BLOCKING mode that prevents pipeline continuation

---

## Troubleshooting

### Common Issues

**Issue: High false positive rate**
- **Symptom:** Validations failing but data looks fine
- **Solution:**
  1. Review threshold settings
  2. Check if game cancellations are frequent
  3. Adjust `game_count_threshold` from 0.8 to 0.75
  4. Update environment variable and redeploy

**Issue: BLOCKING mode not preventing bad data**
- **Symptom:** Bad data reaching Phase 4 despite validation
- **Solution:**
  1. Verify BLOCKING mode is enabled for phase3_to_phase4
  2. Check that validation runs BEFORE phase 4 processors
  3. Review validation logic for gaps

**Issue: Validations not running**
- **Symptom:** No records in BigQuery table
- **Solution:**
  1. Check Cloud Function logs for errors
  2. Verify BigQuery table exists
  3. Check IAM permissions for Cloud Functions
  4. Verify `PHASE_VALIDATION_ENABLED=true`

---

## Related Documentation

- [Phase Boundary Validator Implementation](../WEEK-3-4-PHASE-VALIDATION-COMPLETE.md)
- [Deployment Runbook](../deployment/RUNBOOK.md)
- [Rate Limiting Dashboard](./rate-limiting-dashboard.md)

---

## Maintenance

**Update Frequency:** Review dashboard and queries monthly
**Owner:** Data Engineering Team
**Last Updated:** January 21, 2026
**Next Review:** February 21, 2026
