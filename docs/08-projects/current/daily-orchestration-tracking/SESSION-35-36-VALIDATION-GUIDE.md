# Session 35-36 Validation Guide

**Created:** 2026-01-14 (Session 36)
**Purpose:** Document how to validate the improvements deployed in Sessions 35 and 36

---

## Quick Validation Commands

```bash
# 1. Health Dashboard (overall system status)
python scripts/system_health_check.py

# 2. Check failure_category distribution
bq query --use_legacy_sql=false "
SELECT
  COALESCE(failure_category, 'NULL') as category,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1 ORDER BY 2 DESC"

# 3. Check BR roster batch lock
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
for lock in db.collection('batch_processing_locks').stream():
    if 'br_roster' in lock.id:
        print(f'{lock.id}: {lock.to_dict()}')"

# 4. Check Cloud Run revisions
gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"
```

---

## Validation 1: failure_category Field

### What Was Deployed
- **Commit:** `12e432a` (Session 35)
- **Files Modified:**
  - `shared/processors/mixins/run_history_mixin.py` - Added failure_category parameter
  - `data_processors/raw/processor_base.py` - Added `_categorize_failure()` function
  - `data_processors/analytics/analytics_base.py` - Uses _categorize_failure
  - `data_processors/precompute/precompute_base.py` - Uses _categorize_failure
  - `schemas/bigquery/nba_reference/processor_run_history.sql` - Added column

### Expected Behavior
When a processor fails, it should categorize the failure as one of:
- `no_data_available` - Expected, no data to process (DON'T ALERT)
- `upstream_failure` - Dependency failed (DON'T ALERT)
- `processing_error` - Real error (ALERT!)
- `timeout` - Operation timed out (ALERT!)
- `configuration_error` - Missing required options (ALERT!)
- `unknown` - Backward compatibility default (ALERT!)

### Validation Query
```sql
-- Check failure_category distribution (run 24-48 hours after deployment)
SELECT
  failure_category,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct,
  COUNT(DISTINCT processor_name) as affected_processors
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
GROUP BY failure_category
ORDER BY count DESC;
```

### Success Criteria
| Metric | Target | How to Verify |
|--------|--------|---------------|
| NULL failure_category | 0% (new failures only) | Query above - NULL should be 0% for recent failures |
| no_data_available | 80-90% of failures | Most failures should be expected |
| processing_error | <10% of failures | Real errors should be rare |
| Alert noise reduction | >80% | (no_data_available + upstream_failure) / total |

### What If Validation Fails?
1. **All NULL:** Processors haven't run since deployment - wait for next scheduled run
2. **All processing_error:** Check `_categorize_failure()` patterns in processor_base.py
3. **Mixed results:** Expected during transition - old failures have NULL, new ones categorized

---

## Validation 2: BR Roster Batch Lock

### What Was Deployed
- **Commit:** `129a5bf` (Session 35)
- **File Modified:** `data_processors/raw/main_processor_service.py` (lines 864-952)

### Expected Behavior
When Basketball Reference roster files are processed:
1. First instance acquires Firestore lock (`batch_processing_locks/br_roster_batch_{season}`)
2. First instance runs batch processor for ALL 30 teams
3. Other 29 instances see lock exists → return "skipped" (200 OK)
4. Result: 1 BigQuery MERGE instead of 30 concurrent writes

### Validation Query - Check for Lock Documents
```python
# Run in Python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
for lock in db.collection('batch_processing_locks').stream():
    data = lock.to_dict()
    print(f"Lock: {lock.id}")
    print(f"  Status: {data.get('status')}")
    print(f"  Started: {data.get('started_at')}")
    print(f"  Trigger: {data.get('trigger_file', 'N/A')[:60]}")
    print()
```

### Validation Query - Check for Reduced Failures
```sql
-- Compare BR roster failures before and after deployment
-- BEFORE: Should see many concurrent failures with "Too many DML" errors
-- AFTER: Should see mostly successes or "skipped" status

SELECT
  DATE(started_at) as date,
  processor_name,
  status,
  COUNT(*) as count
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name LIKE '%Roster%'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC;
```

### Success Criteria
| Metric | Target | How to Verify |
|--------|--------|---------------|
| BR roster failures | ~0 per day | Query above - failures should drop dramatically |
| Lock documents | Present | Firestore check - should see `br_roster_batch_*` docs |
| Batch processing | 1 per roster scrape | Logs should show "Acquired batch lock" once |

### What If Validation Fails?
1. **No br_roster locks:** BR rosters haven't been scraped since deployment - wait for next scrape
2. **Still seeing failures:** Check Cloud Run logs for lock acquisition errors
3. **Lock stuck in 'processing':** Check `expireAt` TTL (7 days) - may need manual cleanup

---

## Validation 3: Health Dashboard

### What Was Deployed
- **Commit:** `437c5a4` (Session 36)
- **File Created:** `scripts/system_health_check.py` (693 lines)

### Usage Examples
```bash
# Basic health check (last 24 hours)
python scripts/system_health_check.py

# Last hour only
python scripts/system_health_check.py --hours=1

# Last week
python scripts/system_health_check.py --days=7

# JSON output (for automation)
python scripts/system_health_check.py --json

# Verbose mode (show issue details)
python scripts/system_health_check.py --verbose

# Send to Slack (requires SLACK_WEBHOOK_URL env var)
SLACK_WEBHOOK_URL=https://hooks.slack.com/... python scripts/system_health_check.py --slack
```

### Exit Codes
- `0` - All systems healthy
- `1` - Warnings detected (success rate 50-80%)
- `2` - Critical issues detected (success rate <50%)

### Expected Output
```
🏥 NBA Stats Scraper - System Health Check
📅 Last 24 hours  |  Generated: 2026-01-14 21:00:00

Phase Health Summary
────────────────────────────────────────────────────────────
✅ Phase 2 (Raw Processors)         95.2% success │   2 real failures
✅ Phase 3 (Analytics)              98.1% success │   1 real failures
✅ Phase 4 (Precompute)             92.4% success │   5 real failures
✅ Phase 5 (Predictions)            88.0% success │   3 real failures

📊 Alert Noise Reduction (failure_category)
────────────────────────────────────────────────────────────
Total failures:                       150
Expected (no_data_available):         135 (90.0%)
Real failures (need attention):        15 (10.0%)
🎉 Noise reduction goal achieved! (90.0% > 80% target)
```

---

## Validation Timeline

| Timeframe | What to Check |
|-----------|---------------|
| **Immediately** | Cloud Run revisions are correct |
| **After 1 hour** | Any processor runs show failure_category |
| **After 24 hours** | Full failure_category distribution visible |
| **After BR roster scrape** | Firestore lock documents exist |
| **After 48 hours** | Noise reduction metrics stabilized |
| **After 1 week** | Compare before/after failure counts |

---

## Monitoring Queries for Ongoing Validation

### Daily Health Check
```sql
-- Run daily to track improvement trends
SELECT
  DATE(started_at) as date,
  COUNT(*) as total_failures,
  COUNTIF(failure_category = 'no_data_available') as expected_failures,
  COUNTIF(COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real_failures,
  ROUND(COUNTIF(failure_category = 'no_data_available') * 100.0 / NULLIF(COUNT(*), 0), 2) as noise_reduction_pct
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date
ORDER BY date DESC;
```

### Weekly BR Roster Storm Check
```sql
-- Check if Monday retry storm is eliminated
SELECT
  EXTRACT(DAYOFWEEK FROM started_at) as day_of_week,
  EXTRACT(HOUR FROM started_at) as hour_utc,
  COUNT(*) as failure_count
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name LIKE '%Roster%'
  AND status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 20;
```

---

## Rollback Instructions

If issues are detected:

### Rollback failure_category
The field is additive and backward compatible. No rollback needed - just ignore the field.

### Rollback BR Roster Lock
```bash
# Redeploy previous revision
gcloud run services update-traffic nba-phase2-raw-processors \
  --region=us-west2 \
  --to-revisions=nba-phase2-raw-processors-00089-zlh=100

# Clear any stuck locks
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
for lock in db.collection('batch_processing_locks').stream():
    if 'br_roster' in lock.id:
        lock.reference.delete()
        print(f'Deleted: {lock.id}')"
```

---

**Last Updated:** 2026-01-14 Session 36
