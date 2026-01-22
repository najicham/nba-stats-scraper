# BDL Data Gap Investigation Checklist
**Issue:** Ball Don't Lie API missing 30-40% of games across multiple days
**Date Discovered:** January 21, 2026, 4:20 PM PST
**Priority:** HIGH

---

## Investigation Steps

### Step 1: Check Scraper Logs (10 minutes)

#### A. Check for BDL scraper execution
```bash
# View recent BDL scraper logs
gcloud functions logs read phase1-scrapers --limit=200 | grep -i "bdl\|ball"

# Check execution times
gcloud functions logs read phase1-scrapers --limit=100 | grep -i "timestamp\|started\|completed"
```

**Questions to Answer:**
- [ ] Is the BDL scraper running on schedule?
- [ ] When did it last run successfully?
- [ ] Are there any execution gaps?

#### B. Check for errors
```bash
# Look for errors in scraper
gcloud functions logs read phase1-scrapers --limit=200 | grep -i "error\|exception\|failed"

# Look for rate limiting
gcloud functions logs read phase1-scrapers --limit=200 | grep -i "rate\|429\|throttle\|limit"

# Look for timeout issues
gcloud functions logs read phase1-scrapers --limit=200 | grep -i "timeout\|timed out"
```

**Questions to Answer:**
- [ ] Are there any error messages?
- [ ] Is rate limiting occurring?
- [ ] Are requests timing out?

---

### Step 2: Check BDL Scraper Code (15 minutes)

#### A. Locate BDL scraper
```bash
# Find BDL scraper files
find /home/naji/code/nba-stats-scraper -name "*bdl*.py" -type f | grep -i scraper
```

**Expected locations:**
- `/home/naji/code/nba-stats-scraper/scrapers/balldontlie/`
- `/home/naji/code/nba-stats-scraper/scrapers/bdl_*.py`

#### B. Review scraper logic
```bash
# Read BDL games scraper
cat /home/naji/code/nba-stats-scraper/scrapers/balldontlie/bdl_games.py

# Read BDL boxscores processor
find /home/naji/code/nba-stats-scraper -name "*bdl*box*.py" -type f
```

**Questions to Answer:**
- [ ] What filters are applied to games?
- [ ] Is there date range limiting?
- [ ] Are certain teams excluded?
- [ ] Is there pagination logic?

#### C. Check for game filtering
Look for:
- `if` statements that might exclude games
- Date filters that might be too restrictive
- Team filters that might exclude certain teams
- Status filters (only "Final" games?)

---

### Step 3: Test BDL API Directly (10 minutes)

#### A. Check BDL API documentation
- URL: https://docs.balldontlie.io/ (or similar)
- Check if there are known issues
- Review rate limits
- Check API status page

#### B. Test API manually
```bash
# Test getting games for Jan 20
curl "https://api.balldontlie.io/v1/games?dates[]=2026-01-20" -H "Authorization: YOUR_KEY"

# Test getting specific game
curl "https://api.balldontlie.io/v1/games/GAME_ID" -H "Authorization: YOUR_KEY"
```

**Questions to Answer:**
- [ ] Does the API return all 7 games for Jan 20?
- [ ] Are the missing games (LAL@DEN, MIA@SAC, TOR@GSW) in the API response?
- [ ] Is there an API issue or is our scraper not capturing them?

---

### Step 4: Compare Data Sources (10 minutes)

#### A. Check ESPN boxscores completeness
```sql
-- See if ESPN has the missing games
SELECT
  game_date,
  COUNT(DISTINCT game_id) as espn_games
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date BETWEEN '2026-01-17' AND '2026-01-20'
GROUP BY game_date
ORDER BY game_date DESC;
```

#### B. Check which games ESPN has that BDL doesn't
```sql
-- Find games in ESPN but not BDL for Jan 20
SELECT
  e.game_id,
  'In ESPN, Missing from BDL' as status
FROM (
  SELECT DISTINCT game_id
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date = '2026-01-20'
) e
LEFT JOIN (
  SELECT DISTINCT game_id
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = '2026-01-20'
) b ON e.game_id = b.game_id
WHERE b.game_id IS NULL;
```

**Questions to Answer:**
- [ ] Does ESPN have all 7 games for Jan 20?
- [ ] Can ESPN serve as a backup source?
- [ ] Is ESPN more reliable than BDL?

---

### Step 5: Check Processing Pipeline (10 minutes)

#### A. Check if BDL processor ran
```bash
# Check Phase 2 processor logs
gcloud functions logs read phase2-processors --limit=100 | grep -i "bdl"
```

#### B. Check for processing errors
```sql
-- Check processor execution history (if table exists)
SELECT
  processor_name,
  execution_date,
  status,
  error_message
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE processor_name LIKE '%bdl%'
  AND execution_date >= '2026-01-17'
ORDER BY execution_date DESC;
```

**Questions to Answer:**
- [ ] Did the BDL processor run for Jan 20?
- [ ] Were there any processing errors?
- [ ] Did it complete successfully?

---

### Step 6: Check Game Metadata (5 minutes)

#### A. Check if missing games have special characteristics
```sql
-- Get details of missing games from schedule
SELECT
  game_id,
  game_date,
  home_team_id,
  visitor_team_id,
  season_year,
  is_playoffs
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_id IN (
  '20260120_LAL_DEN',
  '20260120_MIA_SAC',
  '20260120_TOR_GSW',
  '20260119_MIA_GSW'
);
```

**Questions to Answer:**
- [ ] Are missing games all from certain teams?
- [ ] Are they all home/away games?
- [ ] Do they have special status flags?
- [ ] Is there a pattern to what's missing?

---

## Diagnosis Decision Tree

### If Logs Show Rate Limiting
**Root Cause:** API rate limits exceeded
**Solution:**
1. Adjust scraper timing
2. Implement exponential backoff
3. Deploy rate limiting improvements (from robustness project)

### If Logs Show No Errors
**Root Cause:** Scraper filtering too aggressively OR BDL API incomplete
**Solution:**
1. Check scraper filter logic
2. Test BDL API directly
3. Compare with ESPN data
4. Remove filters if too restrictive

### If BDL API Missing Games
**Root Cause:** Upstream API issue
**Solution:**
1. Contact BDL support
2. Switch to ESPN as primary source
3. Implement dual-source strategy
4. Document BDL as unreliable

### If Scraper Not Running
**Root Cause:** Scheduler issue
**Solution:**
1. Check Cloud Scheduler configuration
2. Verify trigger is active
3. Check for execution permissions
4. Re-deploy scraper function

---

## Quick Fixes to Try

### Fix 1: Manual Backfill Script
```bash
# If backfill script exists
python scripts/backfill_bdl_games.py --start-date 2026-01-17 --end-date 2026-01-20

# Or trigger scraper manually
gcloud functions call phase1-scrapers --data '{"scraper": "bdl_boxscores", "date": "2026-01-20"}'
```

### Fix 2: Increase Rate Limits
If rate limiting is the issue:
1. Edit `/home/naji/code/nba-stats-scraper/shared/config/rate_limit_config.py`
2. Increase BDL rate limits
3. Redeploy scraper

### Fix 3: Switch to ESPN
If BDL is unreliable:
1. Update team analytics to use ESPN boxscores
2. Test ESPN completeness
3. Deploy updated analytics processor

---

## Data to Collect During Investigation

### 1. Scraper Execution Times
```
Last 5 BDL scraper runs:
- Date: _____  Time: _____  Status: _____  Games: _____
- Date: _____  Time: _____  Status: _____  Games: _____
- Date: _____  Time: _____  Status: _____  Games: _____
- Date: _____  Time: _____  Status: _____  Games: _____
- Date: _____  Time: _____  Status: _____  Games: _____
```

### 2. Error Summary
```
Total errors in last 7 days: _____
Rate limit errors: _____
Timeout errors: _____
API errors: _____
Other errors: _____
```

### 3. API Test Results
```
Manual API test for Jan 20:
- Total games returned: _____
- Games matching schedule: _____
- Missing games in API: _____
- API response time: _____
```

### 4. Comparison Results
```
Data source completeness for Jan 20:
- Schedule: 7 games
- BDL: _____ games
- ESPN: _____ games
- Gamebook: _____ games
```

---

## Investigation Outcomes

### Outcome 1: BDL API Issue
**Action:** Switch to ESPN or implement dual-source
**Timeline:** 1-2 days
**Priority:** HIGH

### Outcome 2: Rate Limiting
**Action:** Deploy rate limiting improvements
**Timeline:** Same day
**Priority:** MEDIUM

### Outcome 3: Scraper Filter Bug
**Action:** Fix filter logic, redeploy
**Timeline:** Few hours
**Priority:** HIGH

### Outcome 4: Timing Issue
**Action:** Adjust scraper schedule
**Timeline:** 30 minutes
**Priority:** LOW

---

## After Investigation: Backfill Plan

### Missing Games to Backfill

**Jan 20 (3 games):**
1. 20260120_LAL_DEN (Lakers @ Nuggets)
2. 20260120_MIA_SAC (Miami @ Sacramento)
3. 20260120_TOR_GSW (Toronto @ Golden State)

**Jan 19 (1 game):**
4. 20260119_MIA_GSW (Miami @ Golden State)

**Jan 18 (2+ games):**
- Need to identify specific games

**Jan 17 (2+ games):**
- Need to identify specific games

### Backfill Strategy

#### Option A: Manual Scraper Trigger
```bash
# Trigger for specific date
gcloud functions call phase1-scrapers --data '{"scraper": "bdl_boxscores", "date": "2026-01-20", "force": true}'
```

#### Option B: Direct API Call + Load
```python
# Use BDL scraper class directly
from scrapers.balldontlie.bdl_boxscores import BDLBoxscoresScraper
scraper = BDLBoxscoresScraper()
scraper.scrape_date('2026-01-20')
```

#### Option C: Use ESPN as Source
```sql
-- If ESPN has the data, use it instead
INSERT INTO `nba-props-platform.nba_raw.bdl_player_boxscores`
SELECT * FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_id IN ('20260120_LAL_DEN', '20260120_MIA_SAC', '20260120_TOR_GSW');
```

---

## Monitoring Going Forward

### Daily Check Query
```sql
-- Add to daily health check
WITH missing_games AS (
  SELECT
    s.game_date,
    COUNT(DISTINCT s.game_id) as scheduled,
    COUNT(DISTINCT b.game_id) as bdl_captured
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  LEFT JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON s.game_id = b.game_id AND s.game_date = b.game_date
  WHERE s.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY s.game_date
)
SELECT
  game_date,
  scheduled,
  bdl_captured,
  scheduled - bdl_captured as missing,
  ROUND(100.0 * bdl_captured / scheduled, 1) as completeness_pct,
  CASE
    WHEN bdl_captured = scheduled THEN '✅ Complete'
    WHEN bdl_captured >= scheduled * 0.9 THEN '⚠️ Minor gaps'
    ELSE '❌ Critical gaps'
  END as status
FROM missing_games;
```

### Alert Criteria
- Trigger if completeness < 90%
- Notify: Engineering team
- Escalate if: Completeness < 70% for 2+ days

---

## Files & References

**Investigation Checklist:** This file
**Full Health Report:** `/home/naji/code/nba-stats-scraper/PIPELINE-HEALTH-REPORT-JAN-21-2026.md`
**Quick Summary:** `/home/naji/code/nba-stats-scraper/JAN-21-VALIDATION-SUMMARY.md`

**Code Locations:**
- BDL Scrapers: `/home/naji/code/nba-stats-scraper/scrapers/balldontlie/`
- Rate Limit Config: `/home/naji/code/nba-stats-scraper/shared/config/rate_limit_config.py`
- Scraper Base: `/home/naji/code/nba-stats-scraper/scrapers/scraper_base.py`

---

## Checklist Summary

**Investigation Steps:**
- [ ] Step 1: Check scraper logs (10 min)
- [ ] Step 2: Review scraper code (15 min)
- [ ] Step 3: Test BDL API directly (10 min)
- [ ] Step 4: Compare data sources (10 min)
- [ ] Step 5: Check processing pipeline (10 min)
- [ ] Step 6: Analyze game metadata (5 min)

**Total Time:** ~60 minutes

**Outcome:**
- [ ] Root cause identified
- [ ] Fix implemented
- [ ] Missing games backfilled
- [ ] Monitoring added
- [ ] Documentation updated

---

**Created:** January 21, 2026, 4:25 PM PST
**Status:** READY FOR INVESTIGATION
**Priority:** HIGH
