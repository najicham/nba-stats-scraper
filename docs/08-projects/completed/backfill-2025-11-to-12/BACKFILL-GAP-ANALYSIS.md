# Backfill Gap Analysis & Monitoring Queries

**Created:** 2025-11-29
**Purpose:** SQL queries for tracking backfill progress, identifying gaps, and monitoring execution
**Related:** BACKFILL-MASTER-EXECUTION-GUIDE.md

---

## 📋 Table of Contents

1. [Pre-Backfill Gap Analysis](#pre-backfill-gap-analysis)
2. [Progress Monitoring](#progress-monitoring)
3. [Failure Detection](#failure-detection)
4. [Quality Gate Verification](#quality-gate-verification)
5. [Performance Metrics](#performance-metrics)
6. [Recovery Queries](#recovery-queries)

---

## 🔍 Pre-Backfill Gap Analysis {#pre-backfill-gap-analysis}

### 1. Overall Data Coverage by Phase

```sql
-- Show coverage across all phases for historical seasons
WITH schedule AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase2_data AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase3_data AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase4_data AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  EXTRACT(YEAR FROM s.game_date) as year,
  COUNT(DISTINCT s.game_date) as total_games,
  COUNT(DISTINCT p2.game_date) as phase2_exists,
  COUNT(DISTINCT p3.game_date) as phase3_exists,
  COUNT(DISTINCT p4.game_date) as phase4_exists,
  COUNT(DISTINCT s.game_date) - COUNT(DISTINCT p2.game_date) as phase2_missing,
  COUNT(DISTINCT s.game_date) - COUNT(DISTINCT p3.game_date) as phase3_missing,
  COUNT(DISTINCT s.game_date) - COUNT(DISTINCT p4.game_date) as phase4_missing,
  ROUND(100.0 * COUNT(DISTINCT p2.game_date) / COUNT(DISTINCT s.game_date), 1) as phase2_pct,
  ROUND(100.0 * COUNT(DISTINCT p3.game_date) / COUNT(DISTINCT s.game_date), 1) as phase3_pct,
  ROUND(100.0 * COUNT(DISTINCT p4.game_date) / COUNT(DISTINCT s.game_date), 1) as phase4_pct
FROM schedule s
LEFT JOIN phase2_data p2 ON s.game_date = p2.game_date
LEFT JOIN phase3_data p3 ON s.game_date = p3.game_date
LEFT JOIN phase4_data p4 ON s.game_date = p4.game_date
GROUP BY year
ORDER BY year
```

**Expected Output (Before Backfill):**
```
year | total_games | phase2_exists | phase3_exists | phase4_exists | phase2_missing | phase3_missing | phase4_missing | phase2_pct | phase3_pct | phase4_pct
-----|-------------|---------------|---------------|---------------|----------------|----------------|----------------|------------|------------|------------
2021 | 72          | 72            | 34            | 0             | 0              | 38             | 72             | 100.0      | 47.2       | 0.0
2022 | 215         | 215           | 91            | 0             | 0              | 124            | 215            | 100.0      | 42.3       | 0.0
2023 | 205         | 205           | 112           | 0             | 0              | 93             | 205            | 100.0      | 54.6       | 0.0
2024 | 146         | 146           | 74            | 0             | 0              | 72             | 146            | 100.0      | 50.7       | 0.0
```

**Expected Output (After Complete Backfill):**
```
All phase*_pct should be 100.0
All phase*_missing should be 0
```

---

### 2. Exact Missing Dates in Phase 3

```sql
-- Get exact list of dates missing from Phase 3
SELECT s.game_date
FROM `nba-props-platform.nba_raw.nbac_schedule` s
WHERE s.game_status = 3
  AND s.game_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND s.game_date NOT IN (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
  )
ORDER BY s.game_date
```

**Save to CSV:**
```bash
bq query --use_legacy_sql=false --format=csv --max_rows=1000 \
  "$(cat query_above)" > phase3_missing_dates.csv

# Count missing dates
wc -l phase3_missing_dates.csv
```

---

### 3. Exact Missing Dates in Phase 4

```sql
-- Get exact list of dates missing from Phase 4
SELECT s.game_date
FROM `nba-props-platform.nba_raw.nbac_schedule` s
WHERE s.game_status = 3
  AND s.game_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND s.game_date NOT IN (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
  )
ORDER BY s.game_date
```

---

### 4. Monthly Gap Summary

```sql
-- Show gaps by month for easier planning
WITH schedule AS (
  SELECT
    DATE_TRUNC(game_date, MONTH) as month,
    COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY month
),
phase3 AS (
  SELECT
    DATE_TRUNC(game_date, MONTH) as month,
    COUNT(DISTINCT game_date) as phase3_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY month
)
SELECT
  s.month,
  s.total_dates,
  COALESCE(p3.phase3_dates, 0) as phase3_dates,
  s.total_dates - COALESCE(p3.phase3_dates, 0) as phase3_missing,
  ROUND(100.0 * COALESCE(p3.phase3_dates, 0) / s.total_dates, 1) as completeness_pct
FROM schedule s
LEFT JOIN phase3 p3 ON s.month = p3.month
ORDER BY s.month
```

---

## 📊 Progress Monitoring {#progress-monitoring}

### 5. Real-Time Backfill Progress

```sql
-- Run this during backfill to track progress
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase3 AS (
  SELECT COUNT(DISTINCT game_date) as completed_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p3.completed_dates,
  s.total_dates - p3.completed_dates as remaining,
  ROUND(100.0 * p3.completed_dates / s.total_dates, 1) as pct_complete,
  CASE
    WHEN p3.completed_dates = s.total_dates THEN '✅ COMPLETE'
    WHEN p3.completed_dates >= s.total_dates * 0.75 THEN '🟡 75%+ Complete'
    WHEN p3.completed_dates >= s.total_dates * 0.50 THEN '🟠 50%+ Complete'
    WHEN p3.completed_dates >= s.total_dates * 0.25 THEN '🔴 25%+ Complete'
    ELSE '⚪ Just Started'
  END as status
FROM schedule s, phase3 p3
```

**Run every 30-60 minutes during backfill to track progress.**

---

### 6. Processor-Level Progress

```sql
-- Check which processors have processed which dates
SELECT
  processor_name,
  COUNT(DISTINCT data_date) as dates_processed,
  MIN(data_date) as earliest_date,
  MAX(data_date) as latest_date,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_runs,
  SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed_runs,
  ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND created_at >= TIMESTAMP('2025-11-29 10:00:00')  -- Today's backfill start
GROUP BY processor_name
ORDER BY processor_name
```

---

### 7. Hourly Progress Rate

```sql
-- See how many dates are being processed per hour
WITH hourly_completions AS (
  SELECT
    TIMESTAMP_TRUNC(created_at, HOUR) as hour,
    COUNT(DISTINCT data_date) as dates_completed
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name = 'PlayerGameSummaryProcessor'
    AND success = true
    AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
    AND created_at >= TIMESTAMP('2025-11-29 10:00:00')
  GROUP BY hour
)
SELECT
  hour,
  dates_completed,
  SUM(dates_completed) OVER (ORDER BY hour) as cumulative_completed,
  ROUND(AVG(dates_completed) OVER (ORDER BY hour ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1) as rolling_avg_per_hour
FROM hourly_completions
ORDER BY hour DESC
LIMIT 24
```

**Use this to estimate time remaining:**
- If averaging 20 dates/hour, 327 dates = ~16 hours
- If averaging 30 dates/hour, 327 dates = ~11 hours

---

### 8. Last 10 Completed Dates

```sql
-- See most recent completions
SELECT
  data_date,
  processor_name,
  success,
  rows_processed,
  processing_time_seconds,
  created_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND created_at >= TIMESTAMP('2025-11-29 10:00:00')
ORDER BY created_at DESC
LIMIT 10
```

---

## 🚨 Failure Detection {#failure-detection}

### 9. Current Failures Needing Attention

```sql
-- Find all failed runs that haven't been resolved
SELECT
  data_date,
  processor_name,
  error_message,
  processing_decision,
  created_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) as hours_ago
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = false
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  -- Only show failures that weren't later successful
  AND data_date NOT IN (
    SELECT DISTINCT data_date
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE phase = 'phase_3_analytics'
      AND processor_name = processor_name  -- Same processor
      AND success = true
  )
ORDER BY created_at DESC
```

---

### 10. Failure Pattern Analysis

```sql
-- Group failures by error type to identify patterns
SELECT
  REGEXP_EXTRACT(error_message, r'^([^:]+):') as error_type,
  COUNT(*) as occurrence_count,
  COUNT(DISTINCT data_date) as affected_dates,
  COUNT(DISTINCT processor_name) as affected_processors,
  MIN(created_at) as first_occurrence,
  MAX(created_at) as last_occurrence
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = false
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND created_at >= TIMESTAMP('2025-11-29 10:00:00')
GROUP BY error_type
ORDER BY occurrence_count DESC
```

---

### 11. Dates with Partial Completion

```sql
-- Find dates where some processors succeeded but others failed
WITH date_processor_count AS (
  SELECT
    data_date,
    COUNT(DISTINCT processor_name) as total_processors,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_processors,
    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed_processors
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE phase = 'phase_3_analytics'
    AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
    AND created_at >= TIMESTAMP('2025-11-29 10:00:00')
  GROUP BY data_date
)
SELECT
  data_date,
  total_processors,
  successful_processors,
  failed_processors,
  CASE
    WHEN failed_processors > 0 AND successful_processors > 0 THEN '⚠️ PARTIAL'
    WHEN failed_processors = total_processors THEN '❌ ALL FAILED'
    WHEN successful_processors = total_processors THEN '✅ ALL SUCCESS'
    ELSE '❓ UNKNOWN'
  END as status
FROM date_processor_count
WHERE failed_processors > 0
ORDER BY data_date
```

**Partial failures need special attention - some data exists but not complete.**

---

### 12. Retry List Generator

```sql
-- Generate exact list of dates to retry
SELECT DISTINCT data_date
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = false
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  -- Only dates that never succeeded
  AND data_date NOT IN (
    SELECT DISTINCT data_date
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE phase = 'phase_3_analytics'
      AND success = true
      AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  )
ORDER BY data_date
```

**Export to CSV for retry script:**
```bash
bq query --use_legacy_sql=false --format=csv \
  "$(cat query_above)" > dates_to_retry.csv
```

---

## ✅ Quality Gate Verification {#quality-gate-verification}

### 13. Gate 0: Pre-Backfill - Phase 2 Completeness

```sql
-- Verify Phase 2 is 100% complete before starting
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase2 AS (
  SELECT COUNT(DISTINCT game_date) as phase2_dates
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p2.phase2_dates,
  s.total_dates - p2.phase2_dates as missing_dates,
  ROUND(100.0 * p2.phase2_dates / s.total_dates, 1) as completeness_pct,
  CASE
    WHEN p2.phase2_dates = s.total_dates THEN '✅ READY TO START'
    ELSE '❌ PHASE 2 INCOMPLETE - CANNOT START'
  END as gate_status
FROM schedule s, phase2 p2
```

**Must show:** `gate_status = '✅ READY TO START'`

---

### 14. Gate 1: Stage 1 Complete - Phase 3 at 100%

```sql
-- Verify Phase 3 is 100% complete before Stage 2
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase3 AS (
  SELECT COUNT(DISTINCT game_date) as phase3_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p3.phase3_dates,
  s.total_dates - p3.phase3_dates as missing_dates,
  ROUND(100.0 * p3.phase3_dates / s.total_dates, 1) as completeness_pct,
  CASE
    WHEN p3.phase3_dates = s.total_dates THEN '✅ READY FOR STAGE 2'
    WHEN p3.phase3_dates >= s.total_dates * 0.95 THEN '🟡 95%+ - Almost ready'
    ELSE '⚠️ STAGE 1 INCOMPLETE'
  END as gate_status
FROM schedule s, phase3 p3
```

**Must show:** `gate_status = '✅ READY FOR STAGE 2'`

---

### 15. Gate 2: Stage 2 Complete - Phase 4 at 100%

```sql
-- Verify Phase 4 is 100% complete before Stage 3
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase4 AS (
  SELECT COUNT(DISTINCT game_date) as phase4_dates
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p4.phase4_dates,
  s.total_dates - p4.phase4_dates as missing_dates,
  ROUND(100.0 * p4.phase4_dates / s.total_dates, 1) as completeness_pct,
  CASE
    WHEN p4.phase4_dates = s.total_dates THEN '✅ READY FOR STAGE 3'
    WHEN p4.phase4_dates >= s.total_dates * 0.95 THEN '🟡 95%+ - Almost ready'
    ELSE '⚠️ STAGE 2 INCOMPLETE'
  END as gate_status
FROM schedule s, phase4 p4
```

**Must show:** `gate_status = '✅ READY FOR STAGE 3'`

---

### 16. All-Tables Completeness Check

```sql
-- Verify all Phase 3 tables have data
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  'player_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates_with_data,
  (SELECT total_dates FROM schedule) as expected_dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total_dates FROM schedule), 1) as completeness_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

UNION ALL

SELECT
  'team_defense_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates_with_data,
  (SELECT total_dates FROM schedule) as expected_dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total_dates FROM schedule), 1) as completeness_pct
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

UNION ALL

SELECT
  'team_offense_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates_with_data,
  (SELECT total_dates FROM schedule) as expected_dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total_dates FROM schedule), 1) as completeness_pct
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

UNION ALL

SELECT
  'upcoming_player_game_context' as table_name,
  COUNT(DISTINCT game_date) as dates_with_data,
  (SELECT total_dates FROM schedule) as expected_dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total_dates FROM schedule), 1) as completeness_pct
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

UNION ALL

SELECT
  'upcoming_team_game_context' as table_name,
  COUNT(DISTINCT game_date) as dates_with_data,
  (SELECT total_dates FROM schedule) as expected_dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total_dates FROM schedule), 1) as completeness_pct
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

ORDER BY table_name
```

**All tables should show 100% completeness.**

---

## ⚡ Performance Metrics {#performance-metrics}

### 17. Average Processing Time per Date

```sql
-- See how long each date takes to process
SELECT
  data_date,
  COUNT(DISTINCT processor_name) as processors_run,
  AVG(processing_time_seconds) as avg_time_seconds,
  MAX(processing_time_seconds) as max_time_seconds,
  SUM(rows_processed) as total_rows_processed
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = true
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND created_at >= TIMESTAMP('2025-11-29 10:00:00')
GROUP BY data_date
ORDER BY avg_time_seconds DESC
LIMIT 20
```

**Use to identify slow dates that may need investigation.**

---

### 18. Processor Performance Comparison

```sql
-- Which processors are slowest?
SELECT
  processor_name,
  COUNT(*) as runs,
  AVG(processing_time_seconds) as avg_time,
  MAX(processing_time_seconds) as max_time,
  MIN(processing_time_seconds) as min_time,
  STDDEV(processing_time_seconds) as stddev_time
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = true
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND created_at >= TIMESTAMP('2025-11-29 10:00:00')
GROUP BY processor_name
ORDER BY avg_time DESC
```

---

## 🔄 Recovery Queries {#recovery-queries}

### 19. Identify Dates for Full Re-run

```sql
-- Dates that need complete re-run (all processors failed or incomplete)
SELECT DISTINCT data_date
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND data_date NOT IN (
    -- Exclude dates where at least 3 of 5 processors succeeded
    SELECT data_date
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE phase = 'phase_3_analytics'
      AND success = true
      AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
    GROUP BY data_date
    HAVING COUNT(DISTINCT processor_name) >= 3
  )
ORDER BY data_date
```

---

### 20. Identify Specific Processor Failures to Retry

```sql
-- Which specific processors need retry for which dates?
SELECT
  data_date,
  processor_name,
  COUNT(*) as failure_count,
  MAX(error_message) as last_error,
  MAX(created_at) as last_attempt
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = false
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
GROUP BY data_date, processor_name
ORDER BY data_date, processor_name
```

---

## 📝 Quick Reference Commands

### Export Queries to CSV

```bash
# Missing dates for Phase 3
bq query --use_legacy_sql=false --format=csv --max_rows=1000 \
  "SELECT ... FROM ..." > phase3_missing.csv

# Current progress
bq query --use_legacy_sql=false --format=table \
  "SELECT ... FROM ..."

# Failure list
bq query --use_legacy_sql=false --format=csv \
  "SELECT ... FROM ..." > failures_to_investigate.csv
```

### Run Queries in Loop

```bash
# Monitor progress every 5 minutes
while true; do
  clear
  echo "=== Backfill Progress ($(date)) ==="
  bq query --use_legacy_sql=false "Query #5 from above"
  sleep 300  # 5 minutes
done
```

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29
**Related Docs:**
- BACKFILL-MASTER-EXECUTION-GUIDE.md
- BACKFILL-FAILURE-RECOVERY.md
