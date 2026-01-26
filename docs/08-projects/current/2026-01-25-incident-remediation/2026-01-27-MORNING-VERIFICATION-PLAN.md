# 2026-01-27 Morning Verification Plan

**Date:** 2026-01-27
**Purpose:** Verify that the 2026-01-26 configuration fix is working correctly
**Expected First Trigger:** 7:00 AM - 8:00 AM ET
**Total Verification Time:** ~15 minutes

---

## What We're Verifying

The betting_lines workflow should now trigger at **7-8 AM** (12 hours before games) instead of **1 PM** (6 hours before games).

**Success Criteria:**
- ✅ Workflow decisions show RUN action in morning (not afternoon)
- ✅ Betting data collected by 8-9 AM
- ✅ Phase 3 can run by 10 AM with betting data present

---

## Timeline & Checks

### 8:00 AM ET - Initial Check

**Run verification script:**
```bash
cd ~/code/nba-stats-scraper
python scripts/verify_betting_workflow_fix.py --date 2026-01-27
```

**Expected Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Betting Lines Workflow Verification
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 Games Scheduled for 2026-01-27
   Count: 7 games ✅

🔍 Betting Lines Workflow Decisions for 2026-01-27
   Total decisions: 1-2
   RUN decisions: 1

   ✅ First execution: 2026-01-27 07:XX:XX (or 08:XX:XX)
   ✅ PASS: Workflow triggered in morning (07:xx or 08:xx)
   ✅ This confirms the 12-hour window fix is working!

📊 Betting Data Collected for 2026-01-27
   Player Props:
      Count: 80-100+ props
      Players: 40-50+ unique players
      ✅ Data found

   Game Lines:
      Count: 7+ lines
      ✅ Data found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Verification Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Games scheduled: ✅
   Workflow decisions: ✅
   Betting data collected: ✅

✅ VERIFICATION PASSED
   The configuration fix is working correctly!
```

### If Script Shows "TOO EARLY" (Before 7 AM)

**Message:**
```
⏳ TOO EARLY TO VERIFY
   No workflow decisions yet - check back after 7 AM ET
```

**Action:** Wait until 7:30 AM and run again

---

### 8:30 AM ET - Manual BigQuery Check (If Needed)

If the script is unclear or you want to dig deeper:

**Check workflow decisions:**
```sql
SELECT
  FORMAT_TIMESTAMP('%H:%M', decision_time, 'America/New_York') as time_et,
  action,
  reason,
  ARRAY_LENGTH(scrapers_triggered) as scraper_count
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = '2026-01-27'
  AND workflow_name = 'betting_lines'
ORDER BY decision_time
```

**Expected Results:**
| time_et | action | scraper_count | Notes |
|---------|--------|---------------|-------|
| 07:XX | RUN | 5 | ✅ First trigger in morning! |
| 09:XX | RUN | 5 | Second trigger (2 hours later) |

**Check betting data:**
```sql
-- Player props
SELECT COUNT(*) as prop_count, COUNT(DISTINCT player_lookup) as player_count
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date = '2026-01-27';

-- Game lines
SELECT COUNT(*) as line_count
FROM `nba-props-platform.nba_raw.odds_api_game_lines`
WHERE game_date = '2026-01-27';
```

**Expected Results:**
- Props: 80-120 records, 40-60 unique players
- Lines: 7-14 records (spread + total for each game)

---

### 9:00 AM ET - Check Config Drift (Optional)

**Verify production is still correct:**
```bash
python scripts/detect_config_drift.py
```

**Expected Output:**
```
✅ No config drift detected
   Production config matches current HEAD
```

---

## Success Scenarios

### ✅ Scenario 1: Perfect Success (Expected)

**Indicators:**
- Verification script shows: ✅ VERIFICATION PASSED
- First RUN decision at 7:XX AM or 8:XX AM
- Betting data present (props + lines)

**Action:** Success! Document in completion report and move on.

**Next Steps:**
- Add note to `REMEDIATION-COMPLETE-SUMMARY.md`
- Consider this incident fully resolved
- Monitor for a few days to ensure consistency

---

### ⚠️ Scenario 2: Workflow Ran But No Data

**Indicators:**
- Workflow decisions show RUN at 7-8 AM ✅
- But no data in BigQuery tables ❌

**Possible Causes:**
1. Scraper failed (check Cloud Run logs)
2. API key issue (check Secrets Manager)
3. Odds API down (check third-party status)

**Action:**
```bash
# Check scraper service logs
gcloud run services logs read nba-scrapers \
  --region=us-west2 \
  --limit=100 \
  --format="table(timestamp,textPayload)"

# Look for errors related to odds_api scrapers
```

**Escalation:** If scrapers failed, this is a different issue (not config-related)

---

### ❌ Scenario 3: Workflow Didn't Run (Unlikely)

**Indicators:**
- No workflow decisions found for 2026-01-27
- Verification script shows: ⏳ TOO EARLY (even at 9 AM)

**Possible Causes:**
1. Master controller not running (check Cloud Scheduler)
2. Config not deployed (check service revision)
3. Master controller crashed (check Cloud Run logs)

**Action:**
```bash
# Check master controller is running
gcloud scheduler jobs describe master-controller-hourly \
  --location=us-west2 \
  --project=nba-props-platform

# Check recent executions
gcloud scheduler jobs logs master-controller-hourly \
  --location=us-west2 \
  --limit=10

# Verify deployed config
python scripts/detect_config_drift.py
```

**Escalation:** If controller isn't running, manually trigger it:
```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe nba-phase1-scrapers \
  --region=us-west2 --format="value(status.url)")

# Get auth token
AUTH_TOKEN=$(gcloud auth print-identity-token)

# Trigger evaluation
curl -X POST \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  -H "Content-Type: application/json" \
  "${SERVICE_URL}/evaluate-workflows"
```

---

### ⚠️ Scenario 4: First Trigger at 1 PM (Config Not Applied)

**Indicators:**
- First RUN decision at 13:XX (1 PM) instead of 7-8 AM
- Config drift detection shows drift

**Possible Causes:**
1. Deployment didn't complete successfully
2. Service rolled back to previous revision
3. Config file not included in deployment

**Action:**
```bash
# Check deployed commit
gcloud run services describe nba-phase1-scrapers \
  --region=us-west2 --format=json | jq -r '.metadata.labels["commit-sha"]'

# Should be: ea41370a or later
# If older: Need to redeploy

# Redeploy if needed
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

**Escalation:** Redeploy immediately and wait for next hourly run (9 AM or 10 AM)

---

## Rollback Plan (If Major Issues)

If the fix caused unexpected problems:

**Step 1: Assess Impact**
- Are other workflows affected?
- Is data being collected for other tables?
- Are scrapers crashing?

**Step 2: Revert Config (If Needed)**
```bash
# Revert to previous commit
git revert a44a4c48  # This session's commit
git revert ea41370a  # The Dockerfile fix commit
git revert f4385d03  # The config fix commit

# Redeploy
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

**Step 3: Manual Trigger**
```bash
# Manually trigger betting data collection for today
# (Scripts in orchestration/cloud_functions/betting_lines/)
```

**Note:** Rollback is extremely unlikely - the fix is simple and well-tested

---

## Documentation After Verification

### If Successful ✅

Add to `REMEDIATION-COMPLETE-SUMMARY.md`:
```markdown
## Verification Results (2026-01-27)

**Date:** 2026-01-27 8:00 AM ET
**Status:** ✅ VERIFIED SUCCESSFUL

### Results
- First betting_lines trigger: 07:XX AM ET ✅
- Betting data collected: 97 props + 8 lines ✅
- Phase 3 analytics: Ready to run ✅

### Conclusion
The configuration fix (window_before_game_hours: 12) is working correctly.
Betting data is now collected in the morning as expected.

**Incident Status:** CLOSED - Verified Resolved
```

### If Issues Found ❌

Create new incident report:
```bash
# Create follow-up incident report
touch docs/incidents/2026-01-27-CONFIG-FIX-FOLLOWUP.md
```

Document:
- What went wrong
- Root cause (different from original)
- Steps taken
- Resolution

---

## Quick Reference Commands

**Verify the fix:**
```bash
python scripts/verify_betting_workflow_fix.py --date 2026-01-27
```

**Check config drift:**
```bash
python scripts/detect_config_drift.py
```

**View workflow decisions:**
```bash
bq query --use_legacy_sql=false '
SELECT
  FORMAT_TIMESTAMP("%H:%M", decision_time, "America/New_York") as time_et,
  action,
  reason
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, "America/New_York") = "2026-01-27"
  AND workflow_name = "betting_lines"
ORDER BY decision_time
'
```

**Check service logs:**
```bash
gcloud run services logs read nba-phase1-scrapers \
  --region=us-west2 \
  --limit=50
```

**Manual trigger (emergency only):**
```bash
SERVICE_URL=$(gcloud run services describe nba-phase1-scrapers \
  --region=us-west2 --format="value(status.url)")
AUTH_TOKEN=$(gcloud auth print-identity-token)

curl -X POST \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  "${SERVICE_URL}/evaluate-workflows"
```

---

## Summary

**What to do:**
1. Run verification script at 8:00 AM ET
2. Check that first RUN decision was in morning (not afternoon)
3. Verify betting data exists in BigQuery
4. Document results

**Total time:** ~5-10 minutes

**Expected outcome:** ✅ Everything works, incident resolved

**Contact if issues:** Create new incident report in `docs/incidents/`

---

**Created:** 2026-01-26 12:20 PM ET
**For Date:** 2026-01-27 Morning
**Estimated Duration:** 15 minutes
**Confidence Level:** Very High (fix is simple and well-tested)
