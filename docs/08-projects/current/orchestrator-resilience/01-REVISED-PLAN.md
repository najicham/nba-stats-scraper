# Orchestrator Health Monitoring - REVISED PLAN

**Session 199 (Revised)** | **Date:** 2026-02-11 | **Status:** Revised Per Opus Feedback

---

## Changes From Original Plan

### Critical Corrections

1. **Processor count: 5, not 6** - Fixed throughout
2. **Root cause re-framed** - Configuration drift (waiting for disabled BDL), not orchestrator failure
3. **Simplified to 2 layers** - Logging + canary (dropped dedicated monitor)
4. **Removed SIGALRM** - Doesn't work reliably in Cloud Functions
5. **Use existing dual-write** - `completion_tracker.py` already writes to BigQuery

### Opus Decisions

| Question | Decision |
|----------|----------|
| Auto-heal default | **Disabled** (correct - don't auto-heal symptoms we don't understand) |
| Alert threshold | **>= 5 with 30-min delay** (5 = all processors, add time buffer) |
| Monitor frequency | **15 min** (cost negligible) |
| Scope | **Phase 2→3 only** (start here, expand later) |
| BigQuery vs Firestore | **Firestore** (source of truth for `_triggered`) |
| Layers | **2, not 3** (logging + canary at 15 min, not separate script) |

---

## The Real Problem (Corrected Understanding)

### What Actually Happened in Session 198

**NOT:** "Orchestrator stuck and failed to set `_triggered=True`"

**ACTUALLY:** "Orchestrator correctly waited for BDL processors that would never arrive because BDL is disabled"

```
Configuration State:
- BDL scrapers: DISABLED (Sessions 41/94)
- Expected processors: 6 (including bdl_player_boxscores)
- Actual processors: 5 (NBA.com + Odds API + BigDataBall)

Result:
- Phase 2 completes with 5/5 active processors ✅
- Orchestrator waits for 6th processor (BDL) ❌
- _triggered never set (correctly waiting, not stuck)
- Phase 3 never triggers (Pub/Sub subscription waiting)
- 3-day silent failure
```

### Why This Matters

The orchestrator is **monitoring-only** (line 6-8 of main.py):
```python
# NOTE: This orchestrator is now MONITORING-ONLY. Phase 3 is triggered directly
# via Pub/Sub subscription (nba-phase3-analytics-sub), not by this orchestrator.
```

**This means:**
- `_triggered=True` is a monitoring flag, not the actual trigger
- Phase 3 is triggered by Pub/Sub subscription `nba-phase3-analytics-sub`
- If `_triggered=False`, it means orchestrator thinks processors aren't complete
- Session 198 was **configuration drift**, not orchestrator code failure

### The Real Lesson

**Prevent configuration drift** where code expects processors that are disabled. This is a different problem than "catch stuck orchestrators."

---

## Revised Solution (2 Layers)

### Layer 1: Enhanced Orchestrator Logging (20 min)

**Objective:** Diagnostic visibility for future issues

**Changes to `orchestration/cloud_functions/phase2_to_phase3/main.py`:**

#### 1A. Checkpoint Logging

```python
# Line ~878 - BEFORE transaction
logger.info(
    f"CHECKPOINT_PRE_TRANSACTION: processor={processor_name}, "
    f"game_date={game_date}, completed_count_before_update={len([k for k in current.keys() if not k.startswith('_')])}"
)

# Line ~893 - AFTER transaction
completed_after = len([k for k in current.keys() if not k.startswith('_')])
logger.info(
    f"CHECKPOINT_POST_TRANSACTION: should_trigger={should_trigger}, "
    f"completed={completed_after}/{EXPECTED_PROCESSOR_COUNT}, game_date={game_date}"
)

# Line ~962 - WHEN triggering
logger.info(
    f"CHECKPOINT_TRIGGER_SET: All {EXPECTED_PROCESSOR_COUNT} processors complete, "
    f"_triggered=True written to Firestore, game_date={game_date}, "
    f"processors={list(EXPECTED_PROCESSOR_SET)}"
)

# Line ~1090 - Still waiting
logger.info(
    f"CHECKPOINT_WAITING: Registered {processor_name}, "
    f"completed={completed_count}/{EXPECTED_PROCESSOR_COUNT}, "
    f"missing={list(EXPECTED_PROCESSOR_SET - set(completed_processors))}, "
    f"game_date={game_date}"
)
```

**Note on Session 198:** With these checkpoints, we would have seen:
```
CHECKPOINT_WAITING: completed=5/6, missing=['p2_bdl_box_scores']
```

This would have immediately revealed the BDL configuration drift.

#### 1B. Transaction Visibility

```python
# In update_completion_atomic() function
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, completion_data):
    logger.info(f"TRANSACTION_START: processor={processor_name}")

    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Log current state
    completed_processors = [k for k in current.keys() if not k.startswith('_')]
    logger.info(
        f"TRANSACTION_READ: doc_exists={doc_snapshot.exists}, "
        f"completed_before={len(completed_processors)}/{EXPECTED_PROCESSOR_COUNT}, "
        f"processors={completed_processors}"
    )

    # ... existing logic ...

    completed_count = len([k for k in current.keys() if not k.startswith('_')])
    logger.info(f"TRANSACTION_COUNT: completed_after={completed_count}/{EXPECTED_PROCESSOR_COUNT}")

    if completed_count >= EXPECTED_PROCESSOR_COUNT and not current.get('_triggered'):
        logger.info(
            f"TRANSACTION_TRIGGERING: Setting _triggered=True, "
            f"all_processors={list(current.keys() - {'_triggered', '_triggered_at', ...})}"
        )

    return (should_trigger, deadline_exceeded)
```

#### 1C. Use Existing Dual-Write (No New Tables Needed)

**Opus note:** `shared/utils/completion_tracker.py` already writes to BigQuery.

**Check first:** Does it track `_triggered` status?

```bash
# Check existing dual-write implementation
grep -A 20 "def record_completion" shared/utils/completion_tracker.py

# Check what's in phase_completions table
bq query --use_legacy_sql=false "
SELECT * FROM nba_orchestration.phase_completions
WHERE game_date = CURRENT_DATE() - 1 AND phase = 'phase2'
LIMIT 5"
```

**If `_triggered` not tracked:** Add to existing `update_aggregate_status()` call:

```python
# Line ~974 in main.py - already exists, just verify it writes _triggered
if COMPLETION_TRACKER_ENABLED:
    tracker = get_completion_tracker()
    tracker.update_aggregate_status(
        phase="phase2",
        game_date=game_date,
        completed_processors=list(EXPECTED_PROCESSOR_SET),
        expected_processors=EXPECTED_PROCESSORS,
        is_triggered=True,  # ← Verify this is written to BQ
        trigger_reason="all_complete",
        mode="monitoring_only"
    )
```

**Benefit:** Pipeline canaries can query BigQuery instead of Firestore.

**Effort:** 20 minutes (logging + verify dual-write)
**Risk:** Low (logging only, use existing infrastructure)

---

### Layer 2: Pipeline Canary with 15-Min Frequency (30 min)

**Objective:** Detect stuck orchestrators in 15 minutes

**Changes to `bin/monitoring/pipeline_canary_queries.py`:**

#### 2A. Add Firestore Check Function

```python
from google.cloud import firestore
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional

def check_orchestrator_health(game_date: str) -> Tuple[bool, Dict, Optional[str]]:
    """
    Check if Phase 2→3 orchestrator triggered for game_date.

    Args:
        game_date: Date to check (YYYY-MM-DD)

    Returns:
        (passed, metrics, error_message)
    """
    try:
        db = firestore.Client(project=PROJECT_ID)

        # Check Phase 2→3 (use yesterday's data for game_date)
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        doc = db.collection('phase2_completion').document(yesterday).get()

        if not doc.exists:
            # No data yet - not necessarily an error (might be no games)
            return (True, {'status': 'no_data'}, None)

        data = doc.to_dict()
        processors_complete = len([k for k in data.keys() if not k.startswith('_')])
        triggered = data.get('_triggered', False)
        first_completion = data.get('_first_completion_at')

        metrics = {
            'game_date': yesterday,
            'processors_complete': processors_complete,
            'expected_processors': 5,  # Fixed: 5, not 6
            'triggered': triggered
        }

        # STUCK: All 5 processors complete but not triggered
        if processors_complete >= 5 and not triggered:
            # Check if stuck for >30 minutes (Opus: add time delay)
            if first_completion:
                from datetime import timezone
                now = datetime.now(timezone.utc)

                # Handle Firestore timestamp
                if hasattr(first_completion, 'seconds'):
                    first_completion_dt = datetime.fromtimestamp(
                        first_completion.seconds, tz=timezone.utc
                    )
                else:
                    first_completion_dt = first_completion

                minutes_stuck = (now - first_completion_dt).total_seconds() / 60

                if minutes_stuck < 30:
                    # Still within grace period
                    metrics['minutes_stuck'] = minutes_stuck
                    return (True, metrics, None)

            # Stuck for >30 minutes - ALERT
            completed_processors = [k for k in data.keys() if not k.startswith('_')]
            missing_processors = list(set([
                'p2_bigdataball_pbp',
                'p2_odds_game_lines',
                'p2_odds_player_props',
                'p2_nbacom_gamebook_pdf',
                'p2_nbacom_boxscores'
            ]) - set(completed_processors))

            error_msg = (
                f"Phase 2→3 orchestrator stuck for {yesterday}: "
                f"{processors_complete}/5 complete but NOT TRIGGERED. "
                f"Completed: {completed_processors}, "
                f"Missing: {missing_processors if missing_processors else 'none (all complete)'}"
            )

            metrics['missing_processors'] = missing_processors
            return (False, metrics, error_msg)

        # HEALTHY: Triggered successfully
        if triggered:
            return (True, metrics, None)

        # WAITING: Processors still completing (normal)
        return (True, metrics, None)

    except Exception as e:
        logger.error(f"Failed to check orchestrator health: {e}", exc_info=True)
        return (False, {}, f"Firestore check failed: {e}")
```

#### 2B. Integrate into Canary Runner

```python
def run_all_canaries():
    """Run all canary checks including orchestrator health"""
    client = bigquery.Client()
    failures = []

    # Run BigQuery-based canaries
    for check in CANARY_CHECKS:
        passed, metrics, error = run_canary_query(client, check)
        if not passed:
            failures.append({
                'name': check.name,
                'phase': check.phase,
                'error': error,
                'metrics': metrics
            })

    # Run Firestore-based orchestrator check (NEW)
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    passed, metrics, error = check_orchestrator_health(yesterday)
    if not passed:
        failures.append({
            'name': 'Phase 2→3 Orchestrator Health',
            'phase': 'orchestrator_p2_p3',
            'error': error,
            'metrics': metrics
        })
        logger.error(f"🔴 ORCHESTRATOR HEALTH FAILED: {error}")

    # Send alerts if failures
    if failures:
        send_canary_failures_alert(failures)
        return False

    logger.info("✅ All canaries passed (including orchestrator health)")
    return True
```

#### 2C. Update Cloud Scheduler to Run Every 15 Minutes

```bash
# Update existing canary scheduler from 30-min to 15-min intervals
gcloud scheduler jobs update http pipeline-canary-queries \
  --schedule="*/15 * * * *" \
  --location=us-west2 \
  --description="Pipeline canary queries including orchestrator health (runs every 15 min)"
```

**Effort:** 30 minutes (code + scheduler update)
**Risk:** Low (adds to existing system)

---

## Implementation Plan (Simplified)

### Phase 1: Enhanced Logging (20 min)

| Task | Effort | Files |
|------|--------|-------|
| Add checkpoint logging | 10 min | `orchestration/cloud_functions/phase2_to_phase3/main.py` |
| Add transaction visibility | 5 min | Same |
| Verify completion_tracker dual-write | 5 min | Check existing code |
| Deploy orchestrator | 5 min | Cloud Functions |

### Phase 2: Canary Integration (30 min)

| Task | Effort | Files |
|------|--------|-------|
| Add orchestrator health check function | 15 min | `bin/monitoring/pipeline_canary_queries.py` |
| Integrate into canary runner | 10 min | Same |
| Update Cloud Scheduler to 15-min | 5 min | GCP config |

### Phase 3: Testing (30 min)

| Task | Effort |
|------|--------|
| Test with current Firestore data | 10 min |
| Verify canary alerts work | 10 min |
| Document runbook | 10 min |

**Total: 80 minutes**

---

## Success Criteria

### Immediate (Post-Implementation)

- [ ] Enhanced logging deployed to Phase 2→3 orchestrator
- [ ] Checkpoint logs visible in Cloud Functions logs
- [ ] Canary includes orchestrator health check
- [ ] Cloud Scheduler runs every 15 minutes
- [ ] Test passes with yesterday's data

### 30 Days (Operational)

- [ ] Configuration drift detected within 30 minutes
- [ ] Zero false positives (30-min delay prevents premature alerts)
- [ ] MTTD < 30 minutes for stuck orchestrators

---

## What This ACTUALLY Prevents

### Problem Type: Configuration Drift

**Example (Session 198):**
- BDL disabled in Sessions 41/94
- Orchestrator still expects BDL processors
- Code waits for processors that will never come
- Silent 3-day failure

**Detection with this solution:**
```
Canary check (15 min after last processor completes):
- Processors: 5/5 complete
- _triggered: False
- Minutes stuck: 45
- Alert: "Phase 2→3 orchestrator stuck"

Log investigation:
- CHECKPOINT_WAITING: missing=['p2_bdl_box_scores']
- Root cause visible immediately
```

### Problem Type: Actual Orchestrator Failure

**Example (hypothetical):**
- All 5 processors complete
- Firestore transaction fails silently
- `_triggered` never set

**Detection with this solution:**
```
Canary check:
- Processors: 5/5 complete
- _triggered: False
- Missing processors: none (all complete)
- Alert: "All processors complete but not triggered"

Log investigation:
- CHECKPOINT_PRE_TRANSACTION: completed=5/5
- CHECKPOINT_POST_TRANSACTION: should_trigger=? (check value)
- Diagnose transaction failure
```

---

## Rollback Plan

### If Logging Causes Issues

```bash
# Revert orchestrator to previous version
git revert <commit-sha>
git push origin main
# Auto-deploy will revert
```

### If Canary Causes Alert Fatigue

```bash
# Temporarily disable orchestrator health check
# Comment out in pipeline_canary_queries.py:
# passed, metrics, error = check_orchestrator_health(yesterday)

# Or reduce frequency back to 30 min:
gcloud scheduler jobs update http pipeline-canary-queries \
  --schedule="*/30 * * * *" \
  --location=us-west2
```

---

## Open Questions (Answered by Opus)

✅ **Auto-heal default:** Disabled (correct approach)
✅ **Alert threshold:** >= 5 with 30-min delay (prevents false positives)
✅ **Monitor frequency:** 15 min (cost negligible)
✅ **Scope:** Phase 2→3 only (start here)
✅ **BigQuery vs Firestore:** Firestore (source of truth for `_triggered`)
✅ **Layers:** 2, not 3 (canary at 15-min is simpler than separate script)

---

## Files to Modify

| File | Changes | Lines |
|------|---------|-------|
| `orchestration/cloud_functions/phase2_to_phase3/main.py` | Add checkpoint logging | ~878, ~893, ~962, ~1090, ~1142 |
| `bin/monitoring/pipeline_canary_queries.py` | Add `check_orchestrator_health()` | New function |
| `bin/monitoring/pipeline_canary_queries.py` | Update `run_all_canaries()` | Existing function |

**No new tables needed** - use existing `completion_tracker` dual-write.

---

## Next Steps (After Approval)

1. ✅ Verify completion_tracker writes `_triggered` to BigQuery
2. ✅ Implement Layer 1 (Enhanced logging)
3. ✅ Test logging with Feb 10 data (processors=6, triggered=False)
4. ✅ Implement Layer 2 (Canary integration)
5. ✅ Update Cloud Scheduler to 15-min frequency
6. ✅ Test full flow
7. ✅ Deploy to production
8. ✅ Monitor for 1 week
9. ✅ Document in handoff

---

## Appendix: Corrected Session 198 Timeline

```
Feb 9-11 (Corrected Understanding):

Phase 2 processors complete: 5/5 ✅
  - p2_nbacom_gamebook_pdf ✅
  - p2_nbacom_boxscores ✅
  - p2_odds_game_lines ✅
  - p2_odds_player_props ✅
  - p2_bigdataball_pbp ✅

Orchestrator state:
  - Expects: 6 processors (including p2_bdl_box_scores)
  - Received: 5 processors
  - Status: Waiting for 6th processor (correctly)
  - _triggered: False (correctly - still waiting)

Root cause:
  - Configuration drift: BDL disabled but orchestrator expects it
  - NOT an orchestrator code failure
  - NOT a stuck transaction

Fix (Session 198):
  - Remove BDL from EXPECTED_PROCESSORS
  - Change expected count from 6 → 5
  - Orchestrator now triggers correctly with 5/5

What we're adding now:
  - Detect this configuration drift in 15-30 minutes
  - Provide diagnostic logs to identify root cause
```

---

**Status:** Revised per Opus feedback, ready for implementation
**Effort:** 80 minutes total (down from 2.5 hours)
**Layers:** 2 (down from 3)
**Complexity:** Significantly reduced
