# Unified Monitoring Guide

**Purpose**: Complete guide for monitoring NBA Props Platform health and performance
**Last Updated**: January 6, 2026
**Tools Covered**: Grafana, Cloud Logging, BigQuery, Manual Checks

---

## Quick Reference

| I need to... | Go to... |
|--------------|----------|
| **Check current system health** | [Daily Health Check](#daily-health-check) |
| **Investigate pipeline failure** | [Failure Investigation](#failure-investigation) |
| **Monitor backfill progress** | [Backfill Monitoring](#backfill-monitoring) |
| **Check data coverage** | [Coverage Monitoring](#coverage-monitoring) |
| **View Grafana dashboards** | [Grafana Dashboards](#grafana-dashboards) |
| **Query Cloud Logging** | [Cloud Logging Queries](#cloud-logging-queries) |

---

## Daily Health Check

**Frequency**: Every morning (10 minutes)
**When**: Before starting any work

### Quick Status Check

```bash
# Run automated health check (if script exists)
bash bin/operations/ops_dashboard.sh

# Or manual checks:
```

### 1. Pipeline Status (2 min)

**Check last 24 hours of pipeline execution**:

```sql
-- Recent Phase 1 scraper runs
SELECT
  DATE(triggered_at) as date,
  TIME(triggered_at) as time,
  scraper_name,
  status,
  error_message
FROM `nba-props-platform.nba_orchestration.scraper_runs`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY triggered_at DESC
LIMIT 20
```

**Expected**: All scrapers SUCCESS status, no ERROR messages

### 2. Data Coverage (2 min)

**Check yesterday's game coverage across all phases**:

```sql
-- Phase 2: Raw data
SELECT 'Phase 2 Raw' as phase, COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date = CURRENT_DATE('America/Los_Angeles') - 1
UNION ALL
-- Phase 3: Analytics
SELECT 'Phase 3 Analytics', COUNT(DISTINCT game_id)
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE('America/Los_Angeles') - 1
UNION ALL
-- Phase 4: Precompute
SELECT 'Phase 4 Precompute', COUNT(DISTINCT game_id)
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE('America/Los_Angeles') - 1
UNION ALL
-- Phase 5: Predictions
SELECT 'Phase 5 Predictions', COUNT(DISTINCT game_id)
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE prediction_date = CURRENT_DATE('America/Los_Angeles') - 1
```

**Expected**: All phases have same game count (yesterday's NBA schedule)

### 3. Recent Errors (2 min)

**Check Cloud Logging for errors in last 24 hours**:

```bash
gcloud logging read '
  severity>=ERROR
  AND timestamp>=2024-01-05T00:00:00Z
  AND (
    resource.labels.service_name=~"nba-.*"
    OR logName=~".*nba.*"
  )
' \
  --limit=50 \
  --format=json \
  --project=nba-props-platform
```

**Expected**: 0 ERROR level logs, or only known non-critical errors

### 4. Prediction Coverage (2 min)

**Check today's prediction coverage**:

```sql
-- Today's predictions
SELECT
  prediction_date,
  COUNT(DISTINCT CONCAT(game_id, '-', player_lookup, '-', prop_type)) as total_predictions,
  COUNT(DISTINCT game_id) as games_covered,
  COUNT(DISTINCT player_lookup) as players_covered
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE prediction_date = CURRENT_DATE('America/Los_Angeles')
GROUP BY prediction_date
```

**Expected**:
- Games covered = today's NBA schedule count
- Total predictions = 200-400 per game (depends on player participation)

### 5. Export Status (2 min)

**Check Phase 6 GCS exports**:

```bash
# Check recent exports to GCS
gsutil ls -l gs://nba-props-platform-public/predictions/$(date +%Y/%m/%d)/ | head -20
```

**Expected**: JSON files for today's games, file sizes >10 KB

---

## Failure Investigation

When a pipeline phase fails, follow this investigation flow:

### Step 1: Identify Failed Component

**Check orchestration logs**:

```sql
-- Find recent failures
SELECT
  triggered_at,
  workflow,
  phase,
  table_name,
  status,
  error_message
FROM `nba-props-platform.nba_orchestration.processor_runs`
WHERE status = 'FAILED'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY triggered_at DESC
LIMIT 20
```

### Step 2: Get Detailed Logs

**For Cloud Run services** (scrapers, processors):

```bash
# Get service logs
gcloud logging read "
  resource.labels.service_name=\"nba-phase2-raw-processors\"
  AND timestamp>=\"2024-01-05T10:00:00Z\"
  AND severity>=WARNING
" \
  --limit=100 \
  --format=json
```

**For Cloud Functions** (orchestrators, utilities):

```bash
# Get function logs
gcloud functions logs read {function-name} \
  --limit=100 \
  --start-time="2024-01-05T10:00:00Z"
```

### Step 3: Check Data Quality

**Validation query template**:

```sql
-- Check for data quality issues
SELECT
  game_date,
  COUNT(*) as row_count,
  COUNT(DISTINCT game_id) as game_count,
  COUNTIF(minutes_played IS NULL) as null_minutes_count,
  COUNTIF(points < 0) as invalid_points_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2024-01-05'  -- Adjust date
GROUP BY game_date
```

**Expected**:
- null_minutes_count = 0 (unless player DNP)
- invalid_points_count = 0
- row_count > 200 (typical game has 20-30 players × 2 teams)

### Step 4: Common Failure Patterns

#### Upstream Data Missing
**Symptom**: Phase N succeeds but produces 0 rows

**Check**:
```sql
-- Verify upstream phase has data
SELECT COUNT(*) as upstream_rows
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date = '2024-01-05'
```

**Fix**: Backfill upstream phase first

#### BigQuery Quota Exceeded
**Symptom**: `Quota exceeded` in logs

**Check**: Concurrent backfills or excessive query rate

**Fix**: Wait for quota reset (midnight UTC), reduce workers, or upgrade quota

#### Duplicate Keys
**Symptom**: `Duplicate key` error in MERGE operation

**Check**:
```sql
-- Find duplicates in source data
SELECT game_date, player_lookup, COUNT(*)
FROM temp_or_source_table
GROUP BY game_date, player_lookup
HAVING COUNT(*) > 1
```

**Fix**: Deduplicate source before MERGE

---

## Backfill Monitoring

When running backfills, monitor progress and health:

### Real-Time Progress

**Log monitoring**:
```bash
# Live tail of backfill logs
tail -f logs/player_game_summary_backfill_*.log | grep -E "Processing|MERGE|Success|ERROR"
```

**Look for**:
- ✅ `Processing date: YYYY-MM-DD` (progress)
- ✅ `MERGE completed: N rows` (data inserted)
- ⚠️ `WARN: Skipping date` (may be expected)
- ❌ `ERROR` (investigate immediately)

### Database Coverage Check

**More reliable than logs**:

```sql
-- Current coverage
SELECT
  COUNT(DISTINCT game_date) as dates_processed,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  ROUND(100.0 * COUNT(DISTINCT game_date) / 918, 1) as pct_complete
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2026-01-03'
```

**Run every 2 hours** during large backfills

### Checkpoint Monitoring

**Check checkpoint file**:
```bash
cat /tmp/backfill_checkpoints/player_game_summary_*.json
```

**Expected fields**:
- `total_dates`: Total dates in range
- `processed_dates`: Dates completed
- `failed_dates`: Dates that errored
- `last_checkpoint`: Most recent date processed

### Performance Metrics

**Track backfill speed**:

```bash
# Calculate dates/hour
START_TIME="2024-01-05 10:00:00"
DATES_PROCESSED=$(bq query --use_legacy_sql=false --format=csv "SELECT COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date >= '2021-10-19'" | tail -1)
HOURS_ELAPSED=$(python3 -c "from datetime import datetime; print((datetime.now() - datetime.strptime('$START_TIME', '%Y-%m-%d %H:%M:%S')).total_seconds() / 3600)")
echo "Speed: $(python3 -c "print(round($DATES_PROCESSED / $HOURS_ELAPSED, 1))") dates/hour"
```

**Expected speed** (with optimal workers):
- Phase 3: 30-40 dates/hour
- Phase 4: 25-35 dates/hour
- Phase 5: 15-25 dates/hour

---

## Coverage Monitoring

### Historical Coverage Analysis

**Full pipeline coverage across all phases**:

```sql
SELECT
  game_date,
  COUNTIF(phase2_present) as phase2,
  COUNTIF(phase3_present) as phase3,
  COUNTIF(phase4_present) as phase4,
  COUNTIF(phase5_present) as phase5
FROM (
  SELECT DISTINCT game_date,
    TRUE as phase2_present
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date >= '2021-10-19'
) p2
LEFT JOIN (
  SELECT DISTINCT game_date,
    TRUE as phase3_present
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-19'
) p3 USING (game_date)
LEFT JOIN (
  SELECT DISTINCT game_date,
    TRUE as phase4_present
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2021-10-19'
) p4 USING (game_date)
LEFT JOIN (
  SELECT DISTINCT game_date,
    TRUE as phase5_present
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE prediction_date >= '2021-10-19'
) p5 ON p2.game_date = p5.prediction_date
GROUP BY game_date
HAVING phase2 = 0 OR phase3 = 0 OR phase4 = 0 OR phase5 = 0
ORDER BY game_date DESC
```

**Result**: Dates with incomplete pipeline coverage

### Coverage Gaps Report

**Identify specific gaps**:

```sql
-- Dates in Phase 2 but missing in Phase 3
SELECT game_date
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= '2021-10-19'
  AND game_date NOT IN (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
  )
GROUP BY game_date
ORDER BY game_date
```

**Use for**: Planning backfills to close gaps

---

## Grafana Dashboards

### Available Dashboards

1. **Pipeline Status Dashboard**
   - Real-time phase execution status
   - Success/failure rates by phase
   - Recent error trends

2. **Data Coverage Dashboard**
   - Historical coverage by phase
   - Gap detection visualization
   - Daily coverage trends

3. **Performance Metrics Dashboard**
   - Query performance (P50, P95, P99)
   - BigQuery quota usage
   - Processing latency by phase

### Accessing Dashboards

**URL**: (Add Grafana URL when available)

**Key Panels**:
- Phase execution status (last 24h)
- Data coverage percentage (all phases)
- Error rate by service
- Prediction coverage (today vs yesterday)

---

## Cloud Logging Queries

### Retry Metrics

**BigQuery retry patterns** (useful for debugging connection issues):

```bash
gcloud logging read '
  jsonPayload.message=~"Retrying BigQuery operation"
  AND timestamp>=2024-01-05T00:00:00Z
' \
  --limit=100 \
  --format=json \
  --project=nba-props-platform
```

See: [BigQuery Retry Queries](./cloud-logging/bigquery-retry-queries.md) for detailed patterns

### Service-Specific Logs

**Phase 2 Raw Processors**:
```bash
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=100 \
  --format=json
```

**Phase 3 Analytics Processors**:
```bash
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"' \
  --limit=100 \
  --format=json
```

**Prediction Coordinator**:
```bash
gcloud logging read 'resource.labels.service_name="prediction-coordinator"' \
  --limit=100 \
  --format=json
```

### Error Pattern Detection

**Find recurring errors**:

```bash
gcloud logging read '
  severity>=ERROR
  AND timestamp>=2024-01-01T00:00:00Z
  AND resource.labels.service_name=~"nba-.*"
' \
  --limit=500 \
  --format=json \
| jq -r '.[] | .jsonPayload.message' \
| sort | uniq -c | sort -rn | head -20
```

**Result**: Top 20 most common error messages (for pattern analysis)

---

## Alert Configuration

### Critical Alerts (Immediate Response)

1. **Pipeline Phase Failure**
   - **Trigger**: Any phase returns non-SUCCESS status
   - **Response**: Investigate within 15 minutes

2. **Data Loss Detected**
   - **Trigger**: Coverage drops >10% day-over-day
   - **Response**: Check for scraper failures, backfill if needed

3. **BigQuery Quota >90%**
   - **Trigger**: Approaching daily quota limit
   - **Response**: Reduce backfill workers or pause non-critical queries

### Warning Alerts (Check Within 2 Hours)

1. **Prediction Coverage <95%**
   - **Trigger**: Today's predictions cover <95% of scheduled games
   - **Response**: Check upstream data, may need same-day backfill

2. **Processing Latency >2 Hours**
   - **Trigger**: Time from game end to prediction export >2 hours
   - **Response**: Check for bottlenecks, optimize slow processors

3. **Repeated Warnings (>10/hour)**
   - **Trigger**: Same WARNING message appears >10 times in 1 hour
   - **Response**: Investigate pattern, may indicate underlying issue

### Informational (Daily Review)

1. **Daily Health Check Summary**
   - Coverage by phase
   - Error count by service
   - Performance metrics

---

## Self-Healing Monitoring

The self-healing Cloud Function automatically recovers from common failures.

### Monitor Self-Healing Activity

```sql
-- Check self-healing trigger frequency
SELECT
  DATE(triggered_at) as date,
  failure_type,
  COUNT(*) as recovery_attempts,
  COUNTIF(recovery_successful) as successes,
  COUNTIF(NOT recovery_successful) as failures
FROM `nba-props-platform.nba_orchestration.self_heal_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date, failure_type
ORDER BY date DESC, recovery_attempts DESC
```

**Expected**:
- Occasional self-healing triggers (1-5 per week normal)
- >90% success rate
- If >10 triggers/day, investigate root cause

### Self-Healing Patterns

**Common self-healed failures**:
- Transient BigQuery connection errors
- GCS temporary unavailability
- Pub/Sub message delivery delays

**Not self-healed** (require manual intervention):
- Data quality validation failures
- Schema mismatches
- Logic bugs in processors

See: [Self-Healing Architecture](../../01-architecture/self-healing-patterns.md)

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Check | Fix |
|---------|--------------|-------|-----|
| Phase N failed | Upstream data missing | Query Phase N-1 for date | Backfill Phase N-1 |
| 0 predictions today | Scraper failed | Check Phase 1 scraper logs | Re-run scraper |
| Duplicate rows | DELETE+INSERT used | Duplicate detection query | Deduplicate + fix code |
| Quota exceeded | Too many concurrent queries | Check backfill workers | Reduce workers or wait |
| Slow backfill | Workers too low | Check dates/hour metric | Increase workers |
| NULL critical fields | Data quality bug | Check field NULL count | Fix processor, reprocess |

---

## Related Documentation

- [Daily Health Check Script](../02-operations/daily-health-check.md) (if exists)
- [Troubleshooting Matrix](../02-operations/troubleshooting-matrix.md) (if exists)
- [Cloud Logging Queries](./cloud-logging/bigquery-retry-queries.md)
- [Self-Healing Patterns](../../01-architecture/self-healing-patterns.md)
- [Backfill Master Guide](../02-operations/backfill/master-guide.md)

---

**Last Updated**: January 6, 2026
**Maintained By**: Operations Team
**Next Review**: When monitoring stack changes (Grafana updates, new alerts, etc.)
