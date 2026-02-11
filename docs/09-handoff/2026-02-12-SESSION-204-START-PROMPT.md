# Session 204 - Start Prompt (Morning Validation)

**Previous Session:** Session 203 - Phase 6 Health Check & System Validation (COMPLETE ✅)

---

## Quick Context

**CRITICAL:** Tonight (Feb 11) was the first autonomous orchestrator test after fixing a 7-day failure. This session validates if the fix worked.

**What happened yesterday:**
- Sessions 197-203 fixed 7-day Phase 2→3 orchestrator failure (BDL dependencies)
- All services deployed with fixes
- Phase 6 exports validated (481 players, game scores working)
- Opus agent reviewed (production-ready with minor gaps)

**Your mission:** Run tomorrow's validation checklist to confirm the orchestrator fix worked.

---

## Read the Handoff First

```bash
cat docs/09-handoff/2026-02-11-SESSION-203-COMPLETE-HANDOFF.md
```

**Key sections:**
- Tomorrow's Validation Checklist (6 steps)
- Priority Fixes for Session 204
- Known Issues (non-blocking)

---

## Quick Start: Run Full Validation

### Step 1: Orchestrator Autonomous Trigger Check (MOST CRITICAL)

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime, timedelta

db = firestore.Client(project='nba-props-platform')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

print(f"=== Phase 2→3 Orchestrator Status ({yesterday}) ===\n")
doc = db.collection('phase2_completion').document(yesterday).get()

if doc.exists:
    data = doc.to_dict()
    processors = [k for k in data.keys() if not k.startswith('_')]
    triggered = data.get('_triggered', False)
    trigger_reason = data.get('_trigger_reason', 'NOT SET')

    print(f"Processors complete: {len(processors)}/5")
    print(f"Processor names: {processors}")
    print(f"Triggered: {triggered}")
    print(f"Trigger reason: {trigger_reason}")

    if len(processors) >= 5 and triggered:
        print("\n✅ SUCCESS - Orchestrator triggered autonomously!")
        print("   The 7-day failure is FIXED")
    elif len(processors) >= 5 and not triggered:
        print("\n❌ FAILURE - Orchestrator still stuck")
        print("   Manual trigger needed: gcloud scheduler jobs run same-day-phase3")
    else:
        print(f"\n⏳ WAITING - Only {len(processors)}/5 processors complete")
else:
    print("❌ NO RECORD - Check if Phase 2 ran at all")
EOF
```

**If SUCCESS:** Continue to Step 2
**If FAILURE:** Investigate immediately - the fix didn't work

### Step 2: Phase 3 Analytics Check

```bash
bq query --use_legacy_sql=false "
-- Yesterday's analytics
SELECT COUNT(*) as players, COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

-- Today's prediction context
SELECT COUNT(DISTINCT player_lookup) as players, COUNT(DISTINCT team_abbr) as teams
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE()"
```

**Expected:** 200+ players yesterday, 400+ today

### Step 3: Tonight Export Game Scores

```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total players: {data.get(\"total_players\", 0)}')
print(f'Games: {len(data.get(\"games\", []))}')
for g in data.get('games', [])[:5]:
    status = g.get('game_status')
    home = g.get('home_score')
    away = g.get('away_score')
    print(f'{g[\"game_id\"]}: {status}, scores={home}-{away}')
"
```

**Expected:** Final games show integer scores, scheduled games show null

### Step 4: Predictions Check

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNTIF(is_actionable = TRUE) as actionable
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()"
```

**Expected:** 50+ predictions with actionable > 0

### Step 5: Props Join Fix (Session 201)

```bash
bq query --use_legacy_sql=false "
SELECT game_date,
  ROUND(100.0 * COUNTIF(over_under_result IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1 ORDER BY 1 DESC"
```

**Expected:** 30-40% for recent dates

### Step 6: Check for Errors

```bash
gcloud logging read "resource.labels.function_name=phase2-to-phase3-orchestrator
  AND severity>=ERROR
  AND timestamp>=\"2026-02-11T20:00:00Z\"" \
  --limit=10
```

**Expected:** Zero errors

---

## If All Checks Pass ✅

**Next Steps:**
1. Report success - the 7-day orchestrator failure is FIXED
2. Proceed to Priority Fixes:
   - Fix `bdl_games` reference (5 min)
   - Add orchestrator health to `/validate-daily` (1 hour)
   - Update CLAUDE.md stale entry (2 min)

## If Any Check Fails ❌

**Immediate Actions:**
1. Note which step failed
2. Check orchestrator logs for errors
3. Manual trigger if needed: `gcloud scheduler jobs run same-day-phase3`
4. Investigate root cause
5. May need to revert or fix the fix

---

## Priority Fixes After Validation

**See handoff for full details. Quick list:**

1. **Fix `bdl_games` validation reference** (5 min, P1)
   - File: `orchestration/cloud_functions/phase2_to_phase3/main.py` line 1089
   - Change: `'game_count_table': 'nbac_schedule'`

2. **Add orchestrator health check to `/validate-daily`** (1 hour, P1)
   - Prevent future undetected failures
   - Check `_triggered` status in Firestore

3. **Update CLAUDE.md stale entry** (2 min, P2)
   - Remove "Phase 6 scheduler broken" entry
   - Schedulers are correctly configured

4. **Implement self-healing auto-trigger** (2-4 hours, P1)
   - Cloud Function runs every 2 hours
   - Auto-triggers Phase 3 if stuck

5. **Clean up BDL references** (30 min, P3)
   - Set `bdl_player_boxscores: False` in team processors

6. **Backfill Feb 7-8 over_under_result** (10 min, P4 optional)

---

## Commands Cheat Sheet

```bash
# Full validation (run all steps above)
# See handoff for complete checklist

# Manual triggers if needed
gcloud scheduler jobs run same-day-phase3 --location=us-west2
gcloud scheduler jobs run same-day-phase4 --location=us-west2
gcloud scheduler jobs run same-day-phase5 --location=us-west2

# Deployment drift
./bin/check-deployment-drift.sh --verbose

# Deploy service
./bin/deploy-service.sh <service-name>
./bin/hot-deploy.sh <service-name>  # Faster
```

---

## Key Files to Read

1. **Full handoff:** `docs/09-handoff/2026-02-11-SESSION-203-COMPLETE-HANDOFF.md`
2. **Orchestrator health:** `docs/02-operations/ORCHESTRATOR-HEALTH.md`
3. **Previous fixes:**
   - Session 197: Discovery
   - Session 198: Phase 2→3 fix
   - Session 203: Phase 3 fix

---

## What Success Looks Like

**All 6 validation steps pass:**
- ✅ Orchestrator triggered autonomously
- ✅ Phase 3 analytics ran
- ✅ Game scores in export
- ✅ Predictions generated
- ✅ Props join working
- ✅ Zero orchestrator errors

**Result:** 7-day orchestrator failure is FIXED and can proceed to cleanup/improvements.

---

## What Failure Looks Like

**Any validation step fails:**
- ❌ Orchestrator still stuck (`_triggered=False`)
- ❌ Phase 3 didn't run
- ❌ Missing data or errors

**Result:** The fix didn't work or there's a new issue. Investigation needed immediately.

---

**Session 204 Ready - First thing: Run Step 1 orchestrator check** 🎯
