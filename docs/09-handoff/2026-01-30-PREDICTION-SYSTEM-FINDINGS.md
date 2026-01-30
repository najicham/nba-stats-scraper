# Prediction System Findings - 2026-01-30

**For:** Prediction system team
**From:** Session 39

---

## Issues Identified

### 1. Completion Event Loss (~50%)

**Location:** `predictions/coordinator/coordinator.py` (lines 1126-1215), `predictions/coordinator/batch_state_manager.py` (lines 279-400)

**Symptom:** Workers publish completion events to Pub/Sub, coordinator receives them (logs show POST /complete → 204), but only ~50% of completions are recorded in Firestore.

**Evidence:**
- Batch `batch_2026-01-30_1769796743`: 175 staging tables, only 68 completions recorded
- Batch `batch_2026-01-30_1769798373`: 173 staging tables, only 126 completions recorded

**Impact:** Batches stall at 48-89% completion, never triggering consolidation.

### 2. CatBoost Model Not Loading

**Location:** `predictions/worker/worker.py`

**Symptom:** Logs show repeated warnings:
```
FALLBACK_PREDICTION: CatBoost V8 model not loaded, using weighted average for [player].
Confidence will be 50.0, recommendation will be PASS.
Check CATBOOST_V8_MODEL_PATH env var and model file accessibility.
```

**Impact:** Predictions use simpler weighted average instead of ML model, likely affecting accuracy.

### 3. Accuracy Variance

**Recent accuracy:**
| Date | Graded | Accuracy |
|------|--------|----------|
| Jan 29 | 90 | 42.2% |
| Jan 28 | 569 | 23.7% |
| Jan 27 | 610 | 20.2% |
| Jan 26 | 715 | 12.3% |
| Jan 25 | 564 | 18.6% |
| Jan 23 | 1,072 | 53.4% |

**Observation:** Accuracy dropped from 53% (Jan 23) to 12-24% (Jan 25-28). May correlate with model loading issues or consolidation problems.

### 4. Low Prediction Counts (Now Fixed)

**Issue:** Schema mismatch was preventing consolidation of staging tables.
**Fix:** Applied in Session 39 - `batch_staging_writer.py` now uses explicit column lists.
**Result:** Jan 30 predictions increased from 911 → 19,506 after fix.

---

## Files to Investigate

| File | Issue | Lines |
|------|-------|-------|
| `predictions/coordinator/coordinator.py` | `/complete` handler | 1126-1215 |
| `predictions/coordinator/batch_state_manager.py` | `record_completion()` | 279-400 |
| `predictions/worker/worker.py` | Model loading, completion publishing | 1851-1888 |

---

## Quick Diagnostic Commands

```bash
# Check for model loading errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND "model not loaded"' --limit=20

# Check completion event flow
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-coordinator" AND "/complete"' --limit=20

# Check Firestore batch state
python3 -c "
from google.cloud import firestore
db = firestore.Client()
for b in db.collection('prediction_batches').where('game_date', '==', '2026-01-30').stream():
    d = b.to_dict()
    print(f\"{b.id}: {len(d.get('completed_players', []))}/{d.get('expected_players')}\")"
```

---

*Document created by Session 39 for handoff to prediction system team.*
