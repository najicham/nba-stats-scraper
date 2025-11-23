# Completeness Checking - Monitoring Guide

**For:** DevOps, SRE, Engineering Team
**Purpose:** Set up monitoring dashboards, alerts, and track completeness metrics
**Time to Read:** 10 minutes

---

## Quick Start

### 1. Import Grafana Dashboard (5 minutes)

**File:** `docs/monitoring/completeness-grafana-dashboard.json`

**Steps:**
1. Open Grafana
2. Navigate to Dashboards → Import
3. Upload `completeness-grafana-dashboard.json`
4. Select your BigQuery data source
5. Click Import

**Result:** 9-panel dashboard with completeness metrics and alerts.

### 2. Set Up Alerts (10 minutes)

Configure alerts on these panels:
- **Active Circuit Breakers** - Alert when >10
- **Overall Completeness Health** - Alert when production_ready_pct <90%
- **Entities Below 90%** - Alert when >20 entities below threshold

---

## Monitoring Dashboard Overview

### 9 Dashboard Panels

| Panel # | Name | Purpose | Alert Threshold |
|---------|------|---------|----------------|
| 1 | Overall Completeness Health | Production readiness by processor | <90% |
| 2 | Active Circuit Breakers | Count of tripped breakers | >10 |
| 3 | Completeness Trends (30d) | Historical completeness patterns | N/A |
| 4 | Entities Below 90% | Players/teams with incomplete data | >20 |
| 5 | Circuit Breaker History | Recent breaker trips | N/A |
| 6 | Bootstrap Mode Records | Early season tracking | N/A |
| 7 | Multi-Window Detail | Per-window completeness breakdown | N/A |
| 8 | Production Readiness Summary | Overall system health | <95% |
| 9 | Reprocessing Patterns | Entities requiring reprocessing | N/A |

---

## Key Metrics to Track

### Daily Health Metrics

#### 1. Production Readiness Percentage

**Target:** ≥95% of entities should be production-ready

**Query:**
```sql
SELECT
  processor_name,
  COUNT(*) as total_entities,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
  AVG(completeness_percentage) as avg_completeness
FROM (
  -- Player Daily Cache
  SELECT
    'player_daily_cache' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  -- Player Composite Factors
  SELECT
    'player_composite_factors' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  -- Player Shot Zone Analysis
  SELECT
    'player_shot_zone_analysis' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  -- Team Defense Zone Analysis
  SELECT
    'team_defense_zone_analysis' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  -- ML Feature Store
  SELECT
    'ml_feature_store' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  -- Upcoming Player Game Context
  SELECT
    'upcoming_player_game_context' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_analytics.upcoming_player_game_context`
  WHERE game_date = CURRENT_DATE()

  UNION ALL

  -- Upcoming Team Game Context
  SELECT
    'upcoming_team_game_context' as processor_name,
    is_production_ready,
    completeness_percentage
  FROM `nba_analytics.upcoming_team_game_context`
  WHERE game_date = CURRENT_DATE()
)
GROUP BY processor_name
ORDER BY production_ready_pct ASC;
```

**Alert if:** Any processor <90% production_ready_pct

---

#### 2. Active Circuit Breakers

**Target:** <5 active circuit breakers (10 is alert threshold)

**Query:**
```sql
SELECT
  processor_name,
  entity_id,
  analysis_date,
  completeness_pct,
  skip_reason,
  attempt_count,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining,
  manual_override_applied
FROM `nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
  AND manual_override_applied = FALSE
ORDER BY days_remaining DESC, processor_name, entity_id;
```

**Alert if:** COUNT(*) >10 active circuit breakers

**Action:**
```bash
cd /home/naji/code/nba-stats-scraper
./scripts/completeness/check-circuit-breaker-status --active-only
```

---

#### 3. Average Completeness Percentage

**Target:** ≥92% across all processors

**Query:**
```sql
SELECT
  'Overall' as scope,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness,
  MIN(completeness_percentage) as min_completeness,
  MAX(completeness_percentage) as max_completeness,
  STDDEV(completeness_percentage) as stddev_completeness
FROM (
  SELECT completeness_percentage FROM `nba_precompute.player_daily_cache` WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT completeness_percentage FROM `nba_precompute.player_composite_factors` WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT completeness_percentage FROM `nba_precompute.player_shot_zone_analysis` WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT completeness_percentage FROM `nba_precompute.team_defense_zone_analysis` WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT completeness_percentage FROM `nba_predictions.ml_feature_store_v2` WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT completeness_percentage FROM `nba_analytics.upcoming_player_game_context` WHERE game_date = CURRENT_DATE()
  UNION ALL
  SELECT completeness_percentage FROM `nba_analytics.upcoming_team_game_context` WHERE game_date = CURRENT_DATE()
);
```

**Alert if:** avg_completeness <85%

---

### Weekly Health Metrics

#### 4. Completeness Trends (7-day)

**Purpose:** Identify systematic data quality issues

**Query:**
```sql
SELECT
  DATE(analysis_date) as date,
  processor_name,
  AVG(completeness_percentage) as avg_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
  COUNT(*) as total_entities
FROM (
  SELECT analysis_date, 'player_daily_cache' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date >= CURRENT_DATE() - 7

  UNION ALL

  SELECT analysis_date, 'player_composite_factors' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date >= CURRENT_DATE() - 7

  -- Add other processors...
)
GROUP BY date, processor_name
ORDER BY date DESC, processor_name;
```

**Look for:**
- Declining trends in avg_completeness
- Sudden drops in production_ready_pct
- Increasing circuit breaker trips

---

#### 5. Circuit Breaker Trip Frequency

**Purpose:** Identify problematic entities or processors

**Query:**
```sql
SELECT
  processor_name,
  entity_id,
  COUNT(*) as trip_count,
  MAX(created_at) as last_trip,
  AVG(completeness_pct) as avg_completeness_at_trip,
  STRING_AGG(DISTINCT skip_reason, ', ') as skip_reasons
FROM `nba_orchestration.reprocess_attempts`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND circuit_breaker_tripped = TRUE
GROUP BY processor_name, entity_id
HAVING trip_count >= 2
ORDER BY trip_count DESC, processor_name, entity_id;
```

**Investigate if:**
- Same entity trips repeatedly
- All trips from one processor
- Consistent skip_reason pattern

---

### Monthly Health Metrics

#### 6. Bootstrap Mode Usage

**Purpose:** Verify bootstrap mode working correctly during early season

**Query:**
```sql
SELECT
  DATE(analysis_date) as date,
  COUNT(*) as total_records,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_count,
  ROUND(100.0 * SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) / COUNT(*), 2) as bootstrap_pct,
  AVG(completeness_percentage) as avg_completeness
FROM (
  SELECT analysis_date, backfill_bootstrap_mode, completeness_percentage
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date >= '2024-10-01' AND analysis_date < '2024-11-01'
)
GROUP BY date
ORDER BY date;
```

**Expected:**
- First 30 days: bootstrap_pct >50%
- After 30 days: bootstrap_pct <5%

---

## Alert Configuration

### Critical Alerts (PagerDuty/On-Call)

#### Alert 1: Widespread Circuit Breaker Trips
```yaml
name: completeness-circuit-breaker-critical
query: |
  SELECT COUNT(*) as active_breakers
  FROM `nba_orchestration.reprocess_attempts`
  WHERE circuit_breaker_tripped = TRUE
    AND circuit_breaker_until > CURRENT_TIMESTAMP()
    AND manual_override_applied = FALSE
condition: active_breakers > 20
severity: critical
notification: pagerduty
```

#### Alert 2: All Processors Failing
```yaml
name: completeness-all-processors-failing
query: |
  SELECT
    COUNT(DISTINCT processor_name) as failing_processors
  FROM (/* UNION ALL processors */)
  WHERE is_production_ready = FALSE
  GROUP BY analysis_date
  HAVING analysis_date = CURRENT_DATE() - 1
condition: failing_processors >= 6
severity: critical
notification: pagerduty
```

---

### Warning Alerts (Slack/Email)

#### Alert 3: Production Readiness Below Threshold
```yaml
name: completeness-production-readiness-low
query: |
  SELECT processor_name, production_ready_pct
  FROM (/* Production Readiness Query */)
  WHERE production_ready_pct < 90
condition: COUNT(*) > 0
severity: warning
notification: slack
channel: "#nba-alerts"
```

#### Alert 4: Completeness Trending Down
```yaml
name: completeness-trending-down
query: |
  SELECT
    processor_name,
    AVG(completeness_percentage) as avg_today,
    (SELECT AVG(completeness_percentage) FROM /* 7 days ago */) as avg_7d_ago,
    avg_today - avg_7d_ago as trend
  FROM (/* Current completeness */)
  HAVING trend < -5.0
condition: COUNT(*) > 0
severity: warning
notification: slack
```

---

## Dashboard Queries

### Query 1: Overall Completeness Health
**Panel:** Time series graph
**Refresh:** Every 5 minutes

```sql
SELECT
  TIMESTAMP(analysis_date) as time,
  processor_name as metric,
  AVG(completeness_percentage) as value
FROM (
  SELECT analysis_date, 'player_daily_cache' as processor_name, completeness_percentage
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date >= CURRENT_DATE() - 30

  UNION ALL

  SELECT analysis_date, 'player_composite_factors' as processor_name, completeness_percentage
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date >= CURRENT_DATE() - 30

  -- Add other processors...
)
GROUP BY time, metric
ORDER BY time DESC, metric;
```

**Thresholds:**
- Green: ≥95%
- Yellow: 90-95%
- Red: <90%

---

### Query 2: Active Circuit Breakers (Count)
**Panel:** Single stat with trend
**Refresh:** Every 1 minute

```sql
SELECT
  COUNT(*) as value,
  'active_breakers' as metric
FROM `nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
  AND manual_override_applied = FALSE;
```

**Thresholds:**
- Green: 0-5
- Yellow: 6-10
- Red: >10

---

### Query 3: Entities Below 90% Completeness
**Panel:** Table
**Refresh:** Every 5 minutes

```sql
SELECT
  processor_name,
  entity_id,
  analysis_date,
  ROUND(completeness_percentage, 2) as completeness_pct,
  expected_games_count,
  actual_games_count,
  missing_games_count,
  data_quality_issues,
  processing_decision_reason
FROM (
  SELECT 'player_daily_cache' as processor_name, player_lookup as entity_id, analysis_date,
         completeness_percentage, expected_games_count, actual_games_count, missing_games_count,
         data_quality_issues, processing_decision_reason
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1 AND completeness_percentage < 90

  UNION ALL

  SELECT 'player_composite_factors' as processor_name, player_lookup as entity_id, analysis_date,
         completeness_percentage, expected_games_count, actual_games_count, missing_games_count,
         data_quality_issues, processing_decision_reason
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE() - 1 AND completeness_percentage < 90

  -- Add other processors...
)
ORDER BY completeness_pct ASC, processor_name, entity_id;
```

---

### Query 4: Multi-Window Completeness Detail
**Panel:** Table with color coding
**Refresh:** Every 5 minutes

```sql
-- Player Daily Cache (4 windows)
SELECT
  'player_daily_cache' as processor,
  player_lookup,
  analysis_date,
  ROUND(completeness_percentage, 2) as overall_pct,
  ROUND(l5_completeness_pct, 2) as l5_pct,
  ROUND(l10_completeness_pct, 2) as l10_pct,
  ROUND(l7d_completeness_pct, 2) as l7d_pct,
  ROUND(l14d_completeness_pct, 2) as l14d_pct,
  is_production_ready
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date = CURRENT_DATE() - 1
  AND is_production_ready = FALSE
ORDER BY completeness_percentage ASC
LIMIT 50;
```

**Color Coding:**
- Green: ≥90%
- Yellow: 80-90%
- Red: <80%

---

### Query 5: Bootstrap Mode Activity
**Panel:** Time series with annotation
**Refresh:** Every 30 minutes

```sql
SELECT
  DATE(analysis_date) as time,
  processor_name as metric,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as value
FROM (
  SELECT analysis_date, 'player_daily_cache' as processor_name, backfill_bootstrap_mode
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date >= CURRENT_DATE() - 60

  UNION ALL

  SELECT analysis_date, 'player_composite_factors' as processor_name, backfill_bootstrap_mode
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date >= CURRENT_DATE() - 60

  -- Add other processors...
)
GROUP BY time, metric
ORDER BY time DESC, metric;
```

**Annotations:**
- Mark season start date
- Mark 30-day bootstrap window end

---

## Importing the Grafana Dashboard

### Prerequisites
- Grafana 8.0+ installed
- BigQuery data source configured
- Permissions to create dashboards

### Step-by-Step Import

**1. Locate the Dashboard File**
```bash
cd /home/naji/code/nba-stats-scraper
cat docs/monitoring/completeness-grafana-dashboard.json
```

**2. Import via Grafana UI**
- Open Grafana: `http://your-grafana-host:3000`
- Navigate: Dashboards → Import
- Click "Upload JSON file"
- Select: `docs/monitoring/completeness-grafana-dashboard.json`
- Click "Load"

**3. Configure Data Source**
- Select your BigQuery data source from dropdown
- Verify connection is working
- Click "Import"

**4. Verify Dashboard**
- Dashboard should load with 9 panels
- Check that data is populating
- Set refresh interval to 5 minutes

**5. Configure Alerts (Optional)**
- Navigate to each alert panel
- Click "Edit" → "Alert" tab
- Configure notification channels
- Save changes

---

## Monitoring Best Practices

### Daily (5 minutes)
- Check active circuit breaker count
- Review production readiness percentage
- Investigate any entities <90% completeness

### Weekly (15 minutes)
- Review 7-day completeness trends
- Check circuit breaker trip frequency
- Identify any systematic issues
- Review bootstrap mode usage (if early season)

### Monthly (30 minutes)
- Analyze completeness patterns by processor
- Correlate completeness with prediction accuracy
- Review alert effectiveness
- Tune thresholds if needed

---

## Troubleshooting Dashboard Issues

### Issue 1: No Data Showing
**Symptoms:** All panels empty or showing "No data"

**Causes:**
- BigQuery data source not connected
- Wrong project/dataset in queries
- Date range filter too restrictive

**Fix:**
```bash
# Verify tables exist
bq ls nba_precompute
bq ls nba_predictions
bq ls nba_analytics
bq ls nba_orchestration

# Test query manually
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM \`nba_precompute.player_daily_cache\`
WHERE analysis_date = CURRENT_DATE() - 1
"
```

### Issue 2: Alerts Not Firing
**Symptoms:** Known issues not triggering alerts

**Causes:**
- Alert rules not saved
- Notification channel not configured
- Alert evaluation interval too long

**Fix:**
- Edit panel → Alert tab → Verify rule
- Test notification channel
- Reduce evaluation interval to 1m

### Issue 3: Query Performance Slow
**Symptoms:** Dashboard takes >30 seconds to load

**Causes:**
- Missing partitioning on analysis_date
- Full table scans instead of partition scans
- Too many UNION ALL queries

**Fix:**
```sql
-- Use partition filter
WHERE analysis_date = CURRENT_DATE() - 1  -- Good (partition scan)
-- vs
WHERE analysis_date >= CURRENT_DATE() - 1  -- Bad (full scan if not partitioned)

-- Limit data range
WHERE analysis_date >= CURRENT_DATE() - 30  -- Don't scan entire history
```

---

## Custom Queries

### Query: Completeness by Day of Week
```sql
SELECT
  FORMAT_TIMESTAMP('%A', TIMESTAMP(analysis_date)) as day_of_week,
  processor_name,
  AVG(completeness_percentage) as avg_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM (
  -- UNION ALL processors
)
WHERE analysis_date >= CURRENT_DATE() - 90
GROUP BY day_of_week, processor_name
ORDER BY
  CASE day_of_week
    WHEN 'Monday' THEN 1
    WHEN 'Tuesday' THEN 2
    WHEN 'Wednesday' THEN 3
    WHEN 'Thursday' THEN 4
    WHEN 'Friday' THEN 5
    WHEN 'Saturday' THEN 6
    WHEN 'Sunday' THEN 7
  END,
  processor_name;
```

### Query: Top 10 Most Incomplete Entities (All Time)
```sql
SELECT
  processor_name,
  entity_id,
  COUNT(*) as incomplete_days,
  AVG(completeness_percentage) as avg_completeness,
  MIN(analysis_date) as first_incomplete,
  MAX(analysis_date) as last_incomplete
FROM (
  SELECT 'player_daily_cache' as processor_name, player_lookup as entity_id,
         completeness_percentage, analysis_date
  FROM `nba_precompute.player_daily_cache`
  WHERE is_production_ready = FALSE

  -- UNION ALL other processors
)
GROUP BY processor_name, entity_id
ORDER BY incomplete_days DESC
LIMIT 10;
```

### Query: Completeness Correlation with Prediction Accuracy
```sql
-- Requires joining with prediction output table
SELECT
  CASE
    WHEN f.completeness_percentage >= 95 THEN '95-100%'
    WHEN f.completeness_percentage >= 90 THEN '90-95%'
    WHEN f.completeness_percentage >= 80 THEN '80-90%'
    ELSE '<80%'
  END as completeness_bucket,
  COUNT(*) as prediction_count,
  AVG(ABS(p.predicted_value - p.actual_value)) as avg_error,
  STDDEV(ABS(p.predicted_value - p.actual_value)) as stddev_error
FROM `nba_predictions.player_prop_predictions` p
JOIN `nba_predictions.ml_feature_store_v2` f
  ON p.player_lookup = f.player_lookup
  AND p.game_date = f.analysis_date
WHERE p.actual_value IS NOT NULL
  AND p.game_date >= CURRENT_DATE() - 30
GROUP BY completeness_bucket
ORDER BY completeness_bucket DESC;
```

---

## Related Documentation

- **[Quick Start Guide](01-quick-start.md)** - Daily operations
- **[Operational Runbook](02-operational-runbook.md)** - Troubleshooting procedures
- **[Helper Scripts](03-helper-scripts.md)** - Circuit breaker management
- **[Implementation Guide](04-implementation-guide.md)** - Technical details

---

**Status:** ✅ Production Ready
**Dashboard File:** `docs/monitoring/completeness-grafana-dashboard.json`
**Last Updated:** 2025-11-22
