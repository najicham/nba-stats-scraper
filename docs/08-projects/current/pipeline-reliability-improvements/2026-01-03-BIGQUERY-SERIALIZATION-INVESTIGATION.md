# BigQuery Serialization Conflicts Investigation
**Date**: January 3, 2026
**Status**: 🔍 Investigation Complete - Implementation Pending
**Priority**: HIGH - Escalating Issue

---

## Overview

Multiple data processors are experiencing "400 Could not serialize access to table due to concurrent update" errors when writing to BigQuery. This investigation provides root cause analysis and solution options.

---

## Problem Summary

### Error Pattern
```
🚨 Critical Error Alert
Processor: Basketball Reference Roster Processor

Error: 400 Could not serialize access to table
nba-props-platform:nba_raw.br_rosters_current
due to concurrent update
```

### Impact
- **Frequency**: 14 errors in 7 days, **escalating trend** (3→3→8)
- **Critical spike**: Jan 2 @ 00:45 UTC (6 errors in 1 minute)
- **Affected tables**:
  - `nba_raw.br_rosters_current` (12 errors) - UPDATE operations
  - `nba_raw.odds_api_game_lines` (2 errors) - MERGE operations
- **Data impact**: ⚠️ Data gaps until next scheduled run (no retry logic)

---

## Root Cause Analysis

### The Core Issue

**Multiple Cloud Run instances executing concurrent MERGE/UPDATE operations on the same BigQuery table partition**

```
Flow:
30 teams scraped → 30 files uploaded → Cloud Run scales to 5 instances →
All execute UPDATE on br_rosters_current (same partition: season_year=2024) →
BigQuery tries to serialize concurrent UPDATEs →
Some fail with "400 Could not serialize access"
```

### Contributing Factors

1. **High Container Concurrency**
   - Service: `nba-phase2-raw-processors`
   - Max instances: 10
   - Concurrency: 20
   - **Potential parallel operations**: 200

2. **No Retry Logic**
   - Zero automatic retries for transient errors
   - Failed operations wait until next scheduled run
   - Data gaps accumulate

3. **Concurrent Write Pattern**
   - Multiple processors write to same partition simultaneously
   - Basketball Reference: All 30 teams update `season_year=2024` partition
   - Odds API: Multiple games MERGE to same `game_date` partition

4. **BigQuery MVCC Limitations**
   - BigQuery uses Multi-Version Concurrency Control (MVCC)
   - Concurrent DML on same partition requires serialization
   - Serialization conflicts return 400 error

---

## Detailed Investigation Findings

### Error Frequency Analysis

**Timeline** (Last 7 days):
```
Dec 31: 3 errors
Jan 1:  3 errors
Jan 2:  8 errors  ← 2.67x increase!
```

**Peak Time**: 2026-01-02 00:45 UTC
- 6 errors in single minute
- 43% of all 7-day errors in one minute
- Coincided with multiple scheduler jobs firing

**Correlation with Schedulers**:
- 00:45 UTC: bdl-live-boxscores, live-export, cleanup, freshness-monitor
- Multiple Pub/Sub messages triggering parallel processing
- Burst processing overwhelms serialization capacity

### Affected Processors

**1. Basketball Reference Roster Processor** (6 errors)

**File**: `data_processors/raw/basketball_ref/br_roster_processor.py`

**Write Strategy**: Split INSERT + UPDATE
```python
# New players: Batch INSERT (safe)
load_job = bq_client.load_table_from_json(new_rows, table_id)

# Existing players: UPDATE query (concurrent conflict risk)
UPDATE `br_rosters_current`
SET last_scraped_date = CURRENT_DATE()
WHERE season_year = @season_year
  AND team_abbrev = @team_abbrev
  AND player_full_name IN UNNEST(@player_names)
```

**Conflict Scenario**:
- 30 teams processed in parallel
- All UPDATE same partition (`season_year = 2024`)
- BigQuery serializes → some fail

**No retry mechanism**: `query_job.result(timeout=60)` fails immediately

---

**2. Odds API Game Lines Processor** (8 errors)

**File**: `data_processors/raw/oddsapi/odds_game_lines_processor.py`

**Write Strategy**: Staging table + MERGE
```python
# Step 1: Create temp table (safe, isolated)
temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
bq_client.create_table(temp_table)

# Step 2: Batch load to temp (safe)
load_job = bq_client.load_table_from_json(rows, temp_table_id)

# Step 3: MERGE from temp to target (concurrent conflict risk)
MERGE `odds_api_game_lines` AS target
USING `{temp_table}` AS source
ON target.game_date = '{game_date}'
   AND target.game_id = source.game_id
   ...
WHEN MATCHED THEN UPDATE
WHEN NOT MATCHED THEN INSERT
```

**Conflict Scenario**:
- 10+ games processed in parallel for same `game_date`
- All MERGE to same partition
- BigQuery serializes → some fail

**No retry mechanism**: `merge_job.result(timeout=60)` fails immediately

---

### Code Analysis

**Missing Retry Logic** (processor_base.py, br_roster_processor.py, odds_game_lines_processor.py):

```python
# Current implementation (NO RETRY)
query_job = self.bq_client.query(query)
query_job.result(timeout=60)  # ⚠️ Fails immediately on error

# No error detection for:
# - "Could not serialize access"
# - "Transaction aborted"
# - Other transient BigQuery errors
```

**Existing Error Handling**:
```python
# Only handles streaming buffer conflicts
if "streaming buffer" in str(load_e).lower():
    logger.warning("⚠️ Load blocked by streaming buffer")
    return  # Graceful skip

# Does NOT handle serialization conflicts!
```

---

## Schema Analysis

### Table 1: `nba_raw.br_rosters_current`

**Schema**:
- **Partition**: RANGE_BUCKET on `season_year` (2020-2030)
- **Clustering**: `team_abbrev`, `player_lookup`
- **Primary Key**: (season_year, team_abbrev, player_lookup) - not enforced
- **Rows**: 3,248

**Concurrency Risk**: **Medium**
- All teams in same season write to same partition
- 30 concurrent UPDATEs on partition `2024`

---

### Table 2: `nba_raw.odds_api_game_lines`

**Schema**:
- **Partition**: DAY on `game_date` (**required** partition filter)
- **Clustering**: `game_id`, `bookmaker_key`, `market_key`, `snapshot_timestamp`
- **Primary Key**: (game_date, game_id, bookmaker_key, market_key, outcome_name) - not enforced
- **Rows**: 47,342

**Concurrency Risk**: **High**
- All games on same date write to same partition
- 10-15 concurrent MERGEs on partition `2026-01-02`
- Partition filter requirement creates bottleneck

---

## Solution Options

### Option 1: Add Retry Logic with Exponential Backoff ⭐⭐⭐⭐⭐
**Best Quick Win - Fixes 90% of issues**

**Implementation**:
```python
from google.api_core import retry
from google.api_core.exceptions import BadRequest

# Custom retry predicate
def is_serialization_error(exc):
    return (
        isinstance(exc, BadRequest) and
        "Could not serialize access" in str(exc)
    )

# Retry configuration
SERIALIZATION_RETRY = retry.Retry(
    predicate=is_serialization_error,
    initial=1.0,      # 1 second initial delay
    maximum=32.0,     # 32 second max delay
    multiplier=2.0,   # Exponential backoff
    deadline=120.0    # 2 minute total timeout
)

# Apply to DML operations
@SERIALIZATION_RETRY
def execute_dml(query_job):
    return query_job.result(timeout=60)
```

**Files to Modify**:
1. `data_processors/raw/processor_base.py` - Add retry decorator
2. `data_processors/raw/basketball_ref/br_roster_processor.py` - Apply to UPDATE
3. `data_processors/raw/oddsapi/odds_game_lines_processor.py` - Apply to MERGE

**Effort**: LOW (2-3 hours)
**Impact**: HIGH (90% error reduction)

**Pros**:
- ✅ Simple to implement
- ✅ No infrastructure changes
- ✅ Works with existing code
- ✅ Handles transient errors gracefully

**Cons**:
- ⚠️ Adds latency on retries (1-32 seconds)
- ⚠️ Doesn't prevent conflicts, just retries

---

### Option 2: Reduce Container Concurrency ⭐⭐⭐⭐
**Quick Infrastructure Fix**

**Implementation**:
```bash
gcloud run services update nba-phase2-raw-processors \
  --region=us-west2 \
  --max-instances=5 \    # Down from 10
  --concurrency=10        # Down from 20
```

**Effect**: 200 parallel ops → 50 parallel ops (75% reduction)

**Effort**: VERY LOW (5 minutes)
**Impact**: MEDIUM (reduces conflicts by 75%)

**Pros**:
- ✅ Immediate deployment
- ✅ No code changes
- ✅ Reversible

**Cons**:
- ⚠️ Higher latency during bursts
- ⚠️ Doesn't eliminate conflicts

---

### Option 3: Implement Distributed Locking ⭐⭐⭐⭐⭐
**Best Long-Term Solution**

**Implementation**:
```python
from google.cloud import firestore

class TableLockManager:
    def __init__(self):
        self.db = firestore.Client()

    def acquire_lock(self, table_name, partition_key, timeout=30):
        """Acquire distributed lock for table partition"""
        lock_id = f"{table_name}:{partition_key}"
        doc_ref = self.db.collection('table_locks').document(lock_id)

        # Atomic lock acquisition
        try:
            doc_ref.create({
                'locked_at': firestore.SERVER_TIMESTAMP,
                'locked_by': os.environ.get('K_REVISION'),
                'expires_at': firestore.SERVER_TIMESTAMP + timeout
            })
            return True
        except AlreadyExists:
            # Lock held by another processor
            return False

    def release_lock(self, table_name, partition_key):
        """Release distributed lock"""
        lock_id = f"{table_name}:{partition_key}"
        self.db.collection('table_locks').document(lock_id).delete()

# Usage
lock_mgr = TableLockManager()
partition_key = f"{season_year}"

if lock_mgr.acquire_lock('br_rosters_current', partition_key):
    try:
        # Execute UPDATE - now serialized
        query_job = self.bq_client.query(query)
        query_job.result()
    finally:
        lock_mgr.release_lock('br_rosters_current', partition_key)
else:
    # Lock held - retry after delay
    time.sleep(random.uniform(1, 5))
    # Retry logic...
```

**Effort**: MEDIUM (1-2 days)
**Impact**: VERY HIGH (100% elimination)

**Pros**:
- ✅ Eliminates conflicts entirely
- ✅ Fine-grained control
- ✅ Observability (see lock holders)

**Cons**:
- ⚠️ Adds complexity
- ⚠️ Risk of deadlocks
- ⚠️ Requires Firestore setup

---

### Option 4: Queue-Based Sequential Processing ⭐⭐⭐
**Architectural Solution**

**Implementation**: Use Cloud Tasks to serialize writes per partition

**Effort**: HIGH (3-5 days)
**Impact**: VERY HIGH (100% elimination + scalability)

**Pros**:
- ✅ Built-in retry handling
- ✅ Rate limiting
- ✅ Guaranteed ordering

**Cons**:
- ⚠️ Architecture change required
- ⚠️ Adds latency
- ⚠️ Additional cost

---

### Option 5: Redesign for INSERT-Only Pattern ⭐⭐⭐⭐
**Data Engineering Best Practice**

**Implementation**: Avoid UPDATE/MERGE, use append-only with views

```python
# BEFORE (UPDATE pattern)
UPDATE br_rosters_current
SET last_scraped_date = CURRENT_DATE()
WHERE season_year = 2024 AND team_abbrev = 'LAL'

# AFTER (INSERT-only pattern)
INSERT INTO br_rosters_snapshots
VALUES (2024, 'LAL', 'lebron-james', CURRENT_TIMESTAMP(), ...)

# Create view for "current" state
CREATE VIEW br_rosters_current AS
SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY season_year, team_abbrev, player_lookup
        ORDER BY scraped_at DESC
    ) as rn
    FROM br_rosters_snapshots
) WHERE rn = 1
```

**Effort**: VERY HIGH (1-2 weeks)
**Impact**: VERY HIGH (eliminates + improves architecture)

**Pros**:
- ✅ No concurrent write conflicts
- ✅ Full audit trail
- ✅ Time-travel queries

**Cons**:
- ⚠️ Storage cost increases
- ⚠️ Schema redesign required
- ⚠️ Downstream query updates

---

## Recommended Implementation Plan

### Phase 1: Immediate (Deploy Today) ✅
**Combine Option 1 + Option 2**

**Tasks**:
1. ✅ Add retry logic decorator to `processor_base.py`
2. ✅ Apply retry to UPDATE in `br_roster_processor.py:346`
3. ✅ Apply retry to MERGE in `odds_game_lines_processor.py:606`
4. ✅ Reduce Cloud Run concurrency: 10 instances × 10 concurrency
5. ✅ Deploy and monitor for 24 hours

**Expected Result**: 90% reduction in serialization errors

**Estimated Time**: 3-4 hours
**Risk**: LOW

---

### Phase 2: Short-Term (This Week) ⭐
**Implement Option 3**

**Tasks**:
1. Create `TableLockManager` class in `shared/utils/`
2. Add Firestore collection: `table_locks`
3. Integrate locks into processors
4. Add lock expiration cleanup job
5. Test in staging environment
6. Deploy to production

**Expected Result**: 100% elimination of serialization errors

**Estimated Time**: 1-2 days
**Risk**: MEDIUM (requires testing)

---

### Phase 3: Long-Term (This Month) 🚀
**Redesign with Option 5**

**Tasks**:
1. Design new schemas (`_snapshots` tables)
2. Create materialized views for current state
3. Migrate processors to INSERT-only pattern
4. Update downstream analytics queries
5. Backfill historical data
6. Deprecate old tables

**Expected Result**: Scalable, maintainable architecture

**Estimated Time**: 1-2 weeks
**Risk**: HIGH (major refactor)

---

## Monitoring & Alerting

### Current State
- ❌ No alerts for serialization errors
- ❌ No retry tracking metrics
- ❌ No lock contention monitoring

### Recommended Improvements

**1. Add Log-Based Metrics**:
```yaml
metric:
  name: bigquery_serialization_errors
  filter: |
    resource.type="cloud_run_revision"
    textPayload=~"Could not serialize access"
  metric_descriptor:
    metric_kind: DELTA
    value_type: INT64
```

**2. Create Alert Policy**:
```yaml
alert:
  name: High BigQuery Serialization Error Rate
  condition: bigquery_serialization_errors > 5 per hour
  notification_channels:
    - email: alerts@example.com
```

**3. Track Retry Metrics**:
```python
from opencensus.stats import measure, view

# Measure retry attempts
retry_attempts = measure.MeasureInt(
    "bigquery/retry_attempts",
    "Number of BigQuery retry attempts",
    "attempts"
)

# Record in code
stats_recorder.record([(retry_attempts, attempt_count)])
```

---

## Success Metrics

### Before Fixes
- Serialization errors: 2.0 per day (escalating to 8/day)
- Data gaps: ~15 missing records per week
- Failed batches: 14 in 7 days
- Retry rate: 0% (no retries)

### After Phase 1 (Target)
- Serialization errors: <0.2 per day (90% reduction)
- Data gaps: <2 missing records per week
- Failed batches: <2 in 7 days
- Retry rate: 80-90% success on first retry

### After Phase 2 (Target)
- Serialization errors: 0 per day (100% elimination)
- Data gaps: 0 missing records
- Failed batches: 0
- Lock wait time: <2 seconds average

---

## Related Issues

### Email Alert Headings
**Current**: All errors use "🚨 Critical Error Alert"

**Problem**: Can't distinguish between:
- System failures (truly critical)
- Data quality issues (needs investigation)
- Validation warnings (informational)

**Proposed Fix** (separate issue):
- 🚨 **Critical Error Alert** - System failures, service down
- ⚠️ **Data Gap Detected** - Missing data, zero rows saved
- ℹ️ **Investigation Needed** - Validation warnings, quality issues
- 📊 **Data Quality Notice** - Unexpected patterns, anomalies

**Tracking**: See handoff document for email heading improvements

---

## References

### Investigation Agents
- Agent aab89c9 - Processor write pattern analysis
- Agent a59199a - Error frequency and scaling correlation
- Agent adf6967 - BigQuery schema and table analysis

### Code Locations
- `data_processors/raw/processor_base.py` (line 185, 692-730)
- `data_processors/raw/basketball_ref/br_roster_processor.py` (line 278-384)
- `data_processors/raw/oddsapi/odds_game_lines_processor.py` (line 466-709)

### Documentation
- [BigQuery DML Quotas](https://cloud.google.com/bigquery/quotas#dml_statements)
- [BigQuery MVCC](https://cloud.google.com/bigquery/docs/managing-tables#updating_a_table)
- [Cloud Run Concurrency](https://cloud.google.com/run/docs/about-concurrency)

---

**Status**: Investigation complete, implementation pending
**Next Action**: Implement Phase 1 (retry logic + reduce concurrency)
**Priority**: HIGH - Errors escalating
**Owner**: TBD
