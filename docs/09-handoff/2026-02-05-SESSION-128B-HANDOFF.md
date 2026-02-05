# Session 128B Handoff - Orchestrator Trigger Fix Investigation

**Date:** 2026-02-05 ~9:00 AM PT
**Status:** 🟡 IN PROGRESS - Fix identified and committed, deployment pending

---

## Quick Summary

Investigated why Feb 5 predictions weren't generated. Found and confirmed a **distributed systems bug** in orchestrators where `_triggered=True` was set before the actual trigger succeeded, causing orphaned states with no retry.

**Good news:** The fix was already committed in a previous Session 128 (commit `a7dc5d9d`).

---

## Root Cause Analysis

### The Bug

**Location:** Both orchestrators had the same pattern:
- `orchestration/cloud_functions/phase3_to_phase4/main.py`
- `orchestration/cloud_functions/phase4_to_phase5/main.py`

**Pattern:**
```python
# INSIDE Firestore transaction
current['_triggered'] = True  # ← Set BEFORE trigger attempt
transaction.set(doc_ref, current)  # ← Committed here

# OUTSIDE transaction
trigger_phase4(...)  # ← Can raise ValueError here
```

**Problem:**
1. Firestore commits `_triggered=True`
2. `trigger_phase4()` has 5+ validation gates that can raise `ValueError`
3. If ValueError raised, Cloud Function fails
4. But Firestore already has `_triggered=True`
5. Cloud Function has `retryPolicy: RETRY_POLICY_DO_NOT_RETRY`
6. Future messages see `_triggered=True` and skip
7. **Result:** Orphaned state - orchestrator thinks it triggered but it never did

### Why Feb 5 Failed

Evidence from Firestore:
- Phase 3 (Feb 4): `_triggered=True` at 07:03:23 UTC
- Phase 4 (Feb 4): **NO completion records** at all
- Phase 4 processors ran (ML Feature Store has 273 records for Feb 5)
- But orchestrator never tracked completions → Phase 5 never triggered

---

## What Was Done This Session

### 1. Investigation
- Traced orchestrator code flow
- Found the premature `_triggered=True` pattern
- Confirmed fix already exists in commit `a7dc5d9d`

### 2. Attempted Feb 5 Predictions
- Triggered Phase 4 processing for Feb 5
- Results:
  - `player_daily_cache`: 252 records ✅
  - `player_shot_zone_analysis`: 455 records ✅
  - `team_defense_zone_analysis`: 0 records ❌
  - `ml_feature_store_v2`: 273 records ✅

- Triggered coordinator `/start` endpoint (processing, may complete after session)

### 3. Cloud Function Deployments (Started)
Started background deployments for:
- `phase3-to-phase4-orchestrator`
- `phase4-to-phase5-orchestrator`

---

## Immediate Actions for Next Session

### 1. Check if Feb 5 Predictions Exist
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-05' AND system_id = 'catboost_v9'"
```

**If predictions exist (>0):** Great, move on.

**If predictions still 0:**
```bash
# Trigger coordinator again
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "${COORDINATOR_URL}/start" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-05", "system_id": "catboost_v9", "force": true}'
```

### 2. Verify Cloud Function Deployments
```bash
# Check if deployments completed
gcloud functions describe phase3-to-phase4-orchestrator --region=us-west2 --format="value(updateTime)"
gcloud functions describe phase4-to-phase5-orchestrator --region=us-west2 --format="value(updateTime)"
```

**If not deployed recently**, deploy manually:
```bash
# Deploy phase3-to-phase4
gcloud functions deploy phase3-to-phase4-orchestrator \
  --gen2 --region=us-west2 \
  --source=orchestration/cloud_functions/phase3_to_phase4 \
  --entry-point=orchestrate_phase3_to_phase4 \
  --trigger-topic=nba-phase3-analytics-complete \
  --runtime=python312 --memory=512MB --timeout=540s

# Deploy phase4-to-phase5
gcloud functions deploy phase4-to-phase5-orchestrator \
  --gen2 --region=us-west2 \
  --source=orchestration/cloud_functions/phase4_to_phase5 \
  --entry-point=orchestrate_phase4_to_phase5 \
  --trigger-topic=nba-phase4-precompute-complete \
  --runtime=python312 --memory=512MB --timeout=540s
```

### 3. Deploy Other Stale Services
```bash
./bin/check-deployment-drift.sh --verbose
# Deploy any stale services
./bin/deploy-service.sh prediction-coordinator
./bin/deploy-service.sh prediction-worker
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
```

---

## The Fix (Already Committed)

**Commit:** `a7dc5d9d` - "Session 128 - Edge filter, DNP recency, and orchestration fixes"

**Key Changes:**
1. Changed from `_triggered=True` to `_trigger_pending=True` in transaction
2. Added `mark_trigger_success()` helper function
3. Only set `_triggered=True` AFTER successful trigger
4. Wrapped trigger calls in try/except
5. If trigger fails, `_triggered` stays False → allows retry

**Code Pattern (phase4_to_phase5/main.py):**
```python
# In transaction: set pending, not triggered
current['_trigger_pending'] = True
transaction.set(doc_ref, current)

# After transaction, in calling code:
def mark_trigger_success():
    doc_ref.update({
        '_triggered': True,
        '_triggered_at': firestore.SERVER_TIMESTAMP,
        '_trigger_succeeded': True
    })

try:
    trigger_phase5(...)
    mark_trigger_success()  # Only on success
except ValueError as e:
    logger.error(f"Trigger FAILED: {e}. Will retry on next message.")
    raise  # Re-raise to NACK
```

---

## Data Status (as of session end)

| Component | Feb 4 | Feb 5 |
|-----------|-------|-------|
| player_game_summary | 171 records (5/7 games) | N/A (games tonight) |
| player_daily_cache | 218 records | 252 records |
| ml_feature_store_v2 | 257 records | 273 records |
| player_prop_predictions | ? | 0 (pending) |

**Missing Feb 4 games:** CLE@LAC, MEM@SAC (can be recovered with `./bin/fix_feb4_missing_games.sh`)

---

## Key Files

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/phase3_to_phase4/main.py` | Phase 3→4 orchestrator (lines 1431-1470 for trigger logic) |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Phase 4→5 orchestrator (lines 994-1070 for trigger logic) |
| `bin/fix_feb4_missing_games.sh` | Recover missing Feb 4 games |

---

## Validation Commands

```bash
# Check workflow decisions (should show proper time_diff values)
bq query --use_legacy_sql=false "
SELECT decision_time, workflow_name, action,
  JSON_EXTRACT_SCALAR(context, '$.time_diff_minutes') as time_diff
FROM nba_orchestration.workflow_decisions
WHERE DATE(decision_time) = '2026-02-05'
ORDER BY decision_time DESC LIMIT 10"

# Check Firestore completion records
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
for coll in ['phase3_completion', 'phase4_completion']:
    doc = db.collection(coll).document('2026-02-05').get()
    if doc.exists:
        data = doc.to_dict()
        print(f"{coll}: _triggered={data.get('_triggered')}, _trigger_pending={data.get('_trigger_pending')}")
    else:
        print(f"{coll}: NO RECORD")
EOF
```

---

## Session 124 Fixes Status

| Fix | Status | Notes |
|-----|--------|-------|
| Timezone Bug | ✅ WORKING | Workflows running at correct times |
| Game Code Bug | ✅ WORKING | OKC@SAS processed successfully |
| Orchestrator Trigger Bug | ✅ FIXED | Commit a7dc5d9d, needs Cloud Function deployment |

---

## End of Session Checklist

- [ ] Verify Feb 5 predictions exist
- [ ] Verify Cloud Functions deployed with fix
- [ ] Deploy stale Cloud Run services
- [ ] (Optional) Recover missing Feb 4 games

**Co-Authored-By:** Claude Opus 4.5 <noreply@anthropic.com>
