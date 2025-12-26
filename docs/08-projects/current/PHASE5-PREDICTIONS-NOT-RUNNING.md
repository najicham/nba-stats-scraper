# Phase 5 Predictions Not Running

**Created:** December 25, 2025
**Priority:** HIGH
**Status:** Needs Investigation
**Last Predictions:** December 20, 2025

---

## Summary

The Phase 5 prediction system has stopped generating predictions. The last predictions in the database are from **December 20, 2025**. This affects:

1. **Live Grading** - The new `/live-grading/{date}.json` endpoint shows no data
2. **Best Bets** - No new recommendations being generated
3. **Tonight's Picks** - Predictions missing from the website
4. **Post-Game Grading** - Nothing to grade (grading function runs but finds no predictions)

---

## Current State

### What's Working
| Component | Status | Notes |
|-----------|--------|-------|
| Phase 1 Scrapers | ✅ Running | Raw data being collected |
| Phase 2 Raw Processors | ✅ Running | Data flowing to BigQuery |
| Phase 5B Grading | ✅ Running | But no predictions to grade |
| Phase 6 Export | ✅ Running | But missing prediction data |

### What's Partially Working
| Component | Status | Notes |
|-----------|--------|-------|
| Phase 3 Analytics | ⚠️ Stuck | `PlayerGameSummaryProcessor` showing "running" for old dates |
| Phase 4 Precompute | ⚠️ Blocked | Failing dependency checks on Phase 3 |

### Services That Exist But Aren't Triggered
| Component | Status | Notes |
|-----------|--------|-------|
| prediction-coordinator | ✅ Deployed | Service exists but not being triggered |
| prediction-worker | ✅ Deployed | Service exists but not being triggered |
| phase4-to-phase5-orchestrator | ✅ Deployed | Not receiving Phase 4 completion messages |

---

## Evidence

### Last Predictions in Database

```sql
SELECT game_date, COUNT(*) as predictions
FROM `nba_predictions.player_prop_predictions`
WHERE system_id = 'ensemble_v1'
  AND is_active = TRUE
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 5;
```

Result:
```
+------------+-------------+
| game_date  | predictions |
+------------+-------------+
| 2025-12-20 |         175 |
+------------+-------------+
```

### Service Check

```bash
gcloud run services describe nba-phase5-prediction-coordinator \
  --region=us-west2 --format="table(status.url)"
# Result: Service not found
```

### Grading Function Logs

The `phase5b-grading` function runs daily at 6 AM ET but finds no predictions to grade for recent dates.

---

## Root Cause: Cascading Pipeline Failure

### The Actual Problem

**Phase 3 → Phase 4 → Phase 5 chain is broken:**

```
Phase 3 (PlayerGameSummaryProcessor) - STUCK in "running" state for 2025-12-23
    ↓
Phase 4 (PrecomputeProcessor) - FAILING dependency checks
    ↓
Phase 4 completion message never published
    ↓
phase4-to-phase5-orchestrator never triggered
    ↓
prediction-coordinator never called
    ↓
NO NEW PREDICTIONS
```

### Error from Phase 4 Logs

```
DependencyError: Upstream PlayerGameSummaryProcessor failed for 2025-12-23.
Error: None
Status: running
```

The Phase 4 processor has strict dependency checks that require Phase 3 to be marked as "completed" before it will run. Since Phase 3 is stuck in "running" status, Phase 4 refuses to process.

### Why Phase 3 is Stuck

The `run_history` tracking in Firestore shows `PlayerGameSummaryProcessor` as "running" for 2025-12-23. This could be:
1. A process that crashed mid-execution without cleanup
2. A timeout that didn't properly mark the run as failed
3. Firestore state corruption

### Immediate Fix Options

**Option A: Reset Phase 3 Status (Quick Fix)**
```python
# In Python, update Firestore to mark stuck runs as failed
from google.cloud import firestore
db = firestore.Client()
# Find and update the stuck run_history document
```

**Option B: Bypass Dependency Checks (Temporary)**
```bash
# Run Phase 4 with backfill_mode=True to skip checks
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2025-12-25", "backfill_mode": true}'
```

**Option C: Fix and Restart the Pipeline**
1. Clear stuck Firestore run_history entries
2. Re-run Phase 3 for affected dates
3. Let pipeline cascade naturally

---

## Files to Check

### Prediction Coordinator
```
predictions/coordinator/coordinator.py
predictions/coordinator/player_loader.py
bin/predictions/deploy/deploy_prediction_coordinator.sh
```

### Prediction Worker
```
predictions/worker/worker.py
bin/predictions/deploy/deploy_prediction_worker.sh
```

### Orchestration
```
orchestration/cloud_functions/phase4_to_phase5/main.py
shared/config/pubsub_topics.py
```

---

## Recommended Actions

### 1. Check Firestore Run History (FIRST!)

```bash
# Check which processors are stuck in "running" state
gcloud firestore documents list \
  --collection-path="run_history" \
  --filter="status=running" \
  --limit=10
```

Or in Python:
```python
from google.cloud import firestore
db = firestore.Client()
stuck = db.collection('run_history').where('status', '==', 'running').stream()
for doc in stuck:
    print(f"{doc.id}: {doc.to_dict()}")
```

### 2. Clear Stuck Run History Entries

```python
from google.cloud import firestore
from datetime import datetime

db = firestore.Client()
stuck_runs = db.collection('run_history').where('status', '==', 'running').stream()

for doc in stuck_runs:
    data = doc.to_dict()
    # Mark as failed with explanation
    doc.reference.update({
        'status': 'failed',
        'error': 'Manually cleared - stuck in running state',
        'updated_at': datetime.utcnow()
    })
    print(f"Cleared: {doc.id}")
```

### 3. Trigger Phase 4 with Backfill Mode

```bash
# Skip dependency checks for today
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2025-12-25", "backfill_mode": true}'
```

### 4. Manually Trigger Predictions

```bash
# Call prediction coordinator directly
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/generate" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-25"}'
```

### 5. Verify Pipeline Flow

```bash
# Check Phase 4 logs for completion
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors" AND "complete"' \
  --limit=5 --format="table(timestamp,textPayload)" --freshness=2h

# Check Phase 4→5 orchestrator
gcloud logging read 'resource.labels.service_name="phase4-to-phase5-orchestrator"' \
  --limit=5 --format="table(timestamp,textPayload)" --freshness=2h

# Check prediction coordinator
gcloud logging read 'resource.labels.service_name="prediction-coordinator"' \
  --limit=5 --format="table(timestamp,textPayload)" --freshness=2h
```

### 6. Backfill Missing Predictions

Once pipeline is fixed:
```bash
# Backfill predictions for missed dates
for date in 2025-12-21 2025-12-22 2025-12-23 2025-12-24 2025-12-25; do
  curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/generate" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\"}"
  sleep 30  # Wait between calls
done
```

---

## Impact on Other Systems

### Live Grading Export (New Feature)
The new `LiveGradingExporter` at `data_processors/publishing/live_grading_exporter.py` requires predictions to exist. Without Phase 5 running:
- `/live-grading/{date}.json` returns empty data
- Website can't show live prediction accuracy

### Challenge System
The Challenge System's live scoring works independently (uses raw player stats), but the prediction accuracy display won't work.

### Best Bets
The `/best-bets/{date}.json` endpoint queries `prediction_accuracy` table which requires both:
1. Predictions (Phase 5)
2. Grading (Phase 5B)

---

## Related Documents

- [Live Scoring Implementation](../../../props-web/docs/06-projects/current/challenge-system/BACKEND-API-QUESTIONS.md)
- [Phase 5 Architecture](../../../docs/03-phases/phase5-predictions/)
- [Deployment Scripts](../../../bin/predictions/deploy/)

---

## Notes for Backfill Work

If you're working on backfill and need predictions:

### The Core Issue
The prediction services ARE deployed, but the pipeline trigger chain is broken because:
1. Phase 3 processor is stuck in "running" status for 2025-12-23
2. Phase 4 refuses to run due to failed dependency check
3. Phase 4 never publishes completion → Phase 5 never triggered

### Priority Order

1. **Fix Phase 3 stuck status** (clear Firestore run_history)
2. **Re-run Phase 3** for 2025-12-23 and subsequent dates
3. **Verify Phase 4** completes and publishes to Pub/Sub
4. **Confirm Phase 5** predictions are generated
5. **Then backfill** any remaining gaps

### Quick Workaround (Skip the Pipeline)

If you need predictions urgently:
```bash
# Directly call the prediction coordinator for each date
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/generate" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-25"}'
```

### Local Testing

```bash
# Test prediction generation locally
PYTHONPATH=. .venv/bin/python predictions/coordinator/coordinator.py \
  --date 2025-12-25 --debug
```

---

## Update Log

| Date | Update |
|------|--------|
| 2025-12-25 | Document created - Phase 5 not running since Dec 20 |
