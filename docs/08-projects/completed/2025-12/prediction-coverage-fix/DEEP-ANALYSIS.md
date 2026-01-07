# Deep Technical Analysis: BigQuery DML Concurrency

**Created:** December 29, 2025

---

## Understanding BigQuery's DML Limits

### What is the limit?

BigQuery enforces a limit of **20 concurrent DML (Data Manipulation Language) statements** per table. This includes:
- `MERGE` statements
- `UPDATE` statements
- `DELETE` statements
- `INSERT` statements (when part of DML, not streaming)

### Why does this limit exist?

BigQuery uses a **snapshot isolation** model for DML operations. Each DML statement:
1. Takes a snapshot of the table
2. Applies the changes
3. Commits atomically

With too many concurrent DML operations:
- Snapshot overhead becomes expensive
- Conflict resolution becomes complex
- Table metadata updates become a bottleneck

### How does our system violate this?

```
Current Flow:
─────────────
Coordinator publishes 158 messages
    │
    ▼
Pub/Sub delivers to workers (near-simultaneously)
    │
    ▼
Workers scale up (20 instances × 5 threads = 100 potential concurrent)
    │
    ▼
All workers try to MERGE within ~10 seconds
    │
    ▼
BigQuery: "Nope, limit is 20"
```

---

## Deep Dive: Current MERGE Pattern

### The Current Code

```python
# worker.py lines 1020-1100 (simplified)
def write_predictions_to_bigquery(predictions):
    # Create unique staging table
    staging_table_id = f"_staging_predictions_{int(time.time() * 1000)}"

    # Step 1: Load to staging (this is fine - no DML limit)
    load_job = bq_client.load_table_from_json(predictions, staging_table_id)
    load_job.result()

    # Step 2: MERGE from staging to main (THIS IS THE PROBLEM)
    merge_query = f"""
    MERGE `{main_table}` T
    USING `{staging_table_id}` S
    ON T.player_lookup = S.player_lookup AND T.game_date = S.game_date
    WHEN MATCHED THEN UPDATE SET ...
    WHEN NOT MATCHED THEN INSERT ROW
    """
    bq_client.query(merge_query).result()  # <-- DML operation

    # Step 3: Cleanup
    bq_client.delete_table(staging_table_id)
```

### Why Use MERGE?

The MERGE pattern was chosen because:
1. **Idempotency:** Re-running predictions for a player updates existing rows
2. **Pub/Sub retries:** If Pub/Sub retries a message, we don't create duplicates
3. **Atomicity:** Either all 25 predictions for a player are written or none

### The Irony

The staging table approach was designed to avoid DML conflicts, but:
- Load to staging = **no DML limit** (it's a batch load)
- MERGE from staging = **counts against DML limit**

We're hitting the limit in the MERGE step, not the load step.

---

## Alternative Write Strategies

### Strategy 1: INSERT-only with Deduplication

Instead of MERGE, use INSERT and handle duplicates separately.

```python
def write_predictions_insert_only(predictions):
    """Insert without MERGE, dedupe later."""
    table_id = f"{PROJECT_ID}.nba_predictions.player_prop_predictions"

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=PREDICTIONS_SCHEMA
    )

    load_job = bq_client.load_table_from_json(predictions, table_id, job_config=job_config)
    load_job.result()
```

**Deduplication query (run periodically):**
```sql
-- Create deduplicated view
CREATE OR REPLACE TABLE `nba_predictions.player_prop_predictions` AS
SELECT * EXCEPT(row_num)
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY player_lookup, game_date, system_id, current_points_line
               ORDER BY created_at DESC
           ) as row_num
    FROM `nba_predictions.player_prop_predictions`
)
WHERE row_num = 1;
```

**Pros:**
- No DML limit on batch loads
- Simple implementation

**Cons:**
- Table grows with duplicates until cleanup
- Queries see duplicates until cleanup runs
- Need scheduled dedup job

### Strategy 2: Partitioned Staging with Single MERGE

```python
def write_to_batch_staging(predictions, batch_id):
    """All workers write to same staging table, partitioned by worker."""
    staging_table = f"nba_predictions._staging_{batch_id}"

    # Each worker appends to the same staging table
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )

    load_job = bq_client.load_table_from_json(predictions, staging_table, job_config=job_config)
    load_job.result()


def consolidate_batch(batch_id):
    """Single MERGE at the end (called by coordinator)."""
    staging_table = f"nba_predictions._staging_{batch_id}"

    merge_query = f"""
    MERGE `nba_predictions.player_prop_predictions` T
    USING `{staging_table}` S
    ON T.player_lookup = S.player_lookup
       AND T.game_date = S.game_date
       AND T.system_id = S.system_id
    WHEN MATCHED THEN UPDATE SET ...
    WHEN NOT MATCHED THEN INSERT ROW
    """

    bq_client.query(merge_query).result()
    bq_client.delete_table(staging_table)
```

**Pros:**
- Only 1 DML operation total (not 100+)
- Workers run at full speed
- Clean atomic update

**Cons:**
- Need coordinator to know when all workers are done
- Staging table must handle concurrent appends
- Predictions not visible until consolidation

### Strategy 3: Worker-Specific Tables with View

```python
def write_to_worker_table(predictions, worker_id):
    """Each worker has its own table, no conflicts."""
    worker_table = f"nba_predictions.predictions_worker_{worker_id}"

    # Direct load - no conflicts possible
    load_job = bq_client.load_table_from_json(predictions, worker_table)
    load_job.result()
```

**Union view for queries:**
```sql
CREATE OR REPLACE VIEW `nba_predictions.player_prop_predictions_all` AS
SELECT * FROM `nba_predictions.predictions_worker_*`
UNION ALL
SELECT * FROM `nba_predictions.player_prop_predictions_archive`;
```

**Pros:**
- Zero DML conflicts
- Instant visibility
- No consolidation step

**Cons:**
- Many tables to manage
- Query performance across UNION
- Cleanup complexity
- Doesn't support upsert semantics

---

## Retry Logic Deep Dive

### Exponential Backoff with Jitter

Why jitter matters:

```
Without jitter (synchronized retries):
┌─────┐ ┌─────┐ ┌─────┐     ┌─────┐ ┌─────┐ ┌─────┐
│Req 1│ │Req 2│ │Req 3│ ... │Req 1│ │Req 2│ │Req 3│  <-- All retry together!
└─────┘ └─────┘ └─────┘     └─────┘ └─────┘ └─────┘
    ▲                           ▲
 t=0 (initial)              t=2s (first retry)
                            Still 100 concurrent = still rate limited!

With jitter (randomized retries):
┌─────┐ ┌─────┐ ┌─────┐           ┌─────┐     ┌─────┐ ┌─────┐
│Req 1│ │Req 2│ │Req 3│ ...   │Req 1│     │Req 2│ │Req 3│
└─────┘ └─────┘ └─────┘       └─────┘     └─────┘ └─────┘
    ▲                           ▲   ▲   ▲   ▲   ▲
 t=0                          t=1.8 2.1 2.3 2.7 3.1  <-- Spread out!
```

### Implementation with Tenacity

```python
from tenacity import (
    retry,
    wait_exponential_jitter,
    stop_after_attempt,
    retry_if_exception_message,
    before_sleep_log,
    after_log
)

logger = logging.getLogger(__name__)

@retry(
    # Exponential backoff: 1s, 2s, 4s, 8s... with random jitter ±50%
    wait=wait_exponential_jitter(initial=1, max=60, jitter=5),

    # Stop after 5 attempts (total time: ~30s max)
    stop=stop_after_attempt(5),

    # Only retry on rate limit errors
    retry=retry_if_exception_message(match=r"Too many DML|Resources exceeded"),

    # Log before each retry
    before_sleep=before_sleep_log(logger, logging.WARNING),

    # Log final result
    after=after_log(logger, logging.INFO)
)
def write_predictions_with_retry(predictions: List[Dict]):
    """Write predictions with automatic retry on rate limits."""
    write_predictions_to_bigquery(predictions)
```

### Calculating Expected Throughput with Retries

Given:
- 100 concurrent workers
- 20 DML limit
- Average DML duration: ~500ms

Without retries:
- 20 succeed, 80 fail immediately
- Success rate: 20%

With retries (5 attempts, exponential backoff):
```
Attempt 1 (t=0):     20 succeed, 80 queued for retry
Attempt 2 (t=2s):    20 more succeed, 60 queued
Attempt 3 (t=4s):    20 more succeed, 40 queued
Attempt 4 (t=8s):    20 more succeed, 20 queued
Attempt 5 (t=16s):   20 more succeed, 0 remaining

Total time: ~20 seconds for 100 players
Success rate: 100%
```

### Edge Cases

1. **Very long DML operations:** If MERGE takes >500ms, backlog grows
2. **Multiple batches overlapping:** Two coordinators running = 200 workers
3. **External DML operations:** Other systems updating the same table

---

## Cost Analysis

### Current Cost (Broken)

- 158 workers running ~2 seconds each
- 90 failures = wasted compute
- Cloud Run: ~$0.00002/vCPU-second
- Wasted: 90 × 2s × 2vCPU = 360 vCPU-seconds = $0.007

Negligible compute waste, but **57% data loss is the real cost**.

### Solution A: Reduced Concurrency

- Same workers, just slower
- 158 players / 12 concurrent = 14 batches × 2s = 28 seconds
- Same cost, just slower

### Solution B: Retry Logic

- Retries add compute time
- 90 failures × 4 average retries × 0.5s = 180 extra seconds
- Split across workers, adds ~1.2s average per worker
- Minimal cost increase (~$0.002)

### Solution C: Batch Consolidation

- Workers finish faster (no waiting for MERGE)
- One large MERGE at end (~5 seconds)
- Actually cheaper due to less idle time

---

## Monitoring Recommendations

### Key Metrics to Track

```python
# Prometheus metrics to add
from prometheus_client import Counter, Histogram, Gauge

# Write success/failure
prediction_writes_total = Counter(
    'prediction_writes_total',
    'Total prediction write attempts',
    ['status']  # success, failure, retry
)

# Write latency
prediction_write_duration = Histogram(
    'prediction_write_duration_seconds',
    'Time to write predictions to BigQuery',
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60]
)

# Retry count
prediction_write_retries = Counter(
    'prediction_write_retries_total',
    'Number of write retries',
    ['attempt']
)

# Current DML queue depth (estimate)
dml_queue_estimate = Gauge(
    'bigquery_dml_queue_estimate',
    'Estimated pending DML operations'
)
```

### Alerting Rules

```yaml
# Alert if write failure rate exceeds threshold
- alert: PredictionWriteFailureHigh
  expr: |
    rate(prediction_writes_total{status="failure"}[5m])
    / rate(prediction_writes_total[5m]) > 0.1
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Prediction write failure rate > 10%"

# Alert if writes are slow
- alert: PredictionWriteSlow
  expr: |
    histogram_quantile(0.95, prediction_write_duration_seconds) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "95th percentile write latency > 5 seconds"
```

---

## Testing Plan

### Unit Tests

```python
def test_retry_on_dml_limit():
    """Verify retry logic triggers on rate limit error."""
    mock_bq = Mock()
    mock_bq.query.side_effect = [
        ResourceExhausted("Too many DML statements"),
        ResourceExhausted("Too many DML statements"),
        Mock()  # Success on third try
    ]

    write_predictions_with_retry([{"player": "test"}])

    assert mock_bq.query.call_count == 3


def test_retry_gives_up_after_max_attempts():
    """Verify we don't retry forever."""
    mock_bq = Mock()
    mock_bq.query.side_effect = ResourceExhausted("Too many DML statements")

    with pytest.raises(ResourceExhausted):
        write_predictions_with_retry([{"player": "test"}])

    assert mock_bq.query.call_count == 5
```

### Integration Tests

```python
def test_concurrent_writes_succeed():
    """Test that concurrent writes eventually succeed."""
    players = [f"player_{i}" for i in range(50)]

    # Simulate concurrent writes
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(write_predictions_with_retry, [{"player": p}])
            for p in players
        ]
        results = [f.result() for f in futures]

    # Verify all writes succeeded
    assert len(results) == 50
```

### Load Tests

```bash
# Simulate production load
hey -n 200 -c 100 \
  -m POST \
  -H "Content-Type: application/json" \
  -d '{"player_lookup":"test","game_date":"2025-12-29"}' \
  https://prediction-worker-xxx.run.app/predict
```

---

## Conclusion

The BigQuery DML limit is a fundamental constraint that cannot be worked around - only accommodated. The recommended approach is:

1. **Short-term:** Reduce concurrency + add retry logic
2. **Long-term:** Batch consolidation pattern

Both solutions should include proper monitoring to detect future issues before they cause data loss.
