# Phase 3 Completion Tracking Reliability Guide

**Created:** 2026-02-04
**Session:** 116
**Status:** Active
**Severity:** P1 CRITICAL - Orchestration reliability

## Executive Summary

This document details the orchestration reliability issues discovered during Feb 3, 2026 validation and provides comprehensive prevention measures to ensure robust Phase 3 to Phase 4 transitions.

### Issues Discovered

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| Orchestrator message processing failures | P1 CRITICAL | Phase 4 not triggered, incomplete completion tracking | Mitigated (manual fix) |
| Late scraper execution | P2 HIGH | Data arrives 6+ hours late, causes race conditions | Investigation needed |
| Concurrent processing duplicates | P2 HIGH | 72 duplicate records, data quality issues | Resolved (deduplication) |

---

## Issue 1: Orchestrator Firestore Tracking Failures

### Symptoms

```
Firestore state:
  - 5 processors have completion data
  - _completed_count: 3 (should be 5)
  - _triggered: None/False (Phase 4 never triggered)
  - _last_update: 05:15 AM (3 processors completed at 3 PM)
```

**Result:** Phase 3 appears incomplete even though all processors succeeded.

### Root Cause

The **Phase 3 to Phase 4 orchestrator Cloud Function** (`phase3-to-phase4-orchestrator`) fails to process some Pub/Sub completion messages due to:

1. **Cold start timeouts** - Messages arrive during cold start and timeout before processing
2. **Concurrent transaction conflicts** - Multiple processors completing simultaneously cause Firestore transaction retries that exhaust retry budget
3. **Duplicate message handling** - The idempotency check at `orchestration/cloud_functions/phase3_to_phase4/main.py:1516-1518` returns early without updating metadata:

```python
if processor_name in current:
    logger.debug(f"Processor {processor_name} already registered (duplicate Pub/Sub message)")
    return (False, 'unknown', 'duplicate')
```

### Why _completed_count Gets Out of Sync

The count is only updated when `update_completion_atomic` runs successfully. If the orchestrator fails to process messages but processors still write completion data to Firestore through CompletionTracker (dual-write), then:

- Processor data exists in Firestore (5 processors) ✓
- `_completed_count` was never updated by atomic transaction (stuck at 3) ✗
- `_triggered` never set to True ✗

### Detection

**Manual check:**
```bash
python3 << 'EOF'
from google.cloud import firestore
import sys

db = firestore.Client(project='nba-props-platform')
date = '2026-02-03'  # Change to target date

doc = db.collection('phase3_completion').document(date).get()
if not doc.exists:
    print(f'❌ No completion document for {date}')
    sys.exit(1)

data = doc.to_dict()
actual_count = len([k for k in data.keys() if not k.startswith('_')])
stored_count = data.get('_completed_count', 0)
triggered = data.get('_triggered', False)

print(f'Date: {date}')
print(f'  Actual processors: {actual_count}')
print(f'  Stored count: {stored_count}')
print(f'  Triggered: {triggered}')

if actual_count != stored_count:
    print(f'\n❌ MISMATCH: {actual_count} processors but count shows {stored_count}')
    sys.exit(1)
elif actual_count >= 5 and not triggered:
    print(f'\n❌ NOT TRIGGERED: {actual_count}/5 complete but not triggered')
    sys.exit(1)
else:
    print(f'\n✅ OK')
EOF
```

**Automated monitoring:**
```bash
# Add to daily health check
gcloud logging read 'resource.type="cloud_function"
  AND resource.labels.function_name="phase3-to-phase4-orchestrator"
  AND severity>=ERROR' \
  --limit=10 --freshness=24h
```

### Remediation

**Immediate fix (manual):**
```bash
python3 << 'EOF'
from google.cloud import firestore

db = firestore.Client(project='nba-props-platform')
date = 'YYYY-MM-DD'  # Set target date

doc_ref = db.collection('phase3_completion').document(date)
doc_ref.update({
    '_completed_count': 5,
    '_triggered': True,
    '_trigger_reason': 'manual_fix_orchestrator_failure',
    '_last_update': firestore.SERVER_TIMESTAMP
})
print(f'✅ Fixed {date}')
EOF
```

**Prevention (code changes):**

1. **Always recalculate _completed_count from document state**

   File: `orchestration/cloud_functions/phase3_to_phase4/main.py`

   ```python
   def update_completion_atomic(transaction, doc_ref, processor_name, record_count, execution_id):
       """Update completion tracking with recalculated count"""
       current = doc_ref.get(transaction=transaction).to_dict() or {}

       # Add processor data
       current[processor_name] = {
           'status': 'success',
           'record_count': record_count,
           'execution_id': execution_id,
           'completed_at': firestore.SERVER_TIMESTAMP
       }

       # ALWAYS recalculate count from actual processors present
       completed_count = len([k for k in current.keys() if not k.startswith('_')])
       current['_completed_count'] = completed_count

       # Check if all processors done
       if completed_count >= 5:
           current['_triggered'] = True
           current['_trigger_reason'] = 'all_processors_complete'

       current['_last_update'] = firestore.SERVER_TIMESTAMP
       transaction.update(doc_ref, current)
       return completed_count
   ```

2. **Add reconciliation job**

   File: `bin/maintenance/reconcile_phase3_completion.py`

   ```python
   #!/usr/bin/env python3
   """
   Reconcile Phase 3 completion tracking.

   Finds dates where:
   - Actual processor count != _completed_count
   - All 5 processors present but _triggered = False

   Usage:
       python bin/maintenance/reconcile_phase3_completion.py --days 7 --fix
   """

   import argparse
   from datetime import datetime, timedelta
   from google.cloud import firestore

   def reconcile_completion(days_back=7, fix=False):
       db = firestore.Client(project='nba-props-platform')
       issues = []

       for i in range(days_back):
           date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
           doc = db.collection('phase3_completion').document(date).get()

           if not doc.exists:
               continue

           data = doc.to_dict()
           actual = len([k for k in data.keys() if not k.startswith('_')])
           stored = data.get('_completed_count', 0)
           triggered = data.get('_triggered', False)

           if actual != stored or (actual >= 5 and not triggered):
               issues.append({
                   'date': date,
                   'actual': actual,
                   'stored': stored,
                   'triggered': triggered
               })

               if fix:
                   db.collection('phase3_completion').document(date).update({
                       '_completed_count': actual,
                       '_triggered': True if actual >= 5 else False,
                       '_trigger_reason': 'reconciliation_fix',
                       '_last_update': firestore.SERVER_TIMESTAMP
                   })
                   print(f'✅ Fixed {date}')

       return issues

   if __name__ == '__main__':
       parser = argparse.ArgumentParser()
       parser.add_argument('--days', type=int, default=7)
       parser.add_argument('--fix', action='store_true')
       args = parser.parse_args()

       issues = reconcile_completion(args.days, args.fix)
       print(f'Found {len(issues)} issues in last {args.days} days')
   ```

3. **Add Cloud Function monitoring**

   Create alert in GCP:
   ```yaml
   alertPolicy:
     displayName: "Phase 3 Orchestrator Failures"
     conditions:
       - displayName: "High error rate"
         conditionThreshold:
           filter: |
             resource.type = "cloud_function"
             resource.labels.function_name = "phase3-to-phase4-orchestrator"
             severity >= ERROR
           comparison: COMPARISON_GT
           thresholdValue: 5
           duration: 300s
     notificationChannels:
       - "projects/nba-props-platform/notificationChannels/slack-critical"
   ```

---

## Issue 2: Late Scraper Execution

### Symptoms

```
Expected: Gamebook scrapers run at ~6 AM ET (after games end at midnight)
Actual:   Gamebook scrapers ran at 2:45 PM ET (8+ hours late)

Timeline Feb 4:
  03:00-06:00  Processor found NO data
  12:30        nbac_player_boxscores loaded (all games Final)
  14:45        First gamebook batch (2 games)
  15:00        Second gamebook batch (8 games)
```

**Impact:**
- Processors run multiple times finding partial data
- Creates race conditions and duplicate records
- Delays downstream predictions

### Root Cause

**Investigation needed:** Why did `nbac_gamebook_player_stats` scraper run so late?

Possible causes:
1. Cloud Scheduler job delayed or failed
2. Scraper timeout/retry logic issue
3. NBA.com data source delayed
4. Rate limiting or IP blocking

### Detection

```bash
# Check scraper execution times
bq query --use_legacy_sql=false "
SELECT
  scraper_name,
  MIN(started_at) as first_run,
  MAX(completed_at) as last_run,
  COUNT(*) as run_count
FROM nba_orchestration.scraper_run_history
WHERE DATE(started_at) = CURRENT_DATE()
  AND scraper_name LIKE '%gamebook%'
GROUP BY scraper_name
"
```

**Expected:** First run before 8 AM ET
**Alert:** First run after 10 AM ET

### Prevention

1. **Add scraper timing alerts**

   ```bash
   # Daily check for late scrapers
   ./bin/monitoring/check_scraper_timing.sh --max-delay-hours 4
   ```

2. **Investigate specific scraper**

   ```bash
   # Check gamebook scraper logs
   gcloud logging read 'resource.labels.service_name="nba-phase1-scrapers"
     AND jsonPayload.scraper_name="nbac_gamebook_player_stats"' \
     --limit=20 --freshness=24h
   ```

3. **Add retry with backoff**

   Ensure scrapers have proper retry logic with exponential backoff (already implemented in most scrapers).

---

## Issue 3: Concurrent Processing Duplicates

### Symptoms

```
MERGE failures:
  "Could not serialize access to table due to concurrent update"

Result:
  - Fallback to DELETE + INSERT
  - 72 duplicate player records created
  - Data quality degraded (duplicate stats)
```

### Root Cause

Multiple processor instances running concurrently for the same date:
1. Processor instance 1 starts at 15:00:06
2. Processor instance 2 starts at 15:00:24 (18 seconds later)
3. Both try to MERGE to `player_game_summary`
4. MERGE fails, both fall back to DELETE + INSERT
5. Both write full datasets, creating duplicates

### Detection

```sql
-- Check for duplicate player records
SELECT
  game_date,
  player_lookup,
  game_id,
  COUNT(*) as record_count
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date, player_lookup, game_id
HAVING COUNT(*) > 1
ORDER BY game_date DESC, record_count DESC
```

**Expected:** 0 duplicates
**Alert:** Any duplicates found

### Prevention

1. **Add distributed locking**

   File: `data_processors/analytics/analytics_base.py`

   ```python
   from google.cloud import firestore
   from datetime import datetime, timedelta

   def acquire_processing_lock(self, game_date: str) -> bool:
       """Acquire distributed lock for processing a date"""
       db = firestore.Client(project=self.project_id)
       lock_id = f"{self.processor_name}_{game_date}"
       lock_ref = db.collection('processing_locks').document(lock_id)

       @firestore.transactional
       def try_acquire(transaction):
           lock_doc = lock_ref.get(transaction=transaction)

           if lock_doc.exists:
               lock_data = lock_doc.to_dict()
               acquired_at = lock_data.get('acquired_at')

               # Lock expired (older than 10 minutes)?
               if acquired_at and acquired_at < datetime.now() - timedelta(minutes=10):
                   # Stale lock, acquire it
                   transaction.update(lock_ref, {
                       'acquired_at': firestore.SERVER_TIMESTAMP,
                       'execution_id': self.run_id,
                       'instance': os.environ.get('K_REVISION', 'local')
                   })
                   return True
               else:
                   # Active lock held by another instance
                   return False
           else:
               # No lock exists, create it
               transaction.set(lock_ref, {
                   'acquired_at': firestore.SERVER_TIMESTAMP,
                   'execution_id': self.run_id,
                   'instance': os.environ.get('K_REVISION', 'local')
               })
               return True

       transaction = db.transaction()
       return try_acquire(transaction)

   def release_processing_lock(self, game_date: str):
       """Release distributed lock"""
       db = firestore.Client(project=self.project_id)
       lock_id = f"{self.processor_name}_{game_date}"
       db.collection('processing_locks').document(lock_id).delete()
   ```

2. **Add pre-write deduplication**

   File: `data_processors/analytics/operations/bigquery_save_ops.py`

   ```python
   def deduplicate_before_write(records: List[Dict], key_fields: List[str]) -> List[Dict]:
       """Remove duplicates from records before writing"""
       seen = set()
       unique = []

       for record in records:
           key = tuple(record.get(f) for f in key_fields)
           if key not in seen:
               seen.add(key)
               unique.append(record)

       duplicates = len(records) - len(unique)
       if duplicates > 0:
           logger.warning(f'Removed {duplicates} duplicate records before write')

       return unique
   ```

3. **Use Cloud Tasks instead of direct invocation**

   Instead of triggering processors directly, queue them:

   ```python
   from google.cloud import tasks_v2

   def queue_processor_task(processor_name: str, game_date: str):
       """Queue processor task with deduplication"""
       client = tasks_v2.CloudTasksClient()
       parent = client.queue_path('nba-props-platform', 'us-west2', 'analytics-processors')

       task = {
           'http_request': {
               'http_method': tasks_v2.HttpMethod.POST,
               'url': f'https://nba-phase3-analytics-processors.run.app/process',
               'headers': {'Content-Type': 'application/json'},
               'body': json.dumps({
                   'processor': processor_name,
                   'game_date': game_date
               }).encode()
           },
           'name': client.task_path(
               'nba-props-platform',
               'us-west2',
               'analytics-processors',
               f'{processor_name}_{game_date}'  # Unique task name prevents duplicates
           )
       }

       try:
           client.create_task(request={'parent': parent, 'task': task})
       except Exception as e:
           if 'already exists' in str(e):
               logger.info(f'Task already queued for {processor_name} on {game_date}')
           else:
               raise
   ```

---

## Monitoring Dashboard

Create a daily health check that runs at 8 AM ET:

```bash
#!/bin/bash
# File: bin/monitoring/phase3_health_check.sh

echo "=== Phase 3 Completion Health Check ==="
echo "Date: $(date)"

# Check yesterday's completion
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

python3 << EOF
from google.cloud import firestore
import sys

db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase3_completion').document('$YESTERDAY').get()

if not doc.exists:
    print(f'❌ No completion document for $YESTERDAY')
    sys.exit(1)

data = doc.to_dict()
actual = len([k for k in data.keys() if not k.startswith('_')])
stored = data.get('_completed_count', 0)
triggered = data.get('_triggered', False)

status = '✅ OK'
if actual != stored:
    status = f'❌ MISMATCH (actual: {actual}, stored: {stored})'
elif actual >= 5 and not triggered:
    status = f'❌ NOT TRIGGERED'

print(f'{status}')
print(f'  Processors: {actual}/5')
print(f'  Count: {stored}')
print(f'  Triggered: {triggered}')

if status != '✅ OK':
    sys.exit(1)
EOF

# Check for duplicates
echo ""
echo "=== Duplicate Check ==="
bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as duplicate_count
FROM (
  SELECT game_date, player_lookup, game_id, COUNT(*) as cnt
  FROM nba_analytics.player_game_summary
  WHERE game_date = DATE('$YESTERDAY')
  GROUP BY 1, 2, 3
  HAVING cnt > 1
)
"

# Check scraper timing
echo ""
echo "=== Scraper Timing ==="
bq query --use_legacy_sql=false --format=csv "
SELECT
  scraper_name,
  MIN(started_at) as first_run,
  TIMESTAMP_DIFF(MIN(started_at), TIMESTAMP('$YESTERDAY 06:00:00'), HOUR) as hours_late
FROM nba_orchestration.scraper_run_history
WHERE DATE(started_at) = CURRENT_DATE()
  AND scraper_name LIKE '%gamebook%'
GROUP BY scraper_name
HAVING hours_late > 4
"
```

**Schedule:**
```bash
# Add to Cloud Scheduler
gcloud scheduler jobs create http phase3-health-check \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://monitoring-service.run.app/phase3-health" \
  --http-method=POST
```

---

## Recovery Playbook

### Scenario 1: Completion Tracking Mismatch

**Symptoms:** Firestore shows incomplete but data exists in BigQuery

**Steps:**
1. Verify data exists:
   ```bash
   bq query "SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = 'YYYY-MM-DD'"
   ```

2. Fix Firestore:
   ```bash
   python bin/maintenance/reconcile_phase3_completion.py --days 1 --fix
   ```

3. Verify Phase 4 triggered:
   ```bash
   bq query "SELECT COUNT(*) FROM nba_precompute.player_daily_cache WHERE cache_date = 'YYYY-MM-DD'"
   ```

### Scenario 2: Duplicate Records

**Symptoms:** Multiple records for same player/game in analytics

**Steps:**
1. Identify duplicates:
   ```sql
   SELECT game_date, player_lookup, game_id, COUNT(*)
   FROM nba_analytics.player_game_summary
   WHERE game_date = 'YYYY-MM-DD'
   GROUP BY 1, 2, 3
   HAVING COUNT(*) > 1
   ```

2. Deduplicate (keep most recent):
   ```sql
   DELETE FROM nba_analytics.player_game_summary
   WHERE (game_date, player_lookup, game_id, processed_at) NOT IN (
     SELECT game_date, player_lookup, game_id, MAX(processed_at)
     FROM nba_analytics.player_game_summary
     WHERE game_date = 'YYYY-MM-DD'
     GROUP BY 1, 2, 3
   )
   AND game_date = 'YYYY-MM-DD'
   ```

### Scenario 3: Late Scrapers

**Symptoms:** Gamebook data arrives after 10 AM ET

**Steps:**
1. Check scheduler:
   ```bash
   gcloud scheduler jobs describe nbac-gamebook-scraper --location=us-west2
   ```

2. Manual trigger if needed:
   ```bash
   gcloud scheduler jobs run nbac-gamebook-scraper --location=us-west2
   ```

3. Investigate root cause in logs

---

## Success Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Phase 3 completion accuracy | 100% | < 95% |
| Scraper on-time execution | > 95% | First run > 10 AM ET |
| Duplicate record rate | 0% | > 0% |
| Orchestrator error rate | < 1% | > 5% |
| Phase 4 trigger delay | < 10 min after Phase 3 | > 30 min |

---

## Related Documentation

- [Daily Operations Runbook](./daily-operations-runbook.md)
- [Troubleshooting Matrix](../troubleshooting-matrix.md)
- [Session 116 Handoff](../../09-handoff/2026-02-04-SESSION-116-HANDOFF.md)

---

## Change Log

| Date | Change | Session |
|------|--------|---------|
| 2026-02-04 | Initial document created | 116 |
