# Admin Dashboard Enhancement Proposal: ML Feature Health Tab

**Date:** 2026-01-31
**Status:** Proposed
**Priority:** HIGH

---

## Overview

Add a new "ML Feature Health" tab to the admin dashboard that surfaces feature quality issues in real-time, using data from `nba_monitoring_west2.feature_health_daily`.

---

## Proposed API Endpoints

### `/api/feature-health/summary`

Returns health status for all monitored features:

```json
{
  "report_date": "2026-01-30",
  "features": [
    {
      "name": "team_win_pct",
      "health_status": "critical",
      "mean": 0.5,
      "stddev": 0.0,
      "zero_pct": 0.0,
      "distinct_values": 1,
      "alert_reasons": ["ZERO_VARIANCE: all values identical"]
    },
    {
      "name": "fatigue_score",
      "health_status": "healthy",
      "mean": 91.2,
      "stddev": 8.4,
      "zero_pct": 0.0,
      "distinct_values": 25,
      "alert_reasons": []
    }
  ],
  "summary": {
    "total_features": 12,
    "healthy": 8,
    "warning": 2,
    "critical": 2
  }
}
```

### `/api/feature-health/trends/<feature_name>`

Returns 30-day trend for a specific feature:

```json
{
  "feature_name": "team_win_pct",
  "trends": [
    {"date": "2026-01-30", "mean": 0.5, "stddev": 0.0, "health_status": "critical"},
    {"date": "2026-01-29", "mean": 0.506, "stddev": 0.15, "health_status": "healthy"},
    ...
  ]
}
```

### `/api/feature-health/comparison`

Compare current day to 30-day baseline:

```json
{
  "report_date": "2026-01-30",
  "comparisons": [
    {
      "name": "team_win_pct",
      "current_mean": 0.5,
      "baseline_mean": 0.52,
      "mean_change_pct": -3.8,
      "current_stddev": 0.0,
      "baseline_stddev": 0.14,
      "stddev_change_pct": -100.0,
      "anomaly": true
    }
  ]
}
```

---

## Proposed UI Components

### 1. Health Status Grid

A grid showing all 37 features with color-coded health status:
- 🟢 Green: Healthy
- 🟡 Yellow: Warning (low variance, mean drift)
- 🔴 Red: Critical (zero variance, out of range)

### 2. Feature Distribution Cards

For each feature, show:
- Mean ± StdDev
- Min / Max
- Zero %
- Null %
- Distinct values count

### 3. Variance Anomaly Alerts

Highlight features with:
- `stddev < threshold` (suspiciously constant)
- `distinct_values < 5` (too few unique values)
- Zero variance (all values identical)

### 4. Historical Comparison Chart

Line chart showing:
- Current mean vs 30-day baseline
- StdDev trend over time
- Anomaly markers

### 5. Feature Investigation Panel

Click on any feature to see:
- Full distribution histogram
- Sample records with that value
- Upstream data source status
- Link to relevant documentation

---

## SQL Queries for Dashboard

### Feature Health Summary

```sql
SELECT
  feature_name,
  health_status,
  ROUND(mean, 2) as mean,
  ROUND(stddev, 2) as stddev,
  ROUND(zero_pct, 1) as zero_pct,
  ROUND(null_pct, 1) as null_pct,
  alert_reasons
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY
  CASE health_status WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
  feature_name
```

### Variance Anomaly Detection

```sql
SELECT
  feature_name,
  report_date,
  mean,
  stddev,
  baseline_stddev,
  ROUND(100 * (stddev - baseline_stddev) / NULLIF(baseline_stddev, 0), 1) as stddev_change_pct
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND stddev < baseline_stddev * 0.5  -- StdDev dropped by 50%+
ORDER BY report_date DESC, stddev_change_pct
```

### Historical Trend

```sql
SELECT
  report_date,
  mean,
  stddev,
  health_status
FROM nba_monitoring_west2.feature_health_daily
WHERE feature_name = @feature_name
  AND report_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY report_date
```

---

## Implementation Plan

### Phase 1: Backend API (1-2 hours)
1. Create `services/admin_dashboard/blueprints/feature_health.py`
2. Add endpoints listed above
3. Register blueprint in app.py

### Phase 2: Frontend UI (2-3 hours)
1. Create `templates/components/feature_health.html`
2. Add tab to `templates/dashboard.html`
3. Add Chart.js trend visualization

### Phase 3: Alerting Integration (1 hour)
1. Add critical alerts to existing alert system
2. Send Slack notification on critical health status

---

## Benefits

1. **Early Detection**: Catch bugs like team_win_pct=0.5 within 24 hours, not weeks
2. **Visual Monitoring**: See all 37 features at a glance
3. **Historical Context**: Compare to baseline to catch regressions
4. **Investigation Tools**: Drill down into specific features
5. **Alerting**: Proactive notification of issues

---

## Success Metrics

- Time to detect feature bugs: ≤24 hours (vs 5+ days currently)
- False positive rate: <5% of alerts
- Dashboard load time: <3 seconds
- User adoption: Check dashboard daily

---

*Proposed as part of Session 49 Feature Quality Monitoring project*
