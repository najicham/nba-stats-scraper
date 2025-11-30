# Phase 2 → Phase 3 Orchestrator

Cloud Function that orchestrates the transition from Phase 2 (Raw Processors) to Phase 3 (Analytics Processors).

## Purpose

Phase 2 consists of 21 independent processors that transform scraped data into raw BigQuery tables. This orchestrator:
1. **Tracks** completion of all 21 processors for each game_date
2. **Triggers** Phase 3 analytics when ALL processors complete
3. **Prevents** race conditions using Firestore atomic transactions
4. **Preserves** correlation IDs for full pipeline tracing

## Architecture

```
Phase 2 Processors (21 total)
  ├─ BdlGamesProcessor ──┐
  ├─ NbacPlayerBoxscoreProcessor ──┐
  ├─ ...                             ├─→ Publish to nba-phase2-raw-complete
  └─ CdnInjuryReportProcessor ──────┘
           ↓
    Orchestrator (this function)
      - Listens: nba-phase2-raw-complete
      - State: Firestore phase2_completion/{game_date}
      - Atomic: Firestore transactions prevent race conditions
           ↓
    When all 21 complete:
      - Publishes to: nba-phase3-trigger
      - Phase 3 processors start
```

## Critical Features

### 1. Race Condition Prevention (Critical Fix 1.1)

**Problem:** Without transactions, simultaneous completions cause duplicate triggers:
```
11:45 PM - Processor A completes, reads Firestore (20/21 complete)
11:45 PM - Processor B completes, reads Firestore (20/21 complete)
Both increment to 21/21 and trigger Phase 3 → DUPLICATE!
```

**Solution:** Firestore transactions with `_triggered` flag:
```python
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, data):
    # Atomic read-modify-write
    doc = doc_ref.get(transaction=transaction)
    current = doc.to_dict() if doc.exists else {}

    # Idempotency check
    if processor_name in current:
        return False  # Already registered

    # Add completion
    current[processor_name] = data
    completed_count = len([k for k in current.keys() if not k.startswith('_')])

    # Only ONE processor can set _triggered=True
    if completed_count >= 21 and '_triggered' not in current:
        current['_triggered'] = True
        transaction.set(doc_ref, current)
        return True  # Trigger Phase 3
    else:
        transaction.set(doc_ref, current)
        return False  # Don't trigger
```

### 2. Idempotency

- Handles duplicate Pub/Sub messages (at-least-once delivery)
- Checks if processor already registered before adding
- Safe to retry without duplicating triggers

### 3. Correlation ID Tracking

- Preserves `correlation_id` from Phase 1 scraper
- Enables tracing: Scraper → Phase 2 → Phase 3 → Phase 4 → Phase 5
- Critical for debugging and audit trail

## Deployment

Deploy to Google Cloud Functions:

```bash
# From project root
./bin/orchestrators/deploy_phase2_to_phase3.sh

# Or manually:
cd orchestration/cloud_functions/phase2_to_phase3
gcloud functions deploy phase2-to-phase3-orchestrator \
  --gen2 \
  --runtime python311 \
  --region us-west2 \
  --source . \
  --entry-point orchestrate_phase2_to_phase3 \
  --trigger-topic nba-phase2-raw-complete \
  --set-env-vars GCP_PROJECT=nba-props-platform \
  --memory 256MB \
  --timeout 60s \
  --max-instances 10 \
  --project nba-props-platform
```

## Environment Variables

- `GCP_PROJECT`: GCP project ID (default: nba-props-platform)

## Firestore State

**Collection:** `phase2_completion`
**Document:** `{game_date}` (e.g., "2025-11-29")

**Schema:**
```json
{
  "BdlGamesProcessor": {
    "completed_at": "2025-11-29T12:00:00Z",
    "correlation_id": "abc-123",
    "status": "success",
    "record_count": 150
  },
  "NbacPlayerBoxscoreProcessor": {
    "completed_at": "2025-11-29T12:01:00Z",
    "correlation_id": "abc-123",
    "status": "success",
    "record_count": 450
  },
  ...
  "_triggered": true,
  "_triggered_at": "2025-11-29T12:05:00Z",
  "_completed_count": 21
}
```

**Metadata Fields:**
- `_triggered`: Boolean flag to prevent duplicate triggers
- `_triggered_at`: Timestamp when Phase 3 was triggered
- `_completed_count`: Running count of completed processors

## Pub/Sub Topics

**Input Topic:** `nba-phase2-raw-complete`
- Receives completion messages from all 21 Phase 2 processors

**Output Topic:** `nba-phase3-trigger`
- Publishes trigger message when all Phase 2 processors complete

## Message Formats

**Input Message** (from Phase 2):
```json
{
  "processor_name": "BdlGamesProcessor",
  "phase": "phase_2_raw",
  "execution_id": "def-456",
  "correlation_id": "abc-123",
  "game_date": "2025-11-29",
  "output_table": "bdl_games",
  "output_dataset": "nba_raw",
  "status": "success",
  "record_count": 150,
  "timestamp": "2025-11-29T12:00:00Z"
}
```

**Output Message** (to Phase 3):
```json
{
  "game_date": "2025-11-29",
  "correlation_id": "abc-123",
  "trigger_source": "orchestrator",
  "triggered_by": "phase2_to_phase3_orchestrator",
  "upstream_processors_count": 21,
  "timestamp": "2025-11-29T12:05:00Z"
}
```

## Monitoring

**Check completion status:**
```python
from orchestrators.phase2_to_phase3.main import get_completion_status

status = get_completion_status('2025-11-29')
print(status)
# {
#   'game_date': '2025-11-29',
#   'status': 'in_progress',  # or 'triggered' or 'not_started'
#   'completed_count': 18,
#   'expected_count': 21,
#   'completed_processors': ['BdlGamesProcessor', ...],
#   'triggered_at': None  # or timestamp if triggered
# }
```

**Cloud Functions Logs:**
```bash
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --limit 50
```

**Firestore Console:**
https://console.firebase.google.com/project/nba-props-platform/firestore/data/phase2_completion

## Testing

**Unit Test:**
```bash
pytest tests/cloud_functions/test_phase2_orchestrator.py -v
```

**Integration Test:**
```bash
# 1. Trigger a few Phase 2 processors manually
curl -X POST https://phase2-processor.../process -d '{"game_date": "2025-11-29"}'

# 2. Check Firestore state
python orchestration/cloud_functions/phase2_to_phase3/main.py 2025-11-29

# 3. Trigger remaining processors until all 21 complete

# 4. Verify Phase 3 received trigger message
gcloud pubsub topics list-subscriptions nba-phase3-trigger
```

## Troubleshooting

### Issue: Orchestrator doesn't trigger Phase 3

**Possible causes:**
1. Not all 21 processors completed successfully
   - Check Firestore: `completed_count < 21`
   - Check processor_run_history for failed processors
2. Already triggered
   - Check Firestore: `_triggered = true`
3. Pub/Sub publishing failed
   - Check Cloud Function logs for errors

**Resolution:**
```bash
# Check status
python orchestration/cloud_functions/phase2_to_phase3/main.py 2025-11-29

# If stuck at 20/21, find missing processor:
bq query "SELECT processor_name FROM processor_run_history
WHERE phase='phase_2_raw' AND data_date='2025-11-29' AND status='success'"

# Manually trigger missing processor
curl -X POST https://missing-processor.../process -d '{"game_date": "2025-11-29"}'
```

### Issue: Duplicate Phase 3 triggers

**This should NOT happen** with atomic transactions. If it does:
1. Check Cloud Function logs for transaction errors
2. Verify Firestore has `_triggered` flag
3. Check if multiple Cloud Function instances deployed

## Related Documentation

- [V1.0 Implementation Plan](../../docs/08-projects/current/phase4-phase5-integration/V1.0-IMPLEMENTATION-PLAN-FINAL.md)
- [Critical Fixes v1.0](../../docs/08-projects/current/phase4-phase5-integration/CRITICAL-FIXES-v1.0.md)
- [Unified Architecture Design](../../docs/08-projects/current/phase4-phase5-integration/UNIFIED-ARCHITECTURE-DESIGN.md)

## Version History

- **1.0** (2025-11-29): Initial implementation with atomic transactions
