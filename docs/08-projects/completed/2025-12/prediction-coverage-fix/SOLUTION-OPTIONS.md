# Solution Options: Prediction Coverage Fix

**Created:** December 29, 2025
**Status:** Under Review

---

## Problem Recap

BigQuery limits concurrent DML operations to 20 per table. Our prediction worker spawns 100+ concurrent processes that all try to MERGE to the same table simultaneously, causing 57% of writes to fail.

---

## Solution Comparison Matrix

| Solution | Complexity | Reliability | Performance | Cost | Recommendation |
|----------|------------|-------------|-------------|------|----------------|
| A: Reduce Concurrency | Low | Medium | Slow | None | Quick fix only |
| B: Retry with Backoff | Medium | High | Medium | None | Good short-term |
| C: Batch Consolidation | High | Very High | Fast | Low | Best long-term |
| D: Streaming Buffer | High | Very High | Fast | Medium | Over-engineered |
| E: Hybrid Approach | Medium | High | Fast | Low | **Recommended** |

---

## Solution A: Reduce Worker Concurrency

### Concept

Simply reduce the number of concurrent workers to stay under BigQuery's 20 DML limit.

### Implementation

```yaml
# Cloud Run service configuration
apiVersion: serving.knative.dev/v1
kind: Service
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "4"    # Was 20
    spec:
      containerConcurrency: 3                     # Was 5
```

**Effective concurrency:** 4 instances × 3 threads = 12 (under 20 limit)

### Pros
- Trivial to implement (one config change)
- No code changes required
- Can be done immediately

### Cons
- **Significantly slower:** 158 players at 12 concurrent = ~13 sequential batches
- At ~2 seconds per player = ~26 seconds vs current ~2 seconds
- Doesn't scale for larger game days (400+ players)
- Wastes compute resources (workers sitting idle)

### Verdict: **Quick fix only** - Use for immediate relief, not long-term

---

## Solution B: Retry with Exponential Backoff

### Concept

Add retry logic to the BigQuery write operation with exponential backoff and jitter.

### Implementation

```python
# predictions/worker/worker.py

from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from google.api_core.exceptions import ResourceExhausted, TooManyRequests

class BigQueryWriteError(Exception):
    """Custom exception for retriable BigQuery errors"""
    pass

@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type((ResourceExhausted, TooManyRequests, BigQueryWriteError))
)
def write_predictions_to_bigquery_with_retry(predictions: List[Dict]):
    """
    Write predictions with automatic retry on rate limiting.

    Retry strategy:
    - Attempt 1: immediate
    - Attempt 2: wait 2s
    - Attempt 3: wait 4s
    - Attempt 4: wait 8s
    - Attempt 5: wait 16s
    Total max wait: ~30 seconds
    """
    try:
        write_predictions_to_bigquery(predictions)
    except Exception as e:
        error_msg = str(e)
        if "Too many DML statements" in error_msg:
            logger.warning(f"DML rate limit hit, will retry: {e}")
            raise BigQueryWriteError(error_msg) from e
        elif "Resources exceeded" in error_msg:
            logger.warning(f"Resource limit hit, will retry: {e}")
            raise BigQueryWriteError(error_msg) from e
        else:
            # Non-retriable error
            raise
```

### Pros
- Moderate implementation effort
- Self-healing - eventually all writes succeed
- Maintains high concurrency for speed
- Works with existing architecture

### Cons
- Increases overall batch time (retries add latency)
- Still hitting rate limits (just recovering from them)
- Could cause cascading delays under heavy load
- Adds dependency on `tenacity` library

### Metrics to Add

```python
# Track retry statistics
RETRY_COUNTER = Counter('prediction_write_retries_total',
                        'Number of BigQuery write retries',
                        ['attempt_number'])

WRITE_LATENCY = Histogram('prediction_write_seconds',
                          'Time to write predictions to BigQuery')
```

### Verdict: **Good short-term** - Solves the problem but doesn't address root cause

---

## Solution C: Batch Consolidation Pattern

### Concept

Instead of each worker writing directly to the predictions table, workers write to individual staging tables. A consolidation job then merges all staging tables into the main table in a single operation.

### Architecture

```
                     ┌────────────────────────────────────┐
                     │        Prediction Workers          │
                     │  (100 concurrent, each writes to   │
                     │   its own staging table)           │
                     └─────────────────┬──────────────────┘
                                       │
          ┌────────────────────────────┼────────────────────────────┐
          ▼                            ▼                            ▼
   ┌─────────────┐              ┌─────────────┐              ┌─────────────┐
   │ staging_001 │              │ staging_002 │     ...      │ staging_100 │
   │ (25 rows)   │              │ (25 rows)   │              │ (25 rows)   │
   └──────┬──────┘              └──────┬──────┘              └──────┬──────┘
          │                            │                            │
          └────────────────────────────┼────────────────────────────┘
                                       │
                                       ▼
                     ┌────────────────────────────────────┐
                     │      Consolidation Job             │
                     │  (Single MERGE from all staging    │
                     │   to main predictions table)       │
                     └─────────────────┬──────────────────┘
                                       │
                                       ▼
                     ┌────────────────────────────────────┐
                     │   player_prop_predictions          │
                     │   (final destination)              │
                     └────────────────────────────────────┘
```

### Implementation

**Step 1: Worker writes to unique staging table**
```python
def write_predictions_to_staging(predictions: List[Dict], worker_id: str):
    """Write to worker-specific staging table (no DML conflicts)."""
    staging_table = f"nba_predictions._staging_{worker_id}"

    # Use INSERT (not MERGE) - much faster, no conflicts
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=PREDICTIONS_SCHEMA
    )

    load_job = bq_client.load_table_from_json(predictions, staging_table, job_config=job_config)
    load_job.result()
```

**Step 2: Coordinator triggers consolidation after all workers complete**
```python
def consolidate_predictions(batch_id: str, game_date: str):
    """Merge all staging tables into main predictions table."""

    # Find all staging tables for this batch
    query = f"""
    MERGE `nba_predictions.player_prop_predictions` T
    USING (
        SELECT * FROM `nba_predictions._staging_*`
        WHERE _TABLE_SUFFIX LIKE '{batch_id}%'
    ) S
    ON T.player_lookup = S.player_lookup
       AND T.game_date = S.game_date
       AND T.system_id = S.system_id
       AND T.current_points_line = S.current_points_line
    WHEN MATCHED THEN UPDATE SET ...
    WHEN NOT MATCHED THEN INSERT ROW
    """

    bq_client.query(query).result()

    # Cleanup staging tables
    cleanup_staging_tables(batch_id)
```

### Pros
- Eliminates DML conflicts entirely
- Workers run at full speed (no rate limiting)
- Single MERGE is more efficient than 100+ individual MERGEs
- Clean separation of concerns

### Cons
- Higher implementation complexity
- Requires coordinator changes
- Staging table cleanup needed
- Adds latency (consolidation step at end)
- Predictions not available until consolidation completes

### Verdict: **Best long-term** - Properly solves the architectural issue

---

## Solution D: Streaming Buffer Pattern

### Concept

Use BigQuery's streaming insert API which has different (higher) rate limits, then periodically flush to the main table.

### Implementation

```python
def stream_predictions(predictions: List[Dict]):
    """Use streaming insert (different rate limits than DML)."""
    table_ref = bq_client.dataset('nba_predictions').table('predictions_stream')

    errors = bq_client.insert_rows_json(table_ref, predictions)
    if errors:
        logger.error(f"Streaming insert errors: {errors}")
        raise StreamingInsertError(errors)
```

### Streaming vs DML Limits

| Operation | Limit |
|-----------|-------|
| DML (MERGE/UPDATE/DELETE) | 20 concurrent per table |
| Streaming inserts | 100,000 rows/second per table |

### Pros
- Much higher throughput limits
- Data available immediately (streaming buffer)
- Simple implementation

### Cons
- Streaming has eventual consistency (data may take seconds to appear)
- Can't do MERGE logic (only INSERT)
- Would need separate deduplication process
- Streaming costs more than batch loads
- Streaming buffer has 7-day retention

### Verdict: **Over-engineered** - Adds complexity without proportional benefit

---

## Solution E: Hybrid Approach (RECOMMENDED)

### Concept

Combine the best elements:
1. **Immediate:** Reduce concurrency to stop the bleeding
2. **Short-term:** Add retry logic for resilience
3. **Medium-term:** Implement batch consolidation

### Phase 1: Emergency Fix (Today)

```bash
# Reduce concurrency immediately
gcloud run services update prediction-worker \
  --max-instances=4 \
  --concurrency=3 \
  --region=us-west2
```

### Phase 2: Add Retry Logic (This Week)

```python
# Add to worker.py
from tenacity import retry, wait_exponential_jitter, stop_after_attempt

@retry(
    wait=wait_exponential_jitter(initial=1, max=30),
    stop=stop_after_attempt(3)
)
def write_predictions_with_retry(predictions):
    write_predictions_to_bigquery(predictions)
```

### Phase 3: Batch Consolidation (Next Sprint)

Implement the full staging table + consolidation pattern for production reliability.

### Phase 4: Monitoring (Ongoing)

```python
# Add write success tracking
def track_write_result(player_lookup: str, success: bool, error: str = None):
    """Track individual write results for monitoring."""
    row = {
        'player_lookup': player_lookup,
        'timestamp': datetime.utcnow().isoformat(),
        'success': success,
        'error': error
    }
    # Stream to monitoring table
    bq_client.insert_rows_json('nba_monitoring.prediction_writes', [row])
```

---

## Additional Fix: Player Lookup Normalization

### Implementation

Add normalization during odds ingestion (Phase 2):

```python
# shared/utils/player_normalization.py

import re

SUFFIX_PATTERNS = [
    (r'jr\.?$', ''),      # Remove Jr./Jr
    (r'sr\.?$', ''),      # Remove Sr./Sr
    (r'iii$', ''),        # Remove III
    (r'ii$', ''),         # Remove II
    (r'iv$', ''),         # Remove IV
]

def normalize_player_lookup(raw_lookup: str) -> str:
    """
    Normalize player lookup for consistent matching.

    Examples:
        garytrentjr -> garytrent
        marvinbagleyiii -> marvinbagley
        lebron-james -> lebronjames
    """
    normalized = raw_lookup.lower().strip()
    normalized = normalized.replace('-', '').replace(' ', '').replace('.', '')

    for pattern, replacement in SUFFIX_PATTERNS:
        normalized = re.sub(pattern, replacement, normalized)

    return normalized


def create_lookup_variants(raw_lookup: str) -> List[str]:
    """
    Create multiple lookup variants for fuzzy matching.

    Returns both the normalized form and common variants.
    """
    base = normalize_player_lookup(raw_lookup)
    variants = [base, raw_lookup.lower()]

    # Add suffix variants
    if not any(raw_lookup.endswith(s) for s in ['jr', 'sr', 'ii', 'iii', 'iv']):
        variants.extend([f"{base}jr", f"{base}ii", f"{base}iii"])

    return list(set(variants))
```

### Integration Point

```python
# In odds ingestion processor
from shared.utils.player_normalization import normalize_player_lookup

def process_odds_record(record: Dict) -> Dict:
    raw_lookup = record['player_lookup']
    normalized = normalize_player_lookup(raw_lookup)

    return {
        **record,
        'player_lookup': normalized,        # Use normalized for joins
        'player_lookup_raw': raw_lookup     # Keep original for debugging
    }
```

---

## Recommendation

**Implement Solution E (Hybrid Approach)** in phases:

| Phase | Action | Timeline | Effort |
|-------|--------|----------|--------|
| 1 | Reduce concurrency | Today | 5 min |
| 2 | Re-run Dec 29 predictions | Today | 10 min |
| 3 | Add retry logic | This week | 2 hours |
| 4 | Add write monitoring | This week | 2 hours |
| 5 | Batch consolidation | Next sprint | 1 day |
| 6 | Player normalization | Next sprint | 4 hours |

---

## Decision Needed

1. **Confirm Phase 1 emergency fix** - Reduce concurrency today?
2. **Approve retry logic approach** - Use tenacity library?
3. **Prioritize batch consolidation** - Include in next sprint?
4. **Player normalization scope** - Fix in odds ingestion or create mapping table?
