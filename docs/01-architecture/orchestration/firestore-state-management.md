# Firestore State Management

**Purpose:** Track orchestrator completion state with atomic transactions
**Status:** v1.0 deployed and operational
**Created:** 2025-11-29 16:54 PST
**Last Updated:** 2025-11-29 16:54 PST

---

## Overview

Firestore provides the state management layer for orchestrators, tracking which processors have completed for each game date and preventing race conditions through atomic transactions.

**Why Firestore?**
- **Atomic transactions:** Prevent race conditions when multiple processors complete simultaneously
- **Real-time updates:** Immediate consistency for state checks
- **Serverless:** No infrastructure to manage, auto-scales
- **Low latency:** Sub-millisecond reads for Cloud Functions in same region
- **Document model:** Natural fit for processor completion tracking

---

## Collections

### phase2_completion

**Path:** `phase2_completion/{game_date}`
**Purpose:** Track Phase 2 raw processor completions (21 processors)

```
phase2_completion/
├── 2025-11-28/
│   ├── BdlGamesProcessor: {...}
│   ├── BdlTeamsProcessor: {...}
│   ├── ... (19 more)
│   ├── _completed_count: 21
│   ├── _triggered: true
│   └── _triggered_at: timestamp
├── 2025-11-29/
│   ├── BdlGamesProcessor: {...}
│   ├── ... (in progress)
│   └── _completed_count: 15
└── ...
```

### phase3_completion

**Path:** `phase3_completion/{game_date}`
**Purpose:** Track Phase 3 analytics processor completions (5 processors)

```
phase3_completion/
├── 2025-11-28/
│   ├── PlayerGameSummaryProcessor: {...}
│   ├── TeamDefenseGameSummaryProcessor: {...}
│   ├── TeamOffenseGameSummaryProcessor: {...}
│   ├── UpcomingPlayerGameContextProcessor: {...}
│   ├── UpcomingTeamGameContextProcessor: {...}
│   ├── _completed_count: 5
│   ├── _triggered: true
│   └── _triggered_at: timestamp
└── ...
```

---

## Document Schema

### Processor Entry

Each processor completion is stored as a field in the document:

```json
{
  "ProcessorName": {
    "completed_at": "2025-11-29T12:00:00.000Z",
    "correlation_id": "abc-123-def-456",
    "status": "success",
    "record_count": 150,
    "execution_id": "exec-001"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `completed_at` | timestamp | When processor finished |
| `correlation_id` | string | Pipeline trace ID |
| `status` | string | "success" or "partial" |
| `record_count` | integer | Records processed |
| `execution_id` | string | Unique execution identifier |

### Phase 3 Additional Fields

Phase 3 processors include change detection metadata:

```json
{
  "PlayerGameSummaryProcessor": {
    "completed_at": "2025-11-29T12:30:00.000Z",
    "correlation_id": "abc-123-def-456",
    "status": "success",
    "record_count": 450,
    "execution_id": "exec-003",
    "is_incremental": true,
    "entities_changed": ["lebron-james", "stephen-curry", "anthony-davis"]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `is_incremental` | boolean | Whether change detection was used |
| `entities_changed` | array | List of entity IDs that changed |

### Metadata Fields

Fields prefixed with `_` are orchestrator metadata:

```json
{
  "_completed_count": 21,
  "_triggered": true,
  "_triggered_at": "2025-11-29T12:00:05.000Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `_completed_count` | integer | Current count of completed processors |
| `_triggered` | boolean | Whether next phase was triggered |
| `_triggered_at` | timestamp | When trigger was published |

---

## Transaction Flow

### Atomic Update Process

```
1. Receive Pub/Sub message
   │
   ▼
2. Start Firestore transaction
   │ (Document locked for atomic access)
   ▼
3. Read current state
   │ count = len([k for k if not k.startswith('_')])
   ▼
4. Check idempotency
   │ if processor_name in current: return False
   ▼
5. Add processor entry
   │ current[processor_name] = completion_data
   ▼
6. Check completion
   │ if count >= EXPECTED and not _triggered:
   │   current['_triggered'] = True
   │   should_trigger = True
   ▼
7. Write atomically
   │ transaction.set(doc_ref, current)
   ▼
8. Release lock
   │
   ▼
9. If should_trigger: publish to next topic
```

### Race Condition Prevention

Without transactions:
```
Time     Processor A          Processor B
─────────────────────────────────────────────
11:45:00 Read: 20/21          Read: 20/21
11:45:01 Write: 21/21 ✓       Write: 21/21 ✓
11:45:02 Trigger Phase 3 ✓    Trigger Phase 3 ✓  ← DUPLICATE!
```

With transactions:
```
Time     Processor A          Processor B
─────────────────────────────────────────────
11:45:00 Lock, Read: 20/21    (waiting for lock)
11:45:01 Write: 21/21         (waiting for lock)
         _triggered=True
         Release lock
11:45:02 Trigger Phase 3 ✓    Lock acquired
                              Read: 21/21
                              _triggered=True already
                              Skip trigger ✓
```

---

## Example Documents

### Complete Phase 2 Document

```json
{
  "BdlGamesProcessor": {
    "completed_at": {"_seconds": 1732903200, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 12,
    "execution_id": "bdl-games-exec-001"
  },
  "BdlTeamsProcessor": {
    "completed_at": {"_seconds": 1732903201, "_nanoseconds": 500000000},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 30,
    "execution_id": "bdl-teams-exec-001"
  },
  "BdlPlayersProcessor": {
    "completed_at": {"_seconds": 1732903202, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 450,
    "execution_id": "bdl-players-exec-001"
  },
  // ... 18 more processors ...

  "_completed_count": 21,
  "_triggered": true,
  "_triggered_at": {"_seconds": 1732903205, "_nanoseconds": 0}
}
```

### Complete Phase 3 Document

```json
{
  "PlayerGameSummaryProcessor": {
    "completed_at": {"_seconds": 1732905000, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 450,
    "execution_id": "pgs-exec-001",
    "is_incremental": true,
    "entities_changed": ["lebron-james", "stephen-curry", "anthony-davis"]
  },
  "TeamDefenseGameSummaryProcessor": {
    "completed_at": {"_seconds": 1732905001, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 30,
    "execution_id": "tdgs-exec-001",
    "is_incremental": true,
    "entities_changed": ["LAL", "GSW", "BOS"]
  },
  "TeamOffenseGameSummaryProcessor": {
    "completed_at": {"_seconds": 1732905002, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 30,
    "execution_id": "togs-exec-001",
    "is_incremental": true,
    "entities_changed": ["LAL", "GSW", "BOS"]
  },
  "UpcomingPlayerGameContextProcessor": {
    "completed_at": {"_seconds": 1732905003, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 450,
    "execution_id": "upgc-exec-001",
    "is_incremental": false,
    "entities_changed": []
  },
  "UpcomingTeamGameContextProcessor": {
    "completed_at": {"_seconds": 1732905004, "_nanoseconds": 0},
    "correlation_id": "scraper-2025-11-29-001",
    "status": "success",
    "record_count": 30,
    "execution_id": "utgc-exec-001",
    "is_incremental": false,
    "entities_changed": []
  },

  "_completed_count": 5,
  "_triggered": true,
  "_triggered_at": {"_seconds": 1732905005, "_nanoseconds": 0}
}
```

---

## Accessing Firestore

### Firebase Console

Direct access via web UI:
```
https://console.firebase.google.com/project/nba-props-platform/firestore
```

Navigate to:
- `phase2_completion` → Click game_date document → View all processor entries
- `phase3_completion` → Click game_date document → View all processor entries

### Python SDK

```python
from google.cloud import firestore

db = firestore.Client()

# Read completion status
doc_ref = db.collection('phase2_completion').document('2025-11-29')
doc = doc_ref.get()

if doc.exists:
    data = doc.to_dict()
    count = len([k for k in data if not k.startswith('_')])
    triggered = data.get('_triggered', False)
    print(f"Completed: {count}/21, Triggered: {triggered}")
```

### gcloud CLI

```bash
# Firestore doesn't have direct gcloud CLI commands
# Use Firebase Console or Python SDK
```

---

## Maintenance

### Cleanup Old Documents

Documents older than 7 days can be safely deleted:

```python
from datetime import datetime, timedelta
from google.cloud import firestore

db = firestore.Client()
cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

# List old documents
docs = db.collection('phase2_completion').stream()
for doc in docs:
    if doc.id < cutoff:
        print(f"Can delete: {doc.id}")
        # doc.reference.delete()  # Uncomment to delete
```

### Manual Reset

If orchestrator state needs reset (rare):

1. Go to Firebase Console
2. Navigate to collection
3. Find the game_date document
4. Delete the `_triggered` field (or entire document)
5. Re-run processors to re-trigger orchestration

**Warning:** Only do this if you understand the implications. Double-triggering will re-process downstream phases.

---

## Cost Estimates

| Operation | Daily Volume | Monthly Cost |
|-----------|--------------|--------------|
| Document reads | ~200 | Free (50k/day free) |
| Document writes | ~130 | Free (20k/day free) |
| Deletes | ~3 (cleanup) | Free (20k/day free) |
| Storage | ~1 KB/doc × 90 docs | Free (<1 GB free) |
| **Total** | | **$0/month** |

---

## Troubleshooting

### Document Not Found

If orchestrator logs show "document not found":
- First processor creates document automatically
- Check if any processors actually ran for that date

### Transaction Timeout

If transactions fail with timeout:
- Check Firestore latency in console
- Verify Cloud Function in same region (us-west2)
- Consider increasing function timeout

### Missing Processor Entry

If document exists but processor missing:
- Check processor logs for Pub/Sub publish errors
- Manually publish completion message if needed:
  ```bash
  gcloud pubsub topics publish nba-phase2-raw-complete \
    --message='{"processor_name":"MissingProcessor","game_date":"2025-11-29","status":"success"}'
  ```

### Stale _triggered Flag

If `_triggered=true` but downstream didn't run:
- Check orchestrator logs for publish errors
- Verify Pub/Sub topic exists
- Check downstream processor logs

---

## Related Documentation

- [Orchestrators Architecture](./orchestrators.md) - Orchestrator implementation details
- [Pub/Sub Topics Architecture](./pubsub-topics.md) - Message flow and formats
- [Orchestrator Monitoring Guide](../../02-operations/orchestrator-monitoring.md) - Operational procedures

---

**Document Version:** 1.0
**Created:** 2025-11-29 16:54 PST
**Last Updated:** 2025-11-29 16:54 PST
