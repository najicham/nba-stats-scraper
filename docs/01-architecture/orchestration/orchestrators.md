# Orchestrators Architecture

**Purpose:** Coordinate phase transitions in the event-driven pipeline
**Status:** v1.0 deployed and operational
**Created:** 2025-11-29 16:53 PST
**Last Updated:** 2025-11-29 16:53 PST

---

## Overview

Orchestrators are Cloud Functions that coordinate transitions between processing phases. They track completion of upstream processors and trigger downstream phases only when all required inputs are ready.

**Key Responsibilities:**
- Track completion counts using Firestore
- Prevent race conditions with atomic transactions
- Aggregate entity changes for selective processing
- Preserve correlation IDs for end-to-end tracing
- Ensure idempotent operation (handle Pub/Sub retries)

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                    Phase 2→3 Orchestrator                              │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌─────────────┐    ┌─────────────────┐    ┌────────────────────┐     │
│  │ Pub/Sub     │───▶│  Cloud Function │───▶│ Pub/Sub            │     │
│  │ nba-phase2- │    │  phase2-to-     │    │ nba-phase3-trigger │     │
│  │ raw-complete│    │  phase3-        │    │                    │     │
│  │             │    │  orchestrator   │    │ (published when    │     │
│  │ (21 msgs)   │    │                 │    │  21/21 complete)   │     │
│  └─────────────┘    └────────┬────────┘    └────────────────────┘     │
│                              │                                         │
│                              ▼                                         │
│                    ┌─────────────────┐                                │
│                    │    Firestore    │                                │
│                    │ phase2_completion│                               │
│                    │ /{game_date}    │                                │
│                    └─────────────────┘                                │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                    Phase 3→4 Orchestrator                              │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌─────────────┐    ┌─────────────────┐    ┌────────────────────┐     │
│  │ Pub/Sub     │───▶│  Cloud Function │───▶│ Pub/Sub            │     │
│  │ nba-phase3- │    │  phase3-to-     │    │ nba-phase4-trigger │     │
│  │ analytics-  │    │  phase4-        │    │                    │     │
│  │ complete    │    │  orchestrator   │    │ + entities_changed │     │
│  │ (5 msgs)    │    │                 │    │   aggregated       │     │
│  └─────────────┘    └────────┬────────┘    └────────────────────┘     │
│                              │                                         │
│                              ▼                                         │
│                    ┌─────────────────┐                                │
│                    │    Firestore    │                                │
│                    │ phase3_completion│                               │
│                    │ /{game_date}    │                                │
│                    └─────────────────┘                                │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 2→3 Orchestrator

**Function:** `phase2-to-phase3-orchestrator`
**Location:** `orchestrators/phase2_to_phase3/main.py`
**Entry Point:** `orchestrate_phase2_to_phase3`

### Configuration

| Setting | Value |
|---------|-------|
| Runtime | Python 3.11 |
| Memory | 256MB |
| Timeout | 60s |
| Max Instances | 10 |
| Trigger | Pub/Sub `nba-phase2-raw-complete` |
| Firestore Collection | `phase2_completion/{game_date}` |

### Behavior

1. **Receive** completion message from Phase 2 processor
2. **Validate** required fields (game_date, processor_name, status)
3. **Update** Firestore document atomically (prevents race conditions)
4. **Check** if all 21 processors have completed
5. **Trigger** Phase 3 if complete (publish to `nba-phase3-trigger`)

### Expected Processors (21)

The orchestrator tracks these 21 Phase 2 raw processors:
- BdlGamesProcessor, BdlTeamsProcessor, BdlPlayersProcessor, BdlBoxscoresProcessor
- NbacBoxscoreProcessor, NbacGamesProcessor, NbacPlayersProcessor, NbacTeamsProcessor, NbacTeamBoxscoreProcessor
- PdGamesProcessor, PdPlayerStatsProcessor, PdTeamsProcessor, PdScheduleProcessor
- OddsGamesProcessor, OddsPlayerPropsProcessor, OddsTeamLinesProcessor
- InjuriesProcessor, NewsProcessor, TransactionsProcessor, RefereesProcessor, StandingsProcessor

### Deployment

```bash
./bin/orchestrators/deploy_phase2_to_phase3.sh
```

---

## Phase 3→4 Orchestrator

**Function:** `phase3-to-phase4-orchestrator`
**Location:** `orchestrators/phase3_to_phase4/main.py`
**Entry Point:** `orchestrate_phase3_to_phase4`

### Configuration

| Setting | Value |
|---------|-------|
| Runtime | Python 3.11 |
| Memory | 256MB |
| Timeout | 60s |
| Max Instances | 10 |
| Trigger | Pub/Sub `nba-phase3-analytics-complete` |
| Firestore Collection | `phase3_completion/{game_date}` |

### Behavior

1. **Receive** completion message from Phase 3 processor
2. **Validate** required fields
3. **Extract** `entities_changed` from message metadata
4. **Update** Firestore document atomically
5. **Check** if all 5 processors have completed
6. **Aggregate** entities_changed from all processors
7. **Trigger** Phase 4 with combined entity list

### Expected Processors (5)

- PlayerGameSummaryProcessor
- TeamDefenseGameSummaryProcessor
- TeamOffenseGameSummaryProcessor
- UpcomingPlayerGameContextProcessor
- UpcomingTeamGameContextProcessor

### Entity Aggregation

The Phase 3→4 orchestrator combines `entities_changed` from all analytics processors:

```json
// Input from PlayerGameSummaryProcessor
{"entities_changed": ["lebron-james", "stephen-curry"]}

// Input from TeamDefenseGameSummaryProcessor
{"entities_changed": ["LAL", "GSW"]}

// Output to Phase 4
{
  "entities_changed": {
    "players": ["lebron-james", "stephen-curry"],
    "teams": ["LAL", "GSW"]
  }
}
```

### Deployment

```bash
./bin/orchestrators/deploy_phase3_to_phase4.sh
```

---

## Critical Features

### 1. Atomic Transactions (Race Condition Prevention)

**Problem:** When multiple processors complete simultaneously, they could all read the same count and all trigger the next phase.

```
Without transactions:
  11:45:00 - Processor A reads (20/21), sees not complete
  11:45:00 - Processor B reads (20/21), sees not complete
  11:45:01 - Processor A writes (21/21), triggers Phase 3 ✓
  11:45:01 - Processor B writes (21/21), triggers Phase 3 again ✗ DUPLICATE!
```

**Solution:** Firestore transactions with optimistic locking:

```python
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, data):
    # Transaction locks document during read-modify-write
    doc = doc_ref.get(transaction=transaction)
    current = doc.to_dict() if doc.exists else {}

    # Check if already triggered (idempotency)
    if current.get('_triggered'):
        return False

    # Add processor
    current[processor_name] = data

    # Count and check
    count = len([k for k in current if not k.startswith('_')])
    if count >= EXPECTED_PROCESSORS:
        current['_triggered'] = True
        transaction.set(doc_ref, current)
        return True  # Trigger!

    transaction.set(doc_ref, current)
    return False
```

### 2. Idempotency (Duplicate Message Handling)

Pub/Sub may deliver messages multiple times. The orchestrator handles this:

```python
# Skip if processor already registered
if processor_name in current:
    logger.debug(f"Duplicate message for {processor_name}")
    return False
```

### 3. Deduplication Marker

The `_triggered` flag prevents double-triggering:

```python
# Only trigger if ALL complete AND not yet triggered
if count >= EXPECTED_PROCESSORS and not current.get('_triggered'):
    current['_triggered'] = True
    # ... trigger next phase
```

### 4. Correlation ID Preservation

Correlation IDs flow through the entire pipeline:

```python
# Extract from incoming message
correlation_id = message_data.get('correlation_id')

# Include in outgoing trigger
trigger_message = {
    'correlation_id': correlation_id,
    # ...
}
```

---

## Firestore Document Schema

### phase2_completion/{game_date}

```json
{
  "BdlGamesProcessor": {
    "completed_at": "2025-11-29T12:00:00Z",
    "correlation_id": "abc-123",
    "status": "success",
    "record_count": 150,
    "execution_id": "exec-001"
  },
  "BdlTeamsProcessor": {
    "completed_at": "2025-11-29T12:00:01Z",
    "correlation_id": "abc-123",
    "status": "success",
    "record_count": 30,
    "execution_id": "exec-002"
  },
  // ... 19 more processors ...

  "_completed_count": 21,
  "_triggered": true,
  "_triggered_at": "2025-11-29T12:00:05Z"
}
```

### phase3_completion/{game_date}

```json
{
  "PlayerGameSummaryProcessor": {
    "completed_at": "2025-11-29T12:30:00Z",
    "correlation_id": "abc-123",
    "status": "success",
    "record_count": 450,
    "execution_id": "exec-003",
    "is_incremental": true,
    "entities_changed": ["lebron-james", "stephen-curry"]
  },
  // ... 4 more processors ...

  "_completed_count": 5,
  "_triggered": true,
  "_triggered_at": "2025-11-29T12:30:05Z"
}
```

---

## Monitoring

### Check Function Status

```bash
# Phase 2→3
gcloud functions describe phase2-to-phase3-orchestrator \
  --region us-west2 \
  --gen2 \
  --format="value(state)"

# Phase 3→4
gcloud functions describe phase3-to-phase4-orchestrator \
  --region us-west2 \
  --gen2 \
  --format="value(state)"
```

### View Logs

```bash
# Phase 2→3 logs
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --limit 50

# Phase 3→4 logs
gcloud functions logs read phase3-to-phase4-orchestrator \
  --region us-west2 \
  --limit 50
```

### Check Firestore State

```bash
# Visit Firebase Console
https://console.firebase.google.com/project/nba-props-platform/firestore

# Collections to monitor:
# - phase2_completion/{game_date}
# - phase3_completion/{game_date}
```

### Helper Functions (Local Debugging)

```python
# Check completion status for a date
from orchestrators.phase2_to_phase3.main import get_completion_status

status = get_completion_status('2025-11-29')
print(f"Completed: {status['completed_count']}/{status['expected_count']}")
print(f"Triggered: {status['status']}")
```

---

## Troubleshooting

### Orchestrator Not Triggering

**Symptoms:** Processors complete but next phase doesn't start

**Check:**
1. Verify all expected processors completed:
   ```bash
   # Check Firestore document
   # Look for missing processor entries
   ```

2. Check for errors in logs:
   ```bash
   gcloud functions logs read phase2-to-phase3-orchestrator \
     --region us-west2 \
     --filter="severity>=ERROR"
   ```

3. Verify Pub/Sub subscription exists:
   ```bash
   gcloud pubsub subscriptions list | grep orchestrator
   ```

### Double Triggering (Should Never Happen)

If Phase 3 triggers twice for the same date:

1. Check `_triggered` flag in Firestore
2. Review transaction logs for conflicts
3. Verify no manual Pub/Sub message injection

### Stale State

Clean up old Firestore documents:

```python
# Documents older than 7 days can be deleted
# Visit Firestore console and delete old game_date documents
```

---

## Cost Estimates

| Component | Daily Usage | Monthly Cost |
|-----------|-------------|--------------|
| Phase 2→3 invocations | ~100 | ~$0.05 |
| Phase 3→4 invocations | ~15 | ~$0.01 |
| Firestore reads | ~200 | Free tier |
| Firestore writes | ~130 | Free tier |
| **Total** | | **~$2/month** |

---

## Related Documentation

- [Pub/Sub Topics Architecture](./pubsub-topics.md) - Topic definitions and message formats
- [Firestore State Management](./firestore-state-management.md) - Detailed state schema
- [Orchestrator Monitoring Guide](../../02-operations/orchestrator-monitoring.md) - Operational procedures
- [v1.0 Deployment Guide](../../04-deployment/v1.0-deployment-guide.md) - Deployment instructions

---

**Document Version:** 1.0
**Created:** 2025-11-29 16:53 PST
**Last Updated:** 2025-11-29 16:53 PST
