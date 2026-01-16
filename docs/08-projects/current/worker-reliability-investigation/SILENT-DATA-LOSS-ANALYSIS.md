# Silent Data Loss Analysis & Multi-Layer Defense Strategy

**Date**: 2026-01-16
**Status**: Analysis Complete, Implementation Pending
**Severity**: P0 - Silent data loss affecting prediction coverage

---

## Executive Summary

Workers can silently lose prediction data when staging writes fail but completion events are still published. The coordinator believes the worker succeeded, Pub/Sub acks the message, and the data is permanently lost with no retry opportunity.

**Current failure rate**: 30-40% of players per batch (not 1-2 as initially reported)

---

## Root Cause Deep Dive

### The Bug

In `predictions/worker/worker.py`, lines 479-486:

```python
# Line 481: Write to staging (may fail)
write_predictions_to_bigquery(predictions, batch_id=batch_id)

# Line 486: ALWAYS publishes, regardless of write success
publish_completion_event(player_lookup, game_date_str, len(predictions), batch_id=batch_id)

# Line 516: ALWAYS returns 204 success
return ('', 204)
```

The `write_predictions_to_bigquery` function at lines 1349-1362:

```python
except Exception as e:
    # Logs error but DOES NOT RAISE
    logger.error(f"Error writing to staging: {e}")
    # Tracks failure metric but DOES NOT SIGNAL FAILURE TO CALLER
    PredictionWriteMetrics.track_write_attempt(..., success=False, ...)
    # CRITICAL BUG: Does not raise, caller has no idea write failed
```

### Data Flow With Bug

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CURRENT FLOW (BUGGY)                             │
└─────────────────────────────────────────────────────────────────────────────┘

Worker receives Pub/Sub message
         │
         ▼
┌─────────────────────┐
│ Generate predictions│  ◄── Success
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Write to staging    │  ◄── FAILS (exception caught, not raised)
│ table               │
└─────────────────────┘
         │
         ▼                    BUG: No conditional check
┌─────────────────────┐
│ Publish completion  │  ◄── ALWAYS executes
│ event               │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Return 204 to       │  ◄── ALWAYS returns success
│ Pub/Sub             │
└─────────────────────┘
         │
         ▼
   Pub/Sub ACKs message
   (no retry, no DLQ)
         │
         ▼
┌─────────────────────┐
│ Coordinator records │  ◄── Thinks worker succeeded
│ completion          │
└─────────────────────┘
         │
         ▼
   When batch "complete"
         │
         ▼
┌─────────────────────┐
│ Consolidation FAILS │  ◄── Staging table doesn't exist!
│ NotFound: Table...  │
└─────────────────────┘
         │
         ▼
   DATA PERMANENTLY LOST
```

### Why Detection Is Late

| Stage | Can We Detect? | Current Behavior |
|-------|---------------|------------------|
| Staging write fails | YES | Error logged, but swallowed |
| Completion published | NO | No write success flag |
| Coordinator receives | NO | No staging table validation |
| Consolidation runs | YES | NotFound error, but too late |
| Data queried | YES | Missing predictions discovered |

---

## Multi-Layer Defense Strategy

### Layer 1: Fix the Bug at Source (PRIMARY)

**Goal**: Prevent data loss by failing fast and allowing retry

**Change**: Worker returns 500 on staging write failure, triggering Pub/Sub retry

```python
def write_predictions_to_bigquery(...) -> bool:  # ADD RETURN TYPE
    """Returns True on success, False on failure"""
    try:
        result = staging_writer.write_to_staging(...)
        if result.success:
            return True
        else:
            logger.error(f"Staging write failed: {result.error_message}")
            return False
    except Exception as e:
        logger.error(f"Staging write exception: {e}")
        return False  # CHANGED: Signal failure

# In handle_prediction_request:
write_success = write_predictions_to_bigquery(predictions, batch_id=batch_id)
if not write_success:
    logger.error(f"Staging write failed for {player_lookup} - returning 500 for retry")
    return ('Staging write failed', 500)  # CHANGED: Trigger Pub/Sub retry

publish_completion_event(...)  # Only if write succeeded
return ('', 204)
```

**Benefits**:
- Pub/Sub retries failed messages
- After max retries, messages go to DLQ
- DLQ can be monitored and processed
- No silent data loss

### Layer 2: Enhanced Completion Events

**Goal**: Include staging write info in completion events for coordinator validation

**Change**: Add staging table info to completion message

```python
def publish_completion_event(
    player_lookup: str,
    game_date: str,
    prediction_count: int,
    batch_id: str,
    staging_table_name: str = None,  # NEW
    staging_write_success: bool = True  # NEW
):
    message_data = {
        'player_lookup': player_lookup,
        'game_date': game_date,
        'predictions_generated': prediction_count,
        'batch_id': batch_id,
        'staging_table_name': staging_table_name,  # NEW
        'staging_write_success': staging_write_success,  # NEW
        'timestamp': datetime.utcnow().isoformat()
    }
```

**Coordinator can then**:
- Skip counting completions with `staging_write_success=False`
- Track which staging tables to expect during consolidation
- Alert on high staging write failure rate

### Layer 3: Firestore State Enhancement

**Goal**: Track staging tables written, not just player completions

**Change**: Add staging table tracking to batch state

```python
# In BatchState dataclass
staging_tables_written: Dict[str, str] = field(default_factory=dict)
# Maps player_lookup -> staging_table_name

# In record_completion:
if staging_table_name and staging_write_success:
    doc_ref.update({
        'completed_players': ArrayUnion([player_lookup]),
        f'staging_tables_written.{player_lookup}': staging_table_name,  # NEW
        ...
    })
```

**Benefits**:
- Pre-consolidation can verify expected vs actual staging tables
- Can identify exactly which players have missing data
- Enables targeted re-processing

### Layer 4: Pre-Consolidation Verification

**Goal**: Verify staging tables exist before MERGE, proceed with partial data if needed

**Change**: Add verification step before consolidation

```python
def consolidate_batch_with_verification(self, batch_id: str, game_date: str) -> ConsolidationResult:
    # Step 1: Get expected staging tables from Firestore
    state = get_batch_state(batch_id)
    expected_tables = set(state.staging_tables_written.values())

    # Step 2: Get actual staging tables from BigQuery
    actual_tables = set(self._find_staging_tables(batch_id))

    # Step 3: Identify gaps
    missing_tables = expected_tables - actual_tables
    extra_tables = actual_tables - expected_tables  # Unexpected but valid

    if missing_tables:
        logger.error(
            f"STAGING TABLE GAP DETECTED for batch {batch_id}: "
            f"expected={len(expected_tables)}, actual={len(actual_tables)}, "
            f"missing={len(missing_tables)}"
        )
        # Record gap for alerting
        record_data_loss_event(
            batch_id=batch_id,
            missing_tables=list(missing_tables),
            gap_percentage=(len(missing_tables) / len(expected_tables)) * 100
        )

    # Step 4: Proceed with available tables (partial data better than no data)
    if actual_tables:
        return self.consolidate_batch(batch_id, game_date, cleanup=True)
    else:
        return ConsolidationResult(success=False, error_message="No staging tables found")
```

### Layer 5: Post-Consolidation Reconciliation

**Goal**: Verify merged data matches expectations

**Change**: Add reconciliation after successful MERGE

```python
def reconcile_after_consolidation(
    batch_id: str,
    game_date: str,
    expected_players: int,
    consolidation_result: ConsolidationResult
) -> ReconciliationResult:
    """
    Compare merged predictions with expected predictions
    """
    # Query predictions table for this game_date
    query = f"""
    SELECT
        COUNT(DISTINCT player_lookup) as unique_players,
        COUNT(*) as total_predictions,
        COUNT(DISTINCT system_id) as systems_seen
    FROM `{PREDICTIONS_TABLE}`
    WHERE game_date = '{game_date}'
    """
    result = bq_client.query(query).result()
    row = list(result)[0]

    actual_players = row.unique_players
    actual_predictions = row.total_predictions
    systems_seen = row.systems_seen

    # Expected: 5 predictions per player (5 systems)
    expected_predictions = expected_players * 5

    player_gap = expected_players - actual_players
    prediction_gap = expected_predictions - actual_predictions

    if player_gap > 0 or prediction_gap > 0:
        logger.warning(
            f"POST-CONSOLIDATION GAP for {game_date}: "
            f"players: {actual_players}/{expected_players} ({player_gap} missing), "
            f"predictions: {actual_predictions}/{expected_predictions} ({prediction_gap} missing)"
        )

        # Record for alerting/reprocessing
        return ReconciliationResult(
            success=False,
            expected_players=expected_players,
            actual_players=actual_players,
            player_gap=player_gap,
            needs_reprocessing=True
        )

    return ReconciliationResult(success=True, ...)
```

### Layer 6: Daily Reconciliation Job

**Goal**: Catch any gaps that slipped through, enable recovery

**Implementation**: Cloud Function or scheduled job

```python
def daily_prediction_reconciliation():
    """
    Run daily to catch any prediction gaps from previous days
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Step 1: Get games from yesterday
    games = get_games_for_date(yesterday)
    expected_players = get_expected_players_for_games(games)

    # Step 2: Get actual predictions
    query = f"""
    SELECT DISTINCT player_lookup
    FROM `{PREDICTIONS_TABLE}`
    WHERE game_date = '{yesterday}'
    """
    actual_players = set(row.player_lookup for row in bq_client.query(query))

    # Step 3: Find gaps
    missing_players = expected_players - actual_players

    if missing_players:
        logger.error(
            f"PREDICTION GAP DETECTED for {yesterday}: "
            f"{len(missing_players)} players missing predictions"
        )

        # Step 4: Trigger alert
        send_alert(
            severity='WARNING',
            title=f'Prediction Gap: {len(missing_players)} players missing',
            details={
                'game_date': yesterday,
                'missing_players': list(missing_players)[:10],  # First 10
                'total_missing': len(missing_players)
            }
        )

        # Step 5: Optionally trigger re-processing
        if len(missing_players) < 20:  # Small gap, worth retrying
            trigger_reprocessing(yesterday, list(missing_players))
```

---

## Detection Points Summary

| Layer | When | What | Action on Failure |
|-------|------|------|-------------------|
| 1 | Write time | Staging write result | Return 500, Pub/Sub retry |
| 2 | Completion | Event includes write status | Skip counting failed writes |
| 3 | Firestore | Track staging tables | Know expected vs actual |
| 4 | Pre-consolidation | Verify tables exist | Alert, proceed with partial |
| 5 | Post-consolidation | Verify row counts | Alert, flag for reprocessing |
| 6 | Daily job | Cross-reference schedule | Alert, trigger reprocessing |

---

## Implementation Priority

| Priority | Layer | Effort | Impact |
|----------|-------|--------|--------|
| P0 | Layer 1: Fix bug | 30 min | Prevents future data loss |
| P1 | Layer 4: Pre-consolidation verification | 1 hour | Detects gaps before too late |
| P2 | Layer 5: Post-consolidation reconciliation | 1 hour | Confirms data integrity |
| P2 | Layer 2: Enhanced completion events | 30 min | Enables coordinator tracking |
| P3 | Layer 3: Firestore enhancement | 1 hour | Full audit trail |
| P3 | Layer 6: Daily reconciliation | 2 hours | Catch-all safety net |

---

## Monitoring & Alerting

### New Metrics to Track

| Metric | Type | Alert Threshold |
|--------|------|-----------------|
| `staging_write_failures_total` | Counter | >5 per batch |
| `staging_tables_missing` | Gauge | >0 at consolidation |
| `prediction_gap_percentage` | Gauge | >5% |
| `dlq_messages_count` | Gauge | >0 |

### New Alerts

1. **staging-write-failure-rate**: >10% of writes failing
2. **staging-table-gap**: Tables missing at consolidation
3. **prediction-coverage-gap**: Players missing predictions
4. **dlq-accumulation**: Messages in dead letter queue

---

## Testing Strategy

### Unit Tests
- Test write failure returns False
- Test 500 returned on write failure
- Test completion event includes staging info

### Integration Tests
- Simulate staging write failure
- Verify Pub/Sub retry behavior
- Verify DLQ routing after max retries

### End-to-End Validation
- Deploy to staging environment
- Run batch with simulated failures
- Verify gaps detected at each layer
- Verify alerts fire correctly

---

## Rollout Plan

### Phase 1: Deploy Layer 1 Fix (Immediate)
1. Modify `write_predictions_to_bigquery` to return success/failure
2. Modify `handle_prediction_request` to return 500 on failure
3. Test in staging
4. Deploy to production

### Phase 2: Add Verification Layers (Next Session)
1. Implement Layer 4 (pre-consolidation verification)
2. Implement Layer 5 (post-consolidation reconciliation)
3. Add monitoring metrics
4. Deploy

### Phase 3: Full Audit Trail (Future)
1. Implement Layer 2 (enhanced completion events)
2. Implement Layer 3 (Firestore staging tracking)
3. Implement Layer 6 (daily reconciliation job)
4. Deploy
