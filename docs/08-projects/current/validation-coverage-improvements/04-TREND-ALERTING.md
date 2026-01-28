# Trend Alerting - Quality Over Time

**Priority**: P3
**Effort**: 4-6 hours
**Status**: Investigation

---

## Problem Statement

Quality can degrade gradually over time. A 1% drop per day for a week = 7% total drop. Our current validation checks point-in-time values but doesn't detect trends.

---

## Proposed Solution

Track key quality metrics over 7-day rolling window and alert on declining trends.

### Metrics to Track
1. Field completeness rates (NULL %)
2. Prediction coverage (predictions / expected)
3. Box score completeness (games with data / games played)
4. Processing success rates

### Alert Conditions
- Metric dropped >5% over 7 days
- 3+ consecutive days of decline
- Current value < 7-day average - 2 standard deviations

---

## Implementation Plan

### Step 1: Create Trend Tracking Table
```sql
CREATE TABLE nba_monitoring.quality_trends (
  metric_date DATE,
  metric_name STRING,
  metric_value FLOAT64,
  rolling_7d_avg FLOAT64,
  rolling_7d_stddev FLOAT64,
  trend_direction STRING,  -- 'improving', 'stable', 'declining'
  alert_triggered BOOLEAN
);
```

### Step 2: Create Daily Trend Update Query
Scheduled query to update trends daily.

### Step 3: Add Trend Visualization
Looker or BigQuery dashboard showing trends.

---

## Investigation Questions

1. What metrics should we track?
2. What's the right alerting threshold? (5%? 10%?)
3. Should we use linear regression or simple comparison?
4. How far back should we look? (7 days? 14 days?)
5. Where should trend data be visualized?

---

## Success Criteria

- [ ] 7-day trends calculated daily
- [ ] Declining trends trigger alerts
- [ ] Trends visible in dashboard
