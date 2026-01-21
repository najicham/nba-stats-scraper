# Phase 3: Retry & Connection Pooling - Implementation Guide

**Status:** 🟡 In Progress
**Start Date:** January 19, 2026
**Target Completion:** February 15, 2026
**Estimated Effort:** 58-82 hours (Weeks 3-4)
**Priority:** P1 - High

---

## 📋 Overview

Phase 3 systematically integrates retry jitter and connection pooling utilities across the entire codebase. All utilities were created in Session 112 and are production-ready. This phase focuses on adoption and validation.

**Key Objectives:**
1. Eliminate thundering herd problem during retries
2. Reduce "too many connections" errors to zero
3. Improve retry success rate from 70% to 95%
4. Reduce connection setup overhead by 40%

**Foundation Already Built:**
- ✅ `shared/utils/retry_with_jitter.py` - Decorrelated jitter algorithm
- ✅ `shared/utils/bigquery_retry.py` - BigQuery-specific retry decorators
- ✅ `shared/clients/bigquery_pool.py` - Thread-safe BigQuery client pooling
- ✅ `shared/clients/http_pool.py` - HTTP session pooling with retry

---

## ✅ Task 3.1: Complete Jitter Adoption in Data Processors

**Status:** ⚪ Not Started
**Effort:** 20 hours
**Files to Update:** ~20 files in `data_processors/`

### Context

Currently 30-40% of the codebase uses retry jitter. The remaining files use:
- Manual retry loops with fixed delays (no exponential backoff)
- Duplicate serialization conflict detection logic
- No retry at all for BigQuery operations

### Sub-Task 3.1.1: Remove Duplicate Serialization Logic

**Files:** 2 files with duplicate `_is_serialization_conflict()` function

1. `data_processors/raw/processor_base.py` (lines 62-78)
2. `data_processors/raw/nbacom/nbac_gamebook_processor.py` (lines 62-78)

**Current Pattern (DUPLICATED):**
```python
def _is_serialization_conflict(exc):
    """Check if exception is a BigQuery serialization conflict."""
    if isinstance(exc, api_exceptions.BadRequest):
        error_msg = str(exc).lower()
        return (
            "could not serialize" in error_msg or
            "concurrent update" in error_msg or
            "concurrent write" in error_msg
        )
    return False
```

**Solution:** This function already exists in `shared/utils/bigquery_retry.py` as `is_serialization_error()` with better logging.

**Implementation Steps:**

```python
# Step 1: In processor_base.py - REMOVE lines 62-78 completely

# Step 2: Add import at top of file
from shared.utils.bigquery_retry import (
    SERIALIZATION_RETRY,
    QUOTA_RETRY,
    is_serialization_error,
    is_quota_exceeded_error
)

# Step 3: Replace any usage of _is_serialization_conflict with is_serialization_error
# Example in retry.Retry configuration:
retry_config = retry.Retry(
    predicate=is_serialization_error,  # ← Changed from _is_serialization_conflict
    initial=1.0,
    maximum=60.0,
    multiplier=2.0,
    deadline=300.0
)
```

**Repeat for `nbac_gamebook_processor.py`**

**Testing:**
```bash
# Verify imports work
cd /home/naji/code/nba-stats-scraper
python3 -c "from data_processors.raw.processor_base import ProcessorBase; print('✓ Import successful')"

# Verify no references to old function remain
grep -r "_is_serialization_conflict" data_processors/
# Should return: No matches (or only in comments)
```

---

### Sub-Task 3.1.2: Replace Manual Retry in batch_writer.py

**File:** `data_processors/precompute/ml_feature_store/batch_writer.py`

**Current Pattern (MANUAL LOOP):**
```python
# Lines 32-34: Configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# Lines 306-343: Load retry loop
for attempt in range(self.MAX_RETRIES):
    try:
        load_job = self.bq_client.load_table_from_file(...)
        load_job.result(timeout=300)
        return True
    except Exception as e:
        if attempt < self.MAX_RETRIES - 1:
            logger.warning(f"Load attempt {attempt + 1} failed: {e}")
            time.sleep(self.RETRY_DELAY_SECONDS)  # ← Fixed delay, no backoff
        else:
            logger.error(f"Load failed after {self.MAX_RETRIES} attempts: {e}")
            raise
```

**Issues:**
- Fixed 5-second delay (no exponential backoff)
- No jitter (synchronized retries across multiple processors)
- Catches all exceptions (should use predicate for specific errors)

**New Pattern (WITH DECORATORS):**
```python
# Step 1: Add imports at top of file
from shared.utils.bigquery_retry import SERIALIZATION_RETRY, QUOTA_RETRY

# Step 2: REMOVE configuration constants (no longer needed)
# DELETE lines 32-34:
# MAX_RETRIES = 3
# RETRY_DELAY_SECONDS = 5

# Step 3: Replace load retry loop (lines 306-343)
@SERIALIZATION_RETRY
def _load_to_temp_table_with_retry(self, temp_table_id, rows, job_config):
    """Load rows to temp table with automatic serialization retry."""
    # Sanitize and convert to NDJSON (keep existing logic)
    sanitized_rows = self._sanitize_rows_for_json(rows)
    ndjson_data = '\n'.join([json.dumps(row) for row in sanitized_rows])
    ndjson_bytes = io.BytesIO(ndjson_data.encode('utf-8'))

    # Execute load (query submission INSIDE decorator)
    load_job = self.bq_client.load_table_from_file(
        ndjson_bytes,
        temp_table_id,
        job_config=job_config
    )
    return load_job.result(timeout=300)

# Step 4: Update caller to use new function
result = self._load_to_temp_table_with_retry(temp_table_id, rows, job_config)
```

**MERGE Retry (lines 417-441) - Use BOTH decorators:**
```python
@QUOTA_RETRY          # Outer: Handle quota exceeded (sustained load)
@SERIALIZATION_RETRY  # Inner: Handle concurrent updates (transient)
def _merge_to_target_with_retry(self, merge_query):
    """Execute MERGE with automatic retry on serialization and quota errors."""
    merge_job = self.bq_client.query(merge_query)  # ← Inside decorator
    result = merge_job.result(timeout=300)

    if merge_job.num_dml_affected_rows is not None:
        logger.info(f"MERGE affected {merge_job.num_dml_affected_rows} rows")

    return result

# Caller:
try:
    self._merge_to_target_with_retry(merge_query)
    return True
except Exception as e:
    error_msg = str(e).lower()
    # Streaming buffer errors are non-retriable - re-raise
    if "streaming buffer" in error_msg:
        logger.warning(
            f"⚠️ MERGE blocked by streaming buffer - {len(rows)} records skipped. "
            f"Will succeed on next run."
        )
        raise
    # All other errors already retried by decorators
    logger.error(f"MERGE failed after retries: {e}")
    raise
```

**Why Both Decorators:**
- ML Feature Store writes to shared tables from 30+ processors
- High concurrency → serialization conflicts (SERIALIZATION_RETRY handles)
- Many DML operations → quota exceeded (QUOTA_RETRY handles)

**Testing:**
```bash
# Verify decorator import
python3 -c "from data_processors.precompute.ml_feature_store.batch_writer import BatchWriter; print('✓ Import successful')"

# Verify no manual retry loops remain
grep -A 5 "for attempt in range" data_processors/precompute/ml_feature_store/batch_writer.py
# Should return: No matches
```

---

### Sub-Task 3.1.3: Apply Jitter to Other Data Processors

**Files Needing Jitter (18 files):**

**Category A: Raw Processors with BigQuery Writes**
1. `data_processors/raw/espn/espn_team_roster_processor.py`
2. `data_processors/raw/basketball_ref/br_roster_processor.py`
3. `data_processors/raw/oddsapi/odds_game_lines_processor.py`
4-18. Other raw processors (use grep to find)

**Pattern to Find:**
```bash
# Find processors with BigQuery writes but no retry decorator
cd /home/naji/code/nba-stats-scraper
grep -l "self.bq_client.query\|load_table_from" data_processors/ -r | \
  xargs grep -L "SERIALIZATION_RETRY\|@retry" | \
  head -15
```

**Implementation Pattern (for each file):**

```python
# 1. Add import
from shared.utils.bigquery_retry import SERIALIZATION_RETRY, QUOTA_RETRY

# 2. Wrap BigQuery write operations
@SERIALIZATION_RETRY
def execute_merge_with_retry(self):
    merge_job = self.bq_client.query(merge_query)  # ← Inside decorator
    return merge_job.result(timeout=120)

# 3. Call the wrapped function
result = execute_merge_with_retry()
```

**CRITICAL RULE:** Query submission (`self.bq_client.query()`) MUST be inside the decorator wrapper, not outside.

❌ **WRONG:**
```python
merge_job = self.bq_client.query(merge_query)  # ← Outside

@SERIALIZATION_RETRY
def execute():
    return merge_job.result()  # ← Only result is retried
```

✅ **CORRECT:**
```python
@SERIALIZATION_RETRY
def execute():
    merge_job = self.bq_client.query(merge_query)  # ← Inside
    return merge_job.result(timeout=120)
```

**Why:** If query submission is outside, all concurrent processors submit queries before any retry happens, causing serialization conflicts that can't be retried.

---

## ✅ Task 3.2: Complete Jitter Adoption in Orchestration

**Status:** ⚪ Not Started
**Effort:** 4 hours
**Files to Update:** ~5 files in `orchestration/`

### Context

Orchestration files make BigQuery queries for state management and need retry protection against serialization conflicts.

### Files to Update

1. `orchestration/cloud_functions/self_heal/main.py`
2. `orchestration/cloud_functions/mlb_self_heal/main.py`
3. `orchestration/cloud_functions/transition_monitor/main.py`
4. `orchestration/cloud_functions/grading/main.py`
5. `orchestration/workflow_executor.py` (HTTP retry - handled in Task 3.4)

### Implementation Pattern

**For BigQuery operations in cloud functions:**
```python
# Add import
from shared.utils.bigquery_retry import SERIALIZATION_RETRY

# Wrap state queries
@SERIALIZATION_RETRY
def query_completion_state(game_date):
    query = f"""
        SELECT * FROM firestore_exports.phase3_completion
        WHERE game_date = '{game_date}'
    """
    query_job = bq_client.query(query)
    return list(query_job.result())
```

**Note:** Firestore operations in orchestrators use transactions (already atomic). Don't add retry decorators to Firestore transaction functions.

---

## ✅ Task 3.3: Integrate BigQuery Connection Pooling

**Status:** ⚪ Not Started
**Effort:** 12 hours
**Files to Update:** ~30 files using `bigquery.Client()`

### Context

Currently every processor creates a new BigQuery client on initialization:
```python
self.bq_client = bigquery.Client(project='nba-props-platform')
```

This causes:
- Connection overhead (200-500ms per client creation)
- Resource exhaustion at scale (30+ concurrent processors)
- No connection reuse

### Find Files to Update

```bash
cd /home/naji/code/nba-stats-scraper

# Find all files creating BigQuery clients
grep -r "bigquery\.Client(" --include="*.py" | grep -v "test" | grep -v ".pyc"

# Expected: ~40 files across data_processors, orchestration, scrapers
```

### Implementation Pattern

**OLD PATTERN (NO POOLING):**
```python
from google.cloud import bigquery

class ProcessorBase:
    def init_clients(self):
        self.bq_client = bigquery.Client(project=self.project_id)  # ← New client every time
```

**NEW PATTERN (WITH POOLING):**
```python
from shared.clients.bigquery_pool import get_bigquery_client

class ProcessorBase:
    def init_clients(self):
        self.bq_client = get_bigquery_client(project_id=self.project_id)  # ← Cached client
```

**Migration Steps for Each File:**

1. **Replace import:**
   ```python
   # OLD
   from google.cloud import bigquery

   # NEW
   from shared.clients.bigquery_pool import get_bigquery_client
   ```

2. **Replace client instantiation:**
   ```python
   # OLD
   self.bq_client = bigquery.Client(project=project_id)

   # NEW
   self.bq_client = get_bigquery_client(project_id=project_id)
   ```

3. **No other changes needed** - Client API is identical

### Special Cases

**Location-Specific Clients:**
```python
# If you need specific location
self.bq_client = get_bigquery_client(
    project_id='nba-props-platform',
    location='US'  # Optional: defaults to None
)
```

**Important:** Use consistent location across all calls for same project to avoid creating multiple cache entries.

### High-Priority Files (Start Here)

1. `data_processors/raw/processor_base.py` - Base class for all raw processors
2. `data_processors/analytics/analytics_base.py` - Base class for analytics processors
3. `data_processors/precompute/precompute_base.py` - Base class for precompute processors
4. `orchestration/cloud_functions/*/main.py` - All cloud functions

**Impact:** Updating base classes cascades to all child processors automatically.

### Testing

```bash
# Verify pooling works
python3 << 'EOF'
from shared.clients.bigquery_pool import get_bigquery_client, get_client_count

# Get client twice for same project
client1 = get_bigquery_client('nba-props-platform')
client2 = get_bigquery_client('nba-props-platform')

# Should be same instance
assert client1 is client2, "Clients should be identical"
assert get_client_count() == 1, "Should only have 1 cached client"

print("✓ BigQuery pooling working correctly")
EOF
```

---

## ✅ Task 3.4: Integrate HTTP Connection Pooling

**Status:** ⚪ Not Started
**Effort:** 8 hours
**Files to Update:** ~20 files making HTTP requests

### Context

Currently HTTP requests use:
- Direct `requests.get()`/`requests.post()` calls (no pooling)
- New `requests.Session()` per request (no reuse)

This causes:
- Connection setup overhead (200ms per connection)
- No connection reuse for same host
- Manual retry configuration per file

### Find Files to Update

```bash
cd /home/naji/code/nba-stats-scraper

# Find files using requests without pooling
grep -r "requests\\.get\|requests\\.post\|requests\\.Session" --include="*.py" | \
  grep -v "test" | grep -v "http_pool.py"

# Expected: ~20 files in scrapers/, orchestration/, backfill_jobs/
```

### Implementation Pattern

**OLD PATTERN (NO POOLING):**
```python
import requests

response = requests.get(url, timeout=20)  # ← New connection every time
```

**NEW PATTERN (WITH POOLING):**
```python
from shared.clients.http_pool import get_http_session

session = get_http_session()
response = session.get(url)  # ← Reuses connections
```

**Or use convenience functions:**
```python
from shared.clients.http_pool import get, post

response = get(url)       # ← get_http_session().get(url)
response = post(url, json=data)  # ← get_http_session().post(url, json=data)
```

### High-Priority Files

**1. workflow_executor.py (Orchestration)**

Current pattern (lines 533-701):
```python
response = requests.post(
    url,
    json=parameters,
    timeout=self.SCRAPER_TIMEOUT  # 180 seconds
)
```

Replace with:
```python
from shared.clients.http_pool import get_http_session

session = get_http_session(timeout=self.SCRAPER_TIMEOUT)
response = session.post(url, json=parameters)
```

**Benefits:**
- Connection pooling across multiple scraper calls
- Built-in retry for 5xx errors (3 attempts, exponential backoff)
- Thread-safe per-thread sessions

**2. Scraper Files**

Find scrapers making HTTP calls:
```bash
grep -r "requests.get\|requests.post" scrapers/ backfill_jobs/ --include="*.py"
```

Replace pattern:
```python
# OLD
import requests
response = requests.get(f"https://api.balldontlie.io/v1/games/{game_id}")

# NEW
from shared.clients.http_pool import get
response = get(f"https://api.balldontlie.io/v1/games/{game_id}")
```

### Testing

```bash
# Verify HTTP pooling works
python3 << 'EOF'
from shared.clients.http_pool import get_http_session
import time

session = get_http_session()

# Make 3 requests to same host
start = time.time()
for i in range(3):
    response = session.get("https://httpbin.org/delay/0")
    print(f"Request {i+1}: {response.status_code}")
duration = time.time() - start

print(f"✓ 3 requests in {duration:.2f}s (pooling enabled)")
print(f"✓ Expected <2s with pooling, >6s without pooling")
EOF
```

---

## ✅ Task 3.5: Performance Testing & Validation

**Status:** ⚪ Not Started
**Effort:** 4 hours

### Baseline Metrics (Before Pooling)

**Run before applying Task 3.3 and 3.4:**

```bash
# Test 1: BigQuery client creation overhead
python3 << 'EOF'
from google.cloud import bigquery
import time

start = time.time()
for i in range(5):
    client = bigquery.Client(project='nba-props-platform')
duration = time.time() - start

print(f"5 client creations: {duration:.2f}s ({duration/5:.3f}s per client)")
# Expected: 1.0-2.5s total (200-500ms per client)
EOF

# Test 2: HTTP connection overhead
python3 << 'EOF'
import requests
import time

start = time.time()
for i in range(10):
    response = requests.get("https://httpbin.org/delay/0")
duration = time.time() - start

print(f"10 requests without pooling: {duration:.2f}s ({duration/10:.3f}s per request)")
# Expected: 2.0-3.0s total (200-300ms per request)
EOF
```

### Post-Pooling Metrics

**Run after applying Task 3.3 and 3.4:**

```bash
# Test 1: BigQuery client pooling
python3 << 'EOF'
from shared.clients.bigquery_pool import get_bigquery_client
import time

start = time.time()
for i in range(5):
    client = get_bigquery_client('nba-props-platform')
duration = time.time() - start

print(f"5 client retrievals: {duration:.2f}s ({duration/5:.6f}s per retrieval)")
# Expected: <0.01s total (<1ms per retrieval after first)
EOF

# Test 2: HTTP connection pooling
python3 << 'EOF'
from shared.clients.http_pool import get_http_session
import time

session = get_http_session()
start = time.time()
for i in range(10):
    response = session.get("https://httpbin.org/delay/0")
duration = time.time() - start

print(f"10 requests with pooling: {duration:.2f}s ({duration/10:.3f}s per request)")
# Expected: 0.5-1.0s total (50-100ms per request)
EOF
```

### Success Criteria

| Metric | Baseline | Target | Pass? |
|--------|----------|--------|-------|
| BigQuery client creation | 200-500ms | <1ms (cached) | ✅ >200x faster |
| HTTP request latency | 200-300ms | 50-100ms | ✅ 4x faster |
| Connection reuse rate | 0% | >90% | ✅ Check logs |
| Retry success rate | 70% | >95% | ✅ Monitor for 1 week |

### Integration Testing

**Test retry jitter prevents thundering herd:**

```bash
# Simulate 10 concurrent processors hitting serialization conflicts
python3 << 'EOF'
from shared.utils.bigquery_retry import SERIALIZATION_RETRY
from google.api_core import exceptions
import time
import random
from concurrent.futures import ThreadPoolExecutor

attempt_times = []

@SERIALIZATION_RETRY
def simulate_processor(processor_id):
    """Simulate processor with occasional serialization conflicts."""
    global attempt_times

    # 50% chance of serialization conflict on first try
    if random.random() < 0.5:
        attempt_times.append((processor_id, time.time()))
        raise exceptions.BadRequest("Could not serialize access to table due to concurrent update")

    return f"Processor {processor_id} succeeded"

# Run 10 processors concurrently
with ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(simulate_processor, range(10)))

print(f"✓ All processors completed")
print(f"✓ Retry attempts: {len(attempt_times)}")

# Check retry timing has jitter (not synchronized)
if len(attempt_times) >= 2:
    times = sorted([t for _, t in attempt_times])
    gaps = [times[i+1] - times[i] for i in range(len(times)-1)]
    print(f"✓ Retry gaps (should vary): {[f'{g:.3f}s' for g in gaps]}")
EOF
```

**Expected:** Retry gaps should vary (1.2s, 0.8s, 1.5s, etc.) indicating jitter working.

---

## 📊 Progress Tracking

Use `JITTER-ADOPTION-TRACKING.md` to track file-by-file progress.

### Phase 3 Checklist

- [ ] Task 3.1.1: Remove duplicate serialization logic (2 files)
- [ ] Task 3.1.2: Replace batch_writer manual retry (1 file)
- [ ] Task 3.1.3: Apply jitter to data processors (18 files)
- [ ] Task 3.2: Apply jitter to orchestration (5 files)
- [ ] Task 3.3: Integrate BigQuery pooling (30 files)
- [ ] Task 3.4: Integrate HTTP pooling (20 files)
- [ ] Task 3.5: Performance testing and validation

**Total Files:** ~76 files to update

---

## 🚨 Common Pitfalls & Solutions

### Pitfall 1: Query Submission Outside Decorator

**Problem:**
```python
merge_job = self.bq_client.query(merge_query)  # ← Outside

@SERIALIZATION_RETRY
def execute():
    return merge_job.result()  # ← Only result is retried
```

**Solution:** Move query submission inside decorator.

---

### Pitfall 2: Stacking Decorators in Wrong Order

**Problem:**
```python
@SERIALIZATION_RETRY  # ← Wrong: inner retry exhausted first
@QUOTA_RETRY
def execute():
    ...
```

**Solution:** QUOTA_RETRY (outer) → SERIALIZATION_RETRY (inner)

---

### Pitfall 3: Using Different Locations for Same Project

**Problem:**
```python
client1 = get_bigquery_client('proj', location='US')
client2 = get_bigquery_client('proj')  # ← Different cache key
```

**Solution:** Standardize on one location per project or explicitly specify every time.

---

### Pitfall 4: Forgetting to Import from Pooling Module

**Problem:**
```python
from google.cloud import bigquery  # ← Still using old import
self.bq_client = bigquery.Client()  # ← No pooling
```

**Solution:** Always use `from shared.clients.bigquery_pool import get_bigquery_client`

---

## 📝 Documentation Updates

After completing Phase 3, update:

1. **IMPLEMENTATION-TRACKING.md** - Mark Phase 3 tasks complete
2. **STATUS-DASHBOARD.md** - Update reliability metrics
3. **README.md** - Update project progress (10/28 → 15/28)
4. **Create SESSION-119-PHASE3-COMPLETE.md** - Handoff document

---

## ✅ Definition of Done

Phase 3 is complete when:

- [ ] All 76 files updated with retry jitter or connection pooling
- [ ] All tests pass (unit + integration)
- [ ] Performance metrics show >200x BigQuery speedup, >4x HTTP speedup
- [ ] No `bigquery.Client()` or `requests.get()` direct calls remain
- [ ] Documentation updated (4 docs)
- [ ] Deployed to staging and validated
- [ ] Deployed to production with monitoring
- [ ] 1 week of production monitoring shows:
  - Zero "too many connections" errors
  - Retry success rate >95%
  - No performance regressions

---

**Last Updated:** January 19, 2026
**Created By:** Session 119
**For:** Phase 3 Implementation Team
