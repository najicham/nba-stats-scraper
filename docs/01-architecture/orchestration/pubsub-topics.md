# Pub/Sub Topics Architecture

**Purpose:** Event-driven communication between pipeline phases
**Status:** v1.0 deployed and operational
**Created:** 2025-11-29 16:51 PST
**Last Updated:** 2025-11-29 16:51 PST

---

## Overview

The NBA Props Platform uses Google Cloud Pub/Sub for asynchronous, event-driven communication between processing phases. This decouples services, enables parallel processing, and provides reliable message delivery with automatic retries.

---

## Architecture Diagram

```
┌─────────────┐
│   Phase 1   │
│  Scrapers   │
└──────┬──────┘
       │ publishes
       ▼
┌──────────────────────────────────┐
│  nba-phase1-scrapers-complete    │  (legacy: nba-scraper-complete)
└──────────────────┬───────────────┘
                   │ triggers
                   ▼
┌─────────────┐
│   Phase 2   │
│ Raw Process │──┐
└──────┬──────┘  │
       │         │ (21 processors each publish)
       ▼         ▼
┌──────────────────────────────────┐
│     nba-phase2-raw-complete      │
└──────────────────┬───────────────┘
                   │ triggers orchestrator
                   ▼
┌────────────────────────────────────┐
│   Phase 2→3 Orchestrator           │
│   (waits for 21/21 complete)       │
└──────────────────┬─────────────────┘
                   │ publishes
                   ▼
┌──────────────────────────────────┐
│       nba-phase3-trigger         │
└──────────────────┬───────────────┘
                   │ triggers
                   ▼
┌─────────────┐
│   Phase 3   │
│ Analytics   │──┐
└──────┬──────┘  │
       │         │ (5 processors each publish)
       ▼         ▼
┌──────────────────────────────────┐
│  nba-phase3-analytics-complete   │
└──────────────────┬───────────────┘
                   │ triggers orchestrator
                   ▼
┌────────────────────────────────────┐
│   Phase 3→4 Orchestrator           │
│   (waits for 5/5 complete)         │
└──────────────────┬─────────────────┘
                   │ publishes
                   ▼
┌──────────────────────────────────┐
│       nba-phase4-trigger         │
└──────────────────┬───────────────┘
                   │ triggers
                   ▼
┌─────────────┐
│   Phase 4   │
│ Precompute  │──┐
└──────┬──────┘  │
       │         │ (5 processors)
       ▼         ▼
┌──────────────────────────────────┐
│  nba-phase4-processor-complete   │ (internal orchestration)
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  nba-phase4-precompute-complete  │ (final Phase 4 output)
└──────────────────┬───────────────┘
                   │ triggers
                   ▼
┌─────────────┐
│   Phase 5   │
│ Predictions │
└──────┬──────┘
       │ publishes
       ▼
┌──────────────────────────────────┐
│ nba-phase5-predictions-complete  │
└──────────────────────────────────┘
```

---

## Topic Reference

### Phase 1: Scrapers

| Topic | `nba-phase1-scrapers-complete` |
|-------|--------------------------------|
| **Purpose** | Signal scraper execution complete |
| **Publisher** | Phase 1 scrapers (Cloud Run) |
| **Subscriber** | Phase 2 raw processors |
| **Legacy Topic** | `nba-scraper-complete` (dual publishing during migration) |

**Message Format:**
```json
{
  "scraper_name": "nbac_boxscore_scraper",
  "game_date": "2025-11-29",
  "games_processed": 12,
  "status": "success",
  "correlation_id": "abc-123",
  "timestamp": "2025-11-29T12:00:00Z"
}
```

---

### Phase 2: Raw Processors

| Topic | `nba-phase2-raw-complete` |
|-------|---------------------------|
| **Purpose** | Signal individual raw processor complete |
| **Publisher** | Phase 2 raw processors (21 total) |
| **Subscriber** | Phase 2→3 Orchestrator (Cloud Function) |
| **Volume** | ~63 messages/day (21 processors × 3 batches) |

**Message Format:**
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

**Phase 2 Processors (21):**
- BdlGamesProcessor
- BdlTeamsProcessor
- BdlPlayersProcessor
- BdlBoxscoresProcessor
- NbacBoxscoreProcessor
- NbacGamesProcessor
- NbacPlayersProcessor
- NbacTeamsProcessor
- NbacTeamBoxscoreProcessor
- PdGamesProcessor
- PdPlayerStatsProcessor
- PdTeamsProcessor
- PdScheduleProcessor
- OddsGamesProcessor
- OddsPlayerPropsProcessor
- OddsTeamLinesProcessor
- InjuriesProcessor
- NewsProcessor
- TransactionsProcessor
- RefereesProcessor
- StandingsProcessor

---

### Phase 2→3 Orchestration

| Topic | `nba-phase3-trigger` |
|-------|----------------------|
| **Purpose** | Trigger Phase 3 analytics when all Phase 2 complete |
| **Publisher** | Phase 2→3 Orchestrator (Cloud Function) |
| **Subscriber** | Phase 3 analytics processors (5 total) |
| **Condition** | Only published when all 21 Phase 2 processors complete |

**Message Format:**
```json
{
  "game_date": "2025-11-29",
  "correlation_id": "abc-123",
  "trigger_source": "orchestrator",
  "triggered_by": "phase2_to_phase3_orchestrator",
  "upstream_processors_count": 21,
  "timestamp": "2025-11-29T12:30:00Z"
}
```

---

### Phase 3: Analytics Processors

| Topic | `nba-phase3-analytics-complete` |
|-------|--------------------------------|
| **Purpose** | Signal individual analytics processor complete |
| **Publisher** | Phase 3 analytics processors (5 total) |
| **Subscriber** | Phase 3→4 Orchestrator (Cloud Function) |
| **Volume** | ~15 messages/day (5 processors × 3 batches) |

**Message Format:**
```json
{
  "processor_name": "PlayerGameSummaryProcessor",
  "phase": "phase_3_analytics",
  "execution_id": "ghi-789",
  "correlation_id": "abc-123",
  "game_date": "2025-11-29",
  "output_table": "player_game_summary",
  "output_dataset": "nba_analytics",
  "status": "success",
  "record_count": 450,
  "metadata": {
    "is_incremental": true,
    "entities_changed": ["lebron-james", "stephen-curry"]
  },
  "timestamp": "2025-11-29T12:45:00Z"
}
```

**Phase 3 Processors (5):**
- PlayerGameSummaryProcessor
- TeamDefenseGameSummaryProcessor
- TeamOffenseGameSummaryProcessor
- UpcomingPlayerGameContextProcessor
- UpcomingTeamGameContextProcessor

---

### Phase 3→4 Orchestration

| Topic | `nba-phase4-trigger` |
|-------|----------------------|
| **Purpose** | Trigger Phase 4 precompute when all Phase 3 complete |
| **Publisher** | Phase 3→4 Orchestrator (Cloud Function) |
| **Subscriber** | Phase 4 precompute processors (5 total) |
| **Condition** | Only published when all 5 Phase 3 processors complete |

**Message Format:**
```json
{
  "game_date": "2025-11-29",
  "correlation_id": "abc-123",
  "trigger_source": "orchestrator",
  "triggered_by": "phase3_to_phase4_orchestrator",
  "upstream_processors_count": 5,
  "timestamp": "2025-11-29T13:00:00Z",
  "entities_changed": {
    "players": ["lebron-james", "stephen-curry"],
    "teams": ["LAL", "GSW"]
  },
  "is_incremental": true
}
```

---

### Phase 4: Precompute Processors

| Topic | `nba-phase4-processor-complete` |
|-------|--------------------------------|
| **Purpose** | Internal Phase 4 orchestration |
| **Publisher** | Phase 4 precompute processors |
| **Subscriber** | Phase 4 internal coordinator |
| **Note** | Used for dependency ordering within Phase 4 |

| Topic | `nba-phase4-precompute-complete` |
|-------|----------------------------------|
| **Purpose** | Signal all Phase 4 processing complete |
| **Publisher** | ml_feature_store_v2 (final Phase 4 processor) |
| **Subscriber** | Phase 5 Prediction Coordinator |

**Message Format:**
```json
{
  "processor_name": "MlFeatureStoreV2Processor",
  "phase": "phase_4_precompute",
  "execution_id": "jkl-012",
  "correlation_id": "abc-123",
  "game_date": "2025-11-29",
  "output_table": "ml_feature_store",
  "output_dataset": "nba_precompute",
  "status": "success",
  "record_count": 450,
  "timestamp": "2025-11-29T13:15:00Z"
}
```

**Phase 4 Processors (5):**
- SimilarPlayerGamesProcessor
- TeamDefenseZoneAnalysisProcessor
- PlayerProjectionsProcessor
- MlFeatureStoreProcessor
- MlFeatureStoreV2Processor

---

### Phase 5: Predictions

| Topic | `nba-phase5-predictions-complete` |
|-------|-----------------------------------|
| **Purpose** | Signal prediction batch complete |
| **Publisher** | Phase 5 Prediction Coordinator |
| **Subscriber** | Optional downstream (monitoring, notifications) |

**Message Format:**
```json
{
  "game_date": "2025-11-29",
  "correlation_id": "abc-123",
  "batch_id": "batch-2025-11-29-001",
  "players_processed": 450,
  "predictions_generated": 450,
  "status": "success",
  "timestamp": "2025-11-29T13:30:00Z"
}
```

---

## Implementation

### Code Reference

Topic definitions are centralized in:

```python
# shared/config/pubsub_topics.py

from shared.config.pubsub_topics import TOPICS

# Usage:
publisher.publish(topic=TOPICS.PHASE2_RAW_COMPLETE, message=...)
```

### Creating Topics

```bash
# Create all topics
./bin/pubsub/create_topics.sh

# Or manually:
gcloud pubsub topics create nba-phase1-scrapers-complete
gcloud pubsub topics create nba-phase2-raw-complete
gcloud pubsub topics create nba-phase3-trigger
gcloud pubsub topics create nba-phase3-analytics-complete
gcloud pubsub topics create nba-phase4-trigger
gcloud pubsub topics create nba-phase4-processor-complete
gcloud pubsub topics create nba-phase4-precompute-complete
gcloud pubsub topics create nba-phase5-predictions-complete
```

### Listing Topics

```bash
gcloud pubsub topics list --project=nba-props-platform | grep nba-phase
```

---

## Message Standards

### Required Fields (All Messages)

| Field | Type | Description |
|-------|------|-------------|
| `correlation_id` | string | UUID tracing request through all phases |
| `game_date` | string | ISO date (YYYY-MM-DD) |
| `timestamp` | string | ISO 8601 timestamp |
| `status` | string | "success", "partial", or "failed" |

### Processor Completion Messages

| Field | Type | Description |
|-------|------|-------------|
| `processor_name` | string | e.g., "BdlGamesProcessor" |
| `phase` | string | e.g., "phase_2_raw" |
| `execution_id` | string | Unique execution identifier |
| `output_table` | string | BigQuery table written to |
| `output_dataset` | string | BigQuery dataset |
| `record_count` | int | Records processed |

### Change Detection Fields (Phase 3+)

| Field | Type | Description |
|-------|------|-------------|
| `metadata.is_incremental` | bool | Whether change detection was used |
| `metadata.entities_changed` | array | List of changed entity IDs |

---

## Correlation Tracking

The `correlation_id` flows through the entire pipeline:

```
Phase 1 (Scraper)     → correlation_id: "abc-123"
    ↓
Phase 2 (Raw)         → correlation_id: "abc-123" (inherited)
    ↓
Orchestrator 2→3      → correlation_id: "abc-123" (passed through)
    ↓
Phase 3 (Analytics)   → correlation_id: "abc-123" (inherited)
    ↓
Orchestrator 3→4      → correlation_id: "abc-123" (passed through)
    ↓
Phase 4 (Precompute)  → correlation_id: "abc-123" (inherited)
    ↓
Phase 5 (Predictions) → correlation_id: "abc-123" (final)
```

Query by correlation_id:
```sql
SELECT phase, processor_name, status, processed_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE correlation_id = 'abc-123'
ORDER BY processed_at ASC
```

---

## Monitoring

### Check Topic Status

```bash
# List all subscriptions
gcloud pubsub subscriptions list --project=nba-props-platform

# Check message backlog
gcloud pubsub subscriptions describe <subscription-name> \
  --format="value(numMessagesUndelivered)"
```

### View Recent Messages

Messages are logged to Cloud Logging. View via:
- [Cloud Functions Logs](https://console.cloud.google.com/functions) - orchestrator processing
- [Cloud Run Logs](https://console.cloud.google.com/run) - processor publishing

---

## Related Documentation

- [Orchestrators Architecture](./orchestrators.md) - How orchestrators coordinate phases
- [Firestore State Management](./firestore-state-management.md) - Orchestrator state tracking
- [Pub/Sub Operations Guide](../../02-operations/pubsub-operations.md) - Operational procedures
- [v1.0 Deployment Guide](../../04-deployment/v1.0-deployment-guide.md) - Deployment instructions

---

**Document Version:** 1.0
**Created:** 2025-11-29 16:51 PST
**Last Updated:** 2025-11-29 16:51 PST
