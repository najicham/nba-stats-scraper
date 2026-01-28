# Trend Alerting - Investigation Findings

**Investigated**: 2026-01-28
**Status**: New Capability Needed

---

## Key Finding: Alerting Infrastructure Exists, Trend Tracking Does Not

We have robust alerting (Slack, email, Cloud Monitoring) but NO trend detection. All current checks use static thresholds - no statistical anomaly detection.

---

## 1. Quality Metrics Currently Tracked

**Field Completeness** (`shared/validation/feature_thresholds.py`):
- minutes_played: 99% threshold
- usage_rate: 95% threshold  
- points, rebounds, assists: 99%+
- Shot distribution metrics: 40-99%

**Data Freshness** (`functions/monitoring/data_completeness_checker/`):
- bdl_injuries: 24h threshold
- odds_api props: 12h
- player_game_summary: 24h

**Processing Metrics**:
- completeness_percentage per processor
- production_ready counts
- circuit_breaker states
- prediction coverage rates

---

## 2. Existing Trend Infrastructure

**BigQuery Views:**
- `completeness_trends` - 30-day history
- `pipeline_health_summary` - 24h and 7d metrics
- `multi_window_completeness` - rolling window analysis

**Gap: No dedicated trend alerting table**
- No 7-day rolling averages stored
- No trend direction classification
- No statistical anomaly detection

---

## 3. Alerting Systems (Robust)

| Channel | Implementation | Features |
|---------|----------------|----------|
| Slack | `notification_system.py` | Multi-tier webhooks, rate limiting |
| Email | `email_alerting_ses.py` | HTML reports, severity routing |
| Cloud Monitoring | `monitoring/alert-policies/` | Auto-close, rate limits |

**Smart Alerting** (`smart_alerting.py`):
- 60-minute cooldown between duplicates
- Backfill mode batches alerts
- 20+ predefined alert types

---

## 4. Data Retention (Sufficient)

| Table Type | Retention |
|------------|-----------|
| Processing logs | 180-365 days |
| Processing issues | 730 days (2 years) |
| Prediction results | 1095 days (3 years) |
| Processor execution | 90 days |
| Player daily cache | 30 days |

**Sufficient for 7-day trends** - most tables retain 90+ days.

---

## 5. Existing Dashboards

**Grafana** (`monitoring/grafana/dashboards/`):
- Success rate gauges
- Duration metrics
- Skip reason charts

**Cloud Console**:
- Pipeline health dashboard
- Grading system dashboard

**Gap**: No trend-specific dashboards showing rolling averages or declining metrics.

---

## 6. Statistical Methods

**Currently Used:**
- Static threshold detection (>40%, >50%, >100%)
- Simple AVG, MIN, MAX aggregations
- Percentage calculations
- TIMESTAMP_DIFF for latency

**NOT Used (needed for trends):**
- ❌ Standard deviation (STDDEV)
- ❌ Percentile-based detection
- ❌ Z-score calculations
- ❌ Linear regression
- ❌ Moving averages
- ❌ Exponential smoothing

---

## 7. Implementation Plan

**Create `nba_monitoring.quality_trends` table:**
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

**Scheduled Query** (daily):
1. Calculate current metric values
2. Compute 7-day rolling average
3. Calculate standard deviation
4. Classify trend direction
5. Alert if declining >5% or 3+ consecutive declines

**Alert Conditions:**
- Metric dropped >5% over 7 days
- 3+ consecutive days of decline
- Value < (7d_avg - 2*stddev)

---

## 8. Summary

| Component | Status |
|-----------|--------|
| Alert delivery | ✅ Ready (Slack, email, Cloud Monitoring) |
| Data retention | ✅ Sufficient (90+ days) |
| Dashboards | ⚠️ Exist but need trend panels |
| Trend tracking | ❌ New capability needed |
| Statistical detection | ❌ New capability needed |
