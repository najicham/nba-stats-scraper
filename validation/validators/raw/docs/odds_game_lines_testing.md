# Odds API Game Lines Validator - Testing Guide

**Status:** ✅ Validator Complete - Ready for Testing  
**Created:** 2025-10-11  
**Data Quality Target:** 99.16% (5,216 of 5,260 games complete)

---

## 🎯 Quick Start

### Test Recent Data (Last 7 Days)
```bash
cd ~/code/nba-stats-scraper

python -m validation.validators.raw.odds_game_lines_validator \
  --last-days 7 \
  --no-notify \
  --verbose
```

**Expected:** ~3-5 games per day × 8 rows each = 168-280 rows  
**Runtime:** ~15-30 seconds

---

## 📋 Test Scenarios

### 1. Quick Smoke Test (Recent Data)
```bash
# Test last 7 days
python -m validation.validators.raw.odds_game_lines_validator \
  --last-days 7 \
  --no-notify
```

**What it checks:**
- ✅ Table accessible and partitioned correctly
- ✅ Recent data exists
- ✅ All 8 custom validations run
- ✅ Basic data quality checks pass

**Expected Result:** 14-16/16 checks passing

---

### 2. Single Month Test
```bash
# Test a complete month
python -m validation.validators.raw.odds_game_lines_validator \
  --start-date 2024-01-01 \
  --end-date 2024-01-31 \
  --no-notify
```

**What it checks:**
- ✅ Monthly data completeness
- ✅ ~120 games × 8 rows = ~960 rows
- ✅ Known incomplete games (if any in January 2024)
- ✅ Bookmaker and market coverage

**Expected Result:** 15-16/16 checks passing  
**Runtime:** ~1-2 minutes

---

### 3. Complete Season Test (2023-24)
```bash
# Test entire 2023-24 season
python -m validation.validators.raw.odds_game_lines_validator \
  --start-date 2023-10-24 \
  --end-date 2024-06-17 \
  --no-notify
```

**What it checks:**
- ✅ Full season coverage (1,313 games)
- ✅ Expected 10,458 rows
- ✅ Completeness: ~99.6%
- ✅ All data quality rules
- ✅ Known issues (Thanksgiving 2023, April 2024)

**Expected Result:** 14-16/16 checks passing (2 warnings for known incomplete games)  
**Runtime:** ~3-5 minutes

---

### 4. Full Historical Validation (All 4 Seasons)
```bash
# WARNING: This validates 41,954 rows - takes time!
python -m validation.validators.raw.odds_game_lines_validator \
  --start-date 2021-10-19 \
  --end-date 2025-03-31 \
  --no-notify
```

**What it checks:**
- ✅ All 5,260 games
- ✅ All 41,954 rows
- ✅ 4 complete seasons
- ✅ All known issues documented
- ✅ Cross-season consistency

**Expected Result:** 14-16/16 checks passing (2 warnings for 44 known incomplete games)  
**Runtime:** ~5-10 minutes

---

### 5. Known Problem Dates (Thanksgiving 2023)
```bash
# Test period with known incomplete games
python -m validation.validators.raw.odds_game_lines_validator \
  --start-date 2023-11-21 \
  --end-date 2023-11-25 \
  --no-notify
```

**What it checks:**
- ✅ Handling of incomplete games
- ✅ Games with only 4 rows (1 bookmaker)
- ✅ Proper warning severity (not error)
- ✅ Affected games listed

**Expected Result:** 13-14/16 checks passing (2-3 warnings for incomplete games)  
**Expected Warnings:**
- "Found 5 incomplete games"
- "Found 3 games with < 2 bookmakers"

---

## 📊 Expected Validation Results

### Perfect Data Period (Dec 2023)
```bash
python -m validation.validators.raw.odds_game_lines_validator \
  --start-date 2023-12-01 \
  --end-date 2023-12-31 \
  --no-notify
```

**Expected Output:**
```
✅ All validations passed!
Checks: 16/16 passed
```

**Checks that should PASS:**
1. ✅ GCS files exist
2. ✅ Row count sufficient
3. ✅ Required fields complete
4. ✅ No duplicates
5. ✅ Date range valid
6. ✅ **Game completeness** (all games have 8 rows)
7. ✅ **Bookmaker coverage** (all games have both)
8. ✅ **Market coverage** (all games have spreads + totals)
9. ✅ **Spread ranges** (all within -25 to +25)
10. ✅ **Totals ranges** (all within 180-260)
11. ✅ **Team names** (all valid NBA teams)
12. ✅ **Odds timing** (all snapshots before games)
13. ✅ Data freshness
14. ✅ Processing schedule
15. ℹ️ **Schedule cross-validation** (informational - team name matching issue)
16. ✅ Custom validations complete

---

### Known Incomplete Period (Thanksgiving 2023)
```bash
python -m validation.validators.raw.odds_game_lines_validator \
  --start-date 2023-11-23 \
  --end-date 2023-11-25 \
  --no-notify
```

**Expected Output:**
```
⚠️ Validation completed with warnings
Checks: 14/16 passed
```

**Checks that should WARN:**
- ⚠️ **Game completeness:** "Found 3 incomplete games"
- ⚠️ **Bookmaker coverage:** "Found 2 games with < 2 bookmakers"

**All other checks should PASS**

---

## 🔍 What Each Validation Checks

### 1. Game Completeness Check
**Query:** Counts rows per game, expects 8  
**Logic:** 2 bookmakers × 2 markets × 2 outcomes = 8 rows  
**Pass Criteria:** < 1% of games incomplete  
**Expected:** 5,216/5,260 games = 99.16% ✅

**Sample Output:**
```
✅ Game completeness: 5,216 games complete (99.16%)
⚠️ Found 44 incomplete games: 24 with 4 rows, 19 with 6 rows, 1 with 16 rows
```

### 2. Bookmaker Coverage Check
**Query:** Counts distinct bookmakers per game  
**Pass Criteria:** < 0.5% missing a bookmaker  
**Expected:** Most games have both DraftKings + FanDuel

**Sample Output:**
```
✅ Bookmaker coverage: 5,236 games have 2 bookmakers (99.54%)
⚠️ Found 24 games with only 1 bookmaker
```

### 3. Market Coverage Check
**Query:** Checks for spreads AND totals per game  
**Pass Criteria:** 100% have both markets  
**Expected:** All games have both

**Sample Output:**
```
✅ Market coverage: All games have both spreads and totals
```

### 4. Spread Range Validation
**Query:** Finds spreads outside -25 to +25  
**Pass Criteria:** 0 spreads outside range  
**Expected:** All spreads reasonable

**Sample Output:**
```
✅ Spread range validation: All spreads within -25 to +25 range
```

### 5. Totals Range Validation
**Query:** Finds totals outside 180-260  
**Pass Criteria:** 0 totals outside range  
**Expected:** All totals reasonable (avg ~225)

**Sample Output:**
```
✅ Totals range validation: All totals within 180-260 range
   Average total: 225.48 points
```

### 6. Team Name Validation
**Query:** Checks team names against valid NBA teams  
**Pass Criteria:** 100% valid team names  
**Expected:** All names valid (30 teams)

**Sample Output:**
```
✅ Team name validation: All team names are valid NBA teams (30 teams)
```

### 7. Odds Timing Validation
**Query:** Verifies snapshot_timestamp < commence_time  
**Pass Criteria:** 100% snapshots before game  
**Expected:** All snapshots at ~18:55:00 UTC (1-2 hours before tip)

**Sample Output:**
```
✅ Odds timing validation: All odds captured before games started
   Average lead time: 1.5 hours before tipoff
```

### 8. Schedule Cross-Validation
**Query:** Matches games with ESPN scoreboard  
**Pass Criteria:** Informational only  
**Expected:** Some mismatches due to team name differences

**Sample Output:**
```
ℹ️ Schedule cross-validation: 15 games not matched (team name normalization needed)
   Note: ESPN uses "LA Clippers" vs Odds API "Los Angeles Clippers"
```

---

## 🐛 Debugging Failed Validations

### If Game Completeness Fails:
```sql
-- Find incomplete games
SELECT 
  game_date,
  game_id,
  home_team,
  away_team,
  COUNT(*) as row_count,
  COUNT(DISTINCT bookmaker_key) as bookmakers,
  COUNT(DISTINCT market_key) as markets
FROM `nba-props-platform.nba_raw.odds_api_game_lines`
WHERE game_date >= '2024-01-01'
  AND game_date <= '2024-01-31'
GROUP BY game_date, game_id, home_team, away_team
HAVING row_count != 8
ORDER BY game_date, game_id;
```

### If Spread Range Fails:
```sql
-- Find unusual spreads
SELECT 
  game_date,
  home_team,
  away_team,
  bookmaker_key,
  outcome_name,
  outcome_point as spread
FROM `nba-props-platform.nba_raw.odds_api_game_lines`
WHERE game_date >= '2024-01-01'
  AND game_date <= '2024-01-31'
  AND market_key = 'spreads'
  AND (outcome_point < -25 OR outcome_point > 25)
ORDER BY ABS(outcome_point) DESC;
```

### If Team Names Fail:
```sql
-- Find invalid team names
SELECT DISTINCT 
  home_team,
  COUNT(*) as games
FROM `nba-props-platform.nba_raw.odds_api_game_lines`
WHERE game_date >= '2024-01-01'
GROUP BY home_team
ORDER BY home_team;
```

---

## 📈 Success Criteria

### For Full Historical Validation (2021-2025):

**Critical (Must Pass):**
- ✅ Total rows: 41,954 (within 1%)
- ✅ Unique games: 5,260
- ✅ Date coverage: 844 dates
- ✅ No null required fields
- ✅ All team names valid
- ✅ All odds before games

**Important (Can Warn):**
- ⚠️ Game completeness: >= 99% (actual: 99.16%)
- ⚠️ Bookmaker coverage: >= 99% (actual: 99.54%)
- ⚠️ Spread range: 100% within -25/+25
- ⚠️ Totals range: 100% within 180-260

**Informational:**
- ℹ️ Schedule cross-validation (team name matching)
- ℹ️ 44 known incomplete games documented

---

## 🎯 After Testing

### If All Checks Pass ✅
1. Document test results
2. Enable notifications
3. Schedule daily validations
4. Set up monitoring dashboard

### If Checks Fail ❌
1. Review specific failed checks
2. Run debug queries
3. Compare with known issues list
4. Determine if data issue or validator bug
5. Update validator if needed

---

## 🔄 Ongoing Monitoring

### Daily Validation (Recommended)
```bash
# Add to cron or Cloud Scheduler
0 2 * * * python -m validation.validators.raw.odds_game_lines_validator \
  --last-days 7 \
  --no-notify
```

### Weekly Comprehensive
```bash
# Every Monday at 3am
0 3 * * 1 python -m validation.validators.raw.odds_game_lines_validator \
  --last-days 30
```

---

## 📞 Support

**If validator fails:**
1. Check BigQuery table exists: `nba_raw.odds_api_game_lines`
2. Verify partition filter working
3. Check GCS bucket access: `gs://nba-scraped-data/odds-api/game-lines-history/`
4. Review logs in Cloud Logging
5. Contact: Data Platform Team

**Known Issues:**
- 44 incomplete games (0.84%) - acceptable
- Team name normalization needed for cross-validation
- No playoff games (historical API limitation)
- No moneyline data (only spreads + totals)

---

**Validator Version:** 1.0  
**Last Updated:** 2025-10-11  
**Data Coverage:** 2021-10-19 to 2025-03-31  
**Total Checks:** 16 (14 core + 2 informational)
