# BigQuery DML Quota Solution - January 6, 2026

**Problem:** Multiple roster processors hitting BigQuery concurrent DML quota limit
**Table:** `nba_raw.br_rosters_current`
**Error:** `403 Quota exceeded: Your table exceeded quota for total number of dml jobs writing to a table`

---

## 🔍 Root Cause Analysis

### The Problem
1. **br_season_roster** scraper runs for all 30 NBA teams during `morning_operations` workflow
2. Each team creates a **separate Pub/Sub message**
3. All 30 messages are processed **in parallel** by Cloud Run
4. Each processor executes a **MERGE operation** on the same table
5. BigQuery limit: **~10-15 concurrent DML operations per table**
6. Result: **Quota exceeded errors** when > 15 teams process simultaneously

### Why It Happens
```
morning_operations workflow
  └─> br_season_roster scraper
       └─> Scrapes all 30 teams (parallel)
            └─> Publishes 30 Pub/Sub messages (parallel)
                 └─> Cloud Run processes 30 messages (parallel)
                      └─> 30 MERGE operations hit br_rosters_current (QUOTA EXCEEDED!)
```

### BigQuery Quotas
- **Concurrent DML operations per table:** ~10-15 (soft limit)
- **Includes:** MERGE, UPDATE, DELETE, INSERT (non-streaming)
- **Retry behavior:** 403 errors are NOT automatically retried by BigQuery client

---

## 💡 Solution Design

### Three-Tier Approach

#### **Tier 1: Immediate Fix - Add Quota Retry Logic** ⚡
**Complexity:** Low
**Implementation Time:** 15 minutes
**Reliability:** 80% (handles bursts, not sustained load)

Add retry logic specifically for quota errors (like we did for serialization conflicts):

```python
def _is_quota_exceeded(exc):
    """Check if exception is a BigQuery quota error."""
    if isinstance(exc, api_exceptions.Forbidden):
        error_msg = str(exc).lower()
        return 'quota exceeded' in error_msg
    return False

# Apply to MERGE operations
retry_config = retry.Retry(
    predicate=_is_quota_exceeded,
    initial=2.0,       # Start with 2 seconds
    maximum=120.0,     # Max 2 minutes between retries
    multiplier=2.0,    # Exponential backoff
    deadline=600.0,    # Total max 10 minutes
)
```

**Pros:**
- Quick implementation
- Auto-recovery from temporary spikes
- No architecture changes

**Cons:**
- Doesn't prevent the problem, just retries
- Long backfills could still hit sustained quota limits
- Wastes resources on failed attempts

---

#### **Tier 2: Medium Fix - Distributed Semaphore** 🔒
**Complexity:** Medium
**Implementation Time:** 1-2 hours
**Reliability:** 95% (prevents quota errors)

Use Firestore as a distributed lock to limit concurrent MERGE operations:

```python
class BigQueryTableSemaphore:
    """Distributed semaphore for BigQuery table operations using Firestore."""

    def __init__(self, table_name: str, max_concurrent: int = 10):
        self.table_name = table_name
        self.max_concurrent = max_concurrent
        self.firestore_client = firestore.Client()
        self.lock_collection = 'bigquery_table_locks'

    def acquire(self, timeout: int = 300):
        """Acquire a slot in the semaphore."""
        lock_id = f"{self.table_name}_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check current lock count
            locks_ref = self.firestore_client.collection(self.lock_collection)
            active_locks = locks_ref.where('table_name', '==', self.table_name)\
                                    .where('expires_at', '>', datetime.utcnow())\
                                    .count().get()

            if active_locks[0][0].value < self.max_concurrent:
                # Acquire lock
                lock_doc = {
                    'lock_id': lock_id,
                    'table_name': self.table_name,
                    'acquired_at': firestore.SERVER_TIMESTAMP,
                    'expires_at': datetime.utcnow() + timedelta(minutes=10),
                    'processor': os.environ.get('K_SERVICE', 'unknown')
                }
                locks_ref.document(lock_id).set(lock_doc)
                return lock_id

            # Wait and retry
            time.sleep(random.uniform(1, 3))

        raise TimeoutError(f"Could not acquire semaphore for {self.table_name}")

    def release(self, lock_id: str):
        """Release the semaphore slot."""
        self.firestore_client.collection(self.lock_collection)\
                            .document(lock_id).delete()
```

**Usage in br_roster_processor.py:**
```python
def save_data(self):
    semaphore = BigQueryTableSemaphore('br_rosters_current', max_concurrent=10)
    lock_id = None

    try:
        # Acquire semaphore before MERGE
        lock_id = semaphore.acquire(timeout=300)
        logger.info(f"Acquired semaphore lock: {lock_id}")

        # Proceed with existing MERGE logic...
        # (all the temp table + MERGE code)

    finally:
        if lock_id:
            semaphore.release(lock_id)
            logger.info(f"Released semaphore lock: {lock_id}")
```

**Pros:**
- Prevents quota errors at the source
- Maintains parallelism (up to limit)
- Distributed - works across multiple Cloud Run instances
- Auto-cleanup (locks expire)

**Cons:**
- Requires Firestore setup
- Adds latency (lock acquisition time)
- More complex than simple retry

---

#### **Tier 3: Long-term Fix - Architectural Improvements** 🏗️
**Complexity:** High
**Implementation Time:** 4-8 hours
**Reliability:** 99% (optimal solution)

##### Option A: Pub/Sub Ordering Keys
Use Pub/Sub ordering keys to force sequential processing per table:

```python
# In scraper: br_season_roster.py
message_data = {
    'bucket': bucket,
    'name': file_path,
    'team': team_abbrev
}

# Add ordering key = table name (forces sequential per table)
publisher.publish(
    topic_path,
    data=json.dumps(message_data).encode('utf-8'),
    ordering_key='br_rosters_current'  # All teams use same key = sequential
)
```

**Pros:**
- Built-in GCP feature
- Zero code in processor
- Guaranteed order

**Cons:**
- Reduces parallelism (30 teams processed sequentially)
- Slower backfills (30x slower)
- All-or-nothing (can't fine-tune concurrency)

##### Option B: Cloud Tasks with Rate Limiting
Replace Pub/Sub with Cloud Tasks for roster processing:

```python
# Create task queue with controlled concurrency
client = tasks_v2.CloudTasksClient()
queue_name = client.queue_path(project, location, 'roster-processing')

# Configure queue with max concurrent
queue = tasks_v2.Queue(
    name=queue_name,
    rate_limits=tasks_v2.RateLimits(
        max_concurrent_dispatches=10  # Max 10 concurrent
    )
)

# Create task for each team
for team in NBA_TEAMS:
    task = tasks_v2.Task(
        http_request=tasks_v2.HttpRequest(
            url=processor_url,
            body=json.dumps({'team': team}).encode()
        )
    )
    client.create_task(parent=queue_name, task=task)
```

**Pros:**
- Native rate limiting
- Better visibility (task queue dashboard)
- Retry built-in

**Cons:**
- Architecture change (Pub/Sub → Cloud Tasks)
- Requires queue setup
- More moving parts

##### Option C: Batch Processing
Collect all teams and do one big MERGE:

```python
# Scraper publishes one message for ALL teams
message = {
    'teams': ['ATL', 'BOS', 'BRK', ...],  # All 30 teams
    'batch': True
}

# Processor handles all teams in one MERGE
def save_data(self):
    # Load all teams to one temp table
    all_rows = []
    for team in self.opts['teams']:
        rows = self.process_team(team)
        all_rows.extend(rows)

    # One big MERGE (instead of 30 small MERGEs)
    self.merge_all(all_rows)
```

**Pros:**
- Single DML operation (no quota issue)
- Most efficient

**Cons:**
- Big architecture change
- All-or-nothing (one failure = all teams fail)
- Harder to debug

---

## 🎯 Recommended Implementation Plan

### Phase 1: Immediate (Today) ✅
**Implement Tier 1 + Tier 2**

1. **Add quota retry logic** (15 minutes)
   - Modify `br_roster_processor.py`
   - Add `_is_quota_exceeded()` predicate
   - Apply to MERGE operation

2. **Implement Firestore semaphore** (1 hour)
   - Create `shared/utils/bigquery_semaphore.py`
   - Integrate into `br_roster_processor.py`
   - Set `max_concurrent=10`

3. **Test** (30 minutes)
   - Trigger 30 roster scrapes simultaneously
   - Verify no quota errors
   - Check semaphore metrics

### Phase 2: This Week (Optional) 🔄
**Evaluate Tier 3 options**

1. Run production for a week with Tier 1+2
2. Monitor:
   - Quota error rate (should be 0%)
   - Semaphore wait times
   - Overall processing duration
3. Decide if Tier 3 needed based on data

---

## 📊 Implementation Details

### File Changes Required

#### 1. Create Semaphore Utility
**File:** `shared/utils/bigquery_semaphore.py` (NEW)
```python
"""
Distributed semaphore for BigQuery table operations using Firestore.
Prevents concurrent DML operations from exceeding quota limits.
"""

import time
import uuid
import random
import logging
from datetime import datetime, timedelta
from typing import Optional
from google.cloud import firestore

logger = logging.getLogger(__name__)

class BigQueryTableSemaphore:
    """Distributed semaphore using Firestore to limit concurrent table operations."""

    def __init__(self, table_name: str, max_concurrent: int = 10):
        self.table_name = table_name
        self.max_concurrent = max_concurrent
        self.firestore_client = firestore.Client()
        self.lock_collection = 'bigquery_table_locks'

    def acquire(self, timeout: int = 300) -> str:
        """Acquire a slot. Returns lock_id. Raises TimeoutError if can't acquire."""
        # Implementation above...

    def release(self, lock_id: str):
        """Release the semaphore slot."""
        # Implementation above...
```

#### 2. Modify Roster Processor
**File:** `data_processors/raw/basketball_ref/br_roster_processor.py`

**Add imports:**
```python
from google.api_core import exceptions as api_exceptions
from shared.utils.bigquery_semaphore import BigQueryTableSemaphore
```

**Add quota predicate:**
```python
def _is_quota_exceeded(exc):
    """Check if exception is a BigQuery quota error."""
    if isinstance(exc, api_exceptions.Forbidden):
        return 'quota exceeded' in str(exc).lower()
    return False
```

**Modify save_data():**
```python
def save_data(self) -> None:
    if not self.transformed_data:
        return

    # Acquire semaphore before processing
    semaphore = BigQueryTableSemaphore('br_rosters_current', max_concurrent=10)
    lock_id = None

    try:
        lock_id = semaphore.acquire(timeout=300)
        logger.info(f"✅ Acquired semaphore for br_rosters_current: {lock_id}")

        # ... existing MERGE logic ...

        # Add retry for quota errors
        @retry.Retry(
            predicate=_is_quota_exceeded,
            initial=2.0,
            maximum=120.0,
            multiplier=2.0,
            deadline=600.0
        )
        def execute_merge_with_retries():
            query_job = self.bq_client.query(merge_query)
            return query_job.result(timeout=120)

        result = execute_merge_with_retries()

    except TimeoutError:
        logger.error("⏰ Timeout waiting for semaphore - too many concurrent operations")
        raise

    finally:
        if lock_id:
            semaphore.release(lock_id)
            logger.info(f"✅ Released semaphore: {lock_id}")
```

#### 3. Firestore Setup (One-time)
```bash
# Enable Firestore API
gcloud services enable firestore.googleapis.com

# Create Firestore database (if not exists)
gcloud firestore databases create --region=us-west2

# Grant Cloud Run service account access
gcloud projects add-iam-policy-binding nba-props-platform \
    --member="serviceAccount:${SERVICE_ACCOUNT}@nba-props-platform.iam.gserviceaccount.com" \
    --role="roles/datastore.user"
```

---

## 🧪 Testing Plan

### Unit Tests
```python
def test_semaphore_basic():
    """Test basic acquire/release."""
    semaphore = BigQueryTableSemaphore('test_table', max_concurrent=2)
    lock1 = semaphore.acquire()
    lock2 = semaphore.acquire()

    # Third should block/timeout
    with pytest.raises(TimeoutError):
        semaphore.acquire(timeout=5)

    semaphore.release(lock1)
    lock3 = semaphore.acquire()  # Should succeed now

def test_semaphore_expiry():
    """Test that expired locks are auto-cleaned."""
    # Create lock with 1-second expiry
    # Wait 2 seconds
    # Verify new lock can be acquired
```

### Integration Tests
```bash
# Test with 30 simultaneous roster scrapes
for team in ATL BOS BRK CHO CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS; do
    # Trigger roster scrape for each team
    echo "Triggering $team..."
done

# Monitor logs for:
# - Semaphore acquire/release messages
# - No quota exceeded errors
# - Processing completes successfully
```

---

## 📈 Monitoring

### Metrics to Track
1. **Quota error rate:** Should be 0%
2. **Semaphore wait time:** Average time to acquire lock
3. **Processing duration:** Total time for all 30 teams
4. **Lock contention:** How often processors wait for locks

### Firestore Queries
```python
# Check active locks
db = firestore.Client()
active_locks = db.collection('bigquery_table_locks')\
                 .where('table_name', '==', 'br_rosters_current')\
                 .where('expires_at', '>', datetime.utcnow())\
                 .get()

print(f"Active locks: {len(active_locks)}")

# Check lock history
all_locks = db.collection('bigquery_table_locks')\
              .where('table_name', '==', 'br_rosters_current')\
              .order_by('acquired_at', direction=firestore.Query.DESCENDING)\
              .limit(100)\
              .get()
```

### Cloud Logging
```bash
# Check for semaphore activity
gcloud logging read 'resource.labels.service_name=nba-phase2-raw-processors
  AND jsonPayload.message=~"semaphore"' --limit=50

# Check for quota errors (should be zero)
gcloud logging read 'resource.labels.service_name=nba-phase2-raw-processors
  AND jsonPayload.message=~"Quota exceeded"' --limit=50
```

---

## 💰 Cost Analysis

### Tier 1: Retry Logic
- **Cost:** $0 (just code changes)
- **Latency:** +10-60 seconds per retry (only on failure)

### Tier 2: Firestore Semaphore
- **Firestore operations:** 2 per roster scrape (acquire + release)
- **Daily volume:** 30 teams × 1 scrape/day = 60 operations/day
- **Monthly cost:** ~$0.01 (negligible)
- **Latency:** +100-500ms for lock acquisition

### Tier 3: Cloud Tasks
- **Task operations:** 30 tasks/day
- **Monthly cost:** ~$0.01 (negligible)
- **Latency:** Depends on queue concurrency setting

**Winner:** Tier 2 (Firestore semaphore) - Negligible cost, good performance

---

## 🎓 Lessons Learned

1. **BigQuery has strict per-table DML limits** (~10-15 concurrent)
2. **Parallel processing needs coordination** when targeting same resource
3. **Retry logic is good, prevention is better**
4. **Firestore works great as distributed lock** for GCP services
5. **Always design for quota limits** when building parallel systems

---

## 📚 References

- [BigQuery Quotas](https://cloud.google.com/bigquery/quotas#standard_tables)
- [Firestore as Distributed Lock](https://cloud.google.com/firestore/docs/solutions/distributed-lock)
- [Pub/Sub Ordering Keys](https://cloud.google.com/pubsub/docs/ordering)
- [Cloud Tasks Rate Limiting](https://cloud.google.com/tasks/docs/creating-queues#rate)

---

**Status:** Ready for Implementation
**Estimated Time:** 2-3 hours for full Tier 1+2 implementation
**Risk Level:** Low (additive changes, graceful degradation)
