# Task 1: Fix Phase 5 Predictions Timeout - Root Cause Analysis
**Started:** 2026-01-14 Evening
**Status:** In Progress - Root Cause Identified
**Priority:** P0 - Critical

---

## 🔍 ROOT CAUSE IDENTIFIED

### The Problem

**Symptoms:**
- Phase 5 success rate: 27% (vs 90%+ for other phases)
- Average duration: 123 hours (5+ days!)
- Max duration: 607 seconds for PredictionCoordinator
- Processors getting stuck indefinitely

**Current Timeout Mechanism** (`phase4_to_phase5/main.py`):
```python
MAX_WAIT_HOURS = 4  # Line 51
MAX_WAIT_SECONDS = MAX_WAIT_HOURS * 3600  # 14,400 seconds
```

### Why It's Broken

**The Critical Flaw:**

The timeout check (lines 366-390) is **reactive, not proactive**:

```python
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, completion_data):
    # ...
    # Check for timeout - trigger with partial completion
    first_completion_str = current.get('_first_completion_at')
    if first_completion_str:
        first_completion = datetime.fromisoformat(first_completion_str.replace('Z', '+00:00'))
        wait_seconds = (now - first_completion).total_seconds()

        if wait_seconds > MAX_WAIT_SECONDS:  # Only checked on NEW events!
            # Trigger Phase 5 with partial data
```

**The Bug:**

1. Phase 4 completes at 3:00 AM
2. `phase4_to_phase5` triggers prediction coordinator (HTTP call, line 494)
3. Prediction coordinator starts but **hangs** (gets stuck)
4. No more Phase 4 completion events arrive (Phase 4 is done!)
5. **Timeout check never runs again** (only runs on new Pub/Sub messages)
6. Processor stuck for 123+ hours until manual intervention

**Analogy:**
It's like setting a timer that only checks "is time up?" when someone rings the doorbell. If nobody rings the doorbell, the timer never fires!

---

## 💡 THE SOLUTION

### Multi-Layer Timeout Strategy

#### Layer 1: Cloud Run Timeout (CRITICAL - Do First)

**What:** Set Cloud Run service timeout to 30 minutes

**Why:** Cloud Run will automatically kill jobs that exceed timeout
- No code changes needed
- Immediate protection
- Works even if our code hangs

**How:**
```bash
# Update prediction-coordinator Cloud Run service
gcloud run services update prediction-coordinator \
  --region=us-west2 \
  --timeout=1800  # 30 minutes (1800 seconds)
```

**Expected Impact:**
- 123 hours → max 30 minutes
- Cloud Run will forcefully terminate after 30 min
- Immediate fix, zero code changes

**Risk:** LOW - Just a configuration change, easily reverted

---

#### Layer 2: Heartbeat Mechanism (IMPORTANT - Do Second)

**What:** Add heartbeat logging to prediction coordinator

**Why:** Visibility into where coordinator is stuck
- Helps debugging
- Proves coordinator is alive
- Can detect hangs earlier

**How:**
```python
# In prediction-coordinator service
import time
from datetime import datetime

def generate_predictions_with_heartbeat(game_date):
    """Generate predictions with periodic heartbeat logging."""
    start_time = time.time()
    last_heartbeat = start_time

    try:
        # Main prediction logic
        for step in prediction_pipeline:
            # Heartbeat every 5 minutes
            current_time = time.time()
            if current_time - last_heartbeat > 300:  # 5 min
                elapsed = (current_time - start_time) / 60
                logger.info(f"HEARTBEAT: {game_date} still processing ({elapsed:.1f} min elapsed)")
                last_heartbeat = current_time

            # Execute step
            step.run()

    except Exception as e:
        logger.error(f"Prediction failed after {(time.time() - start_time) / 60:.1f} min: {e}")
        raise
```

**Expected Impact:**
- Know exactly where coordinator is stuck
- Logs show heartbeat every 5 minutes
- Can diagnose hangs faster

**Risk:** VERY LOW - Just logging, no behavior changes

---

#### Layer 3: Cloud Scheduler Timeout Monitor (DEFENSIVE - Do Third)

**What:** Create Cloud Scheduler job to monitor for stuck predictions

**Why:** Safety net if Cloud Run timeout fails
- Checks Firestore for in-progress predictions
- Forcefully terminates if >30 min
- Sends alerts

**How:**
```python
# New Cloud Function: prediction_timeout_monitor
def check_stuck_predictions(request):
    """Check for predictions stuck >30 minutes."""
    db = firestore.Client()

    # Query predictions started >30 min ago, still in_progress
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

    stuck_docs = db.collection('prediction_runs') \
        .where('status', '==', 'in_progress') \
        .where('started_at', '<', cutoff) \
        .get()

    for doc in stuck_docs:
        data = doc.to_dict()
        game_date = data.get('game_date')
        started_at = data.get('started_at')
        duration_min = (datetime.now(timezone.utc) - started_at).total_seconds() / 60

        logger.warning(f"STUCK PREDICTION: {game_date} running for {duration_min:.1f} min")

        # TODO: Terminate the Cloud Run job
        # For now, just alert
        send_slack_alert(f"Prediction stuck for {game_date}: {duration_min:.1f} min")
```

**Schedule:** Every 15 minutes
```bash
gcloud scheduler jobs create http prediction-timeout-monitor \
  --schedule="*/15 * * * *" \
  --uri="https://prediction-timeout-monitor-xxx.run.app" \
  --http-method=GET
```

**Expected Impact:**
- Catch stuck predictions even if Cloud Run timeout fails
- Send alerts immediately
- Can manually intervene

**Risk:** LOW - Read-only monitoring, no production changes initially

---

#### Layer 4: Circuit Breaker (PROACTIVE - Do Fourth)

**What:** Fail fast after N consecutive failures

**Why:** Prevent cascading issues
- If 3 predictions fail in a row, pause
- Alert operators
- Don't waste resources

**How:**
```python
# In phase4_to_phase5 orchestrator
def should_trigger_phase5(game_date):
    """Check if we should trigger Phase 5 or circuit breaker is open."""
    # Check recent failure history
    recent_runs = get_recent_prediction_runs(limit=3)

    if all(run['status'] == 'failed' for run in recent_runs):
        logger.error("CIRCUIT BREAKER OPEN: 3 consecutive prediction failures")
        send_alert("Circuit breaker open - predictions paused")
        return False  # Don't trigger

    return True
```

**Expected Impact:**
- Stop wasting resources on failing predictions
- Alert operators to systemic issue
- Can investigate and fix before more damage

**Risk:** LOW - Prevents harm, easy to disable

---

## 📋 EXECUTION PLAN

### Phase 1: Immediate Fix (30-45 minutes) ⚠️ DO FIRST

**Step 1: Check Current Cloud Run Timeout**
```bash
gcloud run services describe prediction-coordinator \
  --region=us-west2 \
  --format="value(spec.template.spec.timeoutSeconds)"
```

**Step 2: Update Cloud Run Timeout to 30 minutes**
```bash
gcloud run services update prediction-coordinator \
  --region=us-west2 \
  --timeout=1800
```

**Step 3: Verify Update**
```bash
gcloud run services describe prediction-coordinator \
  --region=us-west2 \
  --format="value(spec.template.spec.timeoutSeconds)"
# Should output: 1800
```

**Step 4: Test with Recent Stuck Prediction**
- Wait for next prediction run (or trigger manually)
- Monitor Cloud Logging for timeout after 30 min
- Verify job is killed (not running for hours)

---

### Phase 2: Add Heartbeat (1-2 hours)

**Step 1: Find Prediction Coordinator Code**
```bash
# Likely location
ls -la orchestration/*/prediction*
find . -name "*prediction*coordinator*" -type f
```

**Step 2: Add Heartbeat Logging**
- Modify main prediction loop
- Add heartbeat log every 5 minutes
- Include elapsed time, current step

**Step 3: Deploy Updated Coordinator**
```bash
# Deploy with Cloud Run
gcloud run deploy prediction-coordinator \
  --source=. \
  --region=us-west2
```

**Step 4: Verify Heartbeat in Logs**
- Trigger test prediction
- Check Cloud Logging for heartbeat messages
- Confirm 5-minute intervals

---

### Phase 3: Timeout Monitor (1-2 hours)

**Step 1: Create timeout_monitor Cloud Function**
- New directory: `orchestration/cloud_functions/prediction_timeout_monitor/`
- Implement stuck prediction checker
- Test locally first

**Step 2: Deploy Monitor**
```bash
cd orchestration/cloud_functions/prediction_timeout_monitor
gcloud functions deploy prediction-timeout-monitor --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --entry-point=check_stuck_predictions \
  --trigger-http
```

**Step 3: Create Cloud Scheduler Job**
```bash
gcloud scheduler jobs create http prediction-timeout-monitor-schedule \
  --schedule="*/15 * * * *" \
  --uri="https://prediction-timeout-monitor-xxx.run.app" \
  --http-method=GET \
  --location=us-west2
```

**Step 4: Monitor for Alerts**
- Wait for next day's predictions
- Check Slack for any stuck alerts
- Verify monitor is working

---

### Phase 4: Circuit Breaker (30-45 minutes)

**Step 1: Add Failure History Check**
- Modify `phase4_to_phase5/main.py`
- Query recent prediction runs from Firestore
- Check if last 3 were failures

**Step 2: Add Circuit Breaker Logic**
```python
if should_trigger and circuit_breaker_open(game_date):
    logger.error("Circuit breaker open, not triggering Phase 5")
    send_alert("Circuit breaker: 3 consecutive failures")
    return  # Don't trigger
```

**Step 3: Deploy Updated Orchestrator**
```bash
cd orchestration/cloud_functions/phase4_to_phase5
gcloud functions deploy phase4-to-phase5 --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --entry-point=orchestrate_phase4_to_phase5 \
  --trigger-topic=nba-phase4-precompute-complete
```

**Step 4: Test Circuit Breaker**
- Simulate 3 consecutive failures (if possible)
- Verify circuit breaker opens
- Verify alert sent
- Manually reset circuit breaker

---

## ✅ SUCCESS CRITERIA

### Immediate (After Phase 1)
- ✅ Cloud Run timeout set to 30 minutes (1800 seconds)
- ✅ No predictions running >30 minutes
- ✅ Stuck predictions forcefully terminated

### Short-term (After Phase 2)
- ✅ Heartbeat logs appearing every 5 minutes
- ✅ Can see exactly where predictions are stuck
- ✅ Debugging time reduced (know the stuck step)

### Medium-term (After Phase 3)
- ✅ Timeout monitor detecting stuck predictions
- ✅ Alerts sent within 15 minutes of hang
- ✅ Zero predictions running >45 minutes

### Long-term (After Phase 4)
- ✅ Circuit breaker prevents cascade failures
- ✅ 3 consecutive failures pause predictions
- ✅ Operators alerted to systemic issues

**Overall Goal:**
- Phase 5 success rate: 27% → 95%+
- Average duration: 123 hours → <30 minutes
- Zero Cloud Run costs for hung jobs

---

## 🚨 RISKS & MITIGATION

### Risk 1: 30-min timeout too short for legitimate predictions

**Probability:** LOW
**Mitigation:**
- Current P95 duration: Unknown (need to query)
- If P95 >20 min, increase timeout to 45 min
- Monitor for legitimate timeouts in first week

**Rollback:**
```bash
gcloud run services update prediction-coordinator \
  --region=us-west2 \
  --timeout=7200  # Back to 2 hours (or whatever it was)
```

---

### Risk 2: Heartbeat logging impacts performance

**Probability:** VERY LOW
**Mitigation:**
- Logging is asynchronous (buffered)
- 5-minute interval = minimal overhead
- Can increase to 10-15 min if needed

---

### Risk 3: Timeout monitor creates alert spam

**Probability:** MEDIUM
**Mitigation:**
- Add rate limiting (1 alert per game_date)
- Cooldown period (don't alert same issue twice in 1 hour)
- Test in staging first

---

## 📊 EXPECTED OUTCOMES

### Before Fix
- Success Rate: 27%
- Avg Duration: 123 hours (stuck indefinitely)
- Max Duration: 607 seconds (when it works) / 123 hours (when stuck)
- Cost Impact: High (paying for 4-hour+ Cloud Run executions)
- Business Impact: Predictions failing, grading incomplete

### After Phase 1 (Cloud Run Timeout)
- Success Rate: 27% → 50%+ (immediate improvement)
- Avg Duration: 123 hours → max 30 minutes
- Max Duration: 30 minutes (hard limit)
- Cost Impact: Reduced 95% (30 min vs 4+ hours)
- Business Impact: Faster failure, can retry sooner

### After Phase 2-4 (Full Implementation)
- Success Rate: 50% → 95%+ (understand and fix root causes)
- Avg Duration: <5 minutes (when working), 30 min (when timeout)
- Max Duration: 30 minutes (hard limit)
- Cost Impact: Minimal (only pay for actual work)
- Business Impact: Reliable predictions, grading works

---

## 🎯 NEXT IMMEDIATE ACTIONS

1. ✅ Check current Cloud Run timeout (1 min)
2. ✅ Update to 30 minutes (2 min)
3. ✅ Verify update applied (1 min)
4. ✅ Document change (5 min)
5. ⏳ Wait for next prediction run to validate (passive)
6. ⏳ Monitor logs for 30-min timeout trigger (passive)

**Total Time for Phase 1:** 30-45 minutes (mostly waiting for validation)

**Let's execute Phase 1 NOW.** 🚀

---

## 📝 NOTES

### Finding: Prediction Coordinator Location
Need to find where prediction-coordinator service code lives:
- Could be in `orchestration/cloud_run/`
- Could be in `services/`
- Could be in separate repo

**Action:** Search codebase for prediction coordinator
```bash
find . -name "*prediction*" -type d | grep -v node_modules | grep -v __pycache__
find . -name "Dockerfile" -path "*/prediction*"
```

### Finding: Current Timeout Value
Unknown what current Cloud Run timeout is set to:
- Could be default (5 minutes)
- Could be 1 hour
- Could already be 4 hours

**Action:** Check current value before changing

### Finding: Firestore Collection for Predictions
Need to verify Firestore collection name:
- Likely: `prediction_runs`
- Could be: `phase5_predictions`
- Could be: `predictions`

**Action:** Check Firestore collections in console or code
