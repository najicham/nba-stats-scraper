# Session 192 Handoff — Per-System Quality Gate Fix for QUANT Models

**Date:** 2026-02-11
**Commit:** `9d8ba4fd`
**Status:** Complete — deployed to production, pending next prediction run for verification

---

## What Was Done

### 1. ROOT CAUSE: Per-System Quality Gate Implementation ✅

**Problem:** QUANT shadow models (Q43, Q45) produced only 2-3 predictions per game day instead of 50-80+ like the champion.

**Root Cause Identified:**
- `quality_gate.py` hardcoded `system_id = 'catboost_v9'` when checking for existing predictions
- Quality gate rule: "Never replace existing predictions"
- **Cascade effect:**
  1. Champion predicts on Player A at 8 AM ✓
  2. RETRY mode runs at 9 AM
  3. Quality gate checks: "Does Player A have a catboost_v9 prediction?" → YES
  4. Quality gate blocks Player A for ALL systems (including Q43, Q45)
  5. Player A never published to Pub/Sub for ANY model
  6. Worker never receives Player A → Q43/Q45 can't predict

**Solution: Per-System Quality Gate**

**Files Changed:**

| File | Change |
|------|--------|
| `predictions/coordinator/quality_gate.py` | Added `system_id` parameter to `get_existing_predictions()` and `apply_quality_gate()` |
| `predictions/coordinator/coordinator.py` | Loop through active systems, run quality gate per system, aggregate viable players (union) |

**Key Changes:**

**quality_gate.py:**
```python
def get_existing_predictions(self, game_date, player_lookups, system_id='catboost_v9'):
    query = f"""
        SELECT DISTINCT player_lookup
        WHERE system_id = @system_id  # ← Parameterized instead of hardcoded
    """
```

**coordinator.py:**
```python
# Get active systems: champion + enabled shadow models
active_systems = get_active_system_ids()  # ['catboost_v9', 'q43', 'q45']

# Run quality gate per system
all_viable_players = set()
for system_id in active_systems:
    gate_results, summary = quality_gate.apply_quality_gate(
        game_date, player_lookups, mode, system_id=system_id
    )
    viable_for_system = {r.player_lookup for r in gate_results if r.should_predict}
    all_viable_players.update(viable_for_system)  # Union across all systems

# Publish aggregated viable set (worker runs all models)
publish_prediction_requests(viable_requests)
```

**Impact:**
- Shadow models now receive prediction requests for ALL viable players
- If champion blocks Player A (already predicted), but Q43 hasn't predicted on Player A yet, Player A is in aggregated viable set → Q43 predicts
- Worker behavior unchanged (still runs all enabled models per message)

**Deployment:**
- Pushed to main at 2026-02-11 00:59 UTC
- Cloud Build auto-deployed in 4m22s
- Coordinator running commit `9d8ba4fd`

**Verification Status:**
- ⏳ Pending next prediction run (expected ~8 AM ET = ~13:00 UTC Feb 11)
- Last prediction run: Feb 10 21:01:40 (before fix)
- **Next session:** Verify Q43/Q45 produce 50-80+ predictions per game day

---

### 2. Backfilled system_id on Historical Subset Picks ✅

**Problem:** All `current_subset_picks` rows before Session 190 had `system_id = NULL`.

**Fix:**
```sql
UPDATE nba_predictions.current_subset_picks
SET system_id = 'catboost_v9'
WHERE system_id IS NULL;
-- 1,865 rows updated (Jan 9 - Feb 7)
```

**Verification:**
```
system_id=catboost_v9: 1,865 rows (Jan 9 - Feb 7)
```

---

### 3. Backfilled Materialized Subset Picks (Feb 8-10) ✅

**Problem:** `current_subset_picks` missing rows for Feb 8-10.

**Fix:**
```python
from data_processors.publishing.subset_materializer import SubsetMaterializer
materializer = SubsetMaterializer()
materializer.materialize('2026-02-08', trigger_source='manual_backfill_session192')
materializer.materialize('2026-02-09', trigger_source='manual_backfill_session192')
materializer.materialize('2026-02-10', trigger_source='manual_backfill_session192')
```

**Results:**
- Feb 8: 24 picks across 8 subsets ✓
- Feb 9: 7 picks across 8 subsets ✓
- Feb 10: 0 picks (expected — QUANT models not producing yet)

**Verification:**
```
Feb 7: 248 picks (champion)
Feb 8: 24 picks (champion)
Feb 9: 7 picks (champion)
Feb 10: Will populate after next prediction run
```

---

### 4. Re-Triggered Feb 1-3 V9 Grading ⏳

**Problem:** 1,026 catboost_v9 predictions reactivated in Session 191, but grading never ran for them.

**Investigation:**
- Feb 1-3 has 1,870 graded predictions (other systems) but ZERO for catboost_v9
- Root cause: Grading ran when V9 predictions were `is_active=FALSE` → grader skipped them
- Session 191 reactivated predictions, but grading didn't re-trigger successfully

**Action Taken:**
```bash
gcloud pubsub topics publish nba-grading-trigger --message='{"game_date": "2026-02-01", ...}'
gcloud pubsub topics publish nba-grading-trigger --message='{"game_date": "2026-02-02", ...}'
gcloud pubsub topics publish nba-grading-trigger --message='{"game_date": "2026-02-03", ...}'
# Published at 2026-02-11 01:15 UTC
```

**Verification Status:**
- ⏳ Triggers sent, grading pending
- **Expected:** 143 + 111 + 259 = 513 catboost_v9 graded predictions
- **Current:** 0 catboost_v9 graded predictions
- **Next session:** Verify grading completed, re-trigger if needed

---

## Outstanding Issues

### Issue 1: QUANT Models Not Yet Verified ⏳

**Status:** Fix deployed, awaiting next prediction run

**What to verify:**
```sql
-- Check QUANT prediction counts after next run
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-11'
  AND system_id LIKE '%q4%'
GROUP BY 1 ORDER BY 1;
```

**Expected results:**
- `catboost_v9_q43_train1102_0131`: 50-80+ predictions (currently 2)
- `catboost_v9_q45_train1102_0131`: 50-80+ predictions (currently 2)

**If fix didn't work:**
- Check coordinator logs for "Active systems for quality gate" message
- Check worker logs for shadow model dispatch
- Verify MONTHLY_MODELS config has `enabled: True` for Q43/Q45

---

### Issue 2: Feb 1-3 V9 Grading Pending ⏳

**Status:** Triggers sent, processing

**Verification:**
```sql
SELECT game_date, system_id, COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND system_id = 'catboost_v9'
GROUP BY 1, 2 ORDER BY 1;
```

**Expected:** 143 + 111 + 259 = 513 rows

**If grading didn't complete:**
```bash
# Re-trigger
for d in 2026-02-01 2026-02-02 2026-02-03; do
  gcloud pubsub topics publish nba-grading-trigger \
    --project=nba-props-platform \
    --message="{\"game_date\": \"$d\", \"trigger_source\": \"manual_backfill\"}"
done
```

---

### Issue 3: Phase 6 Export Backfill (From Session 191)

**Status:** Not started in Session 192 (focused on QUANT fix)

**What's needed:**
- Audit GCS files: which dates have exports, which are missing
- Backfill missing exports (at least past 30 days)
- Consider adding Phase 6 canary query to monitoring pipeline
- Validate export JSON structure for historical dates

**GCS Bucket:** `gs://nba-props-platform-api/v1/`

---

## Key Learnings

### Architectural Insight: Quality Gate Assumptions

**Pre-Session 177:** Single champion model → "never replace predictions" = sensible
**Post-Session 177:** Multiple parallel models → same quality gate logic = broken

**The lesson:** When adding parallel shadow models, ALL upstream filtering logic needs to account for per-system state, not just global state.

**Areas to audit for similar issues:**
- Feature quality gate (currently champion-only?)
- Coverage monitoring (does it track per-system?)
- Alert thresholds (do they aggregate across systems?)

### Worker vs Coordinator Responsibility

**Key insight:** Worker runs ALL enabled models for every prediction request. Coordinator's job is just to determine which players get published. Per-system quality gate = coordinator sends more players, worker decides which models succeed for each.

**This pattern:** Coordinator = "who to predict on", Worker = "how to predict"

---

## Verification Checklist for Next Session

```bash
# 1. Verify QUANT models producing (HIGH PRIORITY)
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id LIKE '%q4%'
GROUP BY 1 ORDER BY 1"
# Expected: 50-80+ predictions each (not 2-3)

# 2. Verify Feb 1-3 grading
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1"
# Expected: 143, 111, 259 rows

# 3. Check coordinator logs for per-system quality gate
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-coordinator"
  AND "Active systems for quality gate"'
  --project=nba-props-platform --limit=5

# 4. Monitor QUANT model performance
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 1

# 5. Phase 6 export audit (if time permits)
gsutil ls -lh gs://nba-props-platform-api/v1/all-subsets-picks/ | tail -30
```

---

## Files Changed

| File | Change |
|------|--------|
| `predictions/coordinator/quality_gate.py` | Added `system_id` parameter to quality gate methods |
| `predictions/coordinator/coordinator.py` | Per-system quality gate loop, aggregated viable players |

---

## Commits

```
9d8ba4fd - fix: Implement per-system quality gate for parallel shadow models (Session 192)
```

---

## Next Session Priorities (Ordered)

1. **Verify QUANT models producing** — Check Feb 11+ prediction counts for Q43/Q45 (should be 50-80+ not 2-3)
2. **Verify Feb 1-3 V9 grading** — Check if 513 predictions graded, re-trigger if needed
3. **Monitor QUANT model hit rate** — If producing, evaluate performance vs champion
4. **Phase 6 export audit** — Audit GCS, backfill missing dates, add monitoring

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-11-SESSION-192-HANDOFF.md

# 2. Verify QUANT fix worked
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE '%q4%' AND game_date >= '2026-02-11'
GROUP BY 1, 2 ORDER BY 2 DESC, 1"

# 3. Verify Feb 1-3 grading
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1"

# 4. If QUANT producing, compare performance
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 3
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q45_train1102_0131 --days 3
```
