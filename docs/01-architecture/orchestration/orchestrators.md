# Orchestrators Architecture

**Purpose:** Track phase completion and trigger downstream processing
**Status:** v3.0 - Added Phase 4→5, Phase 5→6, and morning schedulers
**Created:** 2025-11-29 16:53 PST
**Last Updated:** 2025-12-26

---

## Overview

Orchestrators are Cloud Functions that track processor completions for observability.

> **IMPORTANT (Dec 2025):** The Phase 2→3 orchestrator is now **monitoring-only**. Phase 3 is triggered directly via Pub/Sub subscription (`nba-phase3-analytics-sub`), not by the orchestrator. The orchestrator's output topic (`nba-phase3-trigger`) has no subscribers.

**Key Responsibilities:**
- Track completion counts using Firestore (observability)
- Prevent race conditions with atomic transactions
- Aggregate entity changes for selective processing (Phase 3→4 only)
- Preserve correlation IDs for end-to-end tracing
- Ensure idempotent operation (handle Pub/Sub retries)

---

## When Orchestrators Are Used

| Mode | Orchestrators | How Sequencing Works |
|------|---------------|---------------------|
| **Daily Operations** | ✅ Active | Cloud Functions coordinate via Pub/Sub |
| **Backfill** | ❌ Bypassed | Local script controls sequencing manually |

### Daily Operations (Production Pipeline)

The pipeline uses **direct Pub/Sub subscriptions** for real-time data flow:

```
Scrapers → Phase 2 → nba-phase2-raw-complete → Phase 3 → nba-phase3-analytics-complete → Phase 4 → Phase 5
                            ↓                                      ↓
                     [Orchestrator]                          [Orchestrator]
                     (monitoring only)                       (triggers Phase 4)
```

**Phase 2→3:** Direct subscription triggers Phase 3 immediately. Orchestrator only monitors.
**Phase 3→4:** Orchestrator aggregates entities_changed and triggers Phase 4 when all 5 processors complete.

### Backfill (Historical Data Processing)

Backfill jobs **bypass orchestrators entirely**:

```
Backfill Script → Phase 2 → Phase 3 → Phase 4 (all local, manual sequencing)
```

**How backfill bypasses orchestrators:**
1. Processors run with `backfill_mode=True`
2. This sets `skip_downstream_trigger=True`
3. No Pub/Sub messages are published
4. The backfill script controls sequencing (day by day, phase by phase)

**Why this design?**
- Backfill processes 675+ days - orchestrators would receive 17,000+ messages
- Backfill needs checkpoint/resume; orchestrators don't (single day processing)
- Backfill can run in parallel with daily ops without interference
- Backfill has different error handling needs (retry dates, not individual processors)

**Related:** See `docs/08-projects/current/backfill/PHASE4-BACKFILL-JOBS.md` for backfill documentation.

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                    Phase 2→3 Orchestrator (MONITORING ONLY)            │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌─────────────┐    ┌─────────────────┐                               │
│  │ Pub/Sub     │───▶│  Cloud Function │    ❌ NO OUTPUT               │
│  │ nba-phase2- │    │  phase2-to-     │    (nba-phase3-trigger        │
│  │ raw-complete│    │  phase3-        │     has no subscribers)       │
│  │             │    │  orchestrator   │                               │
│  │ (~6 msgs)   │    │  v2.0           │                               │
│  └──────┬──────┘    └────────┬────────┘                               │
│         │                    │                                         │
│         │                    ▼                                         │
│         │          ┌─────────────────┐                                │
│         │          │    Firestore    │  ← Tracks completion           │
│         │          │ phase2_completion│    for observability          │
│         │          │ /{game_date}    │                                │
│         │          └─────────────────┘                                │
│         │                                                              │
│         └─────────────────────────────────────────────────────────────│
│                               │                                        │
│  ACTUAL TRIGGER:              ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐      │
│  │ nba-phase3-analytics-sub (direct subscription to Phase 3)   │      │
│  └─────────────────────────────────────────────────────────────┘      │
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

## Phase 2→3 Orchestrator (Monitoring Only)

> **v2.0 (Dec 2025):** This orchestrator is now monitoring-only. It tracks completions but does NOT trigger Phase 3. Phase 3 is triggered directly via `nba-phase3-analytics-sub` subscription.

**Function:** `phase2-to-phase3-orchestrator`
**Location:** `orchestration/cloud_functions/phase2_to_phase3/main.py`
**Entry Point:** `orchestrate_phase2_to_phase3`
**Mode:** Monitoring only (no Pub/Sub output)

### Configuration

| Setting | Value |
|---------|-------|
| Runtime | Python 3.11 |
| Memory | 256MB |
| Timeout | 60s |
| Max Instances | 10 |
| Trigger | Pub/Sub `nba-phase2-raw-complete` |
| Firestore Collection | `phase2_completion/{game_date}` |
| **Output** | **None** (monitoring only) |

### Behavior

1. **Receive** completion message from Phase 2 processor
2. **Validate** required fields (game_date, processor_name, status)
3. **Update** Firestore document atomically (prevents race conditions)
4. **Log** completion status for observability
5. ~~Trigger Phase 3~~ (removed in v2.0)

### Expected Processors (6)

The orchestrator tracks these core daily processors:
- `bdl_player_boxscores` - Daily box scores from balldontlie
- `bigdataball_play_by_play` - Per-game play-by-play
- `odds_api_game_lines` - Per-game odds
- `nbac_schedule` - Schedule updates
- `nbac_gamebook_player_stats` - Post-game player stats
- `br_roster` - Basketball-ref rosters

> **Note:** Not all processors publish completion messages. The actual count tracked may be lower.

### HTTP Endpoints (v2.0)

| Endpoint | Purpose |
|----------|---------|
| `/status?date=YYYY-MM-DD` | Query completion status for a date |
| `/health` | Health check |

### Deployment

```bash
./bin/orchestrators/deploy_phase2_to_phase3.sh
```

---

## Phase 3→4 Orchestrator

**Function:** `phase3-to-phase4-orchestrator`
**Location:** `orchestration/cloud_functions/phase3_to_phase4/main.py`
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

## Phase 4→5 Orchestrator

**Function:** `phase4-to-phase5-orchestrator`
**Location:** `orchestration/cloud_functions/phase4_to_phase5/main.py`
**Entry Point:** `orchestrate_phase4_to_phase5`

### Configuration

| Setting | Value |
|---------|-------|
| Runtime | Python 3.11 |
| Memory | 256MB |
| Timeout | 60s |
| Max Instances | 10 |
| Trigger | Pub/Sub `nba-phase4-precompute-complete` |
| Firestore Collection | `phase4_completion/{game_date}` |

### Behavior

1. **Receive** completion message from Phase 4 processor
2. **Normalize** processor name (class name → config name)
3. **Update** Firestore document atomically
4. **Check** if all 5 processors have completed
5. **Trigger** Phase 5 via:
   - Pub/Sub to `nba-predictions-trigger`
   - HTTP POST to prediction-coordinator `/start` endpoint

### Expected Processors (5)

- `team_defense_zone_analysis`
- `player_shot_zone_analysis`
- `player_composite_factors`
- `player_daily_cache`
- `ml_feature_store`

### Deployment

```bash
./bin/orchestrators/deploy_phase4_to_phase5.sh
```

---

## Phase 5→6 Orchestrator

**Function:** `phase5-to-phase6-orchestrator`
**Location:** `orchestration/cloud_functions/phase5_to_phase6/main.py`

### Configuration

| Setting | Value |
|---------|-------|
| Trigger | Pub/Sub `nba-phase5-predictions-complete` |
| Firestore Collection | `phase5_completion/{game_date}` |

### Behavior

1. **Receive** prediction completion message
2. **Check** completion percentage (requires >80%)
3. **Trigger** Phase 6 export if threshold met

---

## Cloud Schedulers (Phase 4/5)

In addition to Pub/Sub orchestrators, several **Cloud Scheduler jobs** trigger Phase 4 and 5 directly.

### Overnight Post-Game Processing

These run overnight and process **YESTERDAY's** games (post-game data):

| Scheduler | Time (PT) | Target | Purpose |
|-----------|-----------|--------|---------|
| `player-composite-factors-daily` | 11:00 PM | Phase 4 | Composite factors for yesterday |
| `player-daily-cache-daily` | 11:15 PM | Phase 4 | Daily cache for yesterday |
| `ml-feature-store-daily` | 11:30 PM | Phase 4 | ML features for yesterday |

> **Note:** These use `analysis_date: "AUTO"` which resolves to **YESTERDAY** in UTC.

### Morning Same-Day Processing (Added Dec 2025)

These run in the morning and process **TODAY's** games (pre-game predictions):

| Scheduler | Time (ET) | Target | Purpose |
|-----------|-----------|--------|---------|
| `same-day-phase3` | 10:30 AM | Phase 3 | UpcomingPlayerGameContext for today |
| `same-day-phase4` | 11:00 AM | Phase 4 | MLFeatureStore for today (same-day mode) |
| `same-day-predictions` | 11:30 AM | Phase 5 | Prediction coordinator for today |

> **Note:** These use `analysis_date: "TODAY"` which resolves to **today in ET timezone**.

### Same-Day vs Overnight Mode

| Mode | When | Date Processed | Key Parameters |
|------|------|----------------|----------------|
| **Overnight** | 11 PM - midnight PT | Yesterday | `backfill_mode: true` (post-game) |
| **Same-Day** | 10:30 - 11:30 AM ET | Today | `strict_mode: false, skip_dependency_check: true` |

### Setup Script

```bash
# Create or recreate same-day schedulers
./bin/orchestrators/setup_same_day_schedulers.sh
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

**Document Version:** 3.0
**Created:** 2025-11-29 16:53 PST
**Last Updated:** 2025-12-26
**Changes:**
- v3.0 (2025-12-26): Added Phase 4→5, Phase 5→6 orchestrators; Added morning schedulers section
- v2.0 (2025-12-23): Phase 2→3 orchestrator converted to monitoring-only mode
