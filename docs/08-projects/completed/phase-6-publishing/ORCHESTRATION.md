# Phase 6: Orchestration Architecture

**Last Updated:** 2025-12-12
**Status:** Implementation Complete

This document describes how Phase 6 publishing is triggered and orchestrated.

---

## Overview

Phase 6 uses a **hybrid triggering strategy**:

| Export Type | Trigger | When |
|-------------|---------|------|
| Tonight predictions | Event-driven | Immediately after Phase 5 predictions complete |
| Results & Best Bets | Cloud Scheduler | 5 AM ET (after games finish) |
| Player Profiles | Cloud Scheduler | 6 AM ET Sundays (weekly) |

---

## Architecture Diagram

```
                        PHASE 5 PREDICTIONS
                               │
                               ▼
            ┌──────────────────────────────────────┐
            │   PredictionCoordinator              │
            │   (predictions/coordinator/)         │
            │                                      │
            │   When all predictions complete:     │
            │   → Publishes to topic               │
            └──────────────────────────────────────┘
                               │
                               ▼
         nba-phase5-predictions-complete (Pub/Sub)
                               │
                               ▼
            ┌──────────────────────────────────────┐
            │   Phase 5→6 Orchestrator             │
            │   (Cloud Function)                   │
            │                                      │
            │   Validates completion (>80%)        │
            │   → Publishes trigger message        │
            └──────────────────────────────────────┘
                               │
                               ▼
           nba-phase6-export-trigger (Pub/Sub)
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
    ┌──────────────────┐              ┌──────────────────┐
    │ Cloud Scheduler  │              │ Phase 6 Export   │
    │ (scheduled jobs) │──────────────│ Cloud Function   │
    │                  │              │                  │
    │ • Results (5AM)  │              │ Routes to:       │
    │ • Profiles (Sun) │              │ • Tonight export │
    └──────────────────┘              │ • Results export │
                                      │ • Player export  │
                                      └──────────────────┘
                                               │
                                               ▼
                                  ┌──────────────────────┐
                                  │ daily_export.py      │
                                  │ (backfill_jobs)      │
                                  │                      │
                                  │ Calls exporters →    │
                                  │ Uploads to GCS       │
                                  └──────────────────────┘
                                               │
                                               ▼
                               gs://nba-props-platform-api/v1/
```

---

## Phase 5→6 Orchestrator

### Purpose

Triggers tonight's predictions export immediately when Phase 5 predictions complete, ensuring the website has fresh data as soon as predictions are ready.

### Configuration

| Property | Value |
|----------|-------|
| Function Name | `phase5-to-phase6-orchestrator` |
| Runtime | Python 3.11 |
| Region | us-west2 |
| Memory | 256MB |
| Timeout | 60s |
| Trigger Topic | `nba-phase5-predictions-complete` |
| Output Topic | `nba-phase6-export-trigger` |

### Location

```
orchestration/cloud_functions/phase5_to_phase6/
├── main.py              # Cloud Function entry point
└── requirements.txt     # Dependencies
```

### Message Flow

**Input message from Phase 5:**
```json
{
  "processor_name": "PredictionCoordinator",
  "phase": "phase_5_predictions",
  "execution_id": "batch_2025-12-12_1734012345",
  "correlation_id": "abc-123",
  "game_date": "2025-12-12",
  "output_table": "player_prop_predictions",
  "status": "success",
  "record_count": 450,
  "metadata": {
    "batch_id": "batch_2025-12-12_1734012345",
    "expected_predictions": 450,
    "completed_predictions": 448,
    "failed_predictions": 2,
    "completion_pct": 99.6
  }
}
```

**Output message to Phase 6:**
```json
{
  "export_types": ["tonight", "tonight-players", "predictions", "streaks"],
  "target_date": "2025-12-12",
  "update_latest": true,
  "trigger_source": "orchestrator",
  "triggered_by": "phase5_to_phase6_orchestrator",
  "correlation_id": "abc-123",
  "timestamp": "2025-12-12T18:00:00Z",
  "upstream_batch_id": "batch_2025-12-12_1734012345",
  "upstream_predictions": 448
}
```

### Validation Rules

The orchestrator validates before triggering Phase 6:

1. **Status check**: Only triggers on `success` or `partial` status
2. **Completion threshold**: Requires ≥80% completion (`MIN_COMPLETION_PCT`)
3. **Required fields**: `game_date` must be present

### Deployment

```bash
# Deploy the orchestrator
./bin/orchestrators/deploy_phase5_to_phase6.sh
```

### Monitoring

```bash
# View logs
gcloud functions logs read phase5-to-phase6-orchestrator --region us-west2 --limit 50

# Test manually
gcloud pubsub topics publish nba-phase5-predictions-complete --message='{
  "game_date":"2024-12-12",
  "status":"success",
  "metadata":{"completion_pct":100}
}'
```

---

## Cloud Scheduler Jobs

For exports that don't need immediate triggering, Cloud Scheduler provides reliable cron-based execution.

### Scheduler Configuration

Located in `config/phase6_publishing.yaml`:

```yaml
scheduler:
  jobs:
    - name: phase6-daily-results
      schedule: "0 10 * * *"  # 10 AM UTC = 5 AM ET
      export_types: [results, performance, best-bets]
      target_date: yesterday

    - name: phase6-tonight-picks
      schedule: "0 18 * * *"  # 6 PM UTC = 1 PM ET
      export_types: [tonight, tonight-players, predictions, streaks]
      target_date: today

    - name: phase6-player-profiles
      schedule: "0 11 * * 0"  # 11 AM UTC Sundays = 6 AM ET
      players: true
      min_games: 5
```

### Why Both Scheduler AND Orchestrator?

| Scenario | Trigger | Reason |
|----------|---------|--------|
| Tonight predictions | Orchestrator | Time-sensitive; want immediate update when predictions ready |
| Tonight predictions backup | Scheduler (1 PM) | Fallback if orchestrator fails or predictions late |
| Results/Best Bets | Scheduler (5 AM) | Not time-critical; games finished overnight |
| Player Profiles | Scheduler (Sunday) | Weekly aggregation; no urgency |

### Deploying Scheduler

```bash
# Deploy scheduler jobs
./bin/deploy/deploy_phase6_scheduler.sh

# Or with dry-run first
./bin/deploy/deploy_phase6_scheduler.sh --dry-run
```

---

## Pub/Sub Topics

### Topics Used

| Topic | Publisher | Consumer |
|-------|-----------|----------|
| `nba-phase5-predictions-complete` | Prediction Coordinator | Phase 5→6 Orchestrator |
| `nba-phase6-export-trigger` | Orchestrator, Scheduler | Phase 6 Export Function |
| `nba-phase6-export-complete` | Phase 6 Export Function | Monitoring (future) |

### Topic Configuration

Topics are defined in `shared/config/pubsub_topics.py`:

```python
class PubSubTopics:
    # Phase 6 topics
    PHASE6_EXPORT_TRIGGER = 'nba-phase6-export-trigger'
    PHASE6_EXPORT_COMPLETE = 'nba-phase6-export-complete'
```

### Creating Topics

```bash
# Create topics if they don't exist
gcloud pubsub topics create nba-phase6-export-trigger
gcloud pubsub topics create nba-phase6-export-complete
```

---

## Phase 6 Export Cloud Function

### Purpose

Receives trigger messages and executes the appropriate export.

### Location

```
orchestration/cloud_functions/phase6_export/
├── main.py              # Cloud Function entry point
└── requirements.txt     # Dependencies
```

### Message Handling

The function handles two message types:

**Daily/Tonight export:**
```json
{
  "export_types": ["tonight", "tonight-players"],
  "target_date": "2025-12-12",
  "update_latest": true
}
```

**Player profiles export:**
```json
{
  "players": true,
  "min_games": 5
}
```

### Deployment

```bash
# Deploy Phase 6 Export function
gcloud functions deploy phase6-export \
  --gen2 \
  --runtime python311 \
  --region us-west2 \
  --source orchestration/cloud_functions/phase6_export \
  --entry-point main \
  --trigger-topic nba-phase6-export-trigger \
  --memory 512MB \
  --timeout 540s \
  --set-env-vars GCP_PROJECT=nba-props-platform,GCS_BUCKET=nba-props-platform-api
```

---

## Complete Trigger Flow

### Scenario 1: Tonight Predictions (Event-Driven)

```
1. Phase 5 PredictionCoordinator completes predictions for 2025-12-12
2. Coordinator publishes to nba-phase5-predictions-complete:
   {"game_date": "2025-12-12", "status": "success", "metadata": {...}}
3. phase5-to-phase6-orchestrator receives message
4. Orchestrator validates: status=success, completion_pct=99%
5. Orchestrator publishes to nba-phase6-export-trigger:
   {"export_types": ["tonight", "tonight-players", ...], "target_date": "2025-12-12"}
6. phase6-export function receives message
7. Function calls daily_export.py with export types
8. Exporters query BigQuery, generate JSON, upload to GCS
9. gs://nba-props-platform-api/v1/tonight/all-players.json updated
```

### Scenario 2: Results Export (Scheduled)

```
1. Cloud Scheduler fires at 5 AM ET (10 AM UTC)
2. Scheduler publishes to nba-phase6-export-trigger:
   {"export_types": ["results", "performance", "best-bets"], "target_date": "yesterday"}
3. phase6-export function receives message
4. Function calculates yesterday's date
5. Function calls daily_export.py with export types
6. Exporters query BigQuery, generate JSON, upload to GCS
7. gs://nba-props-platform-api/v1/results/latest.json updated
```

---

## Error Handling

### Orchestrator Failures

If the Phase 5→6 orchestrator fails:

1. **Pub/Sub retry**: Cloud Functions automatically retry on failure
2. **Scheduler backup**: The 1 PM scheduler job will run tonight exports
3. **Manual fallback**: Run export manually via CLI

### Export Function Failures

If the Phase 6 export function fails:

1. **Pub/Sub retry**: Automatic retries with exponential backoff
2. **Partial success**: Function reports which exports succeeded/failed
3. **Manual recovery**: Run specific exports via CLI

### Manual Export Commands

```bash
# Tonight exports
python backfill_jobs/publishing/daily_export.py --date 2025-12-12 --only tonight,tonight-players

# Results exports
python backfill_jobs/publishing/daily_export.py --date 2025-12-11 --only results,best-bets

# Player profiles
python backfill_jobs/publishing/daily_export.py --players --min-games 5
```

---

## Monitoring

### Logs

```bash
# Orchestrator logs
gcloud functions logs read phase5-to-phase6-orchestrator --region us-west2

# Export function logs
gcloud functions logs read phase6-export --region us-west2

# Filter by severity
gcloud functions logs read phase6-export --region us-west2 --min-log-level ERROR
```

### Metrics to Track

1. **Export latency**: Time from Phase 5 complete to GCS upload
2. **Success rate**: % of triggers that complete successfully
3. **File freshness**: Age of latest.json files

### Future: Alerting

Set up alerts for:

- Export function failures (Cloud Monitoring)
- GCS file staleness (custom check)
- Pub/Sub message backlog

---

## Files Reference

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/phase5_to_phase6/main.py` | Orchestrator Cloud Function |
| `orchestration/cloud_functions/phase6_export/main.py` | Export Cloud Function |
| `bin/orchestrators/deploy_phase5_to_phase6.sh` | Orchestrator deployment |
| `bin/deploy/deploy_phase6_scheduler.sh` | Scheduler deployment |
| `config/phase6_publishing.yaml` | Scheduler configuration |
| `shared/config/pubsub_topics.py` | Topic definitions |
| `backfill_jobs/publishing/daily_export.py` | Export orchestration |
| `data_processors/publishing/*_exporter.py` | Individual exporters |

---

**End of Orchestration Document**
