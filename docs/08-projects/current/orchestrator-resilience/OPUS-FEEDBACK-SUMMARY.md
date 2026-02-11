# Opus Feedback Summary - Orchestrator Resilience Plan

**Date:** 2026-02-11
**Session:** 199

---

## Opus's Assessment

**Overall:** Solid direction, but has factual errors and over-engineering

**Rating:** 80% right - needs corrections and simplification

---

## Critical Corrections Made

### 1. Processor Count: 5, not 6 ✅

**Error:** Plan repeatedly said "6/6 complete"

**Correction:** Phase 2 expects **5 processors**, not 6:
1. `p2_bigdataball_pbp`
2. `p2_odds_game_lines`
3. `p2_odds_player_props`
4. `p2_nbacom_gamebook_pdf`
5. `p2_nbacom_boxscores`

**Impact:** Alert threshold of `>= 5` means "all complete", not "early warning"

---

### 2. Orchestrator is Monitoring-Only ✅

**Error:** Plan assumed `_triggered=False` blocked downstream flow

**Correction:** Orchestrator is monitoring-only. Phase 3 is triggered by **Pub/Sub subscription** (`nba-phase3-analytics-sub`), not by orchestrator setting `_triggered=True`.

**From code (lines 6-8):**
```python
# NOTE: This orchestrator is now MONITORING-ONLY. Phase 3 is triggered directly
# via Pub/Sub subscription (nba-phase3-analytics-sub), not by this orchestrator.
```

**Impact:** Changes root cause analysis completely. Session 198 wasn't a stuck orchestrator - it was **configuration drift** (waiting for disabled BDL processors).

---

### 3. Dual-Write Already Exists ✅

**Error:** Solution 1B proposed creating new `orchestrator_triggers` table

**Correction:** `shared/utils/completion_tracker.py` already writes processor completions to both Firestore and BigQuery.

**Action:** Check if existing `phase_completions` table has what's needed before building new infrastructure.

---

### 4. SIGALRM Won't Work ✅

**Error:** Solution 1C used `signal.SIGALRM` for timeout warnings

**Correction:** Cloud Functions managed runtime doesn't guarantee signal delivery. Function is killed externally by platform.

**Action:** Removed from plan. Use Cloud Function execution duration logs instead.

---

### 5. Three Layers is Over-Engineering ✅

**Error:** Proposed 3 separate layers (logging + canary + dedicated monitor)

**Correction:** Layer 3 (dedicated monitor) duplicates Layer 2 (canary) on tighter interval.

**Action:** Simplified to 2 layers. Run canary at 15-min frequency instead of building separate script.

---

## Opus's Answers to Open Questions

| Question | Opus Decision | Rationale |
|----------|---------------|-----------|
| **Auto-heal default** | **Disabled** | Don't auto-heal symptoms you don't understand yet |
| **Alert threshold** | **>= 5 with 30-min delay** | 5 = all processors, delay prevents false positives |
| **Monitor frequency** | **15 min** | Cost negligible |
| **Scope** | **Phase 2→3 only** | Agree - start here, expand later |
| **BigQuery vs Firestore** | **Firestore** | Source of truth for `_triggered` |
| **Layers** | **2, not 3** | Canary at 15-min is simpler than separate script |

---

## What Got Cut

### ❌ Solution 1C: SIGALRM Timeout Warning

**Why:** Doesn't work reliably in Cloud Functions. Platform kills function externally.

**Replacement:** Check Cloud Function execution duration in existing GCP metrics. If any invocation approaches 540s, investigate.

---

### ❌ Solution 4: Self-Healing Deadman Switch

**Why:** Plan already deferred this, Opus agreed. Adds complexity for marginal benefit.

**Replacement:** None needed. Layer 2 (canary) already covers detection.

---

### ❌ Layer 3: Dedicated Orchestrator Monitor

**Why:** Duplicates Layer 2 (canary) functionality on tighter interval.

**Replacement:** Run canary every 15 minutes instead of 30 minutes.

---

## What's Good (Kept)

### ✅ Layer 1: Checkpoint Logging

**Opus:** "Highest-value change. Zero cost, huge diagnostic value."

**Why:** Session 198's root cause couldn't be diagnosed because no logs between "received completion" and "set _triggered=True".

**Keep:** All checkpoint logging as proposed.

---

### ✅ Layer 2: Canary Integration

**Opus:** "Minimal effort, leverages existing infrastructure. Function is clean, canary structure makes it trivial to add."

**Keep:** Add orchestrator health check to `pipeline_canary_queries.py`.

**Change:** Run every 15 min instead of adding separate script.

---

### ✅ Rollback Plan

**Opus:** "Thoughtful and practical."

**Keep:** As written.

---

## Recommended Changes Before Implementation

### 1. Investigate Root Cause First (20 min)

**Before building 3 layers of monitoring:**
- Did Phase 3 actually fail to run?
- Or did it run but orchestrator's monitoring flag wasn't set?
- These are very different problems

**Action:** Check Cloud Function invocation logs for Feb 9-11.

**Status:** ✅ **DONE** - Read Session 198 handoff. Root cause = BDL configuration drift.

---

### 2. Fix Processor Count (5, not 6)

**Action:** Update all references from 6 to 5 throughout plan.

**Status:** ✅ **DONE** - Revised plan corrected.

---

### 3. Drop SIGALRM

**Action:** Remove Solution 1C. Replace with note to check Cloud Function duration in metrics.

**Status:** ✅ **DONE** - Removed from revised plan.

---

### 4. Check Existing Dual-Write

**Action:** Verify `completion_tracker.py` writes to BigQuery before creating new table.

**Status:** 📋 **TODO** - Check in implementation phase.

---

### 5. Simplify to 2 Layers

**Action:** Drop Layer 3 (dedicated monitor). Run canary at 15-min frequency instead.

**Status:** ✅ **DONE** - Revised plan uses 2 layers.

---

## Revised Effort Estimate

| Phase | Before | After | Savings |
|-------|--------|-------|---------|
| **Layer 1: Logging** | 50 min | 20 min | -30 min (removed SIGALRM, use existing dual-write) |
| **Layer 2: Canary** | 85 min | 30 min | -55 min (no dedicated script, simpler integration) |
| **Layer 3: Dedicated Monitor** | 45 min | 0 min | -45 min (dropped) |
| **Testing** | 60 min | 30 min | -30 min (simpler system to test) |
| **Total** | **240 min** | **80 min** | **-160 min (67% reduction)** |

---

## What This Actually Prevents

### Before: "Stuck Orchestrator" (Incorrect)

We thought: Orchestrator fails to set `_triggered=True` and blocks downstream

### After: "Configuration Drift" (Correct)

**Problem Type 1:** Expecting disabled processors (Session 198)
- BDL disabled but orchestrator expects it
- Code waits for processors that will never come
- Logs show: `CHECKPOINT_WAITING: missing=['p2_bdl_box_scores']`

**Problem Type 2:** Actual orchestrator failure (hypothetical)
- All processors complete
- Transaction fails silently
- Logs show: `CHECKPOINT_POST_TRANSACTION: should_trigger=False` (diagnose why)

---

## Bottom Line (Opus's Words)

> The plan is 80% right. Fix the factual errors, investigate the actual root cause (monitoring-only orchestrator changes the story), and simplify from 3 layers to 2. Then it's ready to implement.

---

## Status After Revisions

✅ **Factual errors corrected** (processor count, orchestrator mode, dual-write)
✅ **Root cause re-framed** (configuration drift, not orchestrator failure)
✅ **Simplified to 2 layers** (logging + canary at 15-min)
✅ **SIGALRM removed** (doesn't work in Cloud Functions)
✅ **Effort reduced 67%** (240 min → 80 min)

**Ready for implementation:** Yes, pending one check (verify existing dual-write)

---

## Next Step

Verify `completion_tracker.py` writes `_triggered` to BigQuery:

```bash
# Check implementation
grep -A 20 "def update_aggregate_status" shared/utils/completion_tracker.py

# Check data
bq query --use_legacy_sql=false "
SELECT game_date, phase, is_triggered, trigger_reason
FROM nba_orchestration.phase_completions
WHERE game_date >= CURRENT_DATE() - 3 AND phase = 'phase2'
ORDER BY game_date DESC"
```

If `_triggered` is already written to BigQuery, canary can query BQ instead of Firestore (simpler, faster).
