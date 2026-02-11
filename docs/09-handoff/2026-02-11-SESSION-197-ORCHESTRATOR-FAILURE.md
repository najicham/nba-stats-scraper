# Session 197 Handoff - Phase 2→3 Orchestrator Failure Investigation

**Date:** 2026-02-11
**Time:** 7:40 AM - 8:30 AM PT
**Status:** 🔴 CRITICAL - Orchestrator failing for 3+ days
**Commits:** TBD (fixes to be implemented)

---

## Executive Summary

**CRITICAL:** The Phase 2→3 orchestrator has been failing to trigger Phase 3 for at least **3 consecutive days** (Feb 9-11), causing a complete pipeline stall. Phase 2 processors complete successfully but the orchestrator never sets `_triggered=True` in Firestore, blocking all downstream phases.

**Impact:**
- No automated Phase 3 analytics processing since Feb 8
- No prediction grading (cascade failure)
- Manual scheduler triggers required daily
- Data quality degraded (64% minutes coverage vs expected 90%+)

---

## What Was Found

### Daily Validation Results (Feb 10)

| Check | Status | Details |
|-------|--------|---------|
| **Phase 2→3 Orchestrator** | 🔴 FAILED | `_triggered=False` despite 6/6 processors complete |
| **Phase 3 Completion** | 🔴 MISSING | No completion record for 2026-02-11 |
| **Box Score Coverage** | 🔴 DEGRADED | 64% minutes coverage (only gamebook, no BDL) |
| **Prediction Grading** | 🔴 BLOCKED | 0% graded (cascade from Phase 3 failure) |
| Grading Service Drift | ⚠️ STALE | 1 commit behind (deploy pending) |
| Usage Rate | ✅ OK | 96.6% coverage |
| Edge Filter | ✅ OK | No low-edge actionable predictions |

### Orchestrator Failure Pattern (Last 3 Days)

```
Phase 2 Completion Status:
2026-02-11: 2 processors complete, triggered=False ❌
2026-02-10: 6 processors complete, triggered=False ❌
2026-02-09: 5 processors complete, triggered=False ❌
```

**All 3 days:** Phase 2 processors completed but orchestrator did NOT trigger Phase 3.

---

## Root Cause Analysis

### Issue 1: Orchestrator Logic Bug (P0 CRITICAL)

**Evidence from logs:**
```
2026-02-11 15:00:35 - MONITORING: Registered p2_nbacom_gamebook_pdf completion, waiting for others
2026-02-11 15:00:32 - Received completion from p2_nbacom_gamebook_pdf for 2026-02-10 (status=success)
```

**Analysis:**
- Orchestrator receives completion events ✅
- Orchestrator registers completions in Firestore ✅
- Orchestrator logs "waiting for others" (stuck in wait state) ❌
- Orchestrator never triggers Phase 3 ❌

**Likely Root Causes:**
1. **Expected processor count mismatch** - Orchestrator expects N processors, but only M complete
2. **Processor name mismatch** - Completion events use different names than expected
3. **Threshold logic bug** - Orchestrator waiting for processor that will never come
4. **BDL dependency** - Orchestrator may be waiting for BDL (which is disabled)

### Issue 2: BDL Not Active (Expected Behavior)

**Finding:** BDL scraper did not run for Feb 10.

**Clarification:** This is **EXPECTED** behavior:
- BDL is set to inactive due to unreliability
- System should NOT wait for BDL data
- Only NBA.com gamebook should be required

**Impact:**
- 64% minutes coverage (only gamebook, no BDL boxscores)
- This is acceptable given BDL unreliability
- NOT a bug, just operating in degraded mode

---

## What Was Fixed

### Immediate Actions Taken

1. **✅ Manually triggered Phase 3** (7:45 AM)
   ```bash
   gcloud scheduler jobs run same-day-phase3 --location=us-west2
   ```
   Result: Unblocked analytics processing for Feb 10

2. **⏳ Deployed grading service** (7:46 AM, in progress)
   ```bash
   ./bin/deploy-service.sh nba-grading-service
   ```
   Result: Bringing service up to date (commit 6dfc2b4c)

3. **📊 Documented failure pattern**
   - 3-day orchestrator failure confirmed
   - Pattern analysis shows consistent `_triggered=False`
   - Logs show "waiting for others" but never triggering

---

## Investigation Required

### Priority 1: Fix Orchestrator Logic (P0 CRITICAL)

**Investigation Steps:**
1. Check `orchestration/cloud_functions/phase2_to_phase3/main.py`:
   - What is the expected processor count?
   - How does it determine "all processors complete"?
   - Is it waiting for BDL processors that are disabled?

2. Compare expected vs actual processor names:
   ```python
   # From logs - what's completing:
   - p2_nbacom_gamebook_pdf
   - p2_nbacom_boxscores
   - OddsApiPropsBatchProcessor
   - OddsApiGameLinesBatchProcessor
   - p2_bigdataball_pbp
   - p2_odds_player_props

   # What's the orchestrator expecting?
   # Check EXPECTED_PROCESSORS config
   ```

3. Check if BDL is in expected processor list:
   - If yes, remove it (BDL is disabled)
   - Update expected count accordingly

4. Add debug logging:
   - Log which processors are expected
   - Log which processors have completed
   - Log threshold calculation
   - Log trigger decision

**Files to Check:**
- `orchestration/cloud_functions/phase2_to_phase3/main.py`
- `orchestration/cloud_functions/phase2_to_phase3/config.py` (if exists)
- Phase 2 processor registry

### Priority 2: Add Monitoring (P1 HIGH)

**Create alert for orchestrator failures:**
```python
# Alert condition:
# IF phase2_completion._triggered = False
# AND processors_complete >= expected_threshold
# AND time_since_last_completion > 30 minutes
# THEN send critical alert
```

**Slack alert format:**
```
🚨 P0 CRITICAL: Phase 2→3 Orchestrator Stuck
Date: {game_date}
Processors: {completed}/{expected}
Triggered: False
Duration: {minutes} minutes stuck
Action: Manual trigger required
```

### Priority 3: Add Self-Healing (P2 MEDIUM)

**Auto-trigger Phase 3 if stuck:**
- Cloud Function runs every 2 hours
- Checks for `_triggered=False` with processors complete
- Auto-triggers Phase 3 if stuck > 1 hour
- Sends alert about auto-trigger
- Logs for post-mortem analysis

---

## Temporary Workaround

**Until orchestrator is fixed:**

1. **Check Phase 2 completion daily** (part of morning validation):
   ```python
   from google.cloud import firestore
   db = firestore.Client(project='nba-props-platform')
   yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
   doc = db.collection('phase2_completion').document(yesterday).get()

   if doc.exists:
       data = doc.to_dict()
       if not data.get('_triggered', False):
           print("⚠️ WARNING: Phase 3 not triggered, manual trigger needed!")
   ```

2. **Manual trigger if needed:**
   ```bash
   gcloud scheduler jobs run same-day-phase3 --location=us-west2
   ```

3. **Add to morning routine:**
   - Run `/validate-daily`
   - Check if orchestrator triggered
   - Manual trigger if needed
   - Report pattern to track recurrence

---

## Data Quality Impact

### Feb 10 Data Status

**After Manual Fix:**
- Phase 3: ✅ Triggered manually (will complete soon)
- Phase 4: ⏳ Waiting for Phase 3
- Phase 5: ⏳ Waiting for Phase 4
- Grading: ⏳ Waiting for deployment + Phase 3 completion

**Known Limitations:**
- Minutes coverage: 64% (acceptable without BDL)
- Usage rate: 96.6% (good)
- No BDL box scores (expected, BDL disabled)

### Historical Impact (Feb 9, Feb 8)

**Need to verify:**
- Were Phase 3, 4, 5 ever run for these dates?
- Check if manual triggers were done previously
- Determine if backfill needed for Feb 8-9

**Check command:**
```bash
# Check if analytics exist for Feb 8-9
for date in 2026-02-08 2026-02-09; do
  echo "=== $date ==="
  bq query "SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date='$date'"
done
```

---

## Files Changed

| File | Status | Change |
|------|--------|--------|
| None yet | - | Investigation only, fixes pending |

---

## Files to Investigate

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/phase2_to_phase3/main.py` | Orchestrator logic |
| `orchestration/cloud_functions/phase2_to_phase3/config.py` | Expected processors config |
| Phase 2 processor registry | Validate processor names |

---

## Recommended Next Session

**Session 198: Fix Phase 2→3 Orchestrator**

**Scope:**
1. Investigate expected vs actual processor list
2. Remove BDL dependency if present
3. Fix threshold/trigger logic
4. Add comprehensive logging
5. Deploy fixed orchestrator
6. Validate triggers for 1 week
7. Add monitoring alerts
8. Implement self-healing

**Success Criteria:**
- Phase 3 triggers automatically after Phase 2 completion
- `_triggered=True` set correctly in Firestore
- Monitoring alerts if orchestrator stalls
- Self-healing triggers Phase 3 if stuck > 1 hour

---

## Lessons Learned

### Detection Gap

**How this went undetected for 3 days:**
1. No monitoring alert for `_triggered=False` condition
2. Daily validation wasn't checking orchestrator status
3. Assumed manual triggers were normal operations
4. No trend analysis of trigger failures

**Fix:**
- Add orchestrator health to `/validate-daily` (Phase 0.6 check)
- Alert on `_triggered=False` when processors complete
- Track trigger success rate over time
- Add to deployment validation

### BDL Context

**Important:**
- BDL is intentionally disabled (unreliability)
- System MUST work without BDL
- Orchestrator MUST NOT wait for BDL
- Document BDL status clearly in runbooks

**Update Documentation:**
- CLAUDE.md: BDL status and why disabled
- Daily validation: BDL not running is expected
- Orchestrator config: BDL not in expected list

---

## Open Questions

1. **When did orchestrator start failing?**
   - Check Firestore for earlier dates
   - Determine if recent code change caused it
   - Check deployment history

2. **Why didn't alerts fire?**
   - Do we have orchestrator health monitoring?
   - Should we add to canary queries?
   - What's the SLA for detection?

3. **Were Feb 8-9 processed at all?**
   - Manual triggers done?
   - Data exists in analytics tables?
   - Backfill needed?

4. **Is this Phase 3→4, 4→5 orchestrator issue too?**
   - Check other orchestrators for same pattern
   - Validate all phase transitions
   - Systematic issue or isolated to 2→3?

---

## Quick Start for Session 198

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-11-SESSION-197-ORCHESTRATOR-FAILURE.md

# 2. Check if manual trigger worked
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase3_completion').document('2026-02-11').get()
if doc.exists:
    data = doc.to_dict()
    print(f"Phase 3: {len([k for k in data.keys() if not k.startswith('_')])}/5 processors")
else:
    print("Phase 3: No record yet (may still be running)")
EOF

# 3. Investigate orchestrator code
cd orchestration/cloud_functions/phase2_to_phase3
grep -n "EXPECTED\|threshold\|trigger" main.py

# 4. Check expected processor list
grep -n "processor\|expected" main.py | head -20

# 5. Compare to what's actually completing
# (From Firestore phase2_completion document keys)
```

---

**Status:** Investigation complete, fixes required
**Next Steps:** Session 198 to fix orchestrator logic
**Timeline:** Fix should be deployed within 24 hours
**Workaround:** Manual `same-day-phase3` trigger each morning
