# External Review Request: Monitoring Data Storage Architecture

**Date**: 2026-01-26
**Request**: Need expert opinion on storage architecture decision
**Context**: Production pipeline blocked by BigQuery quota limits
**Decision Urgency**: High (pipeline currently down)

---

## Background

We operate an NBA stats prediction pipeline that:
- Scrapes data from multiple sources (NBA.com, betting sites)
- Processes through 5 phases (raw → analytics → precompute → ML features → predictions)
- Generates player prop predictions for ~7 games/day
- Runs on Google Cloud (Cloud Run, BigQuery, Firestore, GCS)

The pipeline has been blocked today due to BigQuery quota limits on monitoring tables.

---

## The Problem

### What Happened

BigQuery has a **hard limit of 1,500 load jobs per table per day**. This limit:
- Cannot be increased (Google confirms this is non-negotiable)
- Is not visible in the Cloud Console quotas page
- Resets at midnight Pacific Time

Our monitoring tables exceeded this quota:

| Table | Purpose | Writes/Day | % of Quota |
|-------|---------|-----------|------------|
| `processor_run_history` | Audit trail of every processor execution | 1,321 | 88% |
| `circuit_breaker_state` | Tracks failure states to prevent retry storms | 575 | 38% |
| `analytics_processor_runs` | Tracks Phase 3 completion for orchestration | 570 | 38% |
| **TOTAL** | | **2,466** | **164%** |

### The Code Pattern That Caused It

Each write created an individual BigQuery load job:

```python
# This was called ~2,466 times per day
def log_to_bigquery(record):
    load_job = bq_client.load_table_from_json(
        [record],  # Single record = 1 load job
        table_id,
        job_config
    )
    load_job.result()
```

### Why We Use Load Jobs (Not Streaming Inserts)

BigQuery offers two write methods:

**Streaming Inserts** (`insert_rows_json`):
- No quota limit on count
- BUT: 90-minute buffer before data available for DML
- We can't use MERGE, UPDATE, DELETE for 90 minutes
- We need these operations for deduplication and corrections

**Load Jobs** (`load_table_from_json`):
- Data immediately available for DML
- BUT: 1,500/day quota per table
- This is what we chose, and why we hit the quota

### Impact

When quota exceeded:
1. All writes to monitoring tables fail with HTTP 403
2. Processors can't log completion status
3. Phase 3-5 blocked (can't write results)
4. No predictions generated
5. Pipeline effectively dead until quota resets at midnight PT

---

## Current State

### Fix Already Implemented (Not Deployed)

A batching solution has been coded and committed locally but not pushed to production:

**Before batching**: 1 record = 1 load job
**After batching**: 100 records = 1 load job

| Table | Before | After | Reduction |
|-------|--------|-------|-----------|
| processor_run_history | 1,321 jobs/day | 14 jobs/day | 94x |
| circuit_breaker_state | 575 jobs/day | 12 jobs/day | 48x |
| analytics_processor_runs | 570 jobs/day | 6 jobs/day | 95x |
| **TOTAL** | 2,466 jobs/day | 32 jobs/day | **77x** |

**Quota usage after batching**: 2% (32/1,500)
**Headroom**: 98% (can handle 47x traffic growth)

### What Each Table Stores

**1. processor_run_history** (1,321 writes/day)
```json
{
  "run_id": "uuid",
  "processor_name": "PlayerGameSummaryProcessor",
  "status": "success|failed|skipped",
  "started_at": "2026-01-26T15:00:00Z",
  "completed_at": "2026-01-26T15:00:45Z",
  "duration_seconds": 45.2,
  "records_processed": 150,
  "error_message": null,
  "game_date": "2026-01-26",
  "trigger": "scheduled|manual|retry"
}
```
**Used for**: Debugging failures, detecting duplicates, monitoring health, alerting

**2. circuit_breaker_state** (575 writes/day)
```json
{
  "processor_name": "PlayerGameSummaryProcessor",
  "circuit_key": "phase3_player_game_summary",
  "state": "closed|open|half_open",
  "failure_count": 0,
  "success_count": 47,
  "last_failure_at": null,
  "last_success_at": "2026-01-26T15:00:45Z",
  "updated_at": "2026-01-26T15:00:45Z"
}
```
**Used for**: Preventing retry storms (circuit opens after 5 consecutive failures)

**3. analytics_processor_runs** (570 writes/day)
```json
{
  "processor_type": "PlayerGameSummaryProcessor",
  "game_date": "2026-01-26",
  "status": "completed",
  "records_processed": 150,
  "quality_score": 0.95,
  "started_at": "2026-01-26T15:00:00Z",
  "completed_at": "2026-01-26T15:00:45Z"
}
```
**Used for**: Tracking Phase 3 completion, triggering Phase 4, monitoring data quality

---

## Options Under Consideration

### Option A: Keep BigQuery with Batching

**Description**: Deploy the batching fix, keep all data in BigQuery.

**Implementation**: Already coded, just needs `git push` and Cloud Run rebuild.

**Metrics After Implementation**:
- Quota usage: 2% (32/1,500 jobs)
- Headroom: 98%
- Growth capacity: 47x before hitting quota again

**Pros**:
- Zero migration effort (already implemented)
- All data in one place (easy joins, familiar SQL)
- No new infrastructure
- No additional cost
- Team already knows BigQuery
- No risk of migration bugs

**Cons**:
- Still have 1,500/day hard limit (but 98% headroom)
- Batching adds 30-second latency for low-traffic writes
- Not the "optimal" tool for high-frequency small writes
- Circuit breaker reads query BigQuery (slower than alternatives)

**Cost**: $0 additional

---

### Option B: Migrate to Firestore + Cloud Logging

**Description**: Move monitoring data to more appropriate systems.

**Architecture**:
```
processor_run_history    → Cloud Logging (structured logs)
circuit_breaker_state    → Firestore (real-time document store)
analytics_processor_runs → Cloud Logging (structured logs)
```

**Rationale**:
- Cloud Logging: Designed for high-frequency event logs, no write quotas
- Firestore: Designed for real-time state, fast reads (<10ms vs BigQuery's 500ms+)

**Pros**:
- No write quotas (effectively unlimited)
- "Right tool for each job" architecture
- Circuit breaker reads 50x faster (Firestore <10ms vs BigQuery 500ms+)
- Cloud Logging free up to 50GB/month
- Already have Firestore (used for `phase3_completion`)

**Cons**:
- Significant migration effort (2-3 weeks)
- Team needs to learn new query patterns
- Cloud Logging queries are NOT SQL
- Can't easily join with BigQuery analytics data
- Firestore costs ~$60/month for our write volume
- More operational complexity (3 systems vs 1)
- Need to export to BigQuery anyway for dashboards
- Migration risk (new code, potential bugs)

**Cost**: ~$60-80/month additional

---

### Option C: Partial Migration (Circuit Breaker Only)

**Description**: Move only circuit_breaker_state to Firestore, keep others in BigQuery with batching.

**Rationale**: Circuit breaker is the only table where BigQuery is arguably wrong:
- It's real-time state that's read on every processor run
- Needs fast reads (currently 500ms+ from BigQuery)
- Firestore reads are <10ms
- Already have Firestore infrastructure

**Pros**:
- 50x faster circuit breaker checks
- Firestore is natural fit for state data
- Minimal migration (1 table, 1 week)
- Other tables stay in BigQuery (simpler)

**Cons**:
- Still some migration effort
- Firestore cost: ~$30/month
- State data now in different system
- Need to update dashboards/queries

**Cost**: ~$30/month additional

---

### Option D: Daily Table Rotation

**Description**: Create new table each day with fresh quota.

**Architecture**:
```
processor_run_history_20260126
processor_run_history_20260127
...
```

**Pros**:
- Each day has fresh 1,500 quota
- Simple to implement
- Easy to delete old data (drop table)

**Cons**:
- Wildcard queries are slower
- Table management overhead
- Need cleanup job for old tables
- Batching achieves same goal more simply

**Cost**: $0 additional

---

## Key Technical Details

### BigQuery Load Job Quota

From Google's documentation:
- **Limit**: 1,500 load jobs per table per day
- **Scope**: Per table, not per project
- **Increasable**: NO (hard limit)
- **Reset**: Midnight Pacific Time
- **Workaround**: Batch multiple records into single load job

### Why Not Just Use Streaming Inserts?

Streaming inserts (`insert_rows_json`) have no count quota, but:
1. **90-minute buffer**: Data not available for DML for 90 minutes
2. **We need DML**: MERGE for deduplication, UPDATE for corrections, DELETE for cleanup
3. **Cost**: $0.01 per 200MB (load jobs are free)

We chose load jobs because we need immediate DML access. This is documented in our BigQuery best practices guide.

### Current Query Patterns

**processor_run_history**:
```sql
-- Debug: Find failed runs
SELECT * FROM processor_run_history
WHERE status = 'failed' AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)

-- Detect duplicates
SELECT processor_name, game_date, COUNT(*)
FROM processor_run_history
WHERE status = 'running'
GROUP BY 1, 2 HAVING COUNT(*) > 1
```

**circuit_breaker_state**:
```sql
-- Check if circuit is open
SELECT state, failure_count
FROM circuit_breaker_state
WHERE circuit_key = 'phase3_player_game_summary'
ORDER BY updated_at DESC LIMIT 1
```

**analytics_processor_runs**:
```sql
-- Check Phase 3 completion
SELECT processor_type, status
FROM analytics_processor_runs
WHERE game_date = CURRENT_DATE()
```

### Infrastructure We Already Have

- **BigQuery**: Primary data warehouse, all analytics data
- **Firestore**: Used for `phase3_completion` status (real-time)
- **Cloud Logging**: Auto-captures Cloud Run stdout/stderr
- **Cloud Run**: Serverless compute for all processors

---

## Cost Comparison

| Option | Monthly Cost | Migration Effort | Operational Complexity |
|--------|--------------|------------------|------------------------|
| A: BigQuery + Batching | $14 (current) | None | Low |
| B: Full Migration | $80-100 | 2-3 weeks | High |
| C: Partial (CB only) | $44 | 1 week | Medium |
| D: Table Rotation | $14 | Few days | Medium |

---

## Risk Assessment

### Option A Risks (Batching)
- **Traffic spike**: If traffic grows 50x, we hit quota again
- **Mitigation**: Monitoring alerts at 80%, can increase batch size
- **Residual risk**: Low (47x headroom)

### Option B Risks (Full Migration)
- **Migration bugs**: New code, new systems, potential failures
- **Query migration**: Team needs to learn new query patterns
- **Operational complexity**: 3 systems instead of 1
- **Residual risk**: Medium

### Option C Risks (Partial Migration)
- **Migration scope creep**: "Let's migrate the others too"
- **Split architecture**: Some data here, some there
- **Residual risk**: Low-Medium

### Option D Risks (Rotation)
- **Query complexity**: Wildcard queries across tables
- **Cleanup failures**: Old tables not deleted
- **Residual risk**: Low

---

## Questions for the Reviewer

1. **Is 98% quota headroom (47x growth capacity) sufficient?**
   - Our traffic has been stable for 6 months
   - No expected 50x traffic spikes
   - We would add monitoring to catch issues at 80%

2. **Is circuit breaker read latency actually a problem?**
   - Current: ~500ms (BigQuery query)
   - With Firestore: ~10ms
   - But: No one has complained about processor speed
   - Is the $30/month + 1 week effort worth 490ms savings?

3. **Is "right tool for each job" worth the complexity?**
   - Philosophically, Firestore is better for state, Cloud Logging for events
   - Practically, BigQuery with batching works fine
   - Is architectural purity worth $60/month + 3 weeks + ongoing complexity?

4. **What would you recommend and why?**
   - Please consider: immediate needs, long-term maintainability, cost, risk
   - We're a small team and value simplicity

---

## Our Current Thinking

We're leaning toward **Option A (Batching only)** because:
1. It's already implemented
2. 98% headroom seems sufficient
3. No migration risk
4. No additional cost
5. Simpler architecture

But we want external validation before committing, especially regarding:
- Are we missing something about BigQuery's limitations?
- Is there a better architecture we haven't considered?
- Should we be more concerned about the 1,500/day limit?

---

## Request

Please review this document and provide:

1. **Your recommendation** (A, B, C, D, or something else)
2. **Your reasoning** (what factors influenced your decision)
3. **Any concerns** with our current thinking
4. **Any options we haven't considered**
5. **What you would do differently** if you were in our position

We need to make a decision today as the pipeline is currently down.

---

## Appendix: File Locations

For reference, relevant code is at:

```
# Batching implementation (ready to deploy)
shared/utils/bigquery_batch_writer.py

# Tables that need batching
shared/processors/mixins/run_history_mixin.py
shared/processors/patterns/circuit_breaker_mixin.py
data_processors/analytics/analytics_base.py

# Monitoring
monitoring/bigquery_quota_monitor.py

# Documentation
docs/technical/BIGQUERY-QUOTA-ISSUE-COMPLETE-ANALYSIS.md
```

---

## Appendix: Traffic Patterns

**Daily processor runs**:
- Phase 2 (Raw scrapers): ~150 runs
- Phase 3 (Analytics): ~250 runs
- Phase 4 (Precompute): ~100 runs
- Reference processors: ~50 runs
- Backfills: ~50 runs
- **Total**: ~600 runs/day

**Why 2,466 writes instead of 600?**
- Each run writes 2 records (start + complete)
- Circuit breaker writes on every state change
- Retries multiply the count
- 600 × 2 + circuit breaker + retries = ~2,466

**Traffic growth expectations**:
- Current: ~600 processor runs/day
- 6 months ago: ~400 processor runs/day
- Growth rate: ~50% over 6 months
- At this rate: ~900 runs/day in 6 months
- Still well within 47x headroom

---

**End of Review Request**
