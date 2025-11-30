# Phase 4→5 Integration - Monitoring Guide

**For complete monitoring setup, see full spec Section 9 "Monitoring & Observability"**

This document provides essential monitoring queries.

---

## Daily Health Check

**Run every morning at 11 AM to verify previous night's processing:**

```sql
WITH phase4_status AS (
    SELECT data_date, MAX(processed_at) as phase4_completed
    FROM `nba_reference.processor_run_history`
    WHERE processor_name = 'ml_feature_store_v2'
      AND data_date = CURRENT_DATE()
    GROUP BY data_date
),
phase5_status AS (
    SELECT data_date, MIN(started_at) as phase5_started
    FROM `nba_reference.processor_run_history`
    WHERE processor_name = 'phase5_coordinator'
      AND data_date = CURRENT_DATE()
    GROUP BY data_date
),
predictions_count AS (
    SELECT game_date, COUNT(DISTINCT player_lookup) as predictions
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = CURRENT_DATE()
    GROUP BY game_date
)
SELECT 
    FORMAT_TIMESTAMP('%H:%M', p4.phase4_completed) as phase4_done,
    FORMAT_TIMESTAMP('%H:%M', p5.phase5_started) as phase5_started,
    TIMESTAMP_DIFF(p5.phase5_started, p4.phase4_completed, MINUTE) as latency_min,
    pred.predictions as predictions_generated,
    CASE
        WHEN TIMESTAMP_DIFF(p5.phase5_started, p4.phase4_completed, MINUTE) < 5 THEN '✅ Excellent'
        WHEN TIMESTAMP_DIFF(p5.phase5_started, p4.phase4_completed, MINUTE) < 30 THEN '⚠️ Warning'
        ELSE '❌ Critical'
    END as status
FROM phase4_status p4
LEFT JOIN phase5_status p5 ON p4.data_date = p5.data_date
LEFT JOIN predictions_count pred ON p4.data_date = pred.game_date;
```

---

## Key Metrics

### 1. Phase 4→5 Latency
```sql
SELECT 
    data_date,
    TIMESTAMP_DIFF(phase5_started, phase4_completed, MINUTE) as latency_minutes
FROM (
    SELECT data_date, MAX(processed_at) as phase4_completed
    FROM `nba_reference.processor_run_history`
    WHERE processor_name = 'ml_feature_store_v2'
    GROUP BY data_date
) p4
JOIN (
    SELECT data_date, MIN(started_at) as phase5_started
    FROM `nba_reference.processor_run_history`
    WHERE processor_name = 'phase5_coordinator'
    GROUP BY data_date
) p5 USING (data_date)
WHERE data_date >= CURRENT_DATE() - 7
ORDER BY data_date DESC;
```

**Target:** < 5 minutes (event-driven working)

---

### 2. Prediction Completion Rate
```sql
WITH expected AS (
    SELECT game_date, COUNTIF(is_production_ready) as ready
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = CURRENT_DATE()
    GROUP BY game_date
),
actual AS (
    SELECT game_date, COUNT(DISTINCT player_lookup) as predictions
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = CURRENT_DATE()
    GROUP BY game_date
)
SELECT 
    e.ready as expected,
    a.predictions as actual,
    ROUND(a.predictions / e.ready * 100, 1) as completion_pct
FROM expected e
LEFT JOIN actual a USING (game_date);
```

**Target:** > 95%

---

### 3. Phase 4 Data Quality
```sql
SELECT 
    COUNT(*) as total_players,
    COUNTIF(is_production_ready) as ready_players,
    ROUND(AVG(feature_quality_score), 1) as avg_quality,
    ROUND(SAFE_DIVIDE(COUNTIF(is_production_ready), COUNT(*)) * 100, 1) as ready_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Target:** > 95% ready, > 90 avg quality

---

## Alert Thresholds

| Alert | Condition | Severity |
|-------|-----------|----------|
| Latency high | > 10 minutes | Warning |
| Latency critical | > 60 minutes (scheduler triggered) | Critical |
| Completion low | < 90% | Warning |
| Completion critical | < 50% | Critical |
| Zero predictions | 0 by 7:00 AM PT | Critical |

---

**For complete monitoring setup including dashboards, see full spec Section 9.**
