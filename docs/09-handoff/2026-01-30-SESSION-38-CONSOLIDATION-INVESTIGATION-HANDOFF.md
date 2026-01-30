# Session 38 Handoff - Consolidation Investigation

**Date:** 2026-01-30
**Status:** Root causes identified, partial fix applied, code changes needed

---

## Session Summary

Investigated why predictions were stuck in staging tables and not being consolidated to the main `player_prop_predictions` table. Identified multiple issues and applied partial fixes.

---

## Key Findings

### 1. Completion Event Tracking Gap (~50% loss)

**Observation:**
- Workers write predictions to staging tables successfully
- Workers publish completion events to Pub/Sub
- Coordinator receives events (logs show POST /complete → 204)
- But only ~50% of completions are recorded in Firestore

**Evidence:**
- Batch `batch_2026-01-30_1769796743`: 175 staging tables, only 68 completions recorded
- Batch `batch_2026-01-30_1769798373`: 173 staging tables, only 126 completions recorded

**Root Cause:** Unknown - requires deeper investigation into coordinator `/complete` handler

### 2. Schema Mismatch Between Staging and Main Table

**Observation:**
- Staging tables: 63 columns
- Main table: 72 columns
- MERGE query fails with "wrong column count"

**Missing columns in staging tables:**
```
- calibrated_confidence_score
- calibration_method
- early_season_flag
- feature_count
- feature_data_source
- feature_quality_score
- feature_version
- prediction_error_code
- raw_confidence_score
```

**Impact:** Consolidation MERGE query fails for all batches with new staging schema

### 3. Stalled Batch Detection Not Triggering

**Observation:**
- `/check-stalled` endpoint requires batches to:
  1. Reach `min_completion_pct` threshold (default 95%)
  2. Have no updates for `stall_threshold_minutes` (default 10)
- Batches at 48-89% completion never trigger stall detection

---

## Fixes Applied

| Fix | Status | Impact |
|-----|--------|--------|
| Force-completed batch 1769796743 via `/check-stalled` | ✅ Done | 911 predictions consolidated |
| Force-marked 3 additional batches as `is_complete=True` | ✅ Done | Enabled consolidation attempt |
| Attempted consolidation for other batches | ❌ Failed | Schema mismatch |

---

## Current State

### Predictions Table (2026-01-30)
```
Total predictions: 911
Unique players: 141
Source: Batch 1769796743 only
```

### Stuck Batches
| Batch ID | Completed Players | Status |
|----------|-------------------|--------|
| batch_2026-01-30_1769798373 | 126/141 (89%) | Schema mismatch |
| batch_2026-01-30_1769799350 | 116/141 (82%) | Schema mismatch |
| batch_2026-01-30_1769800318 | 94/141 (67%) | Schema mismatch |

### Staging Tables
- ~400 staging tables exist for 2026-01-30
- Cannot be consolidated due to schema mismatch
- Contain ~2000+ additional predictions

---

## Code Changes Needed

### 1. Fix Schema Mismatch in Consolidation

**File:** `predictions/shared/batch_staging_writer.py`

**Issue:** MERGE query selects all columns from staging, but staging is missing 9 columns

**Options:**
1. **Update MERGE to only select common columns** (recommended)
2. Add missing columns to staging tables at write time
3. Update worker to include all columns

### 2. Improve Completion Event Reliability

**File:** `predictions/worker/worker.py`

**Issue:** `publish_completion_event()` catches all errors silently (lines 1884-1888)

**Change:** Consider re-raising critical errors or using circuit breaker pattern

### 3. Lower Stall Detection Threshold

**File:** `predictions/coordinator/batch_state_manager.py`

**Issue:** Default 95% threshold too high for batches with lost completion events

**Change:** Consider lowering to 80% or making configurable per-batch

---

## Manual Workaround (If Needed)

To manually consolidate batches with schema mismatch:

```sql
-- Insert from staging with explicit column list (only common columns)
INSERT INTO nba_predictions.player_prop_predictions (
  prediction_id, system_id, player_lookup, universal_player_id,
  game_date, game_id, prediction_version, predicted_points,
  confidence_score, recommendation, current_points_line,
  -- ... list all 63 common columns
  created_at, is_active
)
SELECT
  prediction_id, system_id, player_lookup, universal_player_id,
  game_date, game_id, prediction_version, predicted_points,
  confidence_score, recommendation, current_points_line,
  -- ... select all 63 common columns
  created_at, is_active
FROM `nba_predictions._staging_batch_2026_01_30_*`
WHERE _TABLE_SUFFIX LIKE '%1769798373%'
```

---

## Investigation Timeline

1. **Initial symptom:** 0 predictions for today despite 10 games scheduled
2. **Found:** 400+ staging tables with predictions
3. **Found:** Batches stuck at 48-89% completion (never reached 100%)
4. **Found:** Coordinator receiving completion events (204 responses)
5. **Found:** Firestore state not being updated for ~50% of completions
6. **Fixed:** Force-completed batch via `/check-stalled` with lower threshold
7. **Found:** Schema mismatch blocking other batches
8. **Result:** 911 predictions consolidated, ~2000 still stuck

---

## Files Investigated

| File | Relevant Lines | Purpose |
|------|----------------|---------|
| `predictions/coordinator/coordinator.py` | 1126-1215 | `/complete` endpoint handler |
| `predictions/coordinator/batch_state_manager.py` | 279-400 | `record_completion()` method |
| `predictions/shared/batch_staging_writer.py` | 736-900 | `consolidate_batch()` method |
| `predictions/worker/worker.py` | 1851-1888 | `publish_completion_event()` function |

---

## Next Session Priorities

1. **Fix schema mismatch** - Update consolidation MERGE to use common columns only
2. **Consolidate remaining batches** - ~2000 predictions still stuck
3. **Investigate completion event loss** - Why ~50% of events not updating Firestore
4. **Cleanup staging tables** - 400+ tables accumulating

---

## Quick Reference Commands

```bash
# Check predictions count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-30'"

# Count staging tables
bq ls nba_predictions 2>&1 | grep -c '_staging_'

# Check Firestore batch state
python3 -c "
from google.cloud import firestore
db = firestore.Client()
for b in db.collection('prediction_batches').where('game_date', '==', '2026-01-30').stream():
    d = b.to_dict()
    print(f\"{b.id}: {len(d.get('completed_players', []))}/{d.get('expected_players')}\")"

# Force complete a stalled batch
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/check-stalled" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"batch_id": "batch_2026-01-30_XXXX", "min_completion_pct": 30.0}'
```

---

## Session Metrics

- Duration: ~2 hours
- Issues found: 3 (completion tracking, schema mismatch, stall detection)
- Predictions consolidated: 911 (from 1 of 4 active batches)
- Predictions still stuck: ~2000 (3 batches)

---

*Session 38 complete. Root causes identified, partial fix applied. Code changes needed for full resolution.*
