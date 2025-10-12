# Ball Don't Lie Box Scores Validation Queries

Complete validation query suite for BDL player box scores data.

## 📋 Query Overview

| Query | Purpose | Frequency | Severity |
|-------|---------|-----------|----------|
| `season_completeness_check.sql` | Verify all games/teams present | After backfill | CRITICAL |
| `find_missing_games.sql` | Identify specific missing games | When <82 games found | CRITICAL |
| `cross_validate_with_gamebook.sql` | Compare BDL vs NBA.com stats | Weekly | HIGH |
| `verify_playoff_completeness.sql` | Validate playoff game coverage | Post-season | HIGH |
| `daily_check_yesterday.sql` | Verify yesterday's games loaded | Daily (9 AM) | CRITICAL |
| `weekly_check_last_7_days.sql` | Weekly coverage trends | Weekly (Monday) | MEDIUM |
| `realtime_scraper_check.sql` | Monitor today's live games | During games | HIGH |

---

## 🎯 Quick Start

### Daily Monitoring
```bash
# Morning check (9 AM) - Did yesterday's games load?
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

### After Backfill
```bash
# 1. Check season completeness
bq query --use_legacy_sql=false < season_completeness_check.sql

# 2. If teams show <82 games, find specific missing games
bq query --use_legacy_sql=false < find_missing_games.sql
```

### Weekly Quality Check
```bash
# Monday morning routine
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql
bq query --use_legacy_sql=false < cross_validate_with_gamebook.sql
```

---

## 📊 Query Details

### 1. Season Completeness Check
**File:** `season_completeness_check.sql`  
**Purpose:** Comprehensive season validation with player statistics

**Output Columns:**
- `season` - NBA season (2023-24, etc.)
- `team` - Team abbreviation
- `reg_games` - Regular season games (target: 82)
- `playoff_games` - Playoff games (varies by team)
- `unique_players` - Total players used in season
- `avg_players` - Average players per game (~30-35)
- `min_players` - Minimum players in any game (>= 20)
- `max_players` - Maximum players in any game (<= 40)

**Expected Results:**
- ✅ DIAGNOSTICS row: All zeros (no join failures)
- ✅ Regular season: 82 games per team
- ✅ Playoffs: Varies (4-28 games depending on performance)
- ✅ Player counts: 25-35 average per game

**When to Run:** After backfills, monthly during season

---

### 2. Find Missing Games
**File:** `find_missing_games.sql`  
**Purpose:** Identify specific games missing from BDL

**When to Use:**
- Season completeness shows teams with <82 games
- After scraper failures
- Creating backfill lists

**Instructions:**
1. Update date range for season (lines 17-18)
2. Run query
3. Export results to create scraper backfill dates

**Output:** List of games with `MISSING FROM BDL BOX SCORES` status

---

### 3. Cross-Validate with Gamebook
**File:** `cross_validate_with_gamebook.sql`  
**Purpose:** Compare BDL stats with NBA.com official data

**Checks:**
- Players missing from either source
- Point discrepancies (> 2 points = critical)
- Assist/rebound discrepancies (> 2 = warning)

**Output Columns:**
- `presence_status` - "in_both", "missing_from_bdl", "missing_from_gamebook"
- `point_diff`, `assist_diff`, `rebound_diff` - Statistical differences
- `issue_severity` - 🔴 CRITICAL, 🟡 WARNING, ✅ Match

**Expected Results:**
- Empty or minimal results = data sources agree
- Point discrepancies = investigate data quality

**When to Run:** Weekly, after major backfills

---

### 4. Verify Playoff Completeness
**File:** `verify_playoff_completeness.sql`  
**Purpose:** Dynamic playoff validation using schedule as source of truth

**Key Features:**
- Auto-detects expected playoff games from schedule
- No hardcoded game counts (adapts to actual playoff results)
- Validates all playoff rounds (Play-In → Finals)

**Output:**
- `expected_games` - From schedule (source of truth)
- `actual_games` - Found in BDL
- `status` - ✅ Complete, ⚠️ Incomplete, ❌ All Missing

**Instructions:**
1. Update playoff date range (line 17)
2. Run after playoff games complete
3. All teams should show "✅ Complete"

---

### 5. Daily Check Yesterday
**File:** `daily_check_yesterday.sql`  
**Purpose:** Automated daily monitoring

**Schedule:** Run daily at 9 AM (after overnight processing)

**Checks:**
- Games captured vs scheduled
- Total player records
- Average players per game
- Minimum players (>= 20 sanity check)

**Status Codes:**
- ✅ Complete - All games captured
- ✅ No games scheduled - Off day
- ❌ CRITICAL - No data at all
- ⚠️ WARNING - Missing games or low player counts

**Alert Thresholds:**
- Missing any games = alert
- Min players < 20 = alert
- Zero games when games scheduled = critical alert

---

### 6. Weekly Check Last 7 Days
**File:** `weekly_check_last_7_days.sql`  
**Purpose:** Trend analysis over past week

**Output:**
- Daily game counts (scheduled vs captured)
- Player statistics per day
- Status indicators for each day

**Use Cases:**
- Identify patterns (e.g., Sundays always missing)
- Verify scraper consistency
- Generate weekly reports

**When to Run:** Monday mornings for previous week review

---

### 7. Real-time Scraper Check
**File:** `realtime_scraper_check.sql`  
**Purpose:** Monitor today's games as they complete

**Best Time:** 11 PM - 1 AM ET (after games finish)

**Output:**
- Game state (completed, in_progress, scheduled)
- Player counts for each game
- Data availability status
- Recommendations for action

**Status Indicators:**
- ✅ Data captured - Completed games with full data
- 🔵 Live data available - In-progress games
- ❌ CRITICAL - Completed games without data
- ⚪ Normal states - Scheduled/in-progress without data

**Recommendations:**
- "Run scraper immediately" = completed game missing data
- "Check scraper logs" = incomplete data detected
- "No action needed" = normal state

---

## 🚨 Common Issues & Solutions

### Issue: Teams show <82 games
**Solution:**
1. Run `find_missing_games.sql` to identify specific dates
2. Check GCS for missing scraper files
3. Re-run scraper for missing dates
4. Re-run processor for those dates

### Issue: Low player counts (<20 per game)
**Solution:**
1. Check `cross_validate_with_gamebook.sql` for discrepancies
2. Verify scraper captured full game data
3. Check processor logs for parsing errors
4. Compare with NBA.com gamebook as source of truth

### Issue: Point discrepancies with gamebook
**Solution:**
1. Review `cross_validate_with_gamebook.sql` results
2. Check if discrepancy is systematic (all games) or isolated
3. Verify BDL API hasn't changed response format
4. Re-scrape and re-process affected games

### Issue: Missing playoff games
**Solution:**
1. Run `verify_playoff_completeness.sql`
2. Confirm scraper ran for playoff dates (April-June)
3. Check if scraper excludes playoffs (should include!)
4. Backfill missing playoff dates

---

## 🔄 Validation Workflow

### Initial Backfill
```bash
# 1. Run season completeness
bq query --use_legacy_sql=false < season_completeness_check.sql

# 2. If issues found, identify missing games
bq query --use_legacy_sql=false < find_missing_games.sql

# 3. After fixes, verify playoffs
bq query --use_legacy_sql=false < verify_playoff_completeness.sql

# 4. Cross-validate with official source
bq query --use_legacy_sql=false < cross_validate_with_gamebook.sql
```

### Daily Production
```bash
# Morning (9 AM)
bq query --use_legacy_sql=false < daily_check_yesterday.sql

# Alert if not "✅ Complete"
```

### Weekly Review
```bash
# Monday morning
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql
bq query --use_legacy_sql=false < cross_validate_with_gamebook.sql
```

---

## 📝 Updating Queries for New Seasons

When a new season starts, update these date ranges:

### Season Completeness Check
```sql
-- Line 24-27: Add new season
WHEN b.game_date BETWEEN '2025-10-21' AND '2026-06-20' THEN '2025-26'
```

### Find Missing Games
```sql
-- Lines 17-18: Update for season being checked
WHERE s.game_date BETWEEN '2025-10-21' AND '2026-04-20'
```

### Verify Playoff Completeness
```sql
-- Line 17: Update playoff period
WHERE game_date BETWEEN '2025-04-19' AND '2025-06-20'
```

---

## 🎯 Success Criteria

### ✅ Healthy System
- Season completeness: All teams 82/82 regular season
- Daily check: "✅ Complete" every game day
- Weekly check: All days ✅ or ⚪ (no games)
- Cross-validation: Zero or minimal point discrepancies
- Playoff verification: All playoff teams ✅ Complete

### ⚠️ Needs Attention
- Teams with 80-81 games (investigate specific dates)
- Point discrepancies 1-2 points (monitor, may be OK)
- Occasional daily check warnings (transient issues)

### ❌ Critical Issues
- Teams with <80 games (systematic scraper failure)
- Point discrepancies >2 points (data quality issue)
- Multiple consecutive daily check failures (scraper down)
- Missing playoff games (revenue-impacting)

---

## 🔗 Related Documentation

- **Processor Reference:** `NBA Processors Reference Documentation` (section 7)
- **Schema:** `schemas/bigquery/bdl_tables.sql`
- **Validator Config:** `validation/configs/raw/bdl_boxscores.yaml`
- **Validator Code:** `validation/validators/raw/bdl_boxscores_validator.py`

---

**Last Updated:** 2025-10-12  
**Query Version:** 1.0  
**Data Source:** Ball Don't Lie API  
**Coverage:** 2021-22 through 2024-25 seasons
