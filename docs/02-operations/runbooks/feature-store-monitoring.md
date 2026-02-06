# Feature Store Monitoring Runbook

**Purpose:** Ensure the ML feature store (`player_daily_cache`) is populated correctly every day.

**Owner:** Platform Team
**Last Updated:** 2026-02-05

---

## Overview

The feature store (`nba_precompute.player_daily_cache`) is the critical data source for all ML predictions. It contains 76 features computed from player performance, team stats, and matchup context.

**Upstream dependencies:**
- Phase 2: Raw data (game stats, schedules)
- Phase 3: Analytics (player/team summaries)
- Phase 4: Precompute processors (feature computation)

**Downstream consumers:**
- Prediction worker (generates prop predictions)
- Breakout classifier (identifies breakout candidates)
- Model training pipelines

---

## Health Metrics

### Critical Thresholds

| Metric | Target | Warning | Error | Critical |
|--------|--------|---------|-------|----------|
| **Production Ready %** | 100% | <98% | <95% | <90% |
| **NULL Rate (Critical Features)** | 0% | >2% | >5% | >10% |
| **Completeness %** | 100% | <98% | <95% | <90% |
| **Quality Tier (POOR %)** | 0% | >2% | >5% | >10% |
| **Data Staleness** | <6h | >24h | >48h | >72h |
| **Downstream Usage** | >0 predictions | 0 predictions + games scheduled | N/A | N/A |

### Quality Tiers

The feature store includes built-in quality tracking:

- **EXCELLENT**: All data windows complete, high confidence
- **GOOD**: Most windows complete, minor gaps
- **ACCEPTABLE**: Some windows incomplete, usable but degraded
- **POOR**: Significant missing data, not production-ready

---

## Daily Monitoring

### Automated Health Check

**Frequency:** Daily at 9:00 AM ET (after overnight processing)

**Script:**
```bash
python bin/monitoring/feature_store_health_check.py --date YYYY-MM-DD
```

**Automated via:**
- Cloud Scheduler job: `feature-store-daily-health-check`
- Sends Slack alerts to `#feature-store-alerts` if issues found

### Manual Health Check

Run for any date:
```bash
# Today
python bin/monitoring/feature_store_health_check.py

# Specific date
python bin/monitoring/feature_store_health_check.py --date 2026-02-05

# With CI/CD alerting (exits 1 on errors)
python bin/monitoring/feature_store_health_check.py --alert
```

**Checks performed:**
1. ✅ Date Coverage - Records exist for the date
2. ✅ Production Readiness - % of records ready for production
3. ✅ NULL Rates - Critical features have valid data
4. ✅ Quality Tiers - Distribution of quality levels
5. ✅ Completeness - Data windows complete
6. ✅ Downstream Usage - Predictions generated from features
7. ✅ Data Staleness - Recently processed

---

## Common Issues & Fixes

### Issue 1: No Data for Date

**Symptoms:**
- `Date Coverage: CRITICAL - No feature store records`
- 0 records in `player_daily_cache` for date

**Root Causes:**
- Phase 4 processors didn't run
- Upstream Phase 3 data missing
- Date is too far in future (no games scheduled)

**Fix:**
```bash
# 1. Check if games existed on that date
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-05' AND game_status = 3"

# 2. Check Phase 3 completion
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-05'"

# 3. Trigger Phase 4 manually if needed
gcloud pubsub topics publish phase3-complete \
  --message='{"game_date": "2026-02-05", "force_reprocess": true}'

# 4. Wait 5-10 minutes and re-check
python bin/monitoring/feature_store_health_check.py --date 2026-02-05
```

### Issue 2: Low Production Readiness (<95%)

**Symptoms:**
- `Production Readiness: ERROR - X/Y records ready (Z%)`
- Many records with `is_production_ready = FALSE`

**Root Causes:**
- Incomplete player game history (early season)
- Missing Vegas lines
- Data quality issues flagged

**Fix:**
```bash
# 1. Investigate specific records
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  is_production_ready,
  data_quality_issues,
  insufficient_data_reason,
  completeness_percentage
FROM nba_precompute.player_daily_cache
WHERE cache_date = '2026-02-05'
  AND is_production_ready = FALSE
LIMIT 10"

# 2. Check common issue patterns
bq query --use_legacy_sql=false "
SELECT
  insufficient_data_reason,
  COUNT(*) as count
FROM nba_precompute.player_daily_cache
WHERE cache_date = '2026-02-05'
  AND is_production_ready = FALSE
GROUP BY insufficient_data_reason
ORDER BY count DESC"

# 3. If early season issue: Expected, no action needed
# 4. If Vegas line issue: Check odds_api scrapers running
# 5. If data quality: Investigate Phase 3 processors
```

### Issue 3: High NULL Rates (>5%)

**Symptoms:**
- `NULL Rates: ERROR - High NULL rates detected (max: X%)`
- Key features like `points_avg_last_10` have many NULLs

**Root Causes:**
- Phase 3 processors failing to compute aggregates
- Upstream raw data missing
- Player has insufficient game history

**Fix:**
```bash
# 1. Check which feature has highest NULL rate
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(points_avg_last_10 IS NULL) as null_points,
  COUNTIF(minutes_avg_last_10 IS NULL) as null_minutes,
  COUNTIF(usage_rate_last_10 IS NULL) as null_usage,
  COUNT(*) as total
FROM nba_precompute.player_daily_cache
WHERE cache_date = '2026-02-05'"

# 2. Check Phase 3 health
./bin/monitoring/phase3_health_check.sh 2026-02-05

# 3. Regenerate Phase 3 data if needed
python bin/maintenance/reconcile_phase3_completion.py \
  --date 2026-02-05 --fix

# 4. Re-trigger Phase 4
gcloud pubsub topics publish phase3-complete \
  --message='{"game_date": "2026-02-05", "force_reprocess": true}'
```

### Issue 4: Stale Data (>24 hours old)

**Symptoms:**
- `Data Staleness: WARNING - Data is X hours old`
- `processed_at` timestamp is old

**Root Causes:**
- Phase 4 processors not running on schedule
- Batch processing stalled
- Manual override preventing updates

**Fix:**
```bash
# 1. Check Phase 4 batch status
bq query --use_legacy_sql=false "
SELECT
  batch_name, status, updated_at
FROM nba_orchestration.phase4_batch_tracking
WHERE game_date = '2026-02-05'
ORDER BY updated_at DESC
LIMIT 10"

# 2. Check for stalled batches
python bin/monitoring/analyze_healing_patterns.py

# 3. Check Phase 4 service logs
gcloud logging read "resource.type=cloud_run_revision
  resource.labels.service_name=nba-phase4-precompute-processors
  severity>=WARNING" --limit=50

# 4. Force reprocess if needed
gcloud pubsub topics publish phase3-complete \
  --message='{"game_date": "2026-02-05", "force_reprocess": true}'
```

### Issue 5: No Predictions Generated

**Symptoms:**
- `Downstream Usage: WARNING - No predictions generated`
- Feature store has data but no predictions in `player_prop_predictions`

**Root Causes:**
- Prediction coordinator not triggered
- Prediction worker failing
- No Vegas lines available

**Root Causes (continued):**
- Feature store marked not production-ready
- Prediction threshold filters too strict

**Fix:**
```bash
# 1. Check if predictions were triggered
bq query --use_legacy_sql=false "
SELECT COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-05'"

# 2. Check prediction coordinator logs
gcloud logging read "resource.type=cloud_run_revision
  resource.labels.service_name=prediction-coordinator
  timestamp>='2026-02-05T00:00:00Z'
  severity>=INFO" --limit=50 | grep "2026-02-05"

# 3. Check prediction worker health
curl $(gcloud run services describe prediction-worker \
  --region=us-west2 --format='value(status.url)')/health/deep

# 4. Manually trigger predictions if needed
# (Use coordinator API or Pub/Sub trigger)
```

---

## Schema Reference

### Key Fields in player_daily_cache

**Identity:**
- `player_lookup` - Universal player identifier
- `cache_date` - Date for which features are computed
- `universal_player_id` - Numeric player ID

**Core Features (Last 10 games):**
- `points_avg_last_10` - Average points
- `minutes_avg_last_10` - Average minutes
- `usage_rate_last_10` - Usage rate %
- `ts_pct_last_10` - True shooting %

**Quality Metadata:**
- `is_production_ready` - Safe to use in production?
- `quality_tier` - EXCELLENT / GOOD / ACCEPTABLE / POOR
- `quality_score` - Numeric quality score (0-100)
- `completeness_percentage` - % of expected data present
- `data_quality_issues` - JSON array of specific issues
- `all_windows_complete` - All time windows have data?

**Completeness Flags:**
- `l5_is_complete` - Last 5 games complete
- `l10_is_complete` - Last 10 games complete
- `l7d_is_complete` - Last 7 days complete
- `l14d_is_complete` - Last 14 days complete

**Processing Metadata:**
- `created_at` - When record was created
- `processed_at` - Last processing timestamp
- `cache_version` - Feature schema version

---

## Alerting Configuration

### Slack Alerts

**Channel:** `#feature-store-alerts`

**Alert Triggers:**
- ERROR severity: Production readiness <95%
- ERROR severity: NULL rates >5%
- CRITICAL severity: No data for date with scheduled games
- WARNING severity: Data staleness >24 hours

**Alert Format:**
```
⚠️ Feature Store Health Check Alert
Date: 2026-02-05
Status: ❌ UNHEALTHY
Summary: 5/7 checks passed (2 errors)

Run health check: python bin/monitoring/feature_store_health_check.py --date 2026-02-05
```

### Cloud Scheduler Configuration

```bash
# Create daily health check job
gcloud scheduler jobs create http feature-store-health-check \
  --schedule="0 9 * * *" \
  --time-zone="America/New_York" \
  --uri="https://monitoring-service-url/feature-store-check" \
  --http-method=POST \
  --message-body='{"date": "today"}' \
  --location=us-west2
```

---

## Validation Queries

### Quick Health Check Query

```sql
-- Run this for a quick manual check
SELECT
  cache_date,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  COUNTIF(is_production_ready = TRUE) as ready,
  ROUND(100.0 * COUNTIF(is_production_ready = TRUE) / COUNT(*), 1) as pct_ready,
  COUNTIF(all_windows_complete = TRUE) as complete,
  ROUND(AVG(quality_score), 1) as avg_quality_score
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC
```

### Find Problematic Records

```sql
-- Records not production-ready
SELECT
  player_lookup,
  cache_date,
  quality_tier,
  completeness_percentage,
  data_quality_issues,
  insufficient_data_reason
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
  AND is_production_ready = FALSE
ORDER BY quality_score ASC
LIMIT 20
```

### Check Feature Coverage

```sql
-- NULL rate analysis for all numeric features
SELECT
  'points_avg_last_10' as feature,
  COUNT(*) as total,
  COUNTIF(points_avg_last_10 IS NULL) as nulls,
  ROUND(100.0 * COUNTIF(points_avg_last_10 IS NULL) / COUNT(*), 2) as null_pct
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
UNION ALL
SELECT
  'minutes_avg_last_10',
  COUNT(*),
  COUNTIF(minutes_avg_last_10 IS NULL),
  ROUND(100.0 * COUNTIF(minutes_avg_last_10 IS NULL) / COUNT(*), 2)
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
-- Add more features as needed
```

---

## Related Documentation

- **Phase 4 Runbook:** `docs/02-operations/runbooks/phase4-precompute.md`
- **Pipeline Overview:** `docs/01-architecture/pipeline-phases.md`
- **Useful Queries:** `docs/02-operations/useful-queries.md`

---

## Escalation

**Severity: P0 (Critical)**
- No feature store data for today with scheduled games
- Production readiness <50%
- Action: Page on-call engineer immediately

**Severity: P1 (High)**
- Production readiness 50-90%
- Data staleness >48 hours
- Action: Alert platform team via Slack

**Severity: P2 (Medium)**
- Production readiness 90-95%
- NULL rates 5-10%
- Action: Create ticket for investigation

**Severity: P3 (Low)**
- Production readiness 95-98%
- NULL rates 2-5%
- Action: Monitor, no immediate action required

---

**Last Validated:** 2026-02-05
**Validation Result:** ✅ All checks passing (7/7)
