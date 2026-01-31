# Technical Implementation Guide: BDB Reprocessing Pipeline

**Project**: BigDataBall Reprocessing Strategy
**Date**: 2026-01-31
**Status**: Implementation Guide

## Overview

This guide provides detailed technical specifications for implementing automatic prediction regeneration when BigDataBall (BDB) data arrives late.

---

## Component 1: Extended BDB Retry Processor

### Current State (Session 53)

**File**: `bin/monitoring/bdb_retry_processor.py`

**Existing Functionality** ✅:
- Reads from `pending_bdb_games` table
- Checks BDB availability hourly
- Triggers Phase 3 re-run via Pub/Sub `nba-phase3-trigger`
- Updates status: `pending_bdb` → `completed_bdb`
- Progressive backoff (max 72 checks)

**What's Missing** ❌:
- Phase 4 trigger
- Phase 5 prediction regeneration trigger
- Superseding old predictions

### Enhancement Specification

**Location**: `bin/monitoring/bdb_retry_processor.py` (lines 260-290)

**Replace**:
```python
def trigger_phase3_rerun(self, game: Dict) -> bool:
    """Trigger Phase 3 re-processing for a game that now has BDB data."""
    # Existing code...
    return True
```

**With**:
```python
def trigger_full_reprocessing_pipeline(self, game: Dict) -> bool:
    """
    Trigger complete re-processing when BDB data arrives.

    Pipeline:
    1. Phase 3: player_game_summary (existing)
    2. Phase 4: precompute processors (NEW)
    3. Phase 5: prediction regeneration (NEW)
    4. Grading: re-grade if game complete (NEW)

    Args:
        game: Game metadata from pending_bdb_games table

    Returns:
        True if all triggers succeeded, False otherwise
    """
    game_date = game['game_date']
    game_id = game['game_id']
    success = True

    logger.info(f"Starting full reprocessing pipeline for {game_id} ({game_date})")

    # Step 1: Phase 3 Re-run (existing logic)
    if not self.trigger_phase3_rerun(game):
        logger.error(f"Phase 3 trigger failed for {game_id}")
        success = False
        # Continue anyway - partial pipeline is better than nothing

    # Step 2: Phase 4 Re-run (NEW)
    if not self._trigger_phase4_rerun(game_date):
        logger.error(f"Phase 4 trigger failed for {game_date}")
        success = False

    # Step 3: Phase 5 Prediction Regeneration (NEW)
    if not self._trigger_phase5_regeneration(game_date, game):
        logger.error(f"Phase 5 trigger failed for {game_date}")
        success = False

    # Step 4: Re-grade if game complete (NEW - optional)
    if self._is_game_complete(game_date):
        if not self._trigger_regrading(game_date):
            logger.warning(f"Re-grading trigger failed for {game_date}")
            # Don't fail overall - re-grading is nice-to-have

    logger.info(
        f"Full reprocessing pipeline {'succeeded' if success else 'partially failed'} "
        f"for {game_id}"
    )
    return success

def _trigger_phase4_rerun(self, game_date: str) -> bool:
    """Trigger Phase 4 precompute processors for specific date."""
    if self.dry_run:
        logger.info(f"[DRY-RUN] Would trigger Phase 4 re-run for {game_date}")
        return True

    if not self.publisher:
        logger.warning("Pub/Sub not available, cannot trigger Phase 4")
        return False

    try:
        topic_path = self.publisher.topic_path(
            self.project_id,
            'nba-phase4-trigger'
        )
        message = json.dumps({
            'game_date': game_date,
            'reason': 'bdb_data_available',
            'mode': 'reprocess_specific_date',
            'processors': [
                'player_shot_zone_analysis',
                'player_composite_factors',
                'player_daily_cache',
                'ml_feature_store'
            ],
            'priority': 'normal',
            'source': 'bdb_retry_processor'
        }).encode('utf-8')

        future = self.publisher.publish(topic_path, message)
        future.result(timeout=30)
        logger.info(f"✅ Triggered Phase 4 re-run for {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to trigger Phase 4: {e}")
        return False

def _trigger_phase5_regeneration(self, game_date: str, game: Dict) -> bool:
    """Trigger Phase 5 prediction regeneration with superseding."""
    if self.dry_run:
        logger.info(f"[DRY-RUN] Would trigger Phase 5 regeneration for {game_date}")
        return True

    if not self.publisher:
        logger.warning("Pub/Sub not available, cannot trigger Phase 5")
        return False

    try:
        topic_path = self.publisher.topic_path(
            self.project_id,
            'nba-prediction-trigger'
        )
        message = json.dumps({
            'game_date': game_date,
            'reason': 'bdb_upgrade',
            'mode': 'regenerate_with_supersede',
            'metadata': {
                'original_source': game.get('fallback_source'),
                'upgrade_from': 'nbac_fallback',
                'upgrade_to': 'bigdataball',
                'quality_before': game.get('quality_before_rerun', 'silver'),
                'trigger_type': 'bdb_retry_processor',
                'bdb_check_count': game.get('bdb_check_count', 0),
                'bdb_available_at': datetime.now(timezone.utc).isoformat()
            }
        }).encode('utf-8')

        future = self.publisher.publish(topic_path, message)
        future.result(timeout=30)
        logger.info(f"✅ Triggered Phase 5 regeneration for {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to trigger Phase 5: {e}")
        return False

def _is_game_complete(self, game_date: str) -> bool:
    """Check if game is complete (for re-grading)."""
    # Game is complete if game_date is in the past
    try:
        game_dt = date.fromisoformat(game_date) if isinstance(game_date, str) else game_date
        return game_dt < date.today()
    except Exception:
        return False

def _trigger_regrading(self, game_date: str) -> bool:
    """Trigger re-grading of predictions for completed game."""
    if self.dry_run:
        logger.info(f"[DRY-RUN] Would trigger re-grading for {game_date}")
        return True

    # Implementation depends on grading system architecture
    # Could be Pub/Sub trigger or HTTP endpoint call
    logger.info(f"Re-grading trigger for {game_date} (not yet implemented)")
    return True
```

**Integration Point**:
Replace call to `trigger_phase3_rerun()` with `trigger_full_reprocessing_pipeline()` at line 362.

---

## Component 2: Prediction Coordinator Enhancement

### New Endpoint: `/regenerate-with-supersede`

**File**: `predictions/coordinator/coordinator.py`

**Add after existing `/start` endpoint**:

```python
@app.route('/regenerate-with-supersede', methods=['POST'])
def regenerate_with_supersede():
    """
    Regenerate predictions for a specific date and supersede old ones.

    This endpoint is triggered when upstream features change (e.g., BDB data arrives).

    Request body:
    {
        "game_date": "2026-01-17",
        "reason": "bdb_upgrade",
        "metadata": {
            "upgrade_from": "nbac_fallback",
            "upgrade_to": "bigdataball",
            "quality_before": "silver",
            ...
        }
    }

    Response:
    {
        "status": "success",
        "game_date": "2026-01-17",
        "superseded_count": 142,
        "regenerated_count": 145,
        "processing_time_seconds": 12.3
    }
    """
    start_time = time.time()

    try:
        # Parse request
        data = request.json
        game_date = data['game_date']
        reason = data.get('reason', 'feature_upgrade')
        metadata = data.get('metadata', {})

        logger.info(f"Starting prediction regeneration for {game_date}, reason: {reason}")

        # Step 1: Mark existing predictions as superseded
        superseded_count = _mark_predictions_superseded(game_date, reason, metadata)
        logger.info(f"Marked {superseded_count} predictions as superseded")

        # Step 2: Generate new predictions
        result = _generate_predictions_for_date(game_date, metadata)
        regenerated_count = result.get('predictions_generated', 0)
        logger.info(f"Generated {regenerated_count} new predictions")

        # Step 3: Track in audit log
        _log_prediction_regeneration(game_date, reason, metadata, {
            'superseded_count': superseded_count,
            'regenerated_count': regenerated_count
        })

        processing_time = time.time() - start_time

        return jsonify({
            'status': 'success',
            'game_date': game_date,
            'superseded_count': superseded_count,
            'regenerated_count': regenerated_count,
            'processing_time_seconds': round(processing_time, 2)
        })

    except Exception as e:
        logger.error(f"Prediction regeneration failed: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


def _mark_predictions_superseded(
    game_date: str,
    reason: str,
    metadata: Dict
) -> int:
    """
    Mark existing predictions for a date as superseded.

    Args:
        game_date: Date of predictions to supersede
        reason: Reason for superseding (e.g., 'bdb_upgrade')
        metadata: Additional context

    Returns:
        Number of predictions marked as superseded
    """
    from google.cloud import bigquery

    client = bigquery.Client()
    project_id = client.project

    # Query to update existing predictions
    query = f"""
    UPDATE `{project_id}.nba_predictions.player_prop_predictions`
    SET
        superseded = TRUE,
        superseded_at = CURRENT_TIMESTAMP(),
        superseded_reason = @reason,
        superseded_metadata = @metadata
    WHERE game_date = @game_date
      AND (superseded IS NULL OR superseded = FALSE)
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "STRING", game_date),
            bigquery.ScalarQueryParameter("reason", "STRING", reason),
            bigquery.ScalarQueryParameter("metadata", "JSON", json.dumps(metadata))
        ]
    )

    query_job = client.query(query, job_config=job_config)
    result = query_job.result()

    # Get count of updated rows
    superseded_count = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0

    logger.info(f"Marked {superseded_count} predictions as superseded for {game_date}")
    return superseded_count


def _generate_predictions_for_date(
    game_date: str,
    metadata: Dict
) -> Dict:
    """
    Generate new predictions for a specific date.

    Reuses existing prediction generation logic but for historical date.

    Args:
        game_date: Date to generate predictions for
        metadata: Context metadata (BDB upgrade info, etc.)

    Returns:
        Dict with generation results
    """
    # This would call existing prediction generation code
    # but with date override instead of CURRENT_DATE

    # Placeholder - actual implementation would call worker
    logger.info(f"Generating predictions for {game_date} with metadata: {metadata}")

    # TODO: Implement actual prediction generation for historical date
    # Could reuse PredictionBatchProcessor with date override

    return {
        'predictions_generated': 0,  # Placeholder
        'status': 'not_yet_implemented'
    }


def _log_prediction_regeneration(
    game_date: str,
    reason: str,
    metadata: Dict,
    results: Dict
) -> None:
    """
    Log prediction regeneration event to audit table.

    Args:
        game_date: Date regenerated
        reason: Reason for regeneration
        metadata: Context metadata
        results: Regeneration results (counts, etc.)
    """
    from google.cloud import bigquery

    client = bigquery.Client()
    project_id = client.project

    audit_record = {
        'regeneration_timestamp': datetime.now(timezone.utc).isoformat(),
        'game_date': game_date,
        'reason': reason,
        'metadata': metadata,
        'superseded_count': results.get('superseded_count', 0),
        'regenerated_count': results.get('regenerated_count', 0)
    }

    table_id = f"{project_id}.nba_predictions.prediction_regeneration_audit"

    # Insert audit record
    try:
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
        )

        load_job = client.load_table_from_json(
            [audit_record], table_id, job_config=job_config
        )
        load_job.result(timeout=30)
        logger.info(f"Logged regeneration event to audit table")

    except Exception as e:
        logger.warning(f"Failed to log audit record: {e}")
        # Don't fail overall process if audit logging fails
```

---

## Component 3: Schema Migrations

### Migration 1: Predictions Table Superseding

**File**: `schemas/bigquery/nba_predictions/player_prop_predictions.sql`

**Add columns**:
```sql
-- Superseding tracking
superseded BOOL DEFAULT FALSE,
superseded_at TIMESTAMP,
superseded_reason STRING,
superseded_by_prediction_id STRING,
superseded_metadata JSON,

-- Feature versioning
feature_version_hash STRING,
data_source_tier STRING,  -- GOLD, SILVER, BRONZE
shot_zones_source STRING  -- bigdataball_pbp, nbac_play_by_play, unavailable
```

**Migration SQL**:
```sql
-- Run this on nba-props-platform.nba_predictions.player_prop_predictions
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS superseded BOOL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS superseded_reason STRING,
ADD COLUMN IF NOT EXISTS superseded_by_prediction_id STRING,
ADD COLUMN IF NOT EXISTS superseded_metadata JSON,
ADD COLUMN IF NOT EXISTS feature_version_hash STRING,
ADD COLUMN IF NOT EXISTS data_source_tier STRING,
ADD COLUMN IF NOT EXISTS shot_zones_source STRING;

-- Create index for efficient superseding queries
CREATE INDEX IF NOT EXISTS idx_predictions_game_date_superseded
ON `nba-props-platform.nba_predictions.player_prop_predictions` (game_date, superseded);
```

### Migration 2: Grading Table Source Tracking

**File**: `schemas/bigquery/nba_predictions/prediction_accuracy.sql`

**Add columns**:
```sql
-- Data source tracking
shot_zones_source STRING,
data_quality_tier STRING,
feature_completeness_pct FLOAT64,
bdb_available_at_prediction BOOL,

-- Superseding tracking
is_superseded_prediction BOOL DEFAULT FALSE,
original_prediction_id STRING
```

**Migration SQL**:
```sql
-- Run this on nba-props-platform.nba_predictions.prediction_accuracy
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS shot_zones_source STRING,
ADD COLUMN IF NOT EXISTS data_quality_tier STRING,
ADD COLUMN IF NOT EXISTS feature_completeness_pct FLOAT64,
ADD COLUMN IF NOT EXISTS bdb_available_at_prediction BOOL,
ADD COLUMN IF NOT EXISTS is_superseded_prediction BOOL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS original_prediction_id STRING;
```

### Migration 3: Audit Table Creation

**File**: `schemas/bigquery/nba_predictions/prediction_regeneration_audit.sql` (NEW)

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_regeneration_audit` (
  regeneration_timestamp TIMESTAMP NOT NULL,
  game_date DATE NOT NULL,
  reason STRING NOT NULL,
  metadata JSON,
  superseded_count INT64,
  regenerated_count INT64,
  processing_time_seconds FLOAT64,
  triggered_by STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(regeneration_timestamp)
CLUSTER BY game_date, reason;
```

---

## Component 4: Pub/Sub Topic Configuration

### New Topic: `nba-prediction-trigger`

**Create if doesn't exist**:
```bash
gcloud pubsub topics create nba-prediction-trigger \
    --project=nba-props-platform \
    --message-retention-duration=7d
```

**Subscriber** (prediction coordinator):
```bash
gcloud pubsub subscriptions create nba-prediction-trigger-sub \
    --topic=nba-prediction-trigger \
    --push-endpoint=https://prediction-coordinator-<hash>-uw.a.run.app/regenerate-with-supersede \
    --ack-deadline=600 \
    --message-retention-duration=7d
```

---

## Testing Plan

### Unit Tests

**File**: `tests/bin/monitoring/test_bdb_retry_processor.py`

```python
def test_trigger_full_reprocessing_pipeline():
    """Test full pipeline triggering."""
    processor = BDBRetryProcessor(dry_run=False)
    game = {
        'game_date': '2026-01-17',
        'game_id': '0022500593',
        'fallback_source': 'nbac_play_by_play',
        'quality_before_rerun': 'silver'
    }

    # Mock Pub/Sub publisher
    with patch.object(processor, 'publisher') as mock_pub:
        result = processor.trigger_full_reprocessing_pipeline(game)

        # Verify all three Pub/Sub topics were called
        assert mock_pub.publish.call_count == 3
        topics_called = [call[0][0] for call in mock_pub.publish.call_args_list]

        assert 'nba-phase3-trigger' in str(topics_called)
        assert 'nba-phase4-trigger' in str(topics_called)
        assert 'nba-prediction-trigger' in str(topics_called)

        assert result == True


def test_mark_predictions_superseded():
    """Test superseding logic."""
    from predictions.coordinator.coordinator import _mark_predictions_superseded

    game_date = '2026-01-17'
    reason = 'bdb_upgrade'
    metadata = {'upgrade_from': 'nbac_fallback'}

    count = _mark_predictions_superseded(game_date, reason, metadata)

    # Verify predictions were marked
    assert count > 0

    # Verify superseded field set
    query = f"""
    SELECT COUNT(*) as superseded_count
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = '{game_date}'
      AND superseded = TRUE
    """
    result = bq_client.query(query).to_dataframe()
    assert result['superseded_count'][0] == count
```

### Integration Test

**Scenario**: End-to-end BDB reprocessing

```python
def test_e2e_bdb_reprocessing():
    """Test complete BDB reprocessing pipeline."""

    # Step 1: Manually backfill BDB data for Jan 17
    # (assume BDB data now available)

    # Step 2: Trigger retry processor
    processor = BDBRetryProcessor(dry_run=False)
    stats = processor.run(max_age_days=30)

    # Verify retry processor detected BDB availability
    assert stats['games_available'] > 0
    assert stats['phase3_triggered'] > 0

    # Step 3: Wait for Phase 3-4 to complete
    time.sleep(60)  # Wait for processing

    # Step 4: Verify Phase 5 triggered
    # Check audit table for regeneration event
    query = """
    SELECT * FROM `nba-props-platform.nba_predictions.prediction_regeneration_audit`
    WHERE game_date = '2026-01-17'
    ORDER BY regeneration_timestamp DESC
    LIMIT 1
    """
    audit = bq_client.query(query).to_dataframe()
    assert not audit.empty
    assert audit['reason'][0] == 'bdb_upgrade'

    # Step 5: Verify old predictions superseded
    query = """
    SELECT COUNT(*) as count
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = '2026-01-17'
      AND superseded = TRUE
    """
    result = bq_client.query(query).to_dataframe()
    assert result['count'][0] > 0

    # Step 6: Verify new predictions exist
    query = """
    SELECT COUNT(*) as count
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = '2026-01-17'
      AND superseded = FALSE
      AND shot_zones_source = 'bigdataball_pbp'
    """
    result = bq_client.query(query).to_dataframe()
    assert result['count'][0] > 0
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Review and approve implementation plan
- [ ] Run schema migrations on test dataset
- [ ] Test BDB retry processor enhancements locally
- [ ] Test prediction coordinator endpoint locally
- [ ] Create Pub/Sub topics and subscriptions
- [ ] Update monitoring dashboards

### Deployment

- [ ] Run schema migrations on production
- [ ] Deploy enhanced BDB retry processor
- [ ] Deploy prediction coordinator with new endpoint
- [ ] Configure Pub/Sub subscriptions
- [ ] Test with dry-run mode
- [ ] Monitor first automatic trigger

### Post-Deployment

- [ ] Verify first reprocessing event works end-to-end
- [ ] Check audit logs for completeness
- [ ] Analyze accuracy improvement from BDB upgrade
- [ ] Document any issues or edge cases
- [ ] Update runbooks

---

## Monitoring & Alerts

### Key Metrics to Track

```sql
-- Daily BDB reprocessing events
SELECT
    DATE(regeneration_timestamp) as date,
    COUNT(*) as regeneration_events,
    SUM(superseded_count) as total_superseded,
    SUM(regenerated_count) as total_regenerated,
    ROUND(AVG(processing_time_seconds), 2) as avg_processing_time
FROM `nba-props-platform.nba_predictions.prediction_regeneration_audit`
WHERE regeneration_timestamp >= CURRENT_TIMESTAMP() - INTERVAL 7 DAY
GROUP BY date
ORDER BY date DESC;
```

### Alerts

1. **Reprocessing Failure**: Alert if regeneration event fails (status != 'success')
2. **Superseding Mismatch**: Alert if regenerated_count != superseded_count (data loss)
3. **Processing Timeout**: Alert if processing_time > 10 minutes

---

## Rollback Plan

If reprocessing causes issues:

1. **Disable retry processor trigger**: Set `DRY_RUN=true` in environment
2. **Stop Pub/Sub subscription**: Pause `nba-prediction-trigger-sub`
3. **Restore old predictions**: Un-supersede via SQL:
   ```sql
   UPDATE player_prop_predictions
   SET superseded = FALSE, superseded_at = NULL
   WHERE superseded_reason = 'bdb_upgrade'
     AND superseded_at > '2026-01-31'  -- After deployment
   ```
4. **Delete new predictions**: Clean up regenerated predictions
5. **Investigate root cause**: Check logs, fix bugs, re-deploy

---

**Next**: See `DECISION-MATRIX.md` for strategy trade-offs
