# Orchestrator Health Monitoring

**Created:** 2026-02-11 (Session 197)
**Purpose:** Prevent and detect orchestrator failures that block pipeline progression

---

## Overview

The orchestrators (Phase 2→3, 3→4, 4→5, 5→6) are Cloud Functions that trigger the next phase after all processors complete. They use Firestore documents to track completion and set `_triggered=True` when the next phase is initiated.

**Critical Insight (Session 197):** Orchestrator failures can go undetected for days, silently blocking the entire pipeline while individual processors appear healthy.

---

## The Feb 2026 Orchestrator Failure

### What Happened

**Duration:** Feb 9-11, 2026 (at least 3 days)
**Impact:** Phase 2→3 orchestrator failed to trigger Phase 3 for 3 consecutive days
**Detection:** Morning validation on Feb 11
**Root Cause:** BDL (Ball Don't Lie) dependencies in orchestrator and Phase 3 analytics
**Fix:** Session 198 (Feb 11, 2026) - Removed BDL dependencies, deployed successfully

**Failure Pattern:**
```
Phase 2 Completion Status:
2026-02-11: 2 processors complete, _triggered=False ❌
2026-02-10: 6 processors complete, _triggered=False ❌
2026-02-09: 5 processors complete, _triggered=False ❌
```

**Why It Went Undetected:**
- Individual Phase 2 processors completed successfully ✅
- No alerts on `_triggered=False` condition ❌
- Manual scheduler triggers masked the issue ⚠️
- Assumed manual triggers were normal operations ❌

---

## Detection Methods

### Method 1: Firestore Check (Fastest)

```python
from google.cloud import firestore
from datetime import datetime, timedelta

db = firestore.Client(project='nba-props-platform')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

# Check Phase 2→3 trigger
doc = db.collection('phase2_completion').document(yesterday).get()
if doc.exists:
    data = doc.to_dict()
    processors = len([k for k in data.keys() if not k.startswith('_')])
    triggered = data.get('_triggered', False)

    if processors >= 5 and not triggered:
        print(f"🔴 CRITICAL: Phase 2 complete but Phase 3 NOT triggered!")
        print(f"   Processors: {processors}, Triggered: {triggered}")
```

### Method 2: Check Phase Completion Records

```python
# Check if downstream phase has completion record
processing_date = datetime.now().strftime('%Y-%m-%d')
phase3_doc = db.collection('phase3_completion').document(processing_date).get()

if not phase3_doc.exists:
    print(f"⚠️ WARNING: No Phase 3 completion record for {processing_date}")
    print("   Check if Phase 2→3 orchestrator triggered")
```

### Method 3: BigQuery Validation

```sql
-- Check if analytics data exists for yesterday
SELECT COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date = CURRENT_DATE() - 1
```

Expected: 200-300 records
If 0: Phase 3 didn't run (orchestrator failure)

---

## Threshold Logic

### Expected Processor Counts (As of Feb 2026)

**Phase 2 (Raw Processing):**
- **Expected:** 5 processors (BDL is disabled)
- **Critical:** `p2_nbacom_gamebook_pdf`, `p2_nbacom_boxscores`, `p2_odds_game_lines`, `p2_odds_player_props`, `p2_bigdataball_pbp`
- **NOT Expected:** `bdl_player_boxscores` (disabled due to unreliability)

**NOTE (Session 198):** Fixed orchestrator and Phase 3 analytics to NOT wait for BDL data. System now uses NBA.com gamebook exclusively for completeness checks.

**Phase 3 (Analytics):**
- **Expected:** 5 processors
- `player_game_summary`, `team_offense_game_summary`, `team_defense_game_summary`, `upcoming_player_game_context`, `upcoming_team_game_context`

**Phase 4 (Precompute):**
- **Expected:** Variable (depends on configuration)

---

## BDL Status (IMPORTANT)

### Why BDL Is Disabled

**Status:** INACTIVE (intentionally disabled)
**Reason:** Unreliable data source (Session 41, Session 94 investigations)
**Impact:** 64% minutes coverage vs 90%+ with BDL
**Decision:** Acceptable trade-off for reliability

### BDL Not Running Is EXPECTED

**When validating:**
- ✅ BDL boxscore count = 0 is **NORMAL**
- ✅ Minutes coverage 60-70% is **ACCEPTABLE**
- ❌ Do NOT flag as critical issue
- ❌ Do NOT wait for BDL in orchestrators

**Orchestrator Configuration:**
- Phase 2→3 orchestrator MUST NOT wait for BDL processors
- Expected processor list should NOT include `bdl_player_boxscores`
- Trigger threshold should be 5 (not 6)

---

## Manual Workaround

**If orchestrator fails to trigger:**

### Phase 3
```bash
gcloud scheduler jobs run same-day-phase3 --location=us-west2
```

### Phase 4
```bash
gcloud scheduler jobs run same-day-phase4 --location=us-west2
```

### Phase 5
```bash
gcloud scheduler jobs run same-day-phase5 --location=us-west2
```

### Verification
```python
# Wait 2-3 minutes, then check
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase3_completion').document('2026-02-11').get()
if doc.exists:
    print(f"✅ Phase 3 triggered: {len([k for k in doc.to_dict().keys() if not k.startswith('_')])}/5 processors")
```

---

## Monitoring Improvements (Needed)

### Add to Daily Validation

**Phase 0.6 Extension:**
```python
# Check orchestrator trigger status
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
doc = db.collection('phase2_completion').document(yesterday).get()

if doc.exists:
    data = doc.to_dict()
    processors = len([k for k in data.keys() if not k.startswith('_')])
    triggered = data.get('_triggered', False)

    if processors >= 5 and not triggered:
        # P0 CRITICAL: Orchestrator stuck
        send_alert("Phase 2→3 orchestrator failed to trigger")
```

### Alert Conditions

**Critical Alert (P0):**
```
IF phase2_completion._triggered = False
AND processors_complete >= 5
AND time_since_last_completion > 30 minutes
THEN send critical alert
```

**Slack Alert Format:**
```
🚨 P0 CRITICAL: Phase 2→3 Orchestrator Stuck
Date: 2026-02-10
Processors: 6/5 (threshold met)
Triggered: False
Duration: 180 minutes stuck
Action: Run manual trigger
Command: gcloud scheduler jobs run same-day-phase3
```

---

## Self-Healing (Future)

**Auto-Trigger Cloud Function:**
- Runs every 2 hours
- Checks Firestore for stuck orchestrators
- Auto-triggers next phase if stuck > 1 hour
- Sends alert about auto-trigger
- Logs for post-mortem

**Implementation:**
```python
# Pseudo-code
def check_and_heal_orchestrators():
    for phase in ['phase2', 'phase3', 'phase4', 'phase5']:
        doc = get_completion_doc(phase)

        if processors_complete >= threshold and not triggered:
            if time_stuck > 60_minutes:
                # Auto-trigger next phase
                trigger_scheduler_job(f"same-day-{next_phase}")
                send_alert(f"Auto-triggered {next_phase} after orchestrator stall")
                log_healing_event()
```

---

## Investigation Checklist

**When orchestrator fails:**

1. **Check Firestore completion docs:**
   - Which processors completed?
   - Is `_triggered` set to False?
   - How long since last processor completion?

2. **Check orchestrator logs:**
   ```bash
   gcloud functions logs read phase2-to-phase3-orchestrator \
     --region=us-west2 --limit=50
   ```

3. **Check expected processor list:**
   - Is BDL in the expected list? (should NOT be)
   - Does threshold match actual processor count?
   - Are processor names spelled correctly?

4. **Check for code changes:**
   - Recent orchestrator deployments?
   - Recent processor additions/removals?
   - Configuration changes?

5. **Check historical pattern:**
   - Is this a one-time failure or recurring?
   - When did it start?
   - What changed before it started?

---

## Files to Check

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/phase2_to_phase3/main.py` | Phase 2→3 orchestrator logic |
| `orchestration/cloud_functions/phase3_to_phase4/main.py` | Phase 3→4 orchestrator logic |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Phase 4→5 orchestrator logic |
| `orchestration/cloud_functions/phase5_to_phase6/main.py` | Phase 5→6 orchestrator logic |

---

## Related Documentation

- **Session 197 Handoff:** `docs/09-handoff/2026-02-11-SESSION-197-ORCHESTRATOR-FAILURE.md`
- **Daily Validation Skill:** `.claude/skills/validate-daily/instructions.md`
- **Monitoring Guide:** `docs/02-operations/monitoring-guide.md`
- **BDL Investigation:** `docs/08-projects/archive/bdl-quality-investigation/`

---

## Success Metrics

**Orchestrator Health:**
- `_triggered=True` rate: 100%
- Detection time: < 2 hours
- Auto-heal time: < 1 hour
- Manual intervention rate: 0%

**Current Status (Feb 2026):**
- `_triggered=True` rate: 0% (3-day failure)
- Detection time: 3 days
- Auto-heal: Not implemented
- Manual intervention: Required daily

**Target (After Fix):**
- `_triggered=True` rate: 100%
- Detection time: < 30 minutes
- Auto-heal time: < 1 hour
- Manual intervention: < 1% of days

---

## Session 198 Fix (Feb 11, 2026)

### Root Cause Identified

The orchestrator and Phase 3 analytics were waiting for BDL (Ball Don't Lie) data that would never arrive:

1. **Phase 2→3 Orchestrator:** `REQUIRED_PHASE2_TABLES` included `bdl_player_boxscores`
2. **Phase 3 Analytics:** `verify_boxscore_completeness()` queried `bdl_player_boxscores` table
3. **BDL Status:** Intentionally DISABLED since Sessions 41/94 due to unreliability
4. **Impact:** System waited indefinitely for BDL processors that never completed

### Changes Made

**1. orchestration/cloud_functions/phase2_to_phase3/main.py**
- Removed `('nba_raw', 'bdl_player_boxscores', 'game_date')` from `REQUIRED_PHASE2_TABLES`
- Added comment explaining BDL is disabled

**2. data_processors/analytics/main_analytics_service.py**
- Updated `verify_boxscore_completeness()` to use `nbac_gamebook_player_stats` instead of `bdl_player_boxscores`
- Changed trigger condition from `source_table == 'bdl_player_boxscores'` to `source_table == 'nbac_gamebook_player_stats'`
- Updated `trigger_missing_boxscore_scrapes()` to use `nbac_gamebook` scraper instead of `bdl_box_scores`

**3. CLAUDE.md**
- Added troubleshooting entry for orchestrator failures
- Documented BDL disabled status as expected behavior

### Deployment

**Commit:** 2acc368a
**Deployed:** Feb 11, 2026 16:05 UTC
**Method:** Auto-deploy via Cloud Build triggers (push to main)
**Services Updated:**
- Phase 2→3 orchestrator Cloud Function
- Phase 3 analytics Cloud Run service

### Verification

**Next Steps:**
1. Monitor tonight's Phase 2 completion (check Firestore `phase2_completion` for `_triggered=True`)
2. Verify Phase 3 triggers automatically without manual intervention
3. Confirm analytics processors run successfully

**Expected Behavior:**
- Phase 2 completes with 5 processors (no BDL)
- Orchestrator sets `_triggered=True` when all 5 complete
- Phase 3 triggers automatically via Pub/Sub subscription
- No waiting for BDL data
