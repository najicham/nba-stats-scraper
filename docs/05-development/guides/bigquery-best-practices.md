# BigQuery Best Practices - NBA Platform

**Created:** 2025-11-21 18:30:00 PST
**Last Updated:** 2025-11-21 18:30:00 PST

Critical BigQuery patterns and anti-patterns learned from building the NBA props platform.

---

## Overview

This guide documents hard-won lessons about BigQuery integration, focusing on schema enforcement, streaming buffer limitations, and production-safe loading patterns.

**Key topics:**
- Schema enforcement to prevent field mode mismatches
- Streaming buffer limitations (90-minute DML blocking)
- Graceful failure patterns for self-healing systems
- Load Jobs vs Streaming Inserts decision matrix
- Production-validated error handling

---

## 1. Schema Enforcement Pattern

### The Problem

**BigQuery schema inference creates mismatches:**

```
ERROR: Field created_at has changed mode from REQUIRED to NULLABLE
```

**Root cause:**
- BigQuery infers schema from JSON data
- Detects that `created_at` could be None/null
- Creates temp table with NULLABLE field
- Target table has REQUIRED field → mismatch

### The Solution: Force Schema Enforcement

**Critical pattern (3 components):**

```python
# 1. Force exact schema from target table
target_table = self.bq_client.get_table(table_id)

job_config = bigquery.LoadJobConfig(
    schema=target_table.schema,    # Use exact target schema
    autodetect=False,               # Never infer schema
    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    ignore_unknown_values=True
)

# 2. Validate required fields before loading
def ensure_required_defaults(record: dict, required_fields: set) -> dict:
    """Ensure all REQUIRED fields have non-null values."""
    out = dict(record)
    current_utc = datetime.now(timezone.utc)

    if "created_at" in required_fields and out.get("created_at") is None:
        out["created_at"] = current_utc
    if "processed_at" in required_fields and out.get("processed_at") is None:
        out["processed_at"] = current_utc

    return out

validated_data = [ensure_required_defaults(r, required_fields) for r in data]

# 3. Load with schema enforcement
load_job = self.bq_client.load_table_from_json(
    validated_data,
    table_id,
    job_config=job_config
)
load_job.result()
```

**Results:**
- ✅ No more schema mode errors
- ✅ Type validation at load time
- ✅ Consistent field modes across temp and target tables

---

## 2. Streaming Buffer Limitations

### The 90-Minute Problem

**What happens with streaming inserts:**

```python
# This puts data in BigQuery's streaming buffer
self.bq_client.insert_rows_json(table_id, data)

# Data stays in streaming buffer for up to 90 minutes
# During this time, NO DML operations can modify the table
```

**Why MERGE/UPDATE/DELETE get blocked:**

```sql
-- This fails if ANY rows are in streaming buffer
MERGE table AS target
USING temp AS source
ON target.id = source.id
WHEN MATCHED THEN UPDATE ...  -- ← Blocked entirely
```

BigQuery doesn't analyze whether your specific operation affects streaming buffer rows - it blocks any DML if the buffer is active.

### Production Impact

**Real-world scenario:**
```
9:00 AM: Streaming insert of new prop bet data
9:30 AM: Try to UPDATE player stats → BLOCKED
10:00 AM: Try to MERGE new odds → BLOCKED
10:30 AM: Finally works (90+ minutes later)
```

**Impact:** 90-minute lag between writes and ability to modify data - unacceptable for frequent updates.

### The Solution: Batch Loading Only

**Never use streaming inserts in production:**

```python
# ❌ DON'T: Creates streaming buffer
self.bq_client.insert_rows_json(table_id, data)

# ✅ DO: Batch loading (no streaming buffer)
job_config = bigquery.LoadJobConfig(
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    schema=target_table.schema,
    autodetect=False
)
load_job = self.bq_client.load_table_from_json(data, table_id, job_config)
load_job.result()  # Wait for completion

# Can immediately do DML operations - no 90-minute restriction
```

**Trade-offs:**
- Slightly higher latency (2-5 seconds vs immediate)
- No 90-minute DML restriction
- Perfect for scheduled processors (30-60 minute intervals)

---

## 3. Graceful Failure Pattern

### The Problem: Fallback Cycles

**Anti-pattern that creates problems:**

```python
# ❌ DON'T: Creates infinite cycle
try:
    # Batch load + MERGE
    load_and_merge(data)
except Exception as e:
    # Streaming insert fallback ← Creates streaming buffer!
    self.bq_client.insert_rows_json(table_id, data)
    # Next run will be blocked by streaming buffer we just created
```

**Result:** System perpetuates its own problems.

### The Solution: Graceful Failure

**Self-healing approach:**

```python
# ✅ DO: Graceful failure creates self-healing system
try:
    # Batch load + MERGE (works reliably)
    load_and_merge(data)

except Exception as e:
    if "streaming buffer" in str(e).lower():
        logger.warning(f"MERGE blocked - {len(data)} records skipped this run")
        logger.info("Records will be processed on next run when buffer clears")
        return  # Graceful skip - no fallback
    else:
        raise e  # Re-raise genuine errors
```

**Benefits:**
- ✅ Breaks the cycle (no new streaming buffer records)
- ✅ Self-healing (recovers automatically when buffer clears)
- ✅ Predictable (consistent behavior)
- ✅ Simple (no complex fallback logic)

**For NBA platform (30-60 minute processor intervals):**
- Missing one run is acceptable
- Next run succeeds automatically
- Data consistency maintained

---

## 4. Production-Safe Loading Pattern

### Standard Template

```python
def production_safe_load(self, data: list, table_id: str) -> bool:
    """Production-safe loading with graceful failure."""
    temp_table_id = None

    try:
        # 1. Get target table schema
        target_table = self.bq_client.get_table(table_id)
        required_fields = {
            f.name for f in target_table.schema
            if f.mode == "REQUIRED"
        }

        # 2. Create temporary table
        temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
        temp_table = bigquery.Table(temp_table_id, schema=target_table.schema)
        self.bq_client.create_table(temp_table)

        # 3. Validate required fields
        validated_data = [
            ensure_required_defaults(record, required_fields)
            for record in data
        ]

        # 4. Batch load with schema enforcement
        job_config = bigquery.LoadJobConfig(
            schema=target_table.schema,
            autodetect=False,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
        )

        load_job = self.bq_client.load_table_from_json(
            validated_data,
            temp_table_id,
            job_config
        )
        load_job.result()
        logger.info(f"✅ Loaded {len(data)} rows to temp table")

        # 5. MERGE operation
        merge_query = f"""
        MERGE `{table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """

        merge_job = self.bq_client.query(merge_query)
        merge_job.result()
        logger.info(f"✅ MERGE completed successfully")

        return True

    except Exception as e:
        if "streaming buffer" in str(e).lower():
            logger.warning(f"MERGE blocked by streaming buffer - {len(data)} records skipped")
            logger.info("Records will be processed on next run")
            return False  # Graceful failure
        else:
            logger.error(f"Load failed: {str(e)}")
            raise e

    finally:
        # 6. Always cleanup temp tables
        if temp_table_id:
            self.bq_client.delete_table(temp_table_id, not_found_ok=True)
```

---

## 5. Load Jobs vs Streaming Inserts

### Decision Matrix

| Factor | Load Jobs | Streaming Inserts |
|--------|-----------|-------------------|
| **Use case** | Batch/scheduled processing | Real-time event streams |
| **Latency** | 2-5 seconds | Immediate |
| **DML restriction** | None | 90-minute blocking |
| **Cost** | Free (2TB/day), then $0.02/GB | $0.05/GB (2.5x more) |
| **Schema** | Strict validation | Flexible |
| **Best for** | NBA platform ✅ | High-frequency events |

### When to Use Each

**Load Jobs (Recommended for NBA platform):**
```python
# ✅ Use for:
# - Scheduled processors (every 30-60 minutes)
# - Batch data (100-10k rows)
# - Need MERGE/UPDATE/DELETE operations
# - Cost-sensitive applications

job_config = bigquery.LoadJobConfig(
    schema=target_table.schema,
    autodetect=False
)
load_job = self.bq_client.load_table_from_json(data, table_id, job_config)
load_job.result()
```

**Streaming Inserts (Not recommended for us):**
```python
# ⚠️ Only use for:
# - Real-time event processing (< 1 minute intervals)
# - Unpredictable arrival times
# - Never need to UPDATE/DELETE
# - Cost is not a concern

errors = self.bq_client.insert_rows_json(table_id, data)
```

**For NBA platform:** Load Jobs are faster, cheaper, and avoid streaming buffer issues.

---

## 6. Error Handling Quick Reference

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `Field X changed mode REQUIRED to NULLABLE` | Schema inference mismatch | Use `autodetect=False` + `schema=target_table.schema` |
| `UPDATE statement...streaming buffer` | Recent streaming insert | Use batch loading only, graceful failure handling |
| `'dict' object has no attribute 'to_api_repr'` | STRUCT parameter format | Use staging table approach instead |
| `Cannot insert NULL into REQUIRED field` | Missing required field | Use `ensure_required_defaults()` |
| `JSON serialization error` | Complex data types | Convert datetime/Decimal to strings before load |

### Troubleshooting Pattern

```python
# 1. Check error type
if "streaming buffer" in str(e).lower():
    # Graceful skip - will succeed next run
    return False
elif "schema" in str(e).lower() or "mode" in str(e).lower():
    # Schema mismatch - check autodetect and schema enforcement
    raise SchemaError(f"Schema validation failed: {e}")
elif "required" in str(e).lower():
    # Missing required field - check ensure_required_defaults
    raise ValueError(f"Required field validation failed: {e}")
else:
    # Genuine error - investigate
    raise e
```

---

## 7. Best Practices Summary

### ✅ DO

**Schema Management:**
- Always use `autodetect=False`
- Always provide `schema=target_table.schema`
- Validate required fields before loading
- Use native Python types (datetime, not strings)

**Loading Strategy:**
- Use Load Jobs for batch processing
- Never use streaming inserts as fallback
- Implement graceful failure for streaming buffer conflicts
- Clean up temp tables in `finally` blocks

**Error Handling:**
- Detect streaming buffer errors specifically
- Log skipped records for monitoring
- Let system self-heal on next run
- Raise genuine errors immediately

### ❌ DON'T

**Anti-Patterns:**
- Don't rely on schema autodetection
- Don't use streaming inserts for scheduled processors
- Don't create fallback cycles
- Don't use STRUCT parameters for MERGE
- Don't ignore required field validation

**Common Mistakes:**
- Don't convert datetime to string before loading (use native)
- Don't persist temp tables between runs
- Don't retry streaming buffer errors immediately
- Don't batch insert row-by-row in loops

---

## 8. Testing Best Practices

### Local Test Script Pattern

**Rapid iteration without deployment:**

```python
#!/usr/bin/env python3
"""Local test for BigQuery loading patterns."""

from google.cloud import bigquery
from datetime import datetime, timezone
import uuid

def test_schema_enforcement():
    """Test schema-enforced loading locally."""
    client = bigquery.Client()

    # Test data with edge cases
    test_records = [
        {
            'id': 'test1',
            'name': 'Test Player',
            'reviewed_at': None,  # Nullable field
            'created_at': datetime.now(timezone.utc),  # Required field
        }
    ]

    # Use same production pattern
    result = production_safe_load(test_records, 'test_table')

    if result:
        print("✅ Test passed")
    else:
        print("⚠️ Graceful failure (expected for streaming buffer)")

    # Cleanup
    client.query("DELETE FROM test_table WHERE id LIKE 'test%'").result()

if __name__ == "__main__":
    test_schema_enforcement()
```

**Benefits:**
- 10x faster iteration (10 minutes vs 2 hours)
- Tests exact production code
- Catches issues before deployment

---

## 9. Monitoring and Validation

### Check for Streaming Buffer Issues

```sql
-- Monitor for streaming buffer conflicts
SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) as hour,
  COUNT(*) as errors,
  ARRAY_AGG(DISTINCT json_payload.processor_name IGNORE NULLS LIMIT 5) as affected_processors
FROM `project.dataset.logs`
WHERE severity = 'WARNING'
  AND text_payload LIKE '%streaming buffer%'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY hour
ORDER BY hour DESC;
```

### Validate Load Job Performance

```sql
-- Monitor Load Job performance
SELECT
  DATE(creation_time) as date,
  destination_table.table_id,
  COUNT(*) as load_jobs,
  AVG(output_rows) as avg_rows,
  AVG(TIMESTAMP_DIFF(end_time, start_time, SECOND)) as avg_duration_sec,
  COUNTIF(error_result IS NOT NULL) as errors
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE job_type = 'LOAD'
  AND destination_table.dataset_id IN ('nba_raw', 'nba_analytics')
  AND creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date, destination_table.table_id
ORDER BY date DESC, avg_rows DESC;
```

**Expected results:**
- Load duration: 2-5 seconds for 100-1000 rows
- Error rate: <1% (mostly graceful streaming buffer skips)
- No schema validation errors

---

## 10. Migration Checklist

### Updating Existing Processors

**If your processor uses streaming inserts:**

- [ ] Replace `insert_rows_json()` with `load_table_from_json()`
- [ ] Add schema enforcement (`autodetect=False`, `schema=target_table.schema`)
- [ ] Add required field validation (`ensure_required_defaults()`)
- [ ] Implement graceful failure for streaming buffer errors
- [ ] Add temp table cleanup in `finally` block
- [ ] Test with local test script first
- [ ] Deploy and monitor for 1 week
- [ ] Verify no streaming buffer conflicts

**Validation queries:**
```sql
-- Before migration: Check for streaming buffer conflicts
SELECT COUNT(*) FROM logs WHERE text_payload LIKE '%streaming buffer%';

-- After migration: Should be 0 or only graceful warnings
SELECT COUNT(*) FROM logs WHERE text_payload LIKE '%streaming buffer%' AND severity = 'ERROR';
```

---

## References

- **[BigQuery Batching Pattern](../patterns/07-bigquery-batching-current.md)** - Current implementation in `analytics_base.py`
- **[Schema Change Process](04-schema-change-process.md)** - Safe schema change procedures
- **[Analytics Base Implementation](../../data_processors/analytics/analytics_base.py)** - Lines 681-814
- **[Google Cloud: Load Jobs](https://cloud.google.com/bigquery/docs/loading-data)** - Official documentation
- **[Google Cloud: Streaming Inserts](https://cloud.google.com/bigquery/streaming-data-into-bigquery)** - When to use streaming

---

## Key Takeaways

**Critical patterns:**
1. **Schema enforcement** - Always use target table schema, never autodetect
2. **Batch loading only** - Avoid streaming inserts for scheduled processors
3. **Graceful failure** - Self-healing systems better than complex fallbacks
4. **Local testing** - 10x faster iteration before deployment

**Production architecture:**
- Load Jobs for all scheduled processors
- Graceful failure for streaming buffer conflicts
- Schema validation at load time
- Self-healing on next run

**Development philosophy:**
- Test locally, deploy once, fail gracefully
- Remove complexity (no fallback cycles)
- Invest in focused test scripts
- Create predictable, self-healing systems

---

## 11. Duplicate Prevention with Atomic MERGE Pattern

### The Problem: DELETE + INSERT Race Conditions

**Vulnerable pattern that creates duplicates:**

```python
# ❌ DON'T: DELETE + INSERT is not atomic
def save_data(self, data: list, table_id: str):
    # Step 1: Delete existing records
    delete_query = f"DELETE FROM `{table_id}` WHERE game_date = '{date}'"
    self.bq_client.query(delete_query).result()

    # Step 2: Insert new records
    load_job = self.bq_client.load_table_from_json(data, table_id, job_config)
    load_job.result()
```

**Why this creates duplicates:**
1. DELETE succeeds for run #1
2. Run #2 starts before run #1 INSERT completes
3. Run #2 DELETE succeeds (deletes run #1's partial data)
4. Run #1 INSERT completes → records in table
5. Run #2 INSERT completes → **DUPLICATES!**

**Real-world example (Session 134):**
- `upcoming_player_game_context`: 34,728 duplicates (26.6% of table)
- Same player-game combinations inserted 2-8 times
- Timestamps 1-2 seconds apart (within single batch processing)

### The Solution: Atomic MERGE Pattern

**Duplicate-proof implementation:**

```python
# ✅ DO: Atomic MERGE prevents all duplicates
def save_data_atomic(self, data: list, table_id: str, merge_keys: set) -> bool:
    """Save data using atomic MERGE pattern - duplicate-proof."""
    temp_table_id = None

    try:
        # 1. Get target table schema
        target_table = self.bq_client.get_table(table_id)
        target_schema = target_table.schema

        # 2. Create temporary table
        temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
        temp_table = bigquery.Table(temp_table_id, schema=target_schema)
        self.bq_client.create_table(temp_table)

        # 3. Load data to temp table
        ndjson_data = "\n".join(json.dumps(row, default=str) for row in data)
        job_config = bigquery.LoadJobConfig(
            schema=target_schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=False
        )
        load_job = self.bq_client.load_table_from_file(
            io.BytesIO(ndjson_data.encode('utf-8')),
            temp_table_id,
            job_config=job_config
        )
        load_job.result()

        # 4. Build dynamic UPDATE SET clause (exclude merge keys)
        update_columns = [f.name for f in target_schema if f.name not in merge_keys]
        update_set_clause = ", ".join(f"target.{col} = source.{col}" for col in update_columns)

        # 5. Atomic MERGE with source deduplication
        merge_query = f"""
        MERGE `{table_id}` AS target
        USING (
            SELECT * EXCEPT(row_num) FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY {', '.join(merge_keys)}
                    ORDER BY processed_at DESC
                ) as row_num
                FROM `{temp_table_id}`
            ) WHERE row_num = 1
        ) AS source
        ON {' AND '.join(f'target.{k} = source.{k}' for k in merge_keys)}
        WHEN MATCHED THEN
            UPDATE SET {update_set_clause}
        WHEN NOT MATCHED THEN
            INSERT ROW
        """

        merge_job = self.bq_client.query(merge_query)
        merge_job.result()

        return True

    except Exception as e:
        if "streaming buffer" in str(e).lower():
            logger.warning(f"MERGE blocked by streaming buffer - will succeed next run")
            return False
        raise

    finally:
        # Always cleanup temp table
        if temp_table_id:
            self.bq_client.delete_table(temp_table_id, not_found_ok=True)
```

### Why MERGE is Duplicate-Proof

**Key properties:**

1. **Atomic operation** - MERGE is a single DML statement that BigQuery executes atomically
2. **Source deduplication** - ROW_NUMBER() ensures only one record per merge key
3. **No race condition** - Concurrent runs see consistent state
4. **Idempotent** - Run 10 times, get same result

### Merge Keys by Table

| Table | Merge Keys | Notes |
|-------|------------|-------|
| `upcoming_player_game_context` | `(player_lookup, game_id)` | Player-game unique |
| `upcoming_team_game_context` | `(team_abbr, game_id)` | Team-game unique |
| `ml_feature_store_v2` | `(player_lookup, game_date)` | Player-date unique |
| `player_shot_zone_analysis` | `(player_lookup, analysis_date)` | Player-date unique |

### Processors Using Atomic MERGE (as of Session 134)

**Phase 3 Analytics:**
- ✅ `upcoming_player_game_context` - Fixed Session 134
- ✅ `upcoming_team_game_context` - Fixed Session 134
- ⚠️ `player_game_summary` - Uses base class (DELETE+INSERT)
- ⚠️ `team_offense_game_summary` - Uses base class (DELETE+INSERT)
- ⚠️ `team_defense_game_summary` - Uses base class (DELETE+INSERT)

**Phase 4 Precompute:**
- ✅ `ml_feature_store_v2` - Uses BatchWriter with MERGE
- ⚠️ Others use precompute_base (DELETE+INSERT) - no duplicates observed

### Migration Checklist: DELETE+INSERT → MERGE

- [ ] Identify merge keys (unique constraint columns)
- [ ] Add imports: `uuid`, `io`, `time`
- [ ] Create temp table with target schema
- [ ] Load data to temp table via batch load job
- [ ] Build dynamic UPDATE SET clause from schema
- [ ] Execute MERGE with source deduplication (ROW_NUMBER)
- [ ] Handle streaming buffer gracefully
- [ ] Cleanup temp table in `finally` block
- [ ] Test with duplicate data to verify idempotency
- [ ] Monitor for duplicate count = 0

### Validation Query

```sql
-- Check for duplicates after MERGE implementation
SELECT
  'upcoming_player_game_context' as table_name,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(player_lookup, '-', game_id)) as unique_records,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '-', game_id)) as duplicates
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`

UNION ALL

SELECT
  'upcoming_team_game_context' as table_name,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(team_abbr, '-', game_id)) as unique_records,
  COUNT(*) - COUNT(DISTINCT CONCAT(team_abbr, '-', game_id)) as duplicates
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`;
```

**Expected result after MERGE implementation:** `duplicates = 0`

---

**Last Verified:** 2025-12-14
**Maintained By:** NBA Platform Team
