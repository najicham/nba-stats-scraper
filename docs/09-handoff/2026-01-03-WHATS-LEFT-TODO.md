# 🎯 WHAT'S LEFT TO DO - Complete Roadmap

**Created:** Jan 2, 2026 - 11:35 PM ET
**Status:** Post-Betting Lines Fix Committed
**Current Time:** 11:35 PM ET, Jan 2, 2026

---

## 📊 EXECUTIVE SUMMARY

### ✅ What We Just Completed (Last 2 Hours):

1. **Fixed Phase 3 Betting Lines Bug** ✅
   - Moved 11 attributes from unreachable code to `__init__()`
   - Deployed revision 00051-njs successfully
   - Verified with real data: 150 players with betting lines in analytics
   - **COMMITTED:** `6f8a781 - fix: Phase 3 AttributeError`

### 🎯 Critical Path Forward:

**TONIGHT/TOMORROW:**
1. **Jan 3, 8:30 PM ET** - Test full betting lines pipeline (Phase 1→6)
2. **After Test** - Either celebrate or debug (likely celebrate!)

**THIS WEEK:**
3. Complete ML model training (2-3 hours remaining)
4. Fix P0 issues (BR roster concurrency, etc.)
5. Continue historical backfills (nice-to-have)

---

## 1️⃣ BETTING LINES PIPELINE - CRITICAL TEST TOMORROW

### Status: 🟢 95% Complete

**What's Done:**
- ✅ Phase 1: Betting lines collection (14,214 lines for Jan 2)
- ✅ Phase 3: Analytics merging FIXED and VERIFIED (150 players)
- ✅ Event-driven orchestration active (Phase 5→6 auto-trigger)

**What's Left:**
- ⏳ **Jan 3, 8:30 PM ET: Run full pipeline test**
- ⏳ Verify betting lines in predictions table
- ⏳ Verify frontend API updated

### 🎯 Critical Test Window: Jan 3, 8:30 PM ET

**Timeline:**
```
7:00 PM ET: Games start
8:00 PM ET: betting_lines workflow collects lines (automatic)
8:30 PM ET: RUN FULL PIPELINE TEST ← YOUR ACTION
8:45 PM ET: Verify betting lines everywhere
9:00 PM ET: Check frontend API
9:15 PM ET: Celebrate! 🎉
```

**Commands to Run:**

```bash
# 1. Run full pipeline
./bin/pipeline/force_predictions.sh 2026-01-03

# 2. Verify betting lines in ALL layers
bq query --use_legacy_sql=false "
SELECT
  'Raw' as layer, COUNT(*) as lines
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '2026-01-03'

UNION ALL

SELECT 'Analytics', COUNTIF(has_prop_line)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-03'

UNION ALL

SELECT 'Predictions', COUNTIF(current_points_line IS NOT NULL)
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-03' AND system_id = 'ensemble_v1'
"

# Expected: All layers show 100-150+ players

# 3. Check frontend API
curl "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" \
  | jq '{game_date, total_with_lines}'

# Expected: "total_with_lines": 100-150 (NOT 0!)
```

**Success Criteria:**
- [ ] Raw table has ~14,000 betting lines
- [ ] Analytics has 150+ players with `has_prop_line = TRUE`
- [ ] Predictions have 150+ players with `current_points_line IS NOT NULL`
- [ ] Frontend API shows `total_with_lines > 100`

**If Success:** Betting lines pipeline is COMPLETE! 🎉
**If Failure:** Debug (unlikely based on verification tonight)

**Time Required:** 30 minutes

---

## 2️⃣ ML MODEL TRAINING - NEARLY COMPLETE

### Status: 🟡 70% Complete (2-3 Hours Remaining)

**What's Done:**
- ✅ Backfills complete: 6,127 playoff records
- ✅ ML infrastructure built (`ml/train_real_xgboost.py`)
- ✅ 2 model iterations trained:
  - v1: 4.79 MAE (6 features)
  - v2: 4.63 MAE (14 features)
- ✅ Baseline to beat: 4.33 MAE (mock model)

**What's Left:**
1. **Add 7 missing context features** (~1 hour)
   - `is_home`, `days_rest`, `back_to_back`
   - `opponent_def_rating`, `opponent_pace`
   - `injury_absence_rate`, `roster_turnover`

2. **Train v3 model** (~30 minutes)
   - Expected: 4.1-4.2 MAE (beats baseline!)
   - 21 features total

3. **Deploy to production** (~1 hour)
   - Update prediction worker
   - Test in staging
   - Deploy to production
   - Monitor performance

**Expected Outcome:** 3-7% improvement over baseline = $15-30k/year profit

**Documentation:**
- `docs/08-projects/current/ml-model-development/02-EVALUATION-PLAN.md`
- `docs/09-handoff/2026-01-03-FINAL-ML-SESSION-HANDOFF.md`

**Time Required:** 2-3 hours

---

## 3️⃣ P0 ISSUES (HIGH PRIORITY)

### Issue #1: BR Roster Concurrency (Active Failures)

**Problem:** 30 teams writing simultaneously → BigQuery 20 DML limit

**Current Errors:**
```
Error: Could not serialize access to table br_rosters_current due to concurrent update
Error: Too many DML statements outstanding against table, limit is 20
```

**File:** `data_processors/raw/basketball_ref/br_roster_processor.py:355`

**Current Pattern:**
```python
# Delete all existing rows for team
DELETE FROM br_rosters_current WHERE team_abbrev = 'LAL'
# Insert new rows
INSERT INTO br_rosters_current VALUES (...)

# Problem: 30 teams * 2 DML = 60 DML statements!
```

**Solution Options:**

**Option A: Batch Processing**
```python
# Process teams in batches of 10
for batch in [teams[0:10], teams[10:20], teams[20:30]]:
    process_teams(batch)
    time.sleep(2)  # Delay between batches
```

**Option B: Use MERGE (Recommended)**
```python
# Single DML statement per team (atomic)
MERGE INTO br_rosters_current AS target
USING (SELECT ...) AS source
ON target.team_abbrev = source.team_abbrev
   AND target.player_name = source.player_name
WHEN MATCHED THEN UPDATE ...
WHEN NOT MATCHED THEN INSERT ...
```

**Impact:** Medium - Retries succeed, but causes timeouts and unreliable runs

**Time Required:** 1-2 hours (implement MERGE pattern)

---

### Issue #2: Empty Processor Stats in API Response

**Problem:** Phase 3 runs successfully but returns empty `stats: {}` in API response

**Evidence:**
```json
{
  "processor": "UpcomingPlayerGameContextProcessor",
  "stats": {},  // ← Empty!
  "status": "success"
}
```

**Investigation:**
- Processor DOES process data (verified 319 players in table)
- Logs show successful completion
- Stats object just not populated in response

**Impact:** Low - Cosmetic issue, doesn't affect functionality but makes debugging harder

**Time Required:** 1 hour (investigate and fix stats reporting)

---

## 4️⃣ P1 ISSUES (MEDIUM PRIORITY)

### Issue #1: Injury Report Data Loss

**Problem:** Layer 5 validation caught 151 rows scraped but 0 saved

**Log Evidence:**
- Scraper collected 151 injury records
- Processor saved 0 rows
- BigQuery operation may have timed out

**Possible Causes:**
1. BigQuery timeout during save
2. Schema validation failure
3. Duplicate key constraint
4. Concurrent write conflict

**Investigation Needed:**
```bash
gcloud logging read 'service_name="nba-phase2-raw-processors" AND
   textPayload=~"NbacInjuryReportProcessor" AND
   timestamp>="2026-01-03T00:00:00Z"' \
  --limit=50
```

**Impact:** Medium - Layer 5 validation detected it, but data was lost

**Time Required:** 1-2 hours (investigate logs, add retry logic)

---

### Issue #2: Schedule API Failures

**Problem:** 4.1% success rate (was much better before)

**Impact:** Medium - May affect game scheduling data

**Investigation Needed:**
- Check error patterns in logs
- Verify API endpoint still valid
- Check if rate limiting changed

**Time Required:** 1 hour (investigate and fix)

---

### Issue #3: BDL Standings Failures

**Problem:** Failures in Ball Don't Lie standings scraper

**Status:** Non-critical (marked `critical: false` in config)

**Impact:** Low - Supplemental data only

**Time Required:** 30 minutes (low priority, investigate when time permits)

---

## 5️⃣ HISTORICAL BACKFILLS (NICE-TO-HAVE)

### Status: 🟢 Partially Complete

**What's Done:**
- ✅ Playoff backfills: 3 seasons (6,127 records)
- ✅ Gamebook backfill scripts created
- ✅ Phase 3→4 validation working

**What's Left (Optional):**
- ⏳ Regular season backfills (2021-2024)
- ⏳ Older seasons (2019-2020)

**Purpose:** More training data for ML models

**Priority:** LOW - Current playoff data sufficient for v3 model

**Time Required:** 5-10 hours (can be done in background)

---

## 6️⃣ FRONTEND INTEGRATION (WAITING ON BETTING LINES TEST)

### Status: ⏳ Waiting for Tomorrow's Test

**What's Needed:**
1. Verify frontend API receives betting lines
2. Update frontend docs if needed
3. Coordinate with frontend team

**Documentation:**
- `/home/naji/code/props-web/docs/08-projects/current/backend-integration/api-status.md`

**Time Required:** 1 hour (after betting lines test passes)

---

## 🗓️ SUGGESTED TIMELINE

### **TONIGHT (Jan 2, 11:35 PM - Midnight):**
- [x] Commit Phase 3 fix ✅
- [x] Document what's left ✅
- [ ] Optional: Clean up Dockerfile backups
- [ ] Optional: Push commit to remote

### **JAN 3, 8:00-9:30 PM ET (CRITICAL):**
- [ ] Run full betting lines pipeline test
- [ ] Verify all layers have betting lines
- [ ] Check frontend API updated
- [ ] Document results
- [ ] Celebrate or debug

### **JAN 4-5 (THIS WEEK):**
- [ ] Add 7 missing ML features (1 hour)
- [ ] Train ML v3 model (30 min)
- [ ] Deploy ML v3 to production (1 hour)
- [ ] Fix BR roster concurrency (1-2 hours)
- [ ] Investigate injury report data loss (1-2 hours)

### **NEXT WEEK (OPTIONAL):**
- [ ] Fix Schedule API failures (1 hour)
- [ ] Fix empty processor stats (1 hour)
- [ ] Continue historical backfills (5-10 hours)
- [ ] Fix BDL standings (30 min)

---

## 📊 PRIORITY MATRIX

```
┌─────────────┬──────────────────────────────────────────┬──────────┐
│ Priority    │ Task                                     │ Time     │
├─────────────┼──────────────────────────────────────────┼──────────┤
│ P0 - URGENT │ Test betting lines pipeline (Jan 3)     │ 30 min   │
│ P0 - URGENT │ Complete ML v3 training                  │ 2-3 hrs  │
│             │                                          │          │
│ P1 - HIGH   │ Fix BR roster concurrency                │ 1-2 hrs  │
│ P1 - HIGH   │ Investigate injury report data loss      │ 1-2 hrs  │
│             │                                          │          │
│ P2 - MEDIUM │ Fix Schedule API failures                │ 1 hr     │
│ P2 - MEDIUM │ Fix empty processor stats                │ 1 hr     │
│             │                                          │          │
│ P3 - LOW    │ Continue historical backfills            │ 5-10 hrs │
│ P3 - LOW    │ Fix BDL standings                        │ 30 min   │
│ P3 - LOW    │ Frontend integration docs                │ 1 hr     │
└─────────────┴──────────────────────────────────────────┴──────────┘

Total P0/P1 Work: ~7 hours
Total P2/P3 Work: ~8-14 hours
```

---

## 🎯 RECOMMENDED FOCUS

### **This Week (P0/P1 Only):**

1. **Tomorrow Evening (Jan 3):** Betting lines pipeline test (~30 min)
2. **Jan 4-5:** Complete ML v3 (~2-3 hours)
3. **Jan 4-5:** Fix BR roster concurrency (~1-2 hours)
4. **Jan 4-5:** Investigate injury data loss (~1-2 hours)

**Total:** ~7 hours to complete all critical work

### **Next Week (P2/P3 Optional):**

- Schedule API, processor stats, backfills, etc.
- These can be done as time permits

---

## 📚 KEY DOCUMENTATION

**Betting Lines:**
- `docs/09-handoff/2026-01-03-BETTING-LINES-FIX-VERIFIED.md` - Verification results
- `docs/09-handoff/START-HERE-JAN-3.md` - Quick reference
- `docs/09-handoff/2026-01-03-CRITICAL-FIXES-SESSION-HANDOFF.md` - Full context

**ML Training:**
- `docs/09-handoff/2026-01-03-FINAL-ML-SESSION-HANDOFF.md` - Complete ML handoff
- `docs/08-projects/current/ml-model-development/02-EVALUATION-PLAN.md` - Evaluation plan
- `ml/train_real_xgboost.py` - Training script

**Pipeline Issues:**
- `docs/08-projects/current/pipeline-reliability-improvements/FUTURE-PLAN.md` - Known issues

---

## ✅ SUCCESS METRICS

### **This Week:**
- [ ] Betting lines flowing to frontend (total_with_lines > 100)
- [ ] ML v3 model deployed (MAE < 4.33)
- [ ] BR roster concurrency fixed (0 errors)
- [ ] Injury data loss investigated and fixed

### **This Month:**
- [ ] All P0/P1 issues resolved
- [ ] ML v3 in production for 2+ weeks
- [ ] Historical backfills complete
- [ ] All P2/P3 issues resolved

---

**🎉 GREAT WORK TONIGHT!**

The Phase 3 betting lines fix is deployed, tested, verified, and committed. Tomorrow's test is the final validation, and then this critical feature is DONE!

**Next Action:** Wait until Jan 3, 8:30 PM ET to run the full pipeline test.

**Sleep well!** 😊🍀
