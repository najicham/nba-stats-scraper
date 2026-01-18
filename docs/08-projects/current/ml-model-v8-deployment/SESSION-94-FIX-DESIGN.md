# Session 94: Long-Term Fix Design - Grading Duplicate Prevention

**Date:** 2026-01-17
**Status:** 📋 DESIGN - Ready for Implementation
**Priority:** HIGH

---

## Executive Summary

This document outlines a comprehensive, production-grade fix for the grading duplicate issue using the proven **Session 92 three-layer defense pattern**:

1. **Layer 1:** Distributed Lock (prevent concurrent operations)
2. **Layer 2:** Post-Grading Validation (detect any duplicates that slip through)
3. **Layer 3:** Monitoring & Alerting (early detection and response)

**Approach:** Reuse the existing `ConsolidationLock` class from Session 92, adapting it for grading operations.

---

## Design Principles

### Defense in Depth

**Why Three Layers?**
- **Lock alone** might fail (Firestore outage, lock timeout)
- **Validation alone** detects too late (after corruption)
- **Monitoring alone** doesn't prevent issues

**Together:** Belt + Suspenders + Backup Pants

### Minimal Code Changes

**Reuse, Don't Rewrite:**
- ✅ Use existing `ConsolidationLock` class (proven in production)
- ✅ Follow Session 92 patterns (well-documented, tested)
- ✅ Minimal changes to grading processor (reduce risk)

### Backward Compatibility

**Safe Rollout:**
- ✅ Add `use_lock=True` parameter (can disable for testing)
- ✅ Graceful degradation (logs warning if lock fails)
- ✅ No schema changes required

---

## Layer 1: Distributed Lock

### Architecture

**Lock Scope:** `game_date` (not batch_id or run_id)
- Prevents ALL concurrent grading operations for a specific date
- Allows parallel grading of different dates
- Handles retry scenarios automatically

**Lock Key Format:** `grading_{game_date}`
- Example: `grading_2026-01-17`
- Distinct from consolidation locks (`consolidation_{game_date}`)

**Storage:** Firestore collection `grading_locks`
- Separate from prediction consolidation locks
- Easier to monitor and debug
- Clean separation of concerns

### Lock Configuration

```python
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes (same as Session 92)
MAX_RETRIES = 60           # 60 retries × 5s = 5 min max wait
RETRY_INTERVAL_SECONDS = 5 # Check every 5 seconds
```

**Rationale:**
- Grading typically completes in <2 minutes
- 5-minute timeout provides 2.5x safety margin
- Auto-cleanup via Firestore TTL prevents stuck locks

### Implementation

**Option A: Reuse ConsolidationLock (Recommended)**

**Advantages:**
- ✅ Already in production (proven reliable)
- ✅ Well-tested and documented
- ✅ No new code to maintain
- ✅ Consistent locking behavior across pipelines

**Changes Needed:**
1. Rename `ConsolidationLock` → `DistributedLock` (generic)
2. Add `lock_type` parameter (`"consolidation"` or `"grading"`)
3. Use different Firestore collections per type

```python
# predictions/worker/distributed_lock.py

class DistributedLock:
    """
    Distributed lock using Firestore for atomic operations.

    Supports multiple lock types:
    - consolidation: For prediction consolidation operations
    - grading: For grading operations
    """

    def __init__(self, project_id: str, lock_type: str = "consolidation"):
        """
        Initialize distributed lock.

        Args:
            project_id: GCP project ID
            lock_type: Type of lock ("consolidation" or "grading")
        """
        self.project_id = project_id
        self.lock_type = lock_type
        self.db = firestore.Client(project=project_id)

        # Use different collections for different lock types
        self.collection_name = f"{lock_type}_locks"

    def acquire(self, game_date: str, operation_id: str):
        """
        Acquire distributed lock for a game_date.

        Args:
            game_date: Date to lock (YYYY-MM-DD)
            operation_id: Unique ID for this operation (for logging)

        Returns:
            Context manager that releases lock on exit
        """
        lock_key = f"{self.lock_type}_{game_date}"
        # ... (rest of implementation unchanged from Session 92)
```

**Option B: Create GradingLock Class (Alternative)**

**Advantages:**
- ✅ Explicit grading-specific naming
- ✅ No changes to existing consolidation lock

**Disadvantages:**
- ❌ Duplicates code from ConsolidationLock
- ❌ More code to maintain
- ❌ Risk of divergence (one gets bug fixes, other doesn't)

**Recommendation:** Use Option A (refactor to DistributedLock)

### Integration into PredictionAccuracyProcessor

**Modified write_graded_results Method:**

```python
# data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py

from predictions.worker.distributed_lock import DistributedLock

class PredictionAccuracyProcessor:

    def write_graded_results(
        self,
        graded_results: List[Dict],
        game_date: date,
        use_lock: bool = True  # Default enabled, can disable for testing
    ) -> int:
        """
        Write graded results to BigQuery with distributed locking.

        Args:
            graded_results: List of graded prediction dictionaries
            game_date: Date being graded
            use_lock: If True, acquire distributed lock (default: True)

        Returns:
            Number of rows written
        """
        if not graded_results:
            return 0

        game_date_str = game_date.isoformat()

        if use_lock:
            # Use distributed lock to prevent concurrent grading for this date
            lock = DistributedLock(
                project_id=self.project_id,
                lock_type="grading"
            )

            with lock.acquire(game_date=game_date_str, operation_id=f"grading_{game_date_str}"):
                logger.info(f"Acquired grading lock for {game_date_str}")
                return self._write_with_validation(graded_results, game_date)
        else:
            # Testing mode - no lock
            logger.warning(f"Grading WITHOUT lock for {game_date_str} (use_lock=False)")
            return self._write_with_validation(graded_results, game_date)

    def _write_with_validation(
        self,
        graded_results: List[Dict],
        game_date: date
    ) -> int:
        """
        Internal method: DELETE + INSERT + VALIDATE.

        This method is called INSIDE the lock context.
        """
        game_date_str = game_date.isoformat()

        try:
            # STEP 1: DELETE existing records for this date
            delete_query = f"""
            DELETE FROM `{self.accuracy_table}`
            WHERE game_date = '{game_date}'
            """
            delete_job = self.bq_client.query(delete_query)
            delete_job.result(timeout=60)
            deleted_count = delete_job.num_dml_affected_rows or 0

            if deleted_count > 0:
                logger.info(f"  Deleted {deleted_count} existing graded records for {game_date}")

            # STEP 2: INSERT new records using batch loading
            table_ref = self.bq_client.get_table(self.accuracy_table)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                graded_results,
                self.accuracy_table,
                job_config=job_config
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            rows_written = load_job.output_rows or len(graded_results)

            # STEP 3: VALIDATE no duplicates created (Layer 2)
            logger.info(f"  Running post-grading validation for {game_date}...")
            duplicate_count = self._check_for_duplicates(game_date)

            if duplicate_count > 0:
                logger.error(
                    f"  ❌ VALIDATION FAILED: {duplicate_count} duplicate business keys detected "
                    f"for {game_date} despite distributed lock!"
                )
                # Don't raise exception - log and alert, but don't fail grading
                # Alerting system will notify operators
            else:
                logger.info(f"  ✅ Validation passed: No duplicates for {game_date}")

            return rows_written

        except Exception as e:
            logger.error(f"Error writing graded results for {game_date}: {e}")
            return 0
```

**Key Changes:**
1. Import `DistributedLock` from predictions/worker
2. Add `use_lock` parameter (default True)
3. Wrap DELETE + INSERT in lock context
4. Extract write logic to `_write_with_validation()` (testable)
5. Call `_check_for_duplicates()` after write

---

## Layer 2: Post-Grading Validation

### Validation Query

**Purpose:** Detect duplicates that slip through despite the lock (defense in depth)

```python
def _check_for_duplicates(self, game_date: date) -> int:
    """
    Check for duplicate business keys after grading.

    Business key: (player_lookup, game_id, system_id, line_value)

    Args:
        game_date: Date to check

    Returns:
        Number of duplicate business keys found
    """
    game_date_str = game_date.isoformat()

    validation_query = f"""
    SELECT COUNT(*) as duplicate_count
    FROM (
        SELECT
            player_lookup,
            game_id,
            system_id,
            line_value,
            COUNT(*) as occurrence_count
        FROM `{self.accuracy_table}`
        WHERE game_date = '{game_date}'
        GROUP BY player_lookup, game_id, system_id, line_value
        HAVING COUNT(*) > 1
    )
    """

    try:
        query_job = self.bq_client.query(validation_query)
        result = query_job.result(timeout=30)
        row = next(iter(result))
        duplicate_count = row.duplicate_count or 0

        if duplicate_count > 0:
            # Get details for investigation
            details_query = f"""
            SELECT
                player_lookup,
                game_id,
                system_id,
                line_value,
                COUNT(*) as count,
                ARRAY_AGG(graded_at ORDER BY graded_at) as graded_timestamps
            FROM `{self.accuracy_table}`
            WHERE game_date = '{game_date}'
            GROUP BY player_lookup, game_id, system_id, line_value
            HAVING COUNT(*) > 1
            LIMIT 20
            """

            details_result = self.bq_client.query(details_query).result()
            logger.error(f"  Duplicate details for {game_date}:")
            for row in details_result:
                logger.error(
                    f"    - {row.player_lookup} / {row.system_id} / "
                    f"line={row.line_value}: {row.count}x "
                    f"(timestamps: {row.graded_timestamps})"
                )

        return duplicate_count

    except Exception as e:
        logger.error(f"Error checking for duplicates: {e}")
        # Don't fail grading if validation fails
        return -1  # -1 = validation error
```

**When to Run:** After INSERT completes, BEFORE releasing lock

**What to Do If Duplicates Found:**
- ✅ Log detailed error with duplicate details
- ✅ Trigger alert (Slack notification)
- ⚠️ Don't raise exception (grading succeeds, but flagged)
- ℹ️ Operators investigate and manually deduplicate

**Rationale:** Failing grading due to duplicates could cause cascading failures. Better to complete grading and alert operators.

---

## Layer 3: Monitoring & Alerting

### Daily Validation Script Enhancement

**File:** `bin/validation/daily_data_quality_check.sh`

**Add Grading Duplicate Check:**

```bash
# Check 8: Grading table duplicate business keys (CRITICAL)
echo "Check 8: Grading table duplicate business keys..."
DUPLICATE_GRADING_COUNT=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as duplicate_count
FROM (
    SELECT
        player_lookup,
        game_id,
        system_id,
        line_value,
        COUNT(*) as cnt
    FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAYS)
    GROUP BY 1,2,3,4
    HAVING cnt > 1
)
" | tail -n 1)

if [ "$DUPLICATE_GRADING_COUNT" -gt 0 ]; then
    echo "  ❌ CRITICAL: Found $DUPLICATE_GRADING_COUNT duplicate business keys in grading table (last 7 days)"
    echo "  Action: Check SESSION-94-FIX-DESIGN.md and run deduplication"
    send_slack_alert "🔴 CRITICAL: $DUPLICATE_GRADING_COUNT duplicate grading records detected in last 7 days!"
    FAILURE=1
else
    echo "  ✅ No duplicate business keys in grading table (last 7 days)"
fi
```

### Real-Time Alerting in Grading Function

**Add to orchestration/cloud_functions/grading/main.py:**

```python
def send_duplicate_alert(target_date: str, duplicate_count: int):
    """
    Send Slack alert when duplicates are detected.

    Args:
        target_date: Date that was graded
        duplicate_count: Number of duplicate business keys found
    """
    import requests
    from google.cloud import secretmanager

    try:
        # Get Slack webhook from Secret Manager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        webhook_url = response.payload.data.decode("UTF-8")

        # Send alert
        message = {
            "text": f"🔴 *Grading Duplicate Alert*\n\n"
                   f"*Date:* {target_date}\n"
                   f"*Duplicates:* {duplicate_count} business keys\n"
                   f"*Status:* Grading completed but with duplicates\n"
                   f"*Action Required:* Run deduplication query\n"
                   f"*See:* SESSION-94-FIX-DESIGN.md"
        }

        requests.post(webhook_url, json=message, timeout=10)
        logger.info(f"Sent duplicate alert for {target_date}")

    except Exception as e:
        logger.warning(f"Failed to send duplicate alert: {e}")
```

**Integration:**

```python
# In run_prediction_accuracy_grading()
result = processor.process_date(game_date)

if result.get('duplicate_count', 0) > 0:
    send_duplicate_alert(target_date, result['duplicate_count'])
```

### Monitoring Dashboard

**Add to GCP Monitoring:**

**Metric:** Grading duplicate rate
- **Query:** Percentage of duplicate business keys in prediction_accuracy
- **Alert Threshold:** >0% for dates in last 7 days
- **Notification:** Slack + Email

**Metric:** Grading lock contention
- **Query:** Count of lock acquisition retries from Firestore logs
- **Alert Threshold:** >10 retries in a day
- **Interpretation:** High contention = multiple concurrent operations

---

## Data Cleanup Plan

### Phase 1: Backup Current Data

```bash
# Create backup table
bq mk --table \
  nba-props-platform:nba_predictions.prediction_accuracy_backup_20260117 \
  nba-props-platform:nba_predictions.prediction_accuracy

# Copy all data
bq query --use_legacy_sql=false "
INSERT INTO \`nba-props-platform.nba_predictions.prediction_accuracy_backup_20260117\`
SELECT * FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
"

# Verify row counts match
bq query --use_legacy_sql=false "
SELECT 'original' as table_name, COUNT(*) as row_count
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
UNION ALL
SELECT 'backup', COUNT(*)
FROM \`nba-props-platform.nba_predictions.prediction_accuracy_backup_20260117\`
"
```

### Phase 2: Deduplication Query

**Strategy:** Keep earliest graded_at record for each business key

```sql
-- Step 1: Create deduplicated table
CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.prediction_accuracy_deduped` AS
WITH ranked_records AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY player_lookup, game_id, system_id, line_value
            ORDER BY graded_at ASC  -- Keep earliest
        ) as rn
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
)
SELECT * EXCEPT(rn)
FROM ranked_records
WHERE rn = 1;

-- Step 2: Validate deduplication
SELECT
    'original' as table_name,
    COUNT(*) as total_rows,
    COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id, '|', CAST(line_value AS STRING))) as unique_keys
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
UNION ALL
SELECT
    'deduped',
    COUNT(*),
    COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id, '|', CAST(line_value AS STRING)))
FROM `nba-props-platform.nba_predictions.prediction_accuracy_deduped`;

-- Expected results:
-- original: 497,304 rows, 306,489 unique keys
-- deduped:  306,489 rows, 306,489 unique keys (100% unique)
```

### Phase 3: Replace Production Table

```sql
-- Step 1: Drop old table
DROP TABLE `nba-props-platform.nba_predictions.prediction_accuracy`;

-- Step 2: Rename deduplicated table
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy_deduped`
RENAME TO prediction_accuracy;

-- Step 3: Validate final state
SELECT
    COUNT(*) as total_rows,
    COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id, '|', CAST(line_value AS STRING))) as unique_keys,
    COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id, '|', CAST(line_value AS STRING))) as duplicates
FROM `nba-props-platform.nba_predictions.prediction_accuracy`;

-- Expected: total_rows = unique_keys, duplicates = 0
```

### Phase 4: Recalculate Accuracy Metrics

```bash
# Re-run system daily performance aggregation for affected dates
python orchestration/cloud_functions/grading/main.py \
  --date 2026-01-10 \
  --run-aggregation

python orchestration/cloud_functions/grading/main.py \
  --date 2026-01-14 \
  --run-aggregation

# ... for all affected dates
```

---

## Deployment Plan

### Step 1: Refactor DistributedLock (1 hour)

**Tasks:**
1. Rename `ConsolidationLock` → `DistributedLock`
2. Add `lock_type` parameter
3. Update all existing uses of `ConsolidationLock`
4. Add unit tests for grading lock type

**Files:**
- `predictions/worker/distributed_lock.py` (rename + modify)
- `predictions/worker/batch_staging_writer.py` (update import)
- `tests/workers/test_distributed_lock.py` (update tests)

### Step 2: Update PredictionAccuracyProcessor (2 hours)

**Tasks:**
1. Add `_write_with_validation()` method
2. Add `_check_for_duplicates()` method
3. Update `write_graded_results()` to use lock
4. Add `use_lock` parameter
5. Add comprehensive logging

**Files:**
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

### Step 3: Add Alerting (1 hour)

**Tasks:**
1. Add `send_duplicate_alert()` to grading Cloud Function
2. Update daily validation script
3. Configure Slack webhook in Secret Manager

**Files:**
- `orchestration/cloud_functions/grading/main.py`
- `bin/validation/daily_data_quality_check.sh`

### Step 4: Testing (2 hours)

**Test Cases:**
1. **Unit Tests:**
   - Test lock acquisition with `lock_type="grading"`
   - Test `_check_for_duplicates()` with clean data
   - Test `_check_for_duplicates()` with duplicates

2. **Integration Tests:**
   - Run grading with lock enabled (dry-run mode)
   - Simulate concurrent grading attempts (should serialize)
   - Verify lock release after grading

3. **Validation:**
   - Run grading for test date with lock
   - Verify no duplicates created
   - Verify grading completes successfully

### Step 5: Deploy to Production (30 mins)

**Deployment:**
```bash
# Deploy updated grading function
cd orchestration/cloud_functions/grading
gcloud functions deploy phase5b-grading \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=. \
  --entry-point=main \
  --trigger-topic=nba-grading-trigger \
  --timeout=540s \
  --memory=2048MB \
  --set-env-vars GCP_PROJECT=nba-props-platform

# Verify deployment
gcloud functions describe phase5b-grading \
  --gen2 \
  --region=us-west2 \
  --format=json
```

**Validation:**
- Trigger grading for yesterday
- Check logs for lock acquisition
- Verify no duplicates in validation
- Confirm Slack alerts working (if duplicates detected)

### Step 6: Data Cleanup (2 hours)

**Tasks:**
1. Back up current prediction_accuracy table
2. Run deduplication query
3. Validate deduplicated data
4. Replace production table
5. Recalculate accuracy metrics for affected dates

**See Phase 1-4 in Data Cleanup Plan above**

### Step 7: Monitoring (ongoing)

**Tasks:**
1. Monitor grading for 1 week
2. Check for any new duplicates daily
3. Review lock contention metrics
4. Adjust timeouts if needed

---

## Testing Strategy

### Unit Tests

**File:** `tests/processors/grading/test_prediction_accuracy_processor.py`

```python
def test_check_for_duplicates_clean():
    """Test duplicate check with no duplicates."""
    processor = PredictionAccuracyProcessor(project_id="test-project")

    # Mock BigQuery to return 0 duplicates
    mock_result = Mock()
    mock_result.duplicate_count = 0

    duplicate_count = processor._check_for_duplicates(date(2026, 1, 17))

    assert duplicate_count == 0

def test_check_for_duplicates_with_duplicates():
    """Test duplicate check detects duplicates."""
    processor = PredictionAccuracyProcessor(project_id="test-project")

    # Mock BigQuery to return 5 duplicates
    mock_result = Mock()
    mock_result.duplicate_count = 5

    duplicate_count = processor._check_for_duplicates(date(2026, 1, 17))

    assert duplicate_count == 5

def test_write_graded_results_with_lock():
    """Test grading uses distributed lock."""
    processor = PredictionAccuracyProcessor(project_id="test-project")

    graded_results = [
        {'player_lookup': 'test', 'game_id': 'test', ...}
    ]

    # Mock lock and BigQuery
    with patch('predictions.worker.distributed_lock.DistributedLock') as mock_lock:
        processor.write_graded_results(
            graded_results,
            date(2026, 1, 17),
            use_lock=True
        )

        # Verify lock was acquired
        mock_lock.assert_called_with(
            project_id="test-project",
            lock_type="grading"
        )
        mock_lock.return_value.acquire.assert_called_once()
```

### Integration Tests

**Test Scenario 1: Concurrent Grading Attempts**

```bash
# Terminal 1: Start grading for Jan 17
python -c "
from datetime import date
from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
processor = PredictionAccuracyProcessor()
processor.process_date(date(2026, 1, 17))
"

# Terminal 2: While Terminal 1 is running, attempt concurrent grading
python -c "
from datetime import date
from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
processor = PredictionAccuracyProcessor()
processor.process_date(date(2026, 1, 17))
"

# Expected: Terminal 2 waits for Terminal 1 to complete
# Expected: No duplicates in prediction_accuracy table after both complete
```

**Test Scenario 2: Lock Timeout**

```python
# Simulate stuck lock (doesn't release)
from predictions.worker.distributed_lock import DistributedLock
from datetime import date

lock = DistributedLock(project_id="nba-props-platform", lock_type="grading")

# Acquire lock and hold it
with lock.acquire(game_date="2026-01-17", operation_id="test_stuck"):
    # Sleep for 6 minutes (longer than timeout)
    import time
    time.sleep(360)

# Expected: Lock expires after 5 minutes (TTL)
# Expected: Other operations can acquire lock after expiry
```

---

## Success Criteria

### Immediate (After Deployment)

- ✅ Grading completes successfully with lock enabled
- ✅ No duplicates created in new grading runs
- ✅ Lock acquisition logged in Cloud Function logs
- ✅ Post-grading validation passes (0 duplicates)

### Short-Term (1 Week)

- ✅ Zero duplicates in prediction_accuracy table (last 7 days)
- ✅ All scheduled grading runs successful
- ✅ No lock timeout errors
- ✅ No concurrent grading attempts detected

### Long-Term (1 Month)

- ✅ Accuracy metrics stable and reliable
- ✅ No manual intervention required for duplicate cleanup
- ✅ Dashboard shows 0% duplicate rate
- ✅ System performance unchanged (lock overhead <5%)

---

## Rollback Plan

### If Lock Causes Issues

**Symptoms:**
- Lock timeout errors
- Grading failures
- Lock contention warnings

**Rollback:**
1. Deploy with `use_lock=False` in orchestration/cloud_functions/grading/main.py
2. Temporarily disable distributed locking
3. Investigate lock contention
4. Adjust timeout parameters
5. Re-enable with increased timeout

### If Validation Causes False Positives

**Symptoms:**
- Validation detects duplicates despite lock
- Alerts firing incorrectly

**Mitigation:**
1. Review validation query for bugs
2. Check for schema changes affecting business key
3. Adjust validation logic if needed

### If Performance Degrades

**Symptoms:**
- Grading takes >5 minutes
- Lock acquisition slow (>10 seconds)

**Investigation:**
1. Check Firestore latency
2. Review BigQuery query performance
3. Optimize validation query (add indexes)

---

## Cost Impact

### Firestore Costs

**Operations per Grading Run:**
- Lock acquisition: 1 write + ~3 reads (if contention) + 1 delete
- Average: 5 operations per grading run

**Daily Cost:**
- 1 scheduled run/day × 5 operations = 5 operations/day
- Backfills (rare): +20 operations/backfill
- Monthly: ~150 operations (5/day × 30 days)
- **Cost:** $0.18 per 100k operations = **<$0.01/month**

**Conclusion:** Negligible cost impact

### BigQuery Costs

**Validation Query:**
- Scans: ~500k rows (full prediction_accuracy table)
- Query cost: ~$0.0025 per scan
- Daily: 1 scheduled run = $0.0025/day
- Monthly: **~$0.075/month**

**Conclusion:** Minimal cost impact

### Total Cost

**Monthly:** <$0.10/month for duplicate prevention

**Comparison:** Fixing duplicate data issues manually costs hours of engineering time ($$$)

---

## Future Enhancements

### Database Constraints

**Add Unique Constraint on Business Key:**

```sql
-- This would PREVENT duplicates at database level
-- Currently not supported in BigQuery (no unique constraints)
-- Monitor BigQuery features for this capability

-- Alternative: Use clustering + require merge on write
```

**Workaround:** Use validation query + alerts (current approach)

### Automatic Deduplication

**Add to Daily Maintenance:**

```bash
# Automatically detect and fix duplicates nightly
# Run deduplication for last 7 days if duplicates found
# Alert if deduplication needed (indicates lock failure)
```

### Lock Metrics Dashboard

**Grafana/Cloud Monitoring Dashboard:**
- Lock acquisition time histogram
- Lock contention rate (retries)
- Lock timeout errors
- Grading duration before/after lock

---

## References

- **Session 92 Fix:** `docs/08-projects/current/session-92-duplicate-write-fix/SESSION-92-DUPLICATE-WRITE-FIX.md`
- **Distributed Lock:** `predictions/worker/distributed_lock.py`
- **Root Cause:** `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-ROOT-CAUSE-ANALYSIS.md`

---

**Document Version:** 1.0
**Created:** 2026-01-17
**Session:** 94
**Status:** 📋 DESIGN - Ready for Implementation
