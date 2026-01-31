# Validation Queries - Data Quality Self-Healing

Ready-to-use SQL queries for monitoring data quality. Run these manually or integrate into automated checks.

---

## Daily Health Checks

### 1. DNP Status Check (CRITICAL)

Detects the exact issue that caused the DNP corruption incident.

```sql
-- Check DNP handling for recent dates
-- Expected: dnp_marked > 0 and pct_zero < 15% for each date with games
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(is_dnp = TRUE) as dnp_marked,
    COUNTIF(points IS NULL) as null_points,
    COUNTIF(points = 0) as zero_points,
    ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero,
    CASE
        WHEN COUNTIF(is_dnp = TRUE) = 0 THEN 'CRITICAL: No DNPs marked'
        WHEN ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) > 30 THEN 'CRITICAL: High zero rate'
        WHEN ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) > 15 THEN 'WARNING: Elevated zero rate'
        ELSE 'OK'
    END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

### 2. Feature Store Completeness

Ensures ML features are complete before predictions.

```sql
-- Check ML feature store completeness
-- Expected: completeness > 95%, null_features = 0
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(features IS NULL) as null_features,
    ROUND(100.0 * COUNTIF(features IS NOT NULL) / COUNT(*), 1) as completeness_pct,
    ROUND(AVG(ARRAY_LENGTH(features)), 1) as avg_feature_count,
    CASE
        WHEN COUNTIF(features IS NULL) > COUNT(*) * 0.1 THEN 'CRITICAL: >10% null features'
        WHEN COUNTIF(features IS NULL) > COUNT(*) * 0.05 THEN 'WARNING: >5% null features'
        ELSE 'OK'
    END as status
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

### 3. Fatigue Score Validation

Detects the parallel processing bug that caused fatigue=0.

```sql
-- Check fatigue scores
-- Expected: avg between 70-95, no zeros (all players have some fatigue)
SELECT
    game_date,
    COUNT(*) as total_records,
    ROUND(AVG(fatigue_score), 1) as avg_fatigue,
    ROUND(MIN(fatigue_score), 1) as min_fatigue,
    ROUND(MAX(fatigue_score), 1) as max_fatigue,
    COUNTIF(fatigue_score = 0) as zero_fatigue,
    COUNTIF(fatigue_score = 100) as perfect_fatigue,
    CASE
        WHEN AVG(fatigue_score) < 50 THEN 'CRITICAL: Low fatigue average'
        WHEN COUNTIF(fatigue_score = 0) > 10 THEN 'WARNING: Many zero fatigue'
        WHEN AVG(fatigue_score) > 98 THEN 'WARNING: Suspiciously high fatigue'
        ELSE 'OK'
    END as status
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## Historical Audit Queries

### 4. Monthly DNP Audit

Check historical data for DNP corruption.

```sql
-- Monthly DNP audit - find months needing reprocessing
-- Red flag: dnp_marked = 0 AND pct_zero > 25%
SELECT
    DATE_TRUNC(game_date, MONTH) as month,
    COUNT(*) as total_records,
    COUNTIF(is_dnp = TRUE) as dnp_marked,
    COUNTIF(points IS NULL) as null_points,
    ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero,
    CASE
        WHEN COUNTIF(is_dnp = TRUE) = 0 AND ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) > 25 THEN 'NEEDS REPROCESSING'
        WHEN COUNTIF(is_dnp = TRUE) = 0 THEN 'CHECK REQUIRED'
        ELSE 'OK'
    END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2025-10-01'
GROUP BY 1
ORDER BY 1;
```

### 5. Star Player Zero Check

Star players should rarely score exactly 0.

```sql
-- Find star players with suspicious zero scores
-- Star = averaging 20+ points
WITH player_avgs AS (
    SELECT
        player_lookup,
        AVG(CASE WHEN points > 0 THEN points END) as avg_points,
        COUNT(*) as games
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
      AND is_dnp = FALSE
    GROUP BY player_lookup
    HAVING AVG(CASE WHEN points > 0 THEN points END) >= 20
)
SELECT
    pgs.player_lookup,
    pa.avg_points,
    pgs.game_date,
    pgs.points,
    pgs.is_dnp,
    pgs.minutes
FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
JOIN player_avgs pa ON pgs.player_lookup = pa.player_lookup
WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pgs.points = 0
  AND pgs.is_dnp = FALSE
ORDER BY pa.avg_points DESC, pgs.game_date DESC;
```

---

## Anomaly Detection Queries

### 6. Day-over-Day Stat Shifts

Detect sudden changes in aggregate statistics.

```sql
-- Day-over-day stat shifts
-- Alert if >20% change in any metric
WITH daily_stats AS (
    SELECT
        game_date,
        AVG(CASE WHEN is_dnp = FALSE THEN points END) as avg_points,
        AVG(CASE WHEN is_dnp = FALSE THEN minutes END) as avg_minutes,
        ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as pct_zero
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    GROUP BY game_date
)
SELECT
    curr.game_date,
    curr.avg_points as curr_avg_points,
    prev.avg_points as prev_avg_points,
    ROUND(100.0 * (curr.avg_points - prev.avg_points) / NULLIF(prev.avg_points, 0), 1) as points_change_pct,
    curr.pct_zero as curr_pct_zero,
    prev.pct_zero as prev_pct_zero,
    ROUND(curr.pct_zero - prev.pct_zero, 1) as zero_change_pct,
    CASE
        WHEN ABS(100.0 * (curr.avg_points - prev.avg_points) / NULLIF(prev.avg_points, 0)) > 20 THEN 'ALERT: Large points shift'
        WHEN ABS(curr.pct_zero - prev.pct_zero) > 10 THEN 'ALERT: Large zero rate shift'
        ELSE 'OK'
    END as status
FROM daily_stats curr
LEFT JOIN daily_stats prev ON prev.game_date = DATE_SUB(curr.game_date, INTERVAL 1 DAY)
WHERE prev.game_date IS NOT NULL
ORDER BY curr.game_date DESC;
```

### 7. Statistical Distribution Check

Compare recent data to historical baseline.

```sql
-- Compare recent 7 days to prior 30 days
-- Alert if metrics deviate significantly
WITH recent AS (
    SELECT
        'recent' as period,
        AVG(CASE WHEN is_dnp = FALSE THEN points END) as avg_points,
        STDDEV(CASE WHEN is_dnp = FALSE THEN points END) as stddev_points,
        ROUND(100.0 * COUNTIF(is_dnp = TRUE) / COUNT(*), 1) as dnp_rate,
        ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as zero_rate
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
baseline AS (
    SELECT
        'baseline' as period,
        AVG(CASE WHEN is_dnp = FALSE THEN points END) as avg_points,
        STDDEV(CASE WHEN is_dnp = FALSE THEN points END) as stddev_points,
        ROUND(100.0 * COUNTIF(is_dnp = TRUE) / COUNT(*), 1) as dnp_rate,
        ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as zero_rate
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 37 DAY)
      AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
    r.avg_points as recent_avg,
    b.avg_points as baseline_avg,
    ROUND((r.avg_points - b.avg_points) / NULLIF(b.stddev_points, 0), 2) as z_score_points,
    r.dnp_rate as recent_dnp_rate,
    b.dnp_rate as baseline_dnp_rate,
    r.zero_rate as recent_zero_rate,
    b.zero_rate as baseline_zero_rate,
    CASE
        WHEN ABS((r.avg_points - b.avg_points) / NULLIF(b.stddev_points, 0)) > 2 THEN 'ALERT: Points >2 sigma'
        WHEN ABS(r.dnp_rate - b.dnp_rate) > 5 THEN 'ALERT: DNP rate shifted'
        WHEN ABS(r.zero_rate - b.zero_rate) > 5 THEN 'ALERT: Zero rate shifted'
        ELSE 'OK'
    END as status
FROM recent r
CROSS JOIN baseline b;
```

---

## Validation Failure Analysis

### 8. Recent Validation Failures

Review records blocked by pre-write validation (after implementation).

```sql
-- Recent validation failures
SELECT
    DATE(failure_timestamp) as failure_date,
    table_name,
    COUNT(*) as failure_count,
    ARRAY_AGG(DISTINCT violations[SAFE_OFFSET(0)] LIMIT 5) as sample_violations
FROM `nba-props-platform.nba_orchestration.validation_failures`
WHERE failure_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

### 9. Validation Failure Details

Investigate specific validation failures.

```sql
-- Detailed validation failures for a specific date
SELECT
    failure_timestamp,
    player_lookup,
    game_date,
    violations,
    JSON_EXTRACT_SCALAR(record_json, '$.is_dnp') as is_dnp,
    JSON_EXTRACT_SCALAR(record_json, '$.points') as points,
    JSON_EXTRACT_SCALAR(record_json, '$.minutes') as minutes
FROM `nba-props-platform.nba_orchestration.validation_failures`
WHERE game_date = '2026-01-22'  -- Change as needed
ORDER BY failure_timestamp DESC
LIMIT 100;
```

---

## Backfill Queue Monitoring

### 10. Backfill Queue Status

Monitor automated remediation queue (after implementation).

```sql
-- Backfill queue status
SELECT
    status,
    table_name,
    COUNT(*) as count,
    MIN(created_at) as oldest,
    MAX(created_at) as newest,
    AVG(attempts) as avg_attempts
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 11. Failed Backfills

Investigate backfills that failed.

```sql
-- Failed backfills needing attention
SELECT
    queue_id,
    table_name,
    game_date,
    reason,
    attempts,
    last_attempt_at,
    error_message
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE status = 'FAILED'
  OR (status = 'PENDING' AND attempts >= max_attempts)
ORDER BY created_at DESC
LIMIT 20;
```

---

## Quality Metrics Dashboard

### 12. Quality Metrics Trend

View quality metrics over time.

```sql
-- Quality metrics trend for dashboard
SELECT
    metric_date,
    metric_name,
    metric_value,
    threshold_warning,
    threshold_critical,
    status
FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
WHERE metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND table_name = 'player_game_summary'
ORDER BY metric_date DESC, metric_name;
```

### 13. Quality Summary

Current quality status across all tables.

```sql
-- Current quality status (most recent check per metric)
WITH latest AS (
    SELECT
        table_name,
        metric_name,
        metric_value,
        status,
        ROW_NUMBER() OVER (PARTITION BY table_name, metric_name ORDER BY metric_date DESC) as rn
    FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
    WHERE metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
)
SELECT
    table_name,
    COUNTIF(status = 'OK') as ok_count,
    COUNTIF(status = 'WARNING') as warning_count,
    COUNTIF(status = 'CRITICAL') as critical_count,
    CASE
        WHEN COUNTIF(status = 'CRITICAL') > 0 THEN 'CRITICAL'
        WHEN COUNTIF(status = 'WARNING') > 0 THEN 'WARNING'
        ELSE 'OK'
    END as overall_status
FROM latest
WHERE rn = 1
GROUP BY table_name
ORDER BY
    CASE WHEN COUNTIF(status = 'CRITICAL') > 0 THEN 0
         WHEN COUNTIF(status = 'WARNING') > 0 THEN 1
         ELSE 2 END,
    table_name;
```

---

## Quick Reference

| Check | Run When | Action if CRITICAL |
|-------|----------|-------------------|
| DNP Status Check | Daily | Reprocess analytics layer |
| Feature Store Completeness | Before predictions | Reprocess ML feature store |
| Fatigue Score Validation | Daily | Reprocess composite factors |
| Monthly DNP Audit | Weekly | Backfill historical data |
| Star Player Zero Check | Daily | Investigate specific games |
| Day-over-Day Stat Shifts | Daily | Investigate data sources |

---

*Validation Queries v1.0 - 2026-01-30*
