# Session 169: Live Scoring Infrastructure Complete

**Date:** December 25, 2025 (Late Night)
**Status:** Live scoring built, pipeline issue discovered

---

## What Was Built Tonight

### 1. LiveScoresExporter ✅
- **File:** `data_processors/publishing/live_scores_exporter.py`
- **Endpoint:** `/v1/live/{date}.json` and `/v1/live/latest.json`
- **Purpose:** Raw player points for Challenge System grading
- **Tested:** Working - exported to GCS successfully

### 2. LiveGradingExporter ✅
- **File:** `data_processors/publishing/live_grading_exporter.py`
- **Endpoint:** `/v1/live-grading/{date}.json`
- **Purpose:** Show prediction accuracy during live games
- **Tested:** Working - but no predictions to grade (see below)

### 3. Cloud Function ✅
- **File:** `orchestration/cloud_functions/live_export/main.py`
- **Exports both:** live scores + live grading in single call

### 4. Deployment Script ✅
- **File:** `bin/deploy/deploy_live_export.sh`
- **Schedulers:** Every 3 min during game windows (7 PM - 2 AM ET)

---

## Morning Priority: Fix Prediction Pipeline

### The Problem
Phase 5 predictions stopped on Dec 20. Root cause: **Phase 3 stuck in "running" state**.

```
Phase 3 STUCK → Phase 4 BLOCKED → Phase 5 NEVER TRIGGERED
```

### Quick Fix Steps

**Step 1: Check stuck Firestore entries**
```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
db = firestore.Client()
stuck = db.collection('run_history').where('status', '==', 'running').stream()
for doc in stuck:
    print(f'{doc.id}: {doc.to_dict().get(\"processor_name\")} - {doc.to_dict().get(\"analysis_date\")}')"
```

**Step 2: Clear stuck entries**
```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
stuck = db.collection('run_history').where('status', '==', 'running').stream()
for doc in stuck:
    doc.reference.update({'status': 'failed', 'error': 'Manually cleared', 'updated_at': datetime.utcnow()})
    print(f'Cleared: {doc.id}')"
```

**Step 3: Trigger predictions manually**
```bash
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/generate" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-26"}'
```

---

## After Pipeline Fixed: Deploy Live Export

```bash
./bin/deploy/deploy_live_export.sh
```

This will:
1. Deploy Cloud Function `live-export`
2. Create schedulers for game windows
3. Start updating `/v1/live/` and `/v1/live-grading/` every 3 min

---

## Files Changed Tonight

| File | Change |
|------|--------|
| `data_processors/publishing/live_scores_exporter.py` | NEW - Live scores |
| `data_processors/publishing/live_grading_exporter.py` | NEW - Live grading |
| `orchestration/cloud_functions/live_export/main.py` | NEW - Cloud Function |
| `orchestration/cloud_functions/live_export/requirements.txt` | NEW |
| `bin/deploy/deploy_live_export.sh` | NEW - Deploy script |
| `backfill_jobs/publishing/daily_export.py` | Added `live`, `live-grading` |
| `config/phase6_publishing.yaml` | Added live config |
| `docs/08-projects/current/PHASE5-PREDICTIONS-NOT-RUNNING.md` | NEW - Pipeline issue doc |

---

## Frontend Doc Updated

Updated `/home/naji/code/props-web/docs/06-projects/current/challenge-system/BACKEND-API-QUESTIONS.md` with:
- Both live endpoints documented
- Response formats
- Deployment status

---

## Quick Test Commands

```bash
# Test live scores export
BDL_API_KEY=$(gcloud secrets versions access latest --secret=BDL_API_KEY) \
PYTHONPATH=. .venv/bin/python -c "
from data_processors.publishing.live_scores_exporter import LiveScoresExporter
from datetime import date
e = LiveScoresExporter()
path = e.export(date.today().strftime('%Y-%m-%d'))
print(f'Exported: {path}')"

# Check GCS files
gsutil ls -l "gs://nba-props-platform-api/v1/live/"
```

---

## Summary

✅ Live scoring infrastructure complete
⚠️ Pipeline broken (Phase 3 stuck) - fix in morning
📝 Detailed fix guide in `docs/08-projects/current/PHASE5-PREDICTIONS-NOT-RUNNING.md`
