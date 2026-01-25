# Verified Bugs to Fix

**Date:** 2026-01-25
**Status:** Verified and ready for implementation
**Priority:** Fix in order listed

---

## Quick Reference - Most Critical

| Bug | File | Will Cause |
|-----|------|------------|
| Undefined variables in retry | `processor_base.py:1314` | **Crash** on streaming buffer retry |
| Pub/Sub `.result()` no timeout | `pubsub_client.py:176` | **Hang** indefinitely |
| Unsafe `next()` no default | `bdl_player_box_scores_processor.py:357` | **Crash** if game_id missing |
| Firestore dual-write not atomic | `batch_state_manager.py:300-315` | **Data corruption** |

---

## Corrections to Previous Handoff

The previous handoff document (CONSOLIDATED-DISCOVERY-HANDOFF.md) contained some inaccuracies:

| Claimed Issue | Actual Status |
|--------------|---------------|
| Admin dashboard stubs don't work | **WRONG** - Fully implemented, calls Cloud Run endpoints |
| Stale prediction detection is TODO | **WRONG** - Fully implemented with SQL query |
| Sentry DSN exposed in .env | **WRONG** - SENTRY_DSN is commented out, .env is gitignored |

---

## P0 - Critical Bugs (Will Crash or Corrupt Data)

### 1. Undefined Variables in Streaming Buffer Retry

**File:** `data_processors/raw/processor_base.py`
**Lines:** 1314-1316

**Problem:** The retry block uses variables that don't exist in scope.

```python
# Line 1274 uses these variables:
load_job = self.bq_client.load_table_from_file(
    io.BytesIO(ndjson_bytes),  # <-- ndjson_bytes
    table_id,                   # <-- table_id
    job_config=job_config       # <-- job_config
)

# But line 1314-1316 retry uses DIFFERENT variables that don't exist:
load_job = self.bq_client.load_table_from_dataframe(
    df,                         # <-- UNDEFINED
    table_ref,                  # <-- UNDEFINED
    job_config=load_job_config  # <-- UNDEFINED
)
```

**Impact:** When streaming buffer retry is triggered, Python will crash with `NameError`. Data will be lost.

**Fix:**
```python
# Replace lines 1314-1316 with:
load_job = self.bq_client.load_table_from_file(
    io.BytesIO(ndjson_bytes),
    table_id,
    job_config=job_config
)
```

**Test:** Search for streaming buffer errors in logs and verify retry works.

---

### 2. Firestore Dual-Write Not Atomic

**File:** `predictions/coordinator/batch_state_manager.py`
**Lines:** 300-315

**Problem:** Dual-write mode writes to two separate locations without a transaction boundary.

```python
# Line 307-312: Write to OLD structure (inside Firestore, but not transactional)
doc_ref.update({
    'completed_players': ArrayUnion([player_lookup]),
    ...
})

# Line 315: Write to NEW structure (SEPARATE operation, can fail independently)
self._record_completion_subcollection(batch_id, player_lookup, predictions_count)
```

**Impact:** If subcollection write fails after array write succeeds:
- Old structure shows player complete
- New structure shows player incomplete
- 10% validation sampling may miss this (line 319)
- Batch completion tracking becomes unreliable

**Fix:** Wrap both writes in a Firestore transaction:
```python
@firestore.transactional
def _dual_write_transactional(transaction, doc_ref, player_lookup, ...):
    # Both writes happen atomically
    transaction.update(doc_ref, {...})
    # Subcollection write also in transaction
```

**Test:** Force subcollection write failure and verify array write rolls back.

---

### 3. SQL String Interpolation (Injection Risk)

**File:** `data_processors/precompute/mlb/pitcher_features_processor.py`
**Lines:** 1016-1018

**Problem:** SQL query uses f-string interpolation instead of parameterized queries.

```python
delete_query = f"""
DELETE FROM `{self.project_id}.{self.target_table}`
WHERE game_date = '{game_date}'  # <-- String interpolation
"""
```

**Impact:** While `game_date` comes from a Python `date` object (limiting exploitation), this is a bad pattern. Same pattern exists in 20+ files in `bin/validation/`.

**Fix:**
```python
delete_query = """
DELETE FROM `{project}.{table}`
WHERE game_date = @game_date
""".format(project=self.project_id, table=self.target_table)

job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
    ]
)
self.bq_client.query(delete_query, job_config=job_config).result()
```

**Files to fix (production code):**
- `data_processors/precompute/mlb/pitcher_features_processor.py:1016-1018`

**Files to fix (bin scripts - lower priority):**
- `bin/validation/phase_transition_health.py` (6 instances)
- `bin/validation/root_cause_analyzer.py` (10 instances)
- `bin/spot_check_features.py` (2 instances)
- `bin/validate_historical_completeness.py` (1 instance)

---

### 4. DELETE/INSERT Race Condition

**File:** `data_processors/precompute/mlb/pitcher_features_processor.py`
**Lines:** 1016-1027

**Problem:** DELETE and INSERT are separate operations without transaction.

```python
# Step 1: Delete (line 1021)
self.bq_client.query(delete_query).result()

# Gap: Table is empty here! Other readers see no data.

# Step 2: Insert (line 1027)
errors = self.bq_client.insert_rows_json(table_ref, features_list)
```

**Impact:**
- Queries between delete and insert see empty/partial data
- If insert fails, data is permanently lost (delete already committed)
- Concurrent processors could insert duplicates

**Fix:** Use MERGE statement for atomic replace:
```python
merge_query = """
MERGE `{table}` T
USING UNNEST(@features) S
ON T.game_date = S.game_date AND T.pitcher_id = S.pitcher_id
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
"""
```

---

## P1 - High Priority (Silent Data Loss)

### 5. BigQuery Load Errors Silently Ignored

**File:** `shared/utils/bigquery_utils.py`
**Lines:** 231-234

**Problem:** Function returns `False` on errors, but callers may not check return value.

```python
if load_job.errors:
    logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
    logger.error(f"Failed to insert rows into {table_id}: {load_job.errors}")
    return False  # Callers may ignore this!
```

**Impact:** Rows silently not inserted. No exception raised.

**Fix:** Raise exception instead of returning False:
```python
if load_job.errors:
    logger.error(f"Failed to insert rows into {table_id}: {load_job.errors}")
    raise BigQueryInsertError(f"Failed to insert {len(rows)} rows: {load_job.errors[:3]}")
```

---

### 6. Wrong Row Count Calculation on Partial Failure

**File:** `shared/utils/player_registry/alias_manager.py`
**Lines:** 141-144

**Problem:** Calculates successful rows incorrectly.

```python
if load_job.errors:
    logger.error(f"Errors inserting aliases: {load_job.errors}")
    return len(new_rows) - len(load_job.errors)  # WRONG!
```

**Issue:** `load_job.errors` is a list of error dictionaries, not a count of failed rows. One error dict may describe multiple failed rows, or one row may have multiple errors.

**Fix:**
```python
if load_job.errors:
    logger.error(f"Errors inserting aliases: {load_job.errors}")
    # Don't guess - query actual count or raise exception
    raise AliasInsertError(f"Partial failure inserting aliases: {load_job.errors}")
```

---

### 7. Batch Processor Continues on File Failure

**File:** `data_processors/raw/oddsapi/oddsapi_batch_processor.py`
**Lines:** 106-108

**Problem:** When a file fails to process, loop continues and partial data is saved.

```python
except Exception as e:
    logger.error(f"Failed to process game-lines file {blob.name}: {e}")
    # Continue with other files  <-- Accumulates partial data
```

**Impact:**
- MERGE operation runs with incomplete data
- No signal to operator that files were skipped
- Hard to detect missing data later

**Fix:** Track failed files and abort if threshold exceeded:
```python
failed_files = []
for blob in blobs:
    try:
        # ... process
    except Exception as e:
        logger.error(f"Failed to process {blob.name}: {e}")
        failed_files.append(blob.name)

if failed_files:
    raise BatchProcessingError(
        f"Failed to process {len(failed_files)} files: {failed_files[:5]}"
    )
```

---

### 8. Bare Exception Handler

**File:** `bin/monitoring/phase_transition_monitor.py`
**Line:** 311

**Problem:** Catches all exceptions and returns 0.

```python
try:
    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
except:  # <-- Catches EVERYTHING including KeyboardInterrupt
    return 0
```

**Fix:**
```python
try:
    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
except (ValueError, AttributeError) as e:
    logger.debug(f"Could not parse timestamp {timestamp}: {e}")
    return 0
```

---

## P1.5 - High Priority (Service Hangs)

### 9. Pub/Sub Streaming Pull Blocks Forever

**File:** `orchestration/shared/utils/pubsub_client.py`
**Line:** 176

**Problem:** Blocks indefinitely without timeout.

```python
streaming_pull_future.result()  # NO TIMEOUT - blocks forever
```

**Impact:** If Pub/Sub has issues, the entire service hangs. Cloud Run/Functions will eventually timeout, but resources are wasted.

**Fix:**
```python
streaming_pull_future.result(timeout=300)  # 5 minute max
```

---

### 10. Worker Pub/Sub Publish Blocks Forever

**File:** `predictions/worker/worker.py`
**Line:** 1683

**Problem:** Waits for publish without timeout.

```python
future.result()  # NO TIMEOUT
```

**Fix:**
```python
future.result(timeout=30)  # 30 second max for publish
```

---

### 11. BigQuery Cleanup Query No Timeout

**File:** `orchestration/cloud_functions/upcoming_tables_cleanup/main.py`
**Line:** 195

**Problem:** DELETE query blocks without timeout.

```python
job = client.query(delete_query)
job.result()  # NO TIMEOUT
```

**Fix:**
```python
job.result(timeout=120)  # 2 minute max for cleanup
```

---

### 12. Unsafe `next()` Calls Will Crash

**Files:** Multiple processors

**Problem:** Using `next()` without default value crashes with `StopIteration` if no match found.

```python
# bdl_player_box_scores_processor.py:357
game_date = next(row['game_date'] for row in rows if row['game_id'] == game_id)

# nbac_team_boxscore_processor.py:219-220
away_team = next(t for t in teams if t.get('homeAway', '').upper() == 'AWAY')
home_team = next(t for t in teams if t.get('homeAway', '').upper() == 'HOME')
```

**Affected files:**
- `data_processors/raw/balldontlie/bdl_player_box_scores_processor.py:357`
- `data_processors/raw/balldontlie/bdl_boxscores_processor.py:631`
- `data_processors/raw/mlb/mlb_pitcher_stats_processor.py:322`
- `data_processors/raw/mlb/mlb_batter_stats_processor.py:345`
- `data_processors/raw/nbacom/nbac_team_boxscore_processor.py:219-220`
- `data_processors/raw/balldontlie/bdl_standings_processor.py:393-395`

**Fix:** Add default value:
```python
game_date = next((row['game_date'] for row in rows if row['game_id'] == game_id), None)
if game_date is None:
    logger.warning(f"game_id {game_id} not found in rows")
    return  # or handle gracefully
```

---

## P2 - Medium Priority (Data Quality)

### 13. MERGE NULL Handling Edge Case

**File:** `predictions/shared/batch_staging_writer.py`
**Lines:** 337, 347

**Problem:** Uses `COALESCE(current_points_line, -1)` for NULL handling.

```python
PARTITION BY game_id, player_lookup, system_id,
             CAST(COALESCE(current_points_line, -1) AS INT64)
...
AND CAST(COALESCE(T.current_points_line, -1) AS INT64) =
    CAST(COALESCE(S.current_points_line, -1) AS INT64)
```

**Issue:** If a line value is ever actually -1 (unlikely but possible in edge cases), it would collide with NULL values.

**Fix:** Use a sentinel value that can never be a real line:
```python
COALESCE(current_points_line, -999999)  -- Lines are always positive, typically 5-50
```

Or use explicit NULL handling:
```python
AND (T.current_points_line = S.current_points_line
     OR (T.current_points_line IS NULL AND S.current_points_line IS NULL))
```

---

## P2.5 - Memory Leaks (Long-Running Services)

### 14. Unbounded Caches in Prediction Worker

**File:** `predictions/worker/data_loaders.py`
**Lines:** 77, 82, 87, 92

**Problem:** Instance-level caches grow forever without size limits.

```python
self._historical_games_cache: Dict[date, Dict[str, List[Dict]]] = {}
self._features_cache: Dict[date, Dict[str, Dict]] = {}
self._features_cache_timestamps: Dict[date, datetime] = {}
self._game_context_cache: Dict[date, Dict[str, Dict]] = {}
```

**Impact:** Memory grows linearly with unique game dates. Over months, could consume gigabytes.

**Fix:** Add TTL-based cleanup or max size:
```python
from functools import lru_cache

@lru_cache(maxsize=30)  # Keep last 30 days
def _get_historical_games(self, game_date: date) -> Dict:
    ...
```

---

### 15. Feature Extractor Has 12 Unbounded Lookups

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`
**Lines:** 41-57

**Problem:** 12 dictionaries that accumulate data across batch runs.

```python
self._daily_cache_lookup: Dict[str, Dict] = {}
self._composite_factors_lookup: Dict[str, Dict] = {}
self._shot_zone_lookup: Dict[str, Dict] = {}
# ... 9 more
```

**Fix:** Add `clear_batch_caches()` method and call after each batch.

---

### 16. Progress Tracker completion_times List Grows Forever

**File:** `predictions/coordinator/progress_tracker.py`
**Lines:** 82, 159

**Problem:** List appends every completion event, never cleared.

```python
self.completion_times: List[datetime] = []
...
self.completion_times.append(datetime.utcnow())
```

**Fix:** Remove if unused, or limit to last N entries.

---

## P3 - Lower Priority (Code Quality)

### 10. Hardcoded API Endpoints in 16 Files

**Location:** `scrapers/balldontlie/*.py`

Each scraper has its own `_API_ROOT` constant:
```python
_API_ROOT = "https://api.balldontlie.io/v1/stats"
_API_ROOT = "https://api.balldontlie.io/v1/games"
_API_ROOT = "https://api.balldontlie.io/v1/teams"
# ... 13 more
```

**Fix:** Centralize in config:
```python
# shared/config/api_endpoints.py
BDL_API_BASE = os.getenv("BDL_API_BASE", "https://api.balldontlie.io/v1")

# In scrapers:
from shared.config.api_endpoints import BDL_API_BASE
_API_ROOT = f"{BDL_API_BASE}/stats"
```

---

### 11. 356 `time.sleep()` Calls

Many blocking sleeps throughout the codebase. Most are intentional rate limiting, but should be audited for:
- Sleeps in async code paths
- Sleeps without jitter (thundering herd)
- Unnecessarily long sleeps

**Command to find them:**
```bash
grep -rn "time\.sleep" --include="*.py" | grep -v "__pycache__"
```

---

## Verification Commands

```bash
# Verify undefined variable bug still exists
grep -n "load_table_from_dataframe" data_processors/raw/processor_base.py

# Verify SQL injection pattern
grep -rn "WHERE game_date = '\{" --include="*.py" | wc -l

# Verify bare except handler
grep -n "except:" bin/monitoring/phase_transition_monitor.py

# Verify dual-write not atomic
grep -n "_record_completion_subcollection" predictions/coordinator/batch_state_manager.py
```

---

## Testing After Fixes

1. **processor_base.py fix:** Trigger streaming buffer conflict and verify retry works
2. **batch_state_manager.py fix:** Unit test transaction rollback on subcollection failure
3. **pitcher_features_processor.py fix:** Integration test MERGE with existing data
4. **bigquery_utils.py fix:** Test that callers handle the new exception

---

## P4 - Security (Review Required)

### 17. Cloud Functions Lack Authentication

**Location:** `orchestration/cloud_functions/*/main.py`

**Problem:** 94+ Cloud Function endpoints use `@functions_framework.http` without auth validation.

```python
@functions_framework.http
def manual_trigger(request):  # No auth check!
    ...
```

**Affected functions include:**
- `backfill_trigger/main.py` - `manual_trigger()`, `cleanup_old_requests()`
- `daily_health_summary/main.py` - `check_and_send_summary()`
- Many others

**Note:** These may be protected by Cloud Run IAM, but defense-in-depth recommends code-level auth too.

**Fix:** Add auth decorator or check:
```python
def require_auth(f):
    @wraps(f)
    def decorated(request):
        auth = request.headers.get('Authorization')
        if not validate_token(auth):
            return 'Unauthorized', 401
        return f(request)
    return decorated

@functions_framework.http
@require_auth
def manual_trigger(request):
    ...
```

---

### 18. Health Endpoints Expose System Info

**Files:**
- `predictions/worker/worker.py:316-338`
- `predictions/coordinator/coordinator.py:423-439`

**Problem:** Root endpoints return system state without auth.

```python
@app.route('/')
def health():  # No @require_api_key
    return jsonify({
        'current_batch_id': current_batch_id,
        'multi_instance_enabled': ENABLE_MULTI_INSTANCE,
        ...
    })
```

**Impact:** Information disclosure - batch IDs, configuration visible.

**Fix:** Move sensitive info to authenticated `/status` endpoint.

---

## Additional Findings (Not Bugs, But Worth Noting)

### Pre-flight Filter Fallback (Intentional)
**File:** `predictions/coordinator/coordinator.py:856-859`

```python
except Exception as e:
    logger.warning(f"PRE-FLIGHT FILTER: Failed to check quality scores (publishing all): {e}")
    viable_requests = requests  # Fallback to all requests
```

This catches all exceptions but is **intentional graceful degradation** - if pre-flight check fails, publish all requests and let workers handle filtering. Not a bug.

### Circuit Breaker Returns None on Error (Acceptable)
**File:** `scrapers/utils/proxy_utils.py:336-339`

```python
except Exception as e:
    logger.debug(f"BigQuery circuit breaker query failed: {e}")
return None  # Callers handle None
```

Returns None when BigQuery fails. Callers should (and do) treat None as "no circuit breaker data available." Acceptable pattern.

---

## Summary

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 4 | Will crash or corrupt data |
| P1 | 4 | Silent data loss |
| P1.5 | 4 | Service hangs (no timeout) |
| P2 | 1 | Data quality edge case |
| P2.5 | 3 | Memory leaks (long-running) |
| P3 | 2 | Code quality improvements |
| P4 | 2 | Security review needed |

**Start with P0 items** - these are actual bugs that can cause production failures.

**Estimated fix time:**
- P0: 2-4 hours (crashes/corruption)
- P1: 1-2 hours (silent data loss)
- P1.5: 1 hour (add timeouts)
- P2-P4: 2-4 hours (lower priority)

---

*Created: 2026-01-25*
*Verification method: Direct code inspection*
*Agent-assisted discovery with manual verification*
