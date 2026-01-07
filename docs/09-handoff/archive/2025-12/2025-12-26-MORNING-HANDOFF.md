# Morning Handoff - December 26, 2025

**Previous Session:** 169 (Late night Dec 25)
**Priority:** Fix prediction pipeline, deploy live scoring

---

## Executive Summary

Last night we built **live scoring infrastructure** for the Challenge System (frontend feature). Two new exporters were created that fetch live game data and export to GCS every 3 minutes during games.

However, we discovered the **prediction pipeline is broken** - Phase 3 is stuck in "running" state, blocking Phase 4, which blocks Phase 5 (predictions). No new predictions since Dec 20.

---

## Immediate Actions Required

### 1. Fix the Prediction Pipeline (HIGH PRIORITY)

The pipeline chain is broken:
```
Phase 3 STUCK ("running" for 2025-12-23)
    → Phase 4 BLOCKED (dependency check fails)
    → Phase 5 NEVER TRIGGERED
    → No predictions since Dec 20
```

**Step 1: Check stuck entries**
```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
db = firestore.Client()
stuck = db.collection('run_history').where('status', '==', 'running').stream()
for doc in stuck:
    d = doc.to_dict()
    print(f'{doc.id}:')
    print(f'  processor: {d.get(\"processor_name\")}')
    print(f'  date: {d.get(\"analysis_date\")}')
    print(f'  started: {d.get(\"started_at\")}')
    print()
"
```

**Step 2: Clear stuck entries**
```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
stuck = db.collection('run_history').where('status', '==', 'running').stream()
count = 0
for doc in stuck:
    doc.reference.update({
        'status': 'failed',
        'error': 'Manually cleared - was stuck in running state',
        'updated_at': datetime.utcnow()
    })
    print(f'Cleared: {doc.id}')
    count += 1
print(f'Total cleared: {count}')
"
```

**Step 3: Trigger predictions for today**
```bash
# Generate predictions for Dec 26
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/generate" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-26"}'
```

**Step 4: Backfill missed dates (Dec 21-25)**
```bash
for date in 2025-12-21 2025-12-22 2025-12-23 2025-12-24 2025-12-25; do
  echo "Generating predictions for $date..."
  curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/generate" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\"}"
  echo ""
  sleep 30
done
```

**Detailed documentation:** `docs/08-projects/current/PHASE5-PREDICTIONS-NOT-RUNNING.md`

---

### 2. Deploy Live Export Function (AFTER pipeline fixed)

```bash
./bin/deploy/deploy_live_export.sh
```

This deploys:
- Cloud Function `live-export` (HTTP triggered)
- Scheduler `live-export-evening` (7 PM - midnight ET, every 3 min)
- Scheduler `live-export-late-night` (midnight - 2 AM ET, every 3 min)

---

## What Was Built Last Night

### New Files Created

| File | Purpose |
|------|---------|
| `data_processors/publishing/live_scores_exporter.py` | Fetches live player stats from BDL API, exports to GCS |
| `data_processors/publishing/live_grading_exporter.py` | Combines predictions with live stats for accuracy display |
| `orchestration/cloud_functions/live_export/main.py` | Cloud Function that runs both exporters |
| `orchestration/cloud_functions/live_export/requirements.txt` | Dependencies |
| `bin/deploy/deploy_live_export.sh` | Deployment script |
| `docs/08-projects/current/PHASE5-PREDICTIONS-NOT-RUNNING.md` | Pipeline issue documentation |

### Files Modified

| File | Change |
|------|--------|
| `backfill_jobs/publishing/daily_export.py` | Added `live` and `live-grading` export types |
| `config/phase6_publishing.yaml` | Added live export configuration |

### New API Endpoints (after deployment)

| Endpoint | Purpose | Update Frequency |
|----------|---------|------------------|
| `/v1/live/{date}.json` | Live player points for challenge grading | Every 3 min during games |
| `/v1/live/latest.json` | Same, always current | Every 3 min during games |
| `/v1/live-grading/{date}.json` | Live prediction accuracy | Every 3 min during games |
| `/v1/live-grading/latest.json` | Same, always current | Every 3 min during games |

---

## Current System State

### Services Running ✅
- `nba-phase1-scrapers` - Collecting raw data
- `nba-phase2-raw-processors` - Processing to BigQuery
- `nba-phase3-analytics-processors` - Analytics (but blocked)
- `nba-phase4-precompute-processors` - Feature store (but blocked)
- `prediction-coordinator` - Ready but not triggered
- `prediction-worker` - Ready but not triggered
- `phase5b-grading` - Running daily but no predictions to grade

### What's Broken ⚠️
- Phase 3 `PlayerGameSummaryProcessor` stuck in "running" for 2025-12-23
- This blocks Phase 4 dependency checks
- Phase 4 never completes → Phase 5 never triggered
- Last predictions in database: **December 20, 2025**

### Data Freshness
```bash
# Check latest predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM \`nba_predictions.player_prop_predictions\`
WHERE system_id = 'ensemble_v1' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date DESC LIMIT 5"
```

---

## Testing Commands

### Test Live Scores Export
```bash
BDL_API_KEY=$(gcloud secrets versions access latest --secret=BDL_API_KEY --project=nba-props-platform) \
PYTHONPATH=. .venv/bin/python -c "
from data_processors.publishing.live_scores_exporter import LiveScoresExporter
from datetime import date
e = LiveScoresExporter()
data = e.generate_json(date.today().strftime('%Y-%m-%d'))
print(f'Games: {data.get(\"total_games\")}, In Progress: {data.get(\"games_in_progress\")}')
"
```

### Test Live Grading Export
```bash
BDL_API_KEY=$(gcloud secrets versions access latest --secret=BDL_API_KEY --project=nba-props-platform) \
PYTHONPATH=. .venv/bin/python -c "
from data_processors.publishing.live_grading_exporter import LiveGradingExporter
from datetime import date
e = LiveGradingExporter()
data = e.generate_json(date.today().strftime('%Y-%m-%d'))
print(f'Predictions: {data[\"summary\"][\"total_predictions\"]}, Graded: {data[\"summary\"][\"graded\"]}')
"
```

### Check GCS Files
```bash
gsutil ls -l "gs://nba-props-platform-api/v1/live/"
gsutil ls -l "gs://nba-props-platform-api/v1/live-grading/"
```

---

## Frontend Integration

The frontend team's questions have been answered in:
`/home/naji/code/props-web/docs/06-projects/current/challenge-system/BACKEND-API-QUESTIONS.md`

Key points for frontend:
- Use `/v1/live/latest.json` for challenge grading (poll every 30-60 sec)
- `player_lookup` field matches Firestore picks
- `games[].status` values: `scheduled`, `in_progress`, `final`
- Cache TTL is 30 seconds

---

## Verification Checklist

After fixes, verify:

- [ ] Firestore `run_history` has no stuck "running" entries
- [ ] Predictions exist for today: `bq query "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE()"`
- [ ] Live export deployed: `gcloud functions describe live-export --region=us-west2`
- [ ] Schedulers created: `gcloud scheduler jobs list --location=us-west2 --filter="name:live-export"`
- [ ] GCS files updating: `gsutil ls -l "gs://nba-props-platform-api/v1/live/"`

---

## Related Documents

- [Pipeline Issue Details](../08-projects/current/PHASE5-PREDICTIONS-NOT-RUNNING.md)
- [Frontend API Questions](../../props-web/docs/06-projects/current/challenge-system/BACKEND-API-QUESTIONS.md)
- [Session 169 Summary](./2025-12-25-SESSION169-LIVE-SCORING-COMPLETE.md)

---

## Quick Reference

```bash
# Project directory
cd /home/naji/code/nba-stats-scraper

# Activate venv
source .venv/bin/activate

# Check service logs
gcloud logging read 'resource.labels.service_name="prediction-coordinator"' --limit=10 --freshness=1h

# Check Phase 4 errors
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors" AND "error"' --limit=5 --freshness=2h
```
