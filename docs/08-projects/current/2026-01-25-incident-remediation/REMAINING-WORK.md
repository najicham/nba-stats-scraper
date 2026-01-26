# 2026-01-25 Incident Remediation - Remaining Work

**Last Updated:** 2026-01-27 23:30
**Overall Progress:** 40% Complete (2/5 tasks)
**Status:** ⚠️ Active - Multiple Blockers

---

## Quick Summary

### ✅ What's Done (2 tasks)
1. **PBP Proxy Rotation** - Enabled to prevent future IP blocking
2. **GSW/SAC Extraction Fix** - Fixed JOIN bug causing missing teams

### ⚠️ What Remains (3 tasks)
1. **PBP Data Backfill** - 2 games missing (blocked by CloudFront IP ban)
2. **Table ID Bug Fix** - Save operation fails with duplicate dataset name
3. **Database Repopulation** - Need to rerun processor after bug fix

---

## Outstanding Tasks

### 🔴 HIGH PRIORITY - Task 1: Fix BigQuery Save Operation Bug

**Issue:** Processor calculates data correctly but cannot save to BigQuery

**Error:**
```
ValueError: table_id must be a fully-qualified ID in standard SQL format,
got nba-props-platform.nba_analytics.nba_analytics.upcoming_player_game_context
                                    ^^^^^^^^^^^^ duplicate dataset name
```

**Location:**
- File: `data_processors/analytics/operations/bigquery_save_ops.py`
- Line: 125

**Impact:**
- GSW/SAC extraction fix is complete but data can't be saved
- 35 players (17 GSW + 18 SAC) missing from database
- Affects 2/8 games on 2026-01-25

**Investigation Needed:**
```python
# Check how table_name is constructed
# Expected: "nba_analytics.upcoming_player_game_context"
# Actual: "nba-props-platform.nba_analytics.nba_analytics.upcoming_player_game_context"

# Likely causes:
# 1. project_id being prepended when it shouldn't be
# 2. dataset name duplicated in table_id construction
# 3. String formatting issue in save_analytics() method
```

**Steps to Fix:**
1. Read `data_processors/analytics/operations/bigquery_save_ops.py:125`
2. Identify where table_id is constructed
3. Remove duplicate "nba_analytics" or fix project_id prepending
4. Test with dry run
5. Commit fix

**Time Estimate:** 15-30 minutes

---

### 🟡 MEDIUM PRIORITY - Task 2: Rerun Player Context Processor

**Depends On:** Task 1 (save operation bug fix)

**Objective:** Populate GSW/SAC player data in BigQuery

**Command:**
```bash
# After fixing save operation bug:
SKIP_COMPLETENESS_CHECK=true python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor 2026-01-25 --skip-downstream-trigger
```

**Expected Results:**
- 358 players extracted (currently: 358 ✅)
- 227 players processed successfully (currently: 227 ✅)
- 227 players saved to BigQuery (currently: 0 ❌)

**Verification:**
```sql
-- Check GSW/SAC now present
SELECT team_abbr, COUNT(*) as player_count
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = '2026-01-25'
GROUP BY team_abbr
ORDER BY team_abbr

-- Expected to see:
-- GSW: 17 players
-- SAC: 18 players
```

**Success Criteria:**
- All 16 teams present (currently: 14/16)
- GSW and SAC player counts match expectations
- No extraction warnings in logs

**Time Estimate:** 5-10 minutes (processor runtime)

---

### 🟢 LOW PRIORITY - Task 3: Retry Missing PBP Games

**Depends On:** CloudFront IP block clearance (external)

**Objective:** Download 2 missing games to complete PBP dataset

**Games Missing:**
- 0022500651 (DEN @ MEM)
- 0022500652 (DAL @ MIL)

**Current Blocker:** AWS CloudFront IP block (403 Forbidden)

**Test Block Status:**
```bash
# Check if block has cleared:
curl -I https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022500651.json

# Success: HTTP/2 200
# Still blocked: HTTP/2 403
```

**When Block Clears:**
```bash
# Retry with delays (proxy already enabled)
python3 scripts/backfill_pbp_20260125.py --game-id 0022500651
sleep 20
python3 scripts/backfill_pbp_20260125.py --game-id 0022500652
```

**Verification:**
```bash
# Check GCS has all 8 games
gsutil ls gs://nba-scraped-data/nba-com/play-by-play/2026-01-25/ | wc -l
# Expected: 8 (currently: 6)
```

**Alternative Approaches:**
1. **Wait:** CloudFront blocks typically clear within 24-48 hours
2. **Different Network:** Use VPN or different ISP
3. **Cloud Shell:** Run from GCP Cloud Shell (different IP range)
4. **Accept Partial:** 75% completion may be acceptable for most use cases

**Time Estimate:** 5 minutes (once block clears)

---

## Historical Data Impact

### Should We Check Other Dates?

The GSW/SAC extraction bug existed in the code since backfill mode was implemented. This means OTHER historical dates may have similar issues.

**Investigation Query:**
```sql
-- Find dates with suspiciously low team coverage
SELECT
  game_date,
  COUNT(DISTINCT team_abbr) as unique_teams,
  COUNT(*) as total_players
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date >= '2024-10-01'  -- Current season
GROUP BY game_date
HAVING unique_teams < 10  -- Flag dates with <10 teams (expect 10-16)
ORDER BY game_date DESC
```

**Recommendation:**
- Run investigation query AFTER fixing and testing 2026-01-25
- If other dates found, document them for bulk reprocessing
- Consider adding validation checks to detect this in future

---

## Success Criteria

### Definition of Complete

#### PBP Issues (75% done)
- [x] Proxy rotation enabled
- [ ] All 8 games in GCS (6/8 currently)
- [x] Documentation complete

#### Player Context Issues (50% done)
- [x] GSW/SAC extraction bug fixed
- [ ] Save operation bug fixed
- [ ] All 16 teams in database (14/16 currently)

### Overall Completion Metrics

| Task | Status | Progress | Blocker |
|------|--------|----------|---------|
| PBP Proxy | ✅ | 100% | None |
| GSW/SAC Fix | ✅ | 100% | None |
| PBP Backfill | ⚠️ | 75% | CloudFront IP block |
| Table ID Fix | ⚠️ | 0% | Needs investigation |
| DB Repopulation | ⚠️ | 0% | Blocked by Table ID fix |

**Overall:** 40% Complete (2/5 tasks fully done)

---

## Next Actions

### Immediate (This Session)
1. **Fix table_id bug** (15-30 min)
   - Read bigquery_save_ops.py:125
   - Identify duplicate dataset name issue
   - Test fix with dry run
   - Commit changes

2. **Rerun processor** (5-10 min)
   - Execute processor for 2026-01-25
   - Verify GSW/SAC data in database
   - Check for any new errors

### Short-term (Next 24 hours)
3. **Check CloudFront block status** (1 min every 6 hours)
   - Test with curl command
   - Retry PBP games when clear
   - Verify GCS completion

### Medium-term (This Week)
4. **Historical data audit** (30-60 min)
   - Run investigation query for affected dates
   - Document scope of historical impact
   - Plan bulk reprocessing if needed

---

## Risk Assessment

### Critical Path Items
1. **Table ID bug fix** - BLOCKING player context completion
   - Risk: Medium (unknown complexity)
   - Mitigation: Similar bugs likely fixed before, check git history

2. **CloudFront block clearance** - BLOCKING PBP completion
   - Risk: Low (blocks typically clear automatically)
   - Mitigation: Alternative approaches available (Cloud Shell)

### Data Quality Risks
- **Partial PBP data (75%):** Acceptable for most features
- **Missing player teams (12.5%):** More impactful, needs completion
- **Historical dates:** Unknown scope, requires investigation

---

## Questions for Stakeholders

### 1. Is 75% PBP completion acceptable?
- **Current:** 6/8 games have PBP data
- **Missing:** DEN@MEM, DAL@MIL
- **Impact:** Shot zone analysis, detailed play patterns for 2 games

### 2. What features depend on complete player context?
- **Current:** 14/16 teams have player context
- **Missing:** GSW (17 players), SAC (18 players)
- **Impact:** Predictions, analytics for ~35 players

### 3. Should we investigate historical dates?
- **Issue:** Bug existed since backfill mode implementation
- **Scope:** Unknown how many dates affected
- **Effort:** ~30-60 min investigation + potential reprocessing

---

## Documentation Links

### This Project
- [README.md](README.md) - Project overview
- [STATUS.md](STATUS.md) - Detailed status and technical analysis
- [GSW-SAC-FIX.md](GSW-SAC-FIX.md) - GSW/SAC bug investigation and fix
- [COMPLETION-CHECKLIST.md](COMPLETION-CHECKLIST.md) - Quick reference checklist

### Related Incidents
- `docs/incidents/2026-01-25-ACTION-3-REMEDIATION-REPORT.md` - Player context backfill
- `docs/incidents/2026-01-25-PBP-SCRAPER-FINAL-REPORT.md` - PBP IP blocking

### Code Files
- `scrapers/nbacom/nbac_play_by_play.py` - PBP scraper
- `data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py` - Player extraction
- `data_processors/analytics/operations/bigquery_save_ops.py` - Save operations (needs fix)

---

**Last Updated:** 2026-01-27 23:30
**Next Review:** After completing Task 1 (table_id bug fix)
**Owner:** Data Engineering Team
