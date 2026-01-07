# Implementation Plan: Prediction Coverage Fix

**Created:** December 29, 2025
**Status:** Ready for Implementation
**Estimated Effort:** 3-4 days total

---

## Executive Summary

After comprehensive investigation across all phases, we've identified:
- **2 HIGH risk DML concurrency issues** (Prediction Worker, ML Feature Store)
- **12 Phase 2 processors** missing registry integration
- **No monitoring** for prediction coverage or write failures

This plan provides an ordered approach to fix all issues with proper monitoring.

---

## Scope of Changes

### BigQuery DML Concurrency Issues Found

| Component | File | Risk | Fix Priority |
|-----------|------|------|--------------|
| Prediction Worker | `predictions/worker/worker.py` | HIGH | P0 - Immediate |
| ML Feature Store | `data_processors/precompute/ml_feature_store/batch_writer.py` | HIGH | P1 - This Week |
| System Circuit Breaker | `predictions/worker/system_circuit_breaker.py` | MEDIUM | P2 - Next Week |
| Analytics Processors | `upcoming_player_game_context_processor.py` | MEDIUM | P2 - Next Week |

### Player Name Registry Gaps Found

| Component | Count | Risk | Fix Priority |
|-----------|-------|------|--------------|
| Betting Props (OddsAPI, BettingPros) | 2 | HIGH | P0 - Immediate |
| Ball Don't Lie (5 processors) | 5 | HIGH | P1 - This Week |
| ESPN Boxscores | 1 | HIGH | P1 - This Week |
| Basketball Reference | 1 | HIGH | P1 - This Week |
| NBA.com Processors | 4 | MEDIUM | P2 - Next Week |

### Monitoring Gaps Found

| Gap | Impact | Priority |
|-----|--------|----------|
| No BigQuery write success tracking | Can't detect silent failures | P0 |
| No prediction coverage alerting | 57% loss went undetected | P0 |
| No player resolution rate tracking | Name mismatches invisible | P1 |

---

## Ordered Implementation Steps

### Phase 0: Emergency Stabilization (TODAY - 30 min)

**Goal:** Stop the bleeding while we implement proper fixes.

#### Step 0.1: Reduce Worker Concurrency
```bash
gcloud run services update prediction-worker \
  --max-instances=4 \
  --concurrency=3 \
  --region=us-west2
```
- **Impact:** Reduces concurrent MERGE from 100 to 12 (under 20 limit)
- **Trade-off:** Predictions ~3x slower (acceptable for now)

#### Step 0.2: Add Critical Player Aliases
```sql
INSERT INTO nba_reference.player_aliases
(alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display,
 alias_type, alias_source, is_active, notes, created_by, created_at, processed_at)
VALUES
('herbjones', 'herbertjones', 'Herb Jones', 'Herbert Jones',
 'nickname', 'odds_api', TRUE, 'Odds API uses nickname', 'fix_dec29', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
;
```

#### Step 0.3: Re-run Dec 29 Predictions
```bash
curl -X POST https://prediction-coordinator-xxx.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-29", "force": true}'
```

---

### Phase 1: Core Monitoring (Day 1 - 2 hours)

**Goal:** Add visibility before making architectural changes.

#### Step 1.1: Create Prediction Write Metrics

**File:** `predictions/worker/write_metrics.py` (NEW)

```python
"""BigQuery write metrics for prediction worker."""

import logging
from typing import Optional
from shared.utils.metrics_utils import send_metric

logger = logging.getLogger(__name__)

class PredictionWriteMetrics:
    """Track BigQuery write success/failure for predictions."""

    @staticmethod
    def track_write_attempt(
        player_lookup: str,
        records_count: int,
        success: bool,
        duration_seconds: float,
        error_type: Optional[str] = None
    ):
        """Track a BigQuery write attempt."""
        labels = {
            'status': 'success' if success else 'failure',
            'processor': 'prediction_worker'
        }

        send_metric('prediction_write_attempts_total', 1, labels)
        send_metric('prediction_write_records', records_count, labels)
        send_metric('prediction_write_duration_seconds', duration_seconds, labels)

        if not success and error_type:
            error_labels = {**labels, 'error_type': error_type}
            send_metric('prediction_write_errors_total', 1, error_labels)
            logger.error(f"Write failed for {player_lookup}: {error_type}")

    @staticmethod
    def track_dml_rate_limit():
        """Track when we hit BigQuery DML rate limit."""
        send_metric('bq_dml_rate_limit_hits', 1, {'table': 'player_prop_predictions'})
```

#### Step 1.2: Add Coverage Alerting

**File:** `predictions/coordinator/coverage_monitor.py` (NEW)

```python
"""Prediction coverage monitoring and alerting."""

from shared.utils.notification_system import notify_error, notify_warning
from shared.utils.metrics_utils import send_metric

class PredictionCoverageMonitor:
    COVERAGE_THRESHOLD = 95.0  # Alert if < 95%
    CRITICAL_THRESHOLD = 85.0  # Critical if < 85%

    @staticmethod
    def check_coverage(
        players_expected: int,
        players_predicted: int,
        game_date: str
    ) -> bool:
        """Check coverage and alert if below threshold."""
        if players_expected == 0:
            return True

        coverage = (players_predicted / players_expected) * 100

        send_metric('prediction_coverage_percent', coverage, {
            'game_date': game_date
        })

        if coverage < PredictionCoverageMonitor.CRITICAL_THRESHOLD:
            notify_error(
                title=f'CRITICAL: Prediction Coverage {coverage:.1f}%',
                message=f'Only {players_predicted}/{players_expected} players got predictions',
                details={
                    'game_date': game_date,
                    'coverage': f'{coverage:.1f}%',
                    'missing': players_expected - players_predicted
                },
                processor_name='PredictionCoordinator'
            )
            return False

        elif coverage < PredictionCoverageMonitor.COVERAGE_THRESHOLD:
            notify_warning(
                title=f'Prediction Coverage Below Threshold: {coverage:.1f}%',
                message=f'{players_predicted}/{players_expected} players covered',
                details={'game_date': game_date, 'coverage': f'{coverage:.1f}%'}
            )
            return False

        return True
```

#### Step 1.3: Integrate Metrics into Worker

**File:** `predictions/worker/worker.py` - Modify `write_predictions_to_bigquery()`

```python
# Add at top of file
from write_metrics import PredictionWriteMetrics

# Modify write function (around line 1046)
def write_predictions_to_bigquery(predictions, player_lookup):
    start_time = time.time()
    success = False
    error_type = None

    try:
        # ... existing MERGE logic ...
        success = True
    except Exception as e:
        error_msg = str(e)
        if "Too many DML statements" in error_msg:
            error_type = "DML_RATE_LIMIT"
            PredictionWriteMetrics.track_dml_rate_limit()
        else:
            error_type = type(e).__name__
        raise
    finally:
        duration = time.time() - start_time
        PredictionWriteMetrics.track_write_attempt(
            player_lookup=player_lookup,
            records_count=len(predictions),
            success=success,
            duration_seconds=duration,
            error_type=error_type
        )
```

---

### Phase 2: BigQuery Write Pattern Fix (Day 1-2 - 4 hours)

**Goal:** Implement batch consolidation pattern to eliminate DML concurrency issue.

#### Step 2.1: Create Batch Staging Writer

**File:** `predictions/worker/batch_staging_writer.py` (NEW)

```python
"""Batch staging pattern for prediction writes.

Workers write to individual staging tables.
Coordinator consolidates all staging tables in single MERGE.
"""

import time
from google.cloud import bigquery
from typing import List, Dict

class BatchStagingWriter:
    """Write predictions to staging table for later consolidation."""

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        self.bq_client = bq_client
        self.project_id = project_id
        self.staging_dataset = 'nba_predictions'

    def write_to_staging(
        self,
        predictions: List[Dict],
        batch_id: str,
        worker_id: str
    ) -> str:
        """
        Write predictions to batch staging table.

        Uses batch INSERT (not MERGE) - no DML limit concerns.
        Returns staging table name for tracking.
        """
        staging_table = f"{self.staging_dataset}._staging_{batch_id}_{worker_id}"
        full_table_id = f"{self.project_id}.{staging_table}"

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
        )

        load_job = self.bq_client.load_table_from_json(
            predictions,
            full_table_id,
            job_config=job_config
        )
        load_job.result()

        return staging_table


class BatchConsolidator:
    """Consolidate staging tables into main predictions table."""

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        self.bq_client = bq_client
        self.project_id = project_id

    def consolidate_batch(self, batch_id: str, game_date: str) -> int:
        """
        Merge all staging tables for batch into main table.

        Single MERGE operation - complies with DML limits.
        Returns number of rows affected.
        """
        merge_query = f"""
        MERGE `{self.project_id}.nba_predictions.player_prop_predictions` T
        USING (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_date, system_id, current_points_line
                    ORDER BY created_at DESC
                ) as rn
            FROM `{self.project_id}.nba_predictions._staging_{batch_id}_*`
        ) S
        ON T.player_lookup = S.player_lookup
           AND T.game_date = S.game_date
           AND T.system_id = S.system_id
           AND T.current_points_line = S.current_points_line
        WHEN MATCHED AND S.rn = 1 THEN
            UPDATE SET
                predicted_over_probability = S.predicted_over_probability,
                predicted_under_probability = S.predicted_under_probability,
                confidence_score = S.confidence_score,
                updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED AND S.rn = 1 THEN
            INSERT ROW
        """

        result = self.bq_client.query(merge_query).result()
        rows_affected = result.num_dml_affected_rows

        # Cleanup staging tables
        self._cleanup_staging_tables(batch_id)

        return rows_affected

    def _cleanup_staging_tables(self, batch_id: str):
        """Delete staging tables after consolidation."""
        query = f"""
        SELECT table_name
        FROM `{self.project_id}.nba_predictions.INFORMATION_SCHEMA.TABLES`
        WHERE table_name LIKE '_staging_{batch_id}_%'
        """

        tables = list(self.bq_client.query(query).result())
        for row in tables:
            table_id = f"{self.project_id}.nba_predictions.{row.table_name}"
            self.bq_client.delete_table(table_id, not_found_ok=True)
```

#### Step 2.2: Update Worker to Use Staging

Modify `predictions/worker/worker.py` to use staging pattern:

```python
# Replace direct MERGE with staging write
from batch_staging_writer import BatchStagingWriter

staging_writer = BatchStagingWriter(bq_client, PROJECT_ID)

def write_predictions_to_bigquery(predictions, player_lookup, batch_id, worker_id):
    """Write to staging table (no DML limit)."""
    return staging_writer.write_to_staging(predictions, batch_id, worker_id)
```

#### Step 2.3: Update Coordinator to Consolidate

Add consolidation step to `predictions/coordinator/coordinator.py`:

```python
from batch_staging_writer import BatchConsolidator

consolidator = BatchConsolidator(bq_client, PROJECT_ID)

def on_batch_complete(batch_id: str, game_date: str):
    """Called when all workers complete - consolidate staging tables."""
    rows_affected = consolidator.consolidate_batch(batch_id, game_date)
    logger.info(f"Consolidated {rows_affected} predictions for {game_date}")
```

---

### Phase 3: Player Registry Integration (Day 2 - 3 hours)

**Goal:** Integrate RegistryReader into critical processors.

#### Step 3.1: Update Odds API Processor

**File:** `data_processors/raw/oddsapi/odds_api_props_processor.py`

```python
# Add imports at top
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError

class OddsApiPropsProcessor(SmartIdempotencyMixin, ProcessorBase):
    def __init__(self):
        super().__init__()
        # ... existing init ...

        # Add registry reader
        self.registry_reader = RegistryReader(
            source_name='odds_api_props',
            cache_ttl_seconds=300
        )

    def _resolve_player_lookup(self, raw_name: str) -> str:
        """Resolve player name through registry."""
        raw_lookup = normalize_name(raw_name)

        # Try to get canonical lookup via registry
        try:
            # Check if this lookup exists in registry (includes alias check)
            uid = self.registry_reader.get_universal_id(raw_lookup, required=False)
            if uid:
                # Extract canonical lookup from universal_id
                # Format: "lebronjames_001" -> "lebronjames"
                return uid.rsplit('_', 1)[0]
        except Exception as e:
            logger.debug(f"Registry lookup failed for {raw_lookup}: {e}")

        return raw_lookup

    def transform_data(self):
        # ... existing code ...

        for player_name, props in player_props.items():
            # Replace line 482:
            # OLD: 'player_lookup': normalize_name(player_name),
            # NEW:
            player_lookup = self._resolve_player_lookup(player_name)

            row = {
                'player_lookup': player_lookup,
                'player_lookup_raw': normalize_name(player_name),  # Keep original
                # ... rest of row ...
            }
```

#### Step 3.2: Add Missing Aliases

Create script to add all needed aliases:

**File:** `scripts/add_odds_aliases.py`

```python
"""Add aliases for odds API player name mismatches."""

from google.cloud import bigquery
from datetime import datetime

ALIASES_TO_ADD = [
    ('herbjones', 'herbertjones', 'Herb Jones', 'Herbert Jones', 'nickname'),
    ('garytrentjr', 'garytrent', 'Gary Trent Jr.', 'Gary Trent', 'suffix_variation'),
    ('jabarismithjr', 'jabarismith', 'Jabari Smith Jr.', 'Jabari Smith', 'suffix_variation'),
    ('jaimejaquezjr', 'jaimejaquez', 'Jaime Jaquez Jr.', 'Jaime Jaquez', 'suffix_variation'),
    ('michaelporterjr', 'michaelporter', 'Michael Porter Jr.', 'Michael Porter', 'suffix_variation'),
    ('treymurphyiii', 'treymurphy', 'Trey Murphy III', 'Trey Murphy', 'suffix_variation'),
    ('marvinbagleyiii', 'marvinbagley', 'Marvin Bagley III', 'Marvin Bagley', 'suffix_variation'),
    ('robertwilliams', 'robertwilliamsiii', 'Robert Williams', 'Robert Williams III', 'suffix_variation'),
]

def add_aliases():
    client = bigquery.Client()
    now = datetime.utcnow().isoformat()

    for alias in ALIASES_TO_ADD:
        row = {
            'alias_lookup': alias[0],
            'nba_canonical_lookup': alias[1],
            'alias_display': alias[2],
            'nba_canonical_display': alias[3],
            'alias_type': alias[4],
            'alias_source': 'odds_api',
            'is_active': True,
            'notes': 'Added by prediction coverage fix',
            'created_by': 'fix_script',
            'created_at': now,
            'processed_at': now
        }

        # Insert via streaming (or use MERGE for idempotency)
        table_id = 'nba-props-platform.nba_reference.player_aliases'
        errors = client.insert_rows_json(table_id, [row])

        if errors:
            print(f"Error adding {alias[0]}: {errors}")
        else:
            print(f"Added alias: {alias[0]} -> {alias[1]}")

if __name__ == '__main__':
    add_aliases()
```

---

### Phase 4: Restore Full Concurrency (Day 2 - 30 min)

**Goal:** After batch consolidation is deployed, restore full performance.

```bash
# Only after Phase 2 is deployed and tested!
gcloud run services update prediction-worker \
  --max-instances=20 \
  --concurrency=5 \
  --region=us-west2
```

---

### Phase 5: Additional Processor Fixes (Day 3-4)

**Goal:** Fix remaining processors with registry integration.

| Processor | Priority | Estimated Time |
|-----------|----------|----------------|
| `bettingpros_player_props_processor.py` | P1 | 30 min |
| `bdl_active_players_processor.py` | P1 | 30 min |
| `bdl_boxscores_processor.py` | P1 | 30 min |
| `bdl_live_boxscores_processor.py` | P1 | 30 min |
| `bdl_injuries_processor.py` | P1 | 30 min |
| `bdl_player_box_scores_processor.py` | P1 | 30 min |
| `espn_boxscore_processor.py` | P1 | 30 min |
| `br_roster_processor.py` | P1 | 30 min |

Each follows the same pattern as Step 3.1.

---

## Testing Plan

### Unit Tests

```python
# tests/predictions/test_batch_staging_writer.py
def test_write_to_staging():
    """Verify staging write doesn't use MERGE."""
    writer = BatchStagingWriter(mock_client, 'test-project')
    writer.write_to_staging(predictions, 'batch1', 'worker1')

    # Verify load_table_from_json was called (not query with MERGE)
    mock_client.load_table_from_json.assert_called_once()

def test_consolidation_merges_correctly():
    """Verify consolidation uses single MERGE."""
    consolidator = BatchConsolidator(mock_client, 'test-project')
    consolidator.consolidate_batch('batch1', '2025-12-29')

    # Verify single query with MERGE
    assert mock_client.query.call_count == 1
    query = mock_client.query.call_args[0][0]
    assert 'MERGE' in query
```

### Integration Tests

```bash
# Test with reduced concurrency first
gcloud run services update prediction-worker --max-instances=2

# Run predictions for a test date
curl -X POST .../start -d '{"game_date": "2025-12-28", "force": true}'

# Verify all predictions written
bq query 'SELECT COUNT(DISTINCT player_lookup) FROM nba_predictions.player_prop_predictions WHERE game_date = "2025-12-28"'
```

### Monitoring Verification

```sql
-- Verify metrics are being sent
SELECT
  metric_name,
  COUNT(*) as count
FROM `nba-props-platform.monitoring.custom_metrics`
WHERE metric_name LIKE 'prediction_%'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY metric_name;
```

---

## Rollback Plan

### If Batch Consolidation Fails

1. Revert worker to direct MERGE pattern
2. Keep concurrency at 4×3=12
3. Predictions slower but functional

### If Registry Integration Breaks Odds

1. Revert `odds_api_props_processor.py`
2. Keep manual aliases in table
3. Fix and redeploy

---

## Success Criteria

| Metric | Before | Target | Measured By |
|--------|--------|--------|-------------|
| Prediction coverage | 38.6% | >95% | `prediction_coverage_percent` metric |
| BigQuery write success | 43% | 100% | `prediction_write_errors_total` = 0 |
| Player resolution rate | Unknown | >98% | `player_resolution_rate_percent` metric |
| Prediction latency | 2 sec | <5 sec | `prediction_write_duration_seconds` |

---

## Summary

| Phase | Time | Deliverable |
|-------|------|-------------|
| 0: Emergency | 30 min | Stop data loss |
| 1: Monitoring | 2 hours | Visibility into writes and coverage |
| 2: Write Pattern | 4 hours | Batch consolidation eliminates DML issue |
| 3: Registry | 3 hours | Odds processor uses registry |
| 4: Restore | 30 min | Full performance restored |
| 5: Other Processors | 4 hours | All Phase 2 processors use registry |
| **Total** | **~14 hours** | **Full fix with monitoring** |
