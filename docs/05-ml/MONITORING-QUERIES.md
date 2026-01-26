# ML Feature Store Data Quality Monitoring

**Purpose:** SQL queries for monitoring ML feature store and player_game_summary data quality

**Created:** 2026-01-25
**Last Updated:** 2026-01-25

---

## Quick Status Check

Use this as your daily health check for ML features:

```sql
-- Daily Data Quality Dashboard
WITH yesterday AS (
  SELECT CURRENT_DATE() - 1 AS check_date
),
pgs_quality AS (
  SELECT
    'player_game_summary' as table_name,
    COUNT(*) as total_records,
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) / NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_rate_pct,
    COUNTIF(source_team_last_updated IS NOT NULL) as has_team_join
  FROM `nba_analytics.player_game_summary`, yesterday
  WHERE game_date = yesterday.check_date
),
fs_quality AS (
  SELECT
    'ml_feature_store_v2' as table_name,
    COUNT(*) as total_records,
    ROUND(AVG(ARRAY_LENGTH(features)), 1) as avg_feature_count,
    COUNTIF(ARRAY_LENGTH(features) = 34) as correct_count,
    ROUND(100.0 * COUNTIF(ARRAY_LENGTH(features) = 34) / COUNT(*), 1) as correct_count_pct
  FROM `nba_predictions.ml_feature_store_v2`, yesterday
  WHERE game_date = yesterday.check_date
)
SELECT
  (SELECT check_date FROM yesterday) as check_date,
  'player_game_summary' as source,
  pgs.total_records,
  pgs.minutes_pct,
  pgs.usage_rate_pct,
  pgs.has_team_join,
  CASE
    WHEN pgs.minutes_pct >= 95 AND pgs.usage_rate_pct >= 90 THEN '✅ HEALTHY'
    WHEN pgs.minutes_pct >= 80 OR pgs.usage_rate_pct >= 70 THEN '⚠️ DEGRADED'
    ELSE '❌ CRITICAL'
  END as status
FROM pgs_quality pgs
UNION ALL
SELECT
  (SELECT check_date FROM yesterday) as check_date,
  'ml_feature_store_v2' as source,
  fs.total_records,
  NULL as minutes_pct,
  NULL as usage_rate_pct,
  NULL as has_team_join,
  CASE
    WHEN fs.correct_count_pct >= 99 THEN '✅ HEALTHY'
    WHEN fs.correct_count_pct >= 90 THEN '⚠️ DEGRADED'
    ELSE '❌ CRITICAL'
  END as status
FROM fs_quality fs;
```

**Expected Results:**
```
check_date  | source                 | total_records | minutes_pct | usage_rate_pct | status
------------|------------------------|---------------|-------------|----------------|-------------
2026-01-24  | player_game_summary    | 180           | 95.5        | 92.3           | ✅ HEALTHY
2026-01-24  | ml_feature_store_v2    | 180           | NULL        | NULL           | ✅ HEALTHY
```

---

## 1. Player Game Summary Quality

### 1.1 Daily Coverage Check

```sql
-- Check minutes_played and usage_rate coverage for recent dates
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(minutes_played IS NOT NULL) as has_minutes,
    COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
    COUNTIF(source_team_last_updated IS NOT NULL) as has_team_join,
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
    ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_rate_pct,
    -- For active players only
    COUNTIF(minutes_played > 0) as active_players,
    COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) as active_with_usage,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) / NULLIF(COUNTIF(minutes_played > 0), 0), 1) as active_usage_pct
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

**Alert Thresholds:**
- ❌ CRITICAL: `minutes_pct < 90%` OR `active_usage_pct < 90%`
- ⚠️ WARNING: `minutes_pct < 95%` OR `active_usage_pct < 95%`
- ✅ HEALTHY: `minutes_pct >= 95%` AND `active_usage_pct >= 95%`

### 1.2 Monthly Trend Analysis

```sql
-- Monthly data quality trends
SELECT
    DATE_TRUNC(game_date, MONTH) as month,
    COUNT(*) as total_games,
    COUNTIF(minutes_played IS NOT NULL) as has_minutes,
    COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
    ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_rate_pct
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
GROUP BY month
ORDER BY month DESC;
```

**Use Case:** Identify long-term trends or recurring issues.

### 1.3 Team Stats Join Verification

```sql
-- Verify team_offense_game_summary is being joined
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(source_team_last_updated IS NOT NULL) as has_team_join,
    ROUND(100.0 * COUNTIF(source_team_last_updated IS NOT NULL) / COUNT(*), 1) as team_join_pct,
    MIN(source_team_last_updated) as first_update,
    MAX(source_team_last_updated) as last_update
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

**Alert Thresholds:**
- ❌ CRITICAL: `team_join_pct = 0%` (team stats not being joined at all)
- ⚠️ WARNING: `team_join_pct < 50%` (partial processing)
- ✅ HEALTHY: `team_join_pct >= 90%`

---

## 2. ML Feature Store Quality

### 2.1 Feature Count Validation

```sql
-- Verify all records have correct number of features (34)
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(ARRAY_LENGTH(features) = 34) as correct_count,
    COUNTIF(ARRAY_LENGTH(features) = 33) as old_count_33,
    COUNTIF(ARRAY_LENGTH(features) < 33) as invalid_count,
    ROUND(100.0 * COUNTIF(ARRAY_LENGTH(features) = 34) / COUNT(*), 1) as correct_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

**Alert Thresholds:**
- ❌ CRITICAL: `correct_pct < 95%` (many records with wrong feature count)
- ⚠️ WARNING: `correct_pct < 99%` (some records wrong)
- ✅ HEALTHY: `correct_pct >= 99%`

### 2.2 Feature Value Sanity Checks

```sql
-- Check for NULL or invalid values in critical features
WITH feature_checks AS (
  SELECT
    game_date,
    player_lookup,
    ARRAY_LENGTH(features) as num_features,
    features[SAFE_OFFSET(31)] as minutes_feature,  -- minutes_avg_last_10
    features[SAFE_OFFSET(32)] as ppm_feature,      -- ppm_avg_last_10
    features[SAFE_OFFSET(33)] as shot_zone_indicator  -- has_shot_zone_data
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(minutes_feature IS NOT NULL) as has_minutes,
  COUNTIF(minutes_feature >= 10 AND minutes_feature <= 48) as valid_minutes,
  COUNTIF(ppm_feature IS NOT NULL) as has_ppm,
  COUNTIF(ppm_feature >= 0 AND ppm_feature <= 2) as valid_ppm,
  ROUND(100.0 * COUNTIF(minutes_feature IS NOT NULL) / COUNT(*), 1) as minutes_pct,
  ROUND(100.0 * COUNTIF(ppm_feature IS NOT NULL) / COUNT(*), 1) as ppm_pct
FROM feature_checks
GROUP BY game_date
ORDER BY game_date DESC;
```

**Alert Thresholds:**
- ❌ CRITICAL: `minutes_pct < 80%` OR `ppm_pct < 80%`
- ⚠️ WARNING: `minutes_pct < 90%` OR `ppm_pct < 90%`
- ✅ HEALTHY: Both `>= 95%`

### 2.3 Shot Zone Data Availability

```sql
-- Check shot zone data indicator (Feature 33)
WITH shot_zone_check AS (
  SELECT
    game_date,
    player_lookup,
    features[SAFE_OFFSET(33)] as has_shot_zone_data,
    features[SAFE_OFFSET(18)] as paint_rate,
    features[SAFE_OFFSET(19)] as mid_range_rate,
    features[SAFE_OFFSET(20)] as three_pt_rate
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(has_shot_zone_data = 1.0) as has_zones,
  COUNTIF(has_shot_zone_data = 0.0) as missing_zones,
  ROUND(100.0 * COUNTIF(has_shot_zone_data = 1.0) / COUNT(*), 1) as zone_coverage_pct
FROM shot_zone_check
GROUP BY game_date
ORDER BY game_date DESC;
```

**Alert Thresholds:**
- ❌ CRITICAL: `zone_coverage_pct < 70%`
- ⚠️ WARNING: `zone_coverage_pct < 80%`
- ✅ HEALTHY: `zone_coverage_pct >= 80%`

---

## 3. Dependency Validation

### 3.1 Team Stats Availability

```sql
-- Verify team_offense_game_summary exists before player processing
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(CURRENT_DATE() - 7, CURRENT_DATE() - 1, INTERVAL 1 DAY)) AS date
),
team_stats AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_with_team_stats
  FROM `nba_analytics.team_offense_game_summary`
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
),
schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as scheduled_games
  FROM `nba_raw.nbac_schedule`
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
)
SELECT
  dr.date,
  COALESCE(s.scheduled_games, 0) as scheduled_games,
  COALESCE(ts.games_with_team_stats, 0) as games_with_team_stats,
  CASE
    WHEN s.scheduled_games IS NULL THEN 'NO_GAMES'
    WHEN ts.games_with_team_stats >= s.scheduled_games THEN 'OK'
    WHEN ts.games_with_team_stats > 0 THEN 'PARTIAL'
    ELSE 'MISSING'
  END as status
FROM date_range dr
LEFT JOIN schedule s ON dr.date = s.game_date
LEFT JOIN team_stats ts ON dr.date = ts.game_date
ORDER BY dr.date DESC;
```

**Alert:** If any date shows 'MISSING' or 'PARTIAL', team stats processor needs investigation.

### 3.2 Processing Timestamp Check

```sql
-- Check when data was last updated
SELECT
  'player_game_summary' as table_name,
  MAX(source_team_last_updated) as last_team_update,
  MAX(source_nbac_last_updated) as last_nbac_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(source_team_last_updated), HOUR) as hours_since_team_update
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 3;
```

**Alert Thresholds:**
- ❌ CRITICAL: `hours_since_team_update > 48` (processor not running)
- ⚠️ WARNING: `hours_since_team_update > 24` (delayed processing)
- ✅ HEALTHY: `hours_since_team_update < 12`

---

## 4. Diagnostic Queries

### 4.1 Find Records with Missing Minutes

```sql
-- Identify players/games with NULL minutes_played
SELECT
  game_date,
  game_id,
  player_lookup,
  player_full_name,
  team_abbr,
  minutes_played,
  seconds_played,
  points
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
  AND minutes_played IS NULL
  AND points > 0  -- Should have minutes if they scored
ORDER BY game_date DESC, points DESC
LIMIT 50;
```

**Use Case:** Identify data extraction failures where players scored but have no minutes.

### 4.2 Find Records with Missing Usage Rate but Have Team Stats

```sql
-- Find records where team stats joined but usage_rate still NULL
SELECT
  game_date,
  player_lookup,
  player_full_name,
  minutes_played,
  usage_rate,
  source_team_last_updated
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
  AND source_team_last_updated IS NOT NULL  -- Team stats joined
  AND minutes_played > 0  -- Player was active
  AND usage_rate IS NULL  -- But usage_rate missing
ORDER BY game_date DESC, minutes_played DESC
LIMIT 50;
```

**Use Case:** Identify calculation failures in usage_rate logic.

### 4.3 Compare Data Quality Across Data Sources

```sql
-- Compare coverage by source (NBAC vs BigDataBall vs BettingPros)
SELECT
  game_date,
  COUNTIF(source_nbac_last_updated IS NOT NULL) as has_nbac,
  COUNTIF(source_bbd_last_updated IS NOT NULL) as has_bbd,
  COUNTIF(source_bp_last_updated IS NOT NULL) as has_bp,
  COUNTIF(source_team_last_updated IS NOT NULL) as has_team,
  ROUND(100.0 * COUNTIF(source_team_last_updated IS NOT NULL) / COUNT(*), 1) as team_join_pct
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## 5. Alert Queries

### 5.1 Critical Data Quality Alert

```sql
-- Send alert if data quality drops below critical threshold
WITH quality_check AS (
  SELECT
    game_date,
    COUNT(*) as total,
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) / NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_pct
  FROM `nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date
)
SELECT
  game_date,
  total,
  minutes_pct,
  usage_pct,
  CASE
    WHEN minutes_pct < 90 OR usage_pct < 90 THEN '🚨 CRITICAL: Data quality below 90%'
    WHEN minutes_pct < 95 OR usage_pct < 95 THEN '⚠️ WARNING: Data quality below 95%'
    ELSE '✅ OK'
  END as alert_level
FROM quality_check
WHERE minutes_pct < 95 OR usage_pct < 95;  -- Only return if there's an issue
```

**Integration:** Run this query daily in Cloud Scheduler and send results to Slack/Email if any rows returned.

### 5.2 Processor Failure Alert

```sql
-- Alert if processor hasn't run recently
WITH last_run AS (
  SELECT
    MAX(source_team_last_updated) as last_update
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  last_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_update, HOUR) as hours_since_update,
  CASE
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_update, HOUR) > 48 THEN '🚨 CRITICAL: Processor not running'
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_update, HOUR) > 24 THEN '⚠️ WARNING: Processor delayed'
    ELSE '✅ OK'
  END as alert_level
FROM last_run
WHERE TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_update, HOUR) > 24;
```

---

## 6. Weekly Health Report

Run this query weekly for comprehensive health check:

```sql
-- Weekly health report (last 7 days)
WITH daily_quality AS (
  SELECT
    game_date,
    COUNT(*) as total_records,
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) / NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_pct
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
)
SELECT
  'WEEKLY SUMMARY' as report_type,
  COUNT(*) as days_analyzed,
  SUM(total_records) as total_records,
  ROUND(AVG(minutes_pct), 1) as avg_minutes_pct,
  ROUND(AVG(usage_pct), 1) as avg_usage_pct,
  MIN(minutes_pct) as min_minutes_pct,
  MIN(usage_pct) as min_usage_pct,
  COUNTIF(minutes_pct < 95 OR usage_pct < 95) as days_below_threshold
FROM daily_quality;
```

**Expected Results:**
```
report_type      | days | total | avg_minutes | avg_usage | min_minutes | min_usage | days_below
-----------------|------|-------|-------------|-----------|-------------|-----------|------------
WEEKLY SUMMARY   | 7    | 1260  | 96.5        | 94.2      | 92.0        | 90.5      | 1
```

---

## 7. Historical Comparison

Compare current week vs historical baseline:

```sql
-- Compare current week to same week last year
WITH current_week AS (
  SELECT
    'Current Week' as period,
    AVG(CASE WHEN minutes_played IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100 as minutes_pct,
    AVG(CASE WHEN usage_rate IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100 as usage_pct
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= CURRENT_DATE() - 7
),
last_year AS (
  SELECT
    'Same Week Last Year' as period,
    AVG(CASE WHEN minutes_played IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100 as minutes_pct,
    AVG(CASE WHEN usage_rate IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100 as usage_pct
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR) - 7
    AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
)
SELECT * FROM current_week
UNION ALL
SELECT * FROM last_year;
```

---

## Usage Guide

### Daily Routine (5 min)

1. Run **Quick Status Check** (top of this doc)
2. If any ❌ CRITICAL alerts:
   - Run **Diagnostic Queries** to identify issue
   - Check processor logs
   - Follow [Data Quality Validation](../09-handoff/2026-01-25-DATA-QUALITY-VALIDATION.md) runbook

### Weekly Routine (15 min)

1. Run **Weekly Health Report**
2. Run **Monthly Trend Analysis**
3. Review any anomalies or trends
4. Update alert thresholds if needed

### On-Demand (When Issues Reported)

1. Run **Diagnostic Queries** section
2. Use **Historical Comparison** to identify when issue started
3. Check **Dependency Validation** to find root cause

---

## Integration with Monitoring Systems

### Cloud Monitoring / Stackdriver

Create custom metrics based on these queries:

```python
# Example: Push metrics to Cloud Monitoring
from google.cloud import monitoring_v3

client = monitoring_v3.MetricServiceClient()
project_name = f"projects/{project_id}"

# Run query
result = bq_client.query(quality_check_query).result()

# Push metric
series = monitoring_v3.TimeSeries()
series.metric.type = "custom.googleapis.com/ml/feature_quality/minutes_coverage"
series.resource.type = "global"

point = monitoring_v3.Point()
point.value.double_value = result.minutes_pct
point.interval.end_time.seconds = int(time.time())

series.points = [point]
client.create_time_series(name=project_name, time_series=[series])
```

### Slack Alerts

```python
# Example: Send Slack alert if quality drops
if quality < 90:
    slack_webhook.post({
        "text": f"🚨 ML Feature Quality Alert: {quality}% coverage",
        "attachments": [{
            "color": "danger",
            "fields": [
                {"title": "Date", "value": str(game_date), "short": True},
                {"title": "Coverage", "value": f"{quality}%", "short": True}
            ]
        }]
    })
```

---

**Document maintained by:** Data Engineering Team
**Last updated:** 2026-01-25
**Review frequency:** Monthly
