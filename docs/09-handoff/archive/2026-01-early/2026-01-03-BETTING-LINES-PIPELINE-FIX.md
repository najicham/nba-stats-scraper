# Session Handoff: Betting Lines Pipeline Investigation & Fix

**Date**: 2026-01-03, 8:40 PM - 9:15 PM ET
**Duration**: 35 minutes
**Status**: 🔧 Bug Fixed | 🚀 Code Deployed | ⏳ Service Verification Needed

---

## 🎯 MISSION SUMMARY

**User Request:** "Fix betting lines for frontend - showing 0 players with lines"

**Root Cause Found:** Pipeline timing failure + Phase 3 code bug

**Status:**
- ✅ Root cause identified
- ✅ Code bug fixed
- ✅ Fix deployed to Cloud Run
- ⚠️ Service endpoint verification needed
- ⏳ Full pipeline test pending (tomorrow with real Jan 3 betting lines)

---

## 🔍 ROOT CAUSE ANALYSIS

### The Pipeline Timing Problem

```
Timeline (Jan 2):
├─ 1:00 PM ET: Phase 6 exports API → 0 betting lines ❌
├─ 4:32 PM ET: Phase 5 predictions → 0 betting lines ❌
├─ 7:00 PM ET: Games start → Frontend shows 0 lines ❌
└─ 8:00 PM ET: Betting lines collected → 14,214 lines! ✅ (TOO LATE!)

Result: Pipeline never re-runs after betting lines arrive
```

### Critical Bug Discovered

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Bug (Line 462):**
```python
def extract_raw_data(self):
    if self.target_date is None:  # ← AttributeError!
        # ... tries to use self.target_date but it was never initialized
```

**Root Cause:** `__init__` method never initialized `self.target_date = None`

**Impact:** Cannot trigger Phase 3 manually to merge betting lines into analytics

---

## ✅ FIX APPLIED

**File Modified:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py:114`

```python
def __init__(self):
    super().__init__()
    self.table_name = 'nba_analytics.upcoming_player_game_context'
    self.processing_strategy = 'MERGE_UPDATE'
    self.entity_type = 'player'
    self.entity_field = 'player_lookup'

    # FIX: Initialize target_date (set later in extract_raw_data)
    self.target_date = None  # ← ADDED THIS LINE

    # ... rest of __init__
```

**Deployment:**
- Service: `nba-phase3-analytics-processors`
- Revision: `nba-phase3-analytics-processors-00049-5lv`
- Timestamp: 2026-01-03 03:00 UTC (10:00 PM ET Jan 2)
- Status: Deployed successfully, 100% traffic

---

## 📊 DATA FLOW INVESTIGATION

### Phase 1 (Scrapers) - ✅ WORKING PERFECTLY

**BettingPros:**
- Players: 166
- Total lines: 14,214
- Bookmakers: 16
- Table: `nba_raw.bettingpros_player_points_props`

**Odds API:**
- Players: 141
- Total lines: 828
- Bookmakers: 2 (DraftKings, FanDuel)
- Table: `nba_raw.odds_api_player_points_props`

**Insight:** BettingPros provides 15-22x more data than Odds API!

### Phase 3 (Analytics) - ❌ BLOCKED BY BUG

**Purpose:** Merge betting lines from raw tables into analytics

**Input Tables:**
- `nba_raw.bettingpros_player_points_props` ✅
- `nba_raw.odds_api_player_points_props` ✅
- `nba_raw.nbac_gamebook_player_stats` (driver - all players)

**Output Table:**
- `nba_analytics.upcoming_player_game_context`
- Field: `has_prop_line` (TRUE if betting line exists)
- Field: `current_points_line` (actual betting line value)

**Current State (Jan 2):**
```sql
SELECT COUNT(*) as total, COUNTIF(has_prop_line = TRUE) as with_lines
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = '2026-01-02'
-- Result: 319 total, 0 with lines ❌
```

**Issue:** AttributeError prevented manual trigger to merge betting lines

### Phase 5 (Predictions) - ⚠️ INCOMPLETE DATA

**Current State:**
```sql
SELECT
  COUNT(*) as total,
  COUNTIF(current_points_line IS NOT NULL) as with_real_lines,
  ROUND(AVG(estimated_line_value), 2) as avg_estimated
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = '2026-01-02' AND system_id = 'ensemble_v1'
-- Result: 141 total, 0 with real lines, 13.31 avg estimated
```

**Key Distinction:**
- `estimated_line_value`: 13.31 avg ✅ (ML-estimated, always present)
- `current_points_line`: NULL ❌ (actual betting lines from sportsbooks)
- `recommendation`: "NO_LINE" ❌ (because no real betting lines)

**Frontend Needs:** `current_points_line` to display real sportsbook lines!

### Phase 6 (Frontend API) - ⏳ WAITING FOR UPSTREAM

**Current State:**
```json
{
  "game_date": "2026-01-02",
  "generated_at": "2026-01-03T01:51:49+00:00",
  "total_with_lines": 0,  // ❌ Should be 100-150
  "games": [...]
}
```

**Why 0 Lines:** Phase 6 reads from Phase 5 predictions, which have `current_points_line = NULL`

---

## 📋 HEALTH CHECK FINDINGS

### ✅ Working Components

1. **Betting Lines Collection:** 14,214 lines from 16 bookmakers
2. **BR Rosters:** All 30 teams, 608 players (despite concurrency errors)
3. **Injury Data:** 1,230 records for Jan 2
4. **Discovery Workflows:** Running on schedule

### ⚠️ Issues Found

**P0 - BR Roster Concurrency (Actively Failing):**
```
Error: Could not serialize access to table br_rosters_current due to concurrent update
Root Cause: 30 teams writing simultaneously → BigQuery 20 DML limit
Location: data_processors/raw/basketball_ref/br_roster_processor.py:355
Fix Needed: Batch processing (10 teams/batch) OR use MERGE instead of DELETE+INSERT
```

**P0 - Phase 3 Service Routing:**
```
Issue: Service URL returns wrong API (scrapers instead of analytics)
Deployed: nba-phase3-analytics-processors-00049-5lv
URL: https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app
Returns: Scrapers API ({"service":"nba-scrapers"...})
Expected: Analytics processor API
```

**P1 - Injury Report Data Loss:**
```
Scraped: 151 rows
Saved: 0 rows
Detection: Layer 5 validation caught it! ✅
Status: Need to investigate processor logs
```

---

## 🎬 NEXT STEPS

### IMMEDIATE (Tonight - After Service Verification)

1. **Verify Service Routing:**
   ```bash
   curl "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)"
   # Should return analytics processor status, not scrapers
   ```

2. **If Service OK, Test Phase 3 Fix:**
   ```bash
   ./bin/pipeline/force_predictions.sh 2026-01-03
   # Watch for Phase 3 success (not AttributeError)
   ```

### TOMORROW MORNING (Jan 3, ~10 AM ET)

3. **Validate Discovery Workflows:**
   ```sql
   -- Referee Discovery (12-attempt config)
   SELECT FORMAT_TIMESTAMP('%H:%M ET', triggered_at, 'America/New_York') as time_et,
          status
   FROM `nba_orchestration.scraper_execution_log`
   WHERE scraper_name = 'nbac_referee_assignments'
     AND DATE(triggered_at) = '2026-01-03'
   ORDER BY triggered_at
   -- Expect: ~12 attempts throughout the day, at least 1 success 10 AM-2 PM

   -- Injury Discovery (game_date tracking fix)
   SELECT game_date, status,
          JSON_VALUE(data_summary, '$.record_count') as records
   FROM `nba_orchestration.scraper_execution_log`
   WHERE scraper_name = 'nbac_injury_report'
     AND DATE(triggered_at) = '2026-01-03'
   -- Expect: game_date = '2026-01-03' when Jan 3 data found, ~110 records
   ```

### TOMORROW EVENING (Jan 3, 8:30 PM ET)

4. **Check Betting Lines Collected:**
   ```sql
   SELECT COUNT(DISTINCT player_name) as players,
          COUNT(*) as lines,
          COUNT(DISTINCT bookmaker) as bookmakers
   FROM `nba_raw.bettingpros_player_points_props`
   WHERE game_date = '2026-01-03'
   -- Expect: ~150+ players, 10K+ lines, 15+ bookmakers
   ```

5. **Run Full Pipeline for Jan 3:**
   ```bash
   ./bin/pipeline/force_predictions.sh 2026-01-03
   ```

6. **Verify Betting Lines Merged into Analytics:**
   ```sql
   SELECT COUNT(*) as total,
          COUNTIF(has_prop_line = TRUE) as with_prop_line,
          COUNTIF(current_points_line IS NOT NULL) as with_current_line
   FROM `nba_analytics.upcoming_player_game_context`
   WHERE game_date = '2026-01-03'
   -- Expect: ~300 total, 150+ with_prop_line, 150+ with_current_line
   ```

7. **Verify Betting Lines in Predictions:**
   ```sql
   SELECT COUNT(*) as total,
          COUNTIF(current_points_line IS NOT NULL) as with_lines,
          ROUND(AVG(current_points_line), 2) as avg_line
   FROM `nba_predictions.player_prop_predictions`
   WHERE game_date = '2026-01-03'
     AND system_id = 'ensemble_v1'
   -- Expect: 150+ with_lines, avg_line ~15-20
   ```

8. **Trigger Phase 6 Export:**
   ```bash
   gcloud pubsub topics publish nba-phase6-export-trigger \
     --project=nba-props-platform \
     --message='{"export_types": ["tonight", "tonight-players"], "target_date": "2026-01-03"}'
   ```

9. **Verify Frontend API Updated:**
   ```bash
   curl "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" \
     | jq '{game_date, generated_at, total_with_lines}'
   # Expect: total_with_lines: 100-150 (not 0!)
   ```

---

## 💡 LONG-TERM RECOMMENDATIONS

### 1. Fix Pipeline Timing (Choose One)

**Option A: Adjust Scheduler Times (Quick Fix)**
```yaml
# config/phase6_publishing.yaml
tonight_export:
  schedule:
    cron: "0 21 * * *"  # 9 PM ET (after betting lines)
    timezone: "America/New_York"
```

**Option B: Enable Event-Driven Triggering (Better)**
```yaml
# config/phase6_publishing.yaml:142-144
pubsub:
  phase5_completion_listener:
    enabled: true  # ← Change from false to true
    source_topic: "nba-predictions-complete"
```

**Recommendation:** Option B - Already implemented, just needs config change

### 2. Fix BR Roster Concurrency

**File:** `data_processors/raw/basketball_ref/br_roster_processor.py`

**Current:** Processes all 30 teams in parallel → exceeds BigQuery 20 DML limit

**Fix Options:**
1. Batch teams (10 at a time with delays)
2. Use MERGE instead of DELETE+INSERT (single DML statement)
3. Partition table by team (overkill)

**Recommendation:** Option 2 (MERGE) - Most elegant

### 3. Investigate Service Routing Issue

**Problem:** Phase 3 service URL returns wrong API

**Possible Causes:**
1. Wrong Dockerfile deployed
2. URL routing misconfiguration
3. Service name collision

**Action:** Review deployment configuration and Dockerfile

---

## 📁 FILES MODIFIED

1. `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py:114`
   - Added `self.target_date = None` initialization

---

## 🚀 DEPLOYMENT DETAILS

**Service:** `nba-phase3-analytics-processors`
**Revision:** `nba-phase3-analytics-processors-00049-5lv`
**Region:** `us-west2`
**Project:** `nba-props-platform`
**Timestamp:** 2026-01-03 03:00:38 UTC (10:00 PM ET Jan 2)
**Traffic:** 100% to new revision
**Status:** Deployed successfully

**Verification Needed:** Service endpoint returning correct API

---

## 📊 KEY METRICS

**Betting Lines Collected (Jan 2):**
- BettingPros: 14,214 lines
- Odds API: 828 lines
- Total unique players: 166
- Bookmakers: 16

**Current Analytics State (Jan 2):**
- Total players: 319
- With betting lines: 0 ❌ (blocked by Phase 3 bug)

**Current Predictions State (Jan 2):**
- Total predictions: 141
- With real betting lines: 0 ❌
- With estimated lines: 141 ✅

**BR Rosters:**
- Teams: 30/30 ✅
- Players: 608
- Concurrency errors: Yes ⚠️ (but retries succeeded)

---

## ⏱️ SESSION TIMELINE

- **8:40 PM**: Started health check
- **8:45 PM**: Identified betting lines NOT in frontend API
- **8:50 PM**: Traced data flow through all 6 phases
- **8:55 PM**: Discovered Phase 3 bug (AttributeError)
- **9:00 PM**: Applied fix + started deployment
- **9:05 PM**: Deployment completed
- **9:10 PM**: Attempted service verification (routing issue found)
- **9:15 PM**: Documented findings + next steps

---

## 🎯 SUCCESS CRITERIA (Jan 3)

- [ ] Phase 3 service routing verified/fixed
- [ ] Phase 3→4→5 pipeline completes without AttributeError
- [ ] Betting lines present in `nba_analytics.upcoming_player_game_context`
- [ ] Betting lines present in `nba_predictions.player_prop_predictions`
- [ ] Frontend API shows `total_with_lines > 100`
- [ ] Referee discovery running 12 attempts (not 6)
- [ ] Injury discovery tracking game_date correctly (no false positives)

---

**Session End:** 2026-01-03 9:15 PM ET
**Next Session Priority:** Verify service routing, test full pipeline for Jan 3
**Critical Blocker:** Service endpoint verification needed before full test
