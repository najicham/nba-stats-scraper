# Streaming Buffer Improvements

**Created:** 2026-01-25
**Status:** IN PROGRESS
**Priority:** P0 - Critical data integrity issue

---

## Problem Statement

BigQuery's streaming buffer prevents DELETE operations on recently written data (~30 minutes). When backfilling or reprocessing data:

1. Processor attempts to DELETE existing rows
2. Rows in streaming buffer are NOT deleted
3. INSERT either fails (conflict) or creates duplicates
4. Data gaps occur silently

### Observed Impact (Jan 25, 2026 Backfill)

```
Files Processed: 89
Successful: 33 (37.1%)
Skipped due to streaming conflicts: 56 (62.9%)
```

Many games were skipped because their data was still in the streaming buffer from recent orchestration runs.

---

## Current Handling (As Of Jan 25, 2026)

**File:** `data_processors/raw/balldontlie/bdl_boxscores_processor.py`

### Detection Method

```python
# Line 523-551: Proactive buffer detection
check_query = f"""
SELECT COUNT(*) as total_rows,
       COUNTIF(DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) < 90) as recent_rows
FROM `{table_id}`
WHERE game_id = '{game_id}' AND game_date = '{game_date}'
"""
```

### Current Behavior

1. **Detection:** Checks if rows were processed within 90 minutes
2. **Partial Processing:** Skips conflicting games, processes others
3. **Notification:** Sends Slack/email alerts for conflicts
4. **No Retry:** Relies on external retry (Pub/Sub) - which may not trigger

### Identified Gaps

| Gap | Severity | Current State |
|-----|----------|---------------|
| No automatic retry | P0 | Games silently deferred |
| Rigid 90-min window | P1 | No exponential backoff |
| No conflict metrics | P2 | Can't track patterns |
| Force mode risky | P1 | No validation |
| No circuit breaker | P2 | Can't degrade gracefully |
| Missing documentation | P3 | Operators confused |

---

## Proposed Solution

### Phase 1: Add Automatic Retry (P0)

**Location:** `data_processors/raw/balldontlie/bdl_boxscores_processor.py`

```python
# Add to save_data() method

import time
from typing import List, Dict, Optional

MAX_STREAMING_RETRIES = 3
RETRY_DELAYS_SECONDS = [300, 600, 1200]  # 5min, 10min, 20min

def save_data_with_streaming_retry(
    self,
    rows: List[Dict],
    streaming_conflicts: List[Dict]
) -> Dict:
    """
    Save data with automatic retry for streaming buffer conflicts.

    If streaming conflicts exist:
    1. Process non-conflicting games immediately
    2. Retry conflicting games with exponential backoff
    3. Log unresolved conflicts for manual intervention
    """
    results = {
        'rows_loaded': 0,
        'conflicts_resolved': 0,
        'conflicts_unresolved': [],
    }

    # Process non-conflicting games immediately
    non_conflict_rows = [
        row for row in rows
        if row['game_id'] not in {c['game_id'] for c in streaming_conflicts}
    ]
    if non_conflict_rows:
        loaded = self._do_batch_load(non_conflict_rows)
        results['rows_loaded'] += loaded

    # Retry conflicting games
    if streaming_conflicts:
        conflict_game_ids = {c['game_id'] for c in streaming_conflicts}
        conflict_rows = [row for row in rows if row['game_id'] in conflict_game_ids]

        for attempt, delay in enumerate(RETRY_DELAYS_SECONDS, 1):
            logger.info(
                f"Streaming conflict retry {attempt}/{MAX_STREAMING_RETRIES}: "
                f"waiting {delay}s for {len(conflict_game_ids)} games"
            )

            # Log retry attempt
            self._log_streaming_retry(conflict_game_ids, attempt, delay)

            time.sleep(delay)

            # Re-check which games still have conflicts
            still_conflicting = self._check_streaming_status(conflict_game_ids)
            resolved_ids = conflict_game_ids - still_conflicting

            if resolved_ids:
                # Process resolved games
                resolved_rows = [
                    row for row in conflict_rows
                    if row['game_id'] in resolved_ids
                ]
                loaded = self._do_batch_load(resolved_rows)
                results['rows_loaded'] += loaded
                results['conflicts_resolved'] += len(resolved_ids)

                # Update remaining conflicts
                conflict_game_ids = still_conflicting
                conflict_rows = [
                    row for row in conflict_rows
                    if row['game_id'] in still_conflicting
                ]

            if not conflict_game_ids:
                logger.info("All streaming conflicts resolved")
                break

        # Log unresolved conflicts
        if conflict_game_ids:
            results['conflicts_unresolved'] = list(conflict_game_ids)
            self._log_unresolved_conflicts(conflict_game_ids)

    return results

def _check_streaming_status(self, game_ids: set) -> set:
    """Check which games still have streaming buffer conflicts."""
    still_conflicting = set()

    for game_id in game_ids:
        # Extract game_date from game_id (format: YYYYMMDD_AWAY_HOME)
        game_date = game_id.split('_')[0]
        game_date_formatted = f"{game_date[:4]}-{game_date[4:6]}-{game_date[6:8]}"

        query = f"""
        SELECT COUNT(*) as recent_rows
        FROM `{self.table_id}`
        WHERE game_id = '{game_id}'
          AND game_date = '{game_date_formatted}'
          AND DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) < 30
        """

        result = self.bq_client.query(query).result()
        row = list(result)[0]

        if row.recent_rows > 0:
            still_conflicting.add(game_id)

    return still_conflicting
```

### Phase 2: Add Conflict Logging (P1)

**Create table:**
```sql
-- schemas/bigquery/nba_orchestration/streaming_conflict_log.sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.streaming_conflict_log` (
  conflict_id STRING NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  processor_name STRING NOT NULL,
  game_id STRING,
  game_date DATE,
  conflict_type STRING,  -- 'streaming_buffer', 'concurrent_dml', 'quota_exceeded'
  retry_attempt INT64,
  max_retries INT64,
  delay_seconds INT64,
  resolved BOOL,
  resolution_time TIMESTAMP,
  resolution_method STRING,  -- 'auto_retry', 'manual', 'force_mode', 'timeout'
  rows_affected INT64,
  error_message STRING,
  details JSON
)
PARTITION BY DATE(timestamp)
CLUSTER BY processor_name, game_date;
```

**Add logging function:**
```python
def _log_streaming_conflict(
    self,
    game_id: str,
    game_date: str,
    retry_attempt: int,
    resolved: bool,
    resolution_method: str = None,
    error_message: str = None
):
    """Log streaming conflict to BigQuery for monitoring."""
    import uuid
    from datetime import datetime

    record = {
        'conflict_id': str(uuid.uuid4()),
        'timestamp': datetime.utcnow().isoformat(),
        'processor_name': self.__class__.__name__,
        'game_id': game_id,
        'game_date': game_date,
        'conflict_type': 'streaming_buffer',
        'retry_attempt': retry_attempt,
        'max_retries': MAX_STREAMING_RETRIES,
        'delay_seconds': RETRY_DELAYS_SECONDS[retry_attempt - 1] if retry_attempt <= len(RETRY_DELAYS_SECONDS) else None,
        'resolved': resolved,
        'resolution_time': datetime.utcnow().isoformat() if resolved else None,
        'resolution_method': resolution_method,
        'error_message': error_message,
    }

    try:
        self.bq_client.insert_rows_json(
            'nba-props-platform.nba_orchestration.streaming_conflict_log',
            [record]
        )
    except Exception as e:
        logger.error(f"Failed to log streaming conflict: {e}")
```

### Phase 3: Add Circuit Breaker (P2)

```python
# Add circuit breaker to prevent cascading failures

CIRCUIT_BREAKER_THRESHOLD = 0.5  # Trip if >50% of games conflict
CIRCUIT_BREAKER_COOLDOWN = 1800  # 30 minutes

class StreamingCircuitBreaker:
    def __init__(self):
        self.conflict_count = 0
        self.total_count = 0
        self.tripped_at = None

    def record(self, has_conflict: bool):
        self.total_count += 1
        if has_conflict:
            self.conflict_count += 1

    def should_trip(self) -> bool:
        if self.total_count < 3:
            return False
        return (self.conflict_count / self.total_count) > CIRCUIT_BREAKER_THRESHOLD

    def trip(self):
        self.tripped_at = datetime.utcnow()
        logger.warning(
            f"Circuit breaker tripped: {self.conflict_count}/{self.total_count} "
            f"games have streaming conflicts. Pausing for {CIRCUIT_BREAKER_COOLDOWN}s"
        )
        notify_warning(
            title="Streaming Buffer Circuit Breaker Tripped",
            message=f"Pausing processing due to high conflict rate",
            details={
                'conflict_rate': f"{self.conflict_count}/{self.total_count}",
                'cooldown_seconds': CIRCUIT_BREAKER_COOLDOWN,
            }
        )

    def is_open(self) -> bool:
        if self.tripped_at is None:
            return False
        elapsed = (datetime.utcnow() - self.tripped_at).total_seconds()
        return elapsed < CIRCUIT_BREAKER_COOLDOWN
```

### Phase 4: Monitoring Dashboard Query

```sql
-- Daily streaming conflict summary
SELECT
  DATE(timestamp) as date,
  processor_name,
  COUNT(*) as total_conflicts,
  COUNTIF(resolved) as resolved,
  COUNTIF(NOT resolved) as unresolved,
  AVG(retry_attempt) as avg_retries,
  ARRAY_AGG(DISTINCT game_id LIMIT 10) as sample_games
FROM `nba_orchestration.streaming_conflict_log`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date, processor_name
ORDER BY date DESC, total_conflicts DESC;

-- Unresolved conflicts requiring attention
SELECT
  conflict_id,
  timestamp,
  processor_name,
  game_id,
  game_date,
  retry_attempt,
  error_message
FROM `nba_orchestration.streaming_conflict_log`
WHERE NOT resolved
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC;
```

---

## Implementation Plan

### Week 1 (Immediate)
- [ ] Add automatic retry logic to `bdl_boxscores_processor.py`
- [ ] Create `streaming_conflict_log` table
- [ ] Add conflict logging

### Week 2
- [ ] Add circuit breaker
- [ ] Create monitoring dashboard
- [ ] Add to daily health check

### Week 3
- [ ] Apply pattern to other processors with streaming conflicts
- [ ] Create runbook for operators
- [ ] Add alerting for persistent conflicts

---

## Validation

After implementation, verify:

1. **Retry works:**
   ```bash
   # Run backfill, check logs for retry messages
   PYTHONPATH=. python backfill_jobs/raw/bdl_boxscores/bdl_boxscores_raw_backfill.py --dates 2026-01-24 2>&1 | grep -i "retry"
   ```

2. **Conflicts are logged:**
   ```sql
   SELECT * FROM nba_orchestration.streaming_conflict_log
   WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
   ORDER BY timestamp DESC;
   ```

3. **Circuit breaker trips:**
   - Simulate high conflict rate
   - Verify processing pauses
   - Verify notification sent

---

## Related Documentation

- `docs/08-projects/completed/streaming-buffer-migration/` - Migration from streaming inserts
- `data_processors/raw/processor_base.py` - Base class streaming buffer handling
- `shared/utils/bigquery_retry.py` - Retry utilities

---

## Changelog

| Date | Change |
|------|--------|
| 2026-01-25 | Created document, identified gaps |
| | Proposed 4-phase solution |

---

**Owner:** TBD
**Reviewer:** TBD
