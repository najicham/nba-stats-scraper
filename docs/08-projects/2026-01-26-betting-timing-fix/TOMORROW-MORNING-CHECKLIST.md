# Tomorrow Morning Verification Checklist
## Date: 2026-01-27 @ 10:00 AM ET

**Purpose**: Verify the betting_lines timing fix works in production
**Time Required**: 5-10 minutes
**Expected Result**: Betting data available by 9 AM, predictions by 10 AM

---

## Pre-Check: Ensure You Have Access

```bash
# Verify you're in the right directory
cd ~/code/nba-stats-scraper

# Check git status (should show clean or only doc changes)
git status

# Verify deployed commit
git log --oneline -1
# Expected: a6cd5536 or later
```

---

## ✅ CHECK 1: Workflow Started at 8 AM (Not 1 PM)

**What to Check**: Did betting_lines workflow run at 8 AM instead of 1 PM?

```bash
# Check master controller logs for betting_lines runs on 2026-01-27
grep "betting_lines" logs/master_controller.log | grep "2026-01-27" | head -10
```

**Expected Output**:
```
2026-01-27 08:XX:XX - betting_lines - Decision: RUN (window started)
2026-01-27 10:XX:XX - betting_lines - Decision: RUN (2h interval)
```

**Success Criteria**: ✅ First RUN at ~08:00 (not 13:00)

**If Failed**:
- Check if master controller is running: `ps aux | grep master_controller`
- Check if config loaded: `grep "Config reloaded" logs/master_controller.log | tail -1`
- Verify config value: `grep -A 5 "betting_lines:" config/workflows.yaml | grep window_before_game_hours`

---

## ✅ CHECK 2: Betting Data Present by 9 AM

**What to Check**: Is betting data in BigQuery by 9 AM?

```bash
# Check betting props data
bq query --use_legacy_sql=false --location=us-west2 --format=pretty "
SELECT
  COUNT(*) as total_props,
  COUNT(DISTINCT game_id) as games_covered,
  MIN(snapshot_timestamp) as earliest_data,
  MAX(snapshot_timestamp) as latest_data
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = '2026-01-27'
"
```

**Expected Output**:
```
+-------------+---------------+---------------------+---------------------+
| total_props | games_covered |   earliest_data     |    latest_data      |
+-------------+---------------+---------------------+---------------------+
|     200-300 |             7 | 2026-01-27 08:30:XX | 2026-01-27 10:XX:XX |
+-------------+---------------+---------------------+---------------------+
```

**Success Criteria**:
- ✅ 200-300 props records
- ✅ 7 games covered (100% coverage)
- ✅ Earliest data around 8:30 AM

**If Failed**:
- Check if workflow actually ran: See CHECK 1
- Check scraper logs: `grep "oddsa_player_props" logs/scraper_execution.log | grep "2026-01-27"`
- Check for errors: `grep ERROR logs/master_controller.log | grep "2026-01-27"`

---

## ✅ CHECK 3: Game Lines Data Present

**What to Check**: Are game lines also available?

```bash
# Check game lines data
bq query --use_legacy_sql=false --location=us-west2 --format=pretty "
SELECT
  COUNT(*) as total_lines,
  COUNT(DISTINCT game_id) as games_covered
FROM \`nba-props-platform.nba_raw.odds_api_game_lines\`
WHERE game_date = '2026-01-27'
"
```

**Expected Output**:
```
+-------------+---------------+
| total_lines | games_covered |
+-------------+---------------+
|      70-140 |             7 |
+-------------+---------------+
```

**Success Criteria**:
- ✅ 70-140 lines records
- ✅ 7 games covered

---

## ✅ CHECK 4: Phase 3 Analytics Running

**What to Check**: Did Phase 3 processors populate game context?

```bash
# Check player game context
bq query --use_legacy_sql=false --location=us-west2 --format=pretty "
SELECT
  COUNT(*) as player_contexts,
  COUNT(DISTINCT game_id) as games_covered,
  SUM(CASE WHEN has_prop_line THEN 1 ELSE 0 END) as players_with_props
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-27'
"
```

**Expected Output**:
```
+------------------+---------------+--------------------+
| player_contexts  | games_covered | players_with_props |
+------------------+---------------+--------------------+
|          200-300 |             7 |            200-300 |
+------------------+---------------+--------------------+
```

**Success Criteria**:
- ✅ 200-300 player contexts
- ✅ 7 games covered
- ✅ Most players have prop lines (has_prop_line = TRUE)

---

## ✅ CHECK 5: Validation Script (No False Alarms)

**What to Check**: Does validation pass without timing-related false alarms?

```bash
# Run validation script
python scripts/validate_tonight_data.py --date 2026-01-27
```

**Expected Output**:
```
============================================================
TONIGHT'S DATA VALIDATION - 2026-01-27
============================================================

✓ Schedule: 7 games, 14 teams
✓ Roster: 30 teams, last updated 2026-01-27
✓ Betting Props: 247 records, 7 games
✓ Betting Lines: 98 records, 7 games
✓ Game Context: All games have both teams, 239 total players
...

============================================================
SUMMARY
============================================================

✅ All checks passed!
```

**Success Criteria**:
- ✅ No "TOO_EARLY" warnings
- ✅ Betting Props: ✓ (not ⚠️ or ✗)
- ✅ Betting Lines: ✓ (not ⚠️ or ✗)
- ✅ Zero false alarms related to timing

**If Failed**:
- Look for timing-related warnings: `grep "TOO_EARLY\|WITHIN_LAG" output.txt`
- Check if validation ran too early (before 9 AM)
- Review validation script logic: `scripts/validate_tonight_data.py`

---

## ✅ CHECK 6: Predictions Available (Optional)

**What to Check**: Are predictions generated? (May not run until afternoon/evening)

```bash
# Check if predictions exist
bq query --use_legacy_sql=false --location=us-west2 --format=pretty "
SELECT
  COUNT(*) as prediction_count,
  COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27'
  AND is_active = TRUE
  AND system_id = 'ensemble_v1'
"
```

**Expected Output** (if predictions already ran):
```
+------------------+-----------------+
| prediction_count | unique_players  |
+------------------+-----------------+
|          200-300 |         200-300 |
+------------------+-----------------+
```

**Success Criteria**:
- ✅ 200-300 predictions
- ⚠️ If 0: Predictions may run later in day (not critical for timing fix validation)

---

## 📊 Quick Summary Score

After running all checks, count your ✅:

| Check | Status | Critical? |
|-------|--------|-----------|
| 1. Workflow at 8 AM | [ ] | ✅ YES |
| 2. Betting Props | [ ] | ✅ YES |
| 3. Game Lines | [ ] | ✅ YES |
| 4. Phase 3 Analytics | [ ] | ✅ YES |
| 5. Validation Passes | [ ] | ✅ YES |
| 6. Predictions | [ ] | ⚠️ NICE TO HAVE |

**Scoring**:
- **5/5 Critical Checks Passing**: ✅ **SUCCESS** - Fix works perfectly!
- **4/5 Passing**: ⚠️ **Partial Success** - Investigate the 1 failure
- **3/5 or Less**: ❌ **FAILURE** - Consider rollback

---

## 🎯 Expected Outcome: SUCCESS

**If All Checks Pass**:

1. Document success in a new file:
```bash
echo "2026-01-27 - First Production Run: SUCCESS" >> docs/08-projects/2026-01-26-betting-timing-fix/PRODUCTION-RESULTS.md
```

2. Update stakeholders:
```
Subject: Betting Data Timing Fix - First Production Run Successful

The betting_lines timing fix is working as expected:
✅ Workflow started at 8 AM (was 1 PM)
✅ Betting data available by 9 AM (100% coverage)
✅ Phase 3 analytics completed by 10 AM
✅ Validation passed without false alarms

Users can now access predictions by 10 AM daily.
Monitoring will continue for one week.
```

3. Continue monitoring for 7 days (daily checks at 10 AM)

---

## 🚨 If Checks Fail

### Scenario A: Workflow Didn't Start at 8 AM

**Possible Causes**:
1. Config didn't reload
2. Master controller not running
3. No games scheduled for 2026-01-27

**Fix**:
```bash
# Check if games exist
bq query --format=csv "SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.nbac_schedule\` WHERE game_date='2026-01-27'"

# Manually reload controller
systemctl restart nba-master-controller
# OR
pkill -f master_controller && python orchestration/master_controller.py &
```

### Scenario B: Data Exists But Coverage Incomplete

**Possible Causes**:
1. Some games missing from schedule
2. API rate limiting
3. Scraper failures

**Fix**:
```bash
# Check scraper errors
grep ERROR logs/scraper_execution.log | grep "2026-01-27"

# Check which games are missing
bq query "SELECT game_id FROM \`nba_raw.nbac_schedule\` WHERE game_date='2026-01-27'
         EXCEPT DISTINCT
         SELECT game_id FROM \`nba_raw.odds_api_player_points_props\` WHERE game_date='2026-01-27'"

# Manual trigger for missing games if needed
python orchestration/manual_trigger.py --workflow betting_lines --date 2026-01-27
```

### Scenario C: Validation Shows False Alarms

**Possible Causes**:
1. Timing utilities not working correctly
2. Running validation too early (before 9 AM)
3. Logic error in validation script

**Fix**:
```bash
# Check current time
date

# Re-run validation if it's past 9 AM
python scripts/validate_tonight_data.py --date 2026-01-27

# Debug timing calculations
python -c "
from orchestration.workflow_timing import calculate_workflow_window
from datetime import datetime
game_times = [datetime(2026, 1, 27, 19, 0)]
window_start, window_end = calculate_workflow_window('betting_lines', game_times)
print(f'Window: {window_start} - {window_end}')
"
```

### Scenario D: Complete Failure - Need Rollback

**If 3+ critical checks fail AND investigation shows config issue**:

```bash
# Quick rollback
cd ~/code/nba-stats-scraper
git revert f4385d03
git push origin main

# OR manual fix
sed -i 's/window_before_game_hours: 12/window_before_game_hours: 6/' config/workflows.yaml
systemctl restart nba-master-controller

# Verify rollback
grep window_before_game_hours config/workflows.yaml
```

**After Rollback**:
- System returns to 1 PM workflow start (old behavior)
- Investigate why 12-hour window failed
- Review logs and error messages
- Plan fix for the fix

---

## 📝 Documentation After Verification

### If Successful:
Create `PRODUCTION-RESULTS.md` documenting:
- All check results (✅/❌)
- Actual timestamps (workflow start, data arrival)
- Any minor issues encountered
- Next steps (continue monitoring)

### If Failed:
Create `PRODUCTION-FAILURE-ANALYSIS.md` documenting:
- Which checks failed
- Error messages and logs
- Root cause investigation
- Rollback decision and results
- Next steps to fix

---

## ⏰ Timeline Reference

**Today (2026-01-26)**:
- 09:52 AM PST: Deployed to production
- ~10:52 AM PST: Config should hot-reload (automatic)

**Tomorrow (2026-01-27)**:
- 08:00 AM ET: Workflow should run (first time with new config)
- 08:30 AM ET: Betting data should start appearing
- 09:00 AM ET: Phase 3 analytics should trigger
- **10:00 AM ET: YOU RUN THIS CHECKLIST** ← WE ARE HERE
- 10:30 AM ET: Document results

---

## 🎯 Success Definition (Reminder)

**Deployment is successful if**:
1. Workflow starts at 8 AM ✅
2. Betting data by 9 AM ✅
3. 100% game coverage ✅
4. No false alarms ✅
5. Predictions by 10 AM ✅

**ONE SENTENCE SUMMARY**:
> "Betting data available 6 hours earlier (9 AM vs 3 PM) with 100% coverage (7/7 games vs 4/7)."

That's the win. Everything else is details.

---

## Quick Reference Commands

Copy-paste these for fast checking:

```bash
# Quick health check (run all at once)
echo "=== WORKFLOW RUN TIMES ==="
grep "betting_lines.*RUN" logs/master_controller.log | grep "2026-01-27" | head -3

echo -e "\n=== BETTING DATA COUNT ==="
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) as props, COUNT(DISTINCT game_id) as games FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\` WHERE game_date='2026-01-27'"

echo -e "\n=== PHASE 3 ANALYTICS ==="
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) as contexts FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\` WHERE game_date='2026-01-27'"

echo -e "\n=== VALIDATION CHECK ==="
python scripts/validate_tonight_data.py --date 2026-01-27 2>&1 | grep -A 5 "SUMMARY"
```

**Expected Output Time**: ~30 seconds

---

## Contact & Escalation

**If you need help**:
1. Check this document first
2. Review deployment docs: `docs/08-projects/2026-01-26-betting-timing-fix/`
3. Check incident reports: `docs/incidents/`
4. Rollback if needed (commands above)

**Key Files**:
- This checklist: `docs/08-projects/2026-01-26-betting-timing-fix/TOMORROW-MORNING-CHECKLIST.md`
- Deployment complete: `PHASE-3-DEPLOYMENT-COMPLETE.md`
- Executive summary: `EXECUTIVE-SUMMARY.md`

---

**Status**: ⏰ WAITING FOR TOMORROW @ 10:00 AM ET

**Next Action**: Run this checklist on 2026-01-27 at 10:00 AM ET

**Expected Duration**: 5-10 minutes

**Expected Outcome**: ✅ SUCCESS (95% confidence)

---

*Good luck! The fix should work. See you tomorrow morning.* 🚀
