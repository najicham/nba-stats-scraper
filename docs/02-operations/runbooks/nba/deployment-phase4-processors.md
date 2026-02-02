# NBA Phase 4 Precompute Processors Deployment Runbook

**Version**: 1.0
**Last Updated**: 2026-02-02
**Owner**: NBA Data Infrastructure Team

---

## Overview

Phase 4 processors precompute aggregated features and prepare data for predictions. Most critical: `VegasLineSummaryProcessor` which generates `vegas_line_summary` table used by prediction worker. Vegas line coverage is a key system health metric (target: 90%+).

**Service**: `nba-phase4-precompute-processors`
**Region**: `us-west2`
**Repository**: `nba-stats-scraper`
**Dockerfile**: `data_processors/precompute/Dockerfile`

**Critical Processors**:
- `VegasLineSummaryProcessor` - Aggregates betting lines (MOST CRITICAL)
- `PlayerGameContextProcessor` - Player context features
- `TeamOpponentStatsProcessor` - Opponent matchup stats

---

## Pre-Deployment Checklist

**IMPORTANT**: Phase 4 bugs can degrade prediction quality silently!

- [ ] Code changes reviewed and approved
- [ ] Tests passing: `pytest tests/data_processors/precompute/ -v`
- [ ] Schema compatibility verified (esp. `vegas_line_summary`)
- [ ] BigQuery query performance tested
- [ ] Local synced with remote
- [ ] Current Vegas line coverage: Check `./bin/monitoring/check_vegas_line_coverage.sh`
- [ ] Rollback plan documented

---

## Deployment Process

### Step 1: Verify Current State

```bash
# Check current deployment
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format="value(metadata.labels.commit-sha,status.url)"

# Check Vegas line coverage (CRITICAL METRIC)
./bin/monitoring/check_vegas_line_coverage.sh --days 3

# Expected: 90%+ coverage

# Check recent processor executions
gcloud logging read \
  'resource.labels.service_name="nba-phase4-precompute-processors"
   AND textPayload=~"VegasLineSummaryProcessor" OR textPayload=~"Completed processing"' \
  --limit=20 --format="value(timestamp,textPayload)"

# Check for errors
gcloud logging read \
  'resource.labels.service_name="nba-phase4-precompute-processors"
   AND severity>=ERROR' \
  --limit=10
```

**Pre-deployment baseline**:
- Record current Vegas line coverage %
- Record recent error rate
- Note last successful execution time

### Step 2: Deploy Using Automated Script

```bash
# From repository root
./bin/deploy-service.sh nba-phase4-precompute-processors
```

**What the script validates**:
1. Service identity
2. Heartbeat code (prevents Firestore proliferation)
3. **Vegas line coverage check** (specific to Phase 4)
4. Recent error rate

**Deployment takes**: ~6-8 minutes

### Step 3: Post-Deployment Verification

```bash
# 1. Check service health
SERVICE_URL=$(gcloud run services describe nba-phase4-precompute-processors --region=us-west2 --format="value(status.url)")
curl -s $SERVICE_URL/health | jq '.'

# 2. Trigger test processing (use recent date with known data)
curl -X POST $SERVICE_URL/process \
  -H "Content-Type: application/json" \
  -d '{
    "processor": "VegasLineSummaryProcessor",
    "data_date": "2026-02-01",
    "force": true
  }'

# 3. Monitor processing
gcloud logging read \
  'resource.labels.service_name="nba-phase4-precompute-processors"
   AND timestamp>="'$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=50 | grep -E "VegasLineSummaryProcessor|Completed|ERROR"

# 4. Verify data written to BigQuery
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(*) as player_count, COUNT(DISTINCT player_lookup) as unique_players
   FROM nba_predictions.vegas_line_summary
   WHERE game_date >= CURRENT_DATE() - 2
   GROUP BY game_date ORDER BY game_date DESC"

# 5. Check Vegas line coverage (CRITICAL)
./bin/monitoring/check_vegas_line_coverage.sh --days 1

# Expected: Coverage should be >= pre-deployment baseline
```

---

## Common Issues & Troubleshooting

### Issue 1: Vegas Line Coverage Dropped

**Symptom**: Coverage drops from 90%+ to <50%

**Cause** (Session 76 root cause):
- `bettingpros_player_points_props` not scraped/loaded
- Processor logic bug (wrong table join, filter issue)
- Schema mismatch causing silent failures

**Diagnosis**:
```bash
# Check if lines are being scraped
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(*) as line_count
   FROM nba_raw.bettingpros_player_points_props
   WHERE game_date >= CURRENT_DATE() - 3
   GROUP BY game_date ORDER BY game_date DESC"

# Check vegas_line_summary processing
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(*) as summary_count,
          COUNT(DISTINCT player_lookup) as players,
          COUNTIF(line_source = 'ACTUAL_PROP') as actual_lines,
          COUNTIF(line_source = 'NO_PROP_LINE') as no_lines
   FROM nba_predictions.vegas_line_summary
   WHERE game_date >= CURRENT_DATE() - 3
   GROUP BY game_date ORDER BY game_date DESC"

# Compare: summary_count should match line_count
```

**Fix**:
- If lines missing from raw table: Check scraper (nba-scrapers service)
- If lines present but not in summary: Check processor logic
- If in summary but wrong line_source: Check join/filter conditions

### Issue 2: BigQuery Partition Filter Error

**Symptom**: 400 BadRequest: "Cannot query over table without partition filter"

**Cause**: Querying partitioned table without required partition column filter

**Fix**:
```python
# WRONG:
query = f"SELECT * FROM nba_raw.bettingpros_player_points_props WHERE processed_at > ..."

# CORRECT:
query = f"""
  SELECT * FROM nba_raw.bettingpros_player_points_props
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND processed_at > ...
"""
```

**Prevention**: Always include partition column filter for partitioned tables

### Issue 3: Silent BigQuery Write Failure

**Symptom**: Processor logs "Completed successfully" but BigQuery table has 0 records

**Cause** (Session 59 root cause):
- Missing `dataset_id` in table reference
- Wrong dataset name
- Permission errors

**Detection**:
```bash
# Check logs for BigQuery 404 errors
gcloud logging read \
  'resource.labels.service_name="nba-phase4-precompute-processors"
   AND textPayload=~"404.*Dataset"' \
  --limit=20

# Verify record count matches expectation
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM nba_predictions.vegas_line_summary
   WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)"
```

**Fix**:
- Always use: `f"{project_id}.{dataset_id}.{table_name}"`
- Add error handling that fails processor if BigQuery write fails
- Add integration tests verifying actual BigQuery writes

### Issue 4: Quota Exceeded Errors

**Symptom**: "Exceeded rate limits: too many partition modifications"

**Cause**: Single-row writes instead of batching

**Fix**: Use `BigQueryBatchWriter` from `shared/utils/bigquery_batch_writer.py`

---

## Rollback Procedure

```bash
# 1. Check Vegas line coverage BEFORE rollback (document degradation)
./bin/monitoring/check_vegas_line_coverage.sh --days 1

# 2. List recent revisions
gcloud run revisions list --service=nba-phase4-precompute-processors --region=us-west2 --limit=5

# 3. Route to previous revision
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 \
  --to-revisions=nba-phase4-precompute-processors-00122-xyz=100

# 4. Verify rollback
curl -s $(gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format="value(status.url)")/health | jq '.'

# 5. Reprocess recent dates with old code
for date in $(seq 0 2); do
  curl -X POST $(gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
    --format="value(status.url)")/process \
    -H "Content-Type: application/json" \
    -d "{\"processor\": \"VegasLineSummaryProcessor\", \"data_date\": \"$(date -d "$date days ago" +%Y-%m-%d)\", \"force\": true}"
  sleep 30
done

# 6. Verify coverage restored
./bin/monitoring/check_vegas_line_coverage.sh --days 1
```

---

## Scheduler Integration

Phase 4 processors run via Cloud Scheduler:

| Scheduler Job | Time (ET) | Purpose |
|---------------|-----------|---------|
| `phase4-morning` | 6:30 AM | Process yesterday's games |
| `phase4-evening-*` | 6 PM, 10 PM, 1 AM | Evening analytics support |

**Verify schedulers after deployment**:

```bash
gcloud scheduler jobs list --location=us-west2 | grep phase4
```

---

## Service Dependencies

| Dependency | Purpose | Impact if Down |
|------------|---------|----------------|
| BigQuery `bettingpros_player_points_props` | Vegas lines | Line coverage drops to 0% |
| BigQuery `player_game_summary` | Player stats | Context features missing |
| BigQuery `vegas_line_summary` (output) | Prediction input | Predictions fail |

---

## Critical Metrics to Monitor

**First 24 hours** after deployment:

1. **Vegas Line Coverage** (MOST IMPORTANT)
   - Target: 90%+
   - Check: `./bin/monitoring/check_vegas_line_coverage.sh --days 1`
   - Alert if: <80%

2. **Processor Completion Rate**
   - Target: 100% (all processors complete)
   - Check: Firestore heartbeats, dashboard

3. **Error Rate**
   - Target: 0 errors
   - Check: `gcloud logging read ... AND severity>=ERROR`

4. **Data Freshness**
   - Target: Data available by 7 AM ET
   - Check: `processed_at` timestamps in BigQuery

---

## Success Criteria

Deployment is successful when:

- ✅ Service responds to `/health`
- ✅ No errors in logs (10 min window)
- ✅ Vegas line coverage >= 90% (or >= pre-deployment baseline)
- ✅ Test processing completes successfully
- ✅ Prediction quality maintained (check next day)

---

## Related Runbooks

- [Deployment: Prediction Worker](./deployment-prediction-worker.md)
- [Vegas Line Coverage Monitoring](../../MONITORING-QUICK-REFERENCE.md)
- [Phase 4 Documentation](../../../03-phases/phase-4-precompute/)

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-02-02 | 1.0 | Initial runbook | Claude + Session 79 |
