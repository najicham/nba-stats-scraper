<!--
File: validation/queries/raw/bdl_standings/README.md
-->

# Ball Don't Lie Standings Validation Queries

Complete validation query suite for BDL standings data.

## 📋 Query Overview

| Query | Purpose | Frequency | Severity |
|-------|---------|-----------|----------|
| `daily_check_yesterday.sql` | Verify yesterday's standings loaded | Daily (9 AM) | CRITICAL |
| `weekly_check_last_7_days.sql` | Weekly coverage trends | Weekly (Monday) | MEDIUM |
| `season_coverage_check.sql` | Overall season date coverage | After backfill | HIGH |
| `conference_standings_check.sql` | Validate conference rankings | Weekly | HIGH |
| `data_quality_check.sql` | Win/loss math & ranking consistency | Weekly | HIGH |
| `find_missing_dates.sql` | Identify missing snapshots | When gaps found | CRITICAL |

---

## 🎯 Quick Start

### Daily Monitoring
```bash
# Morning check (9 AM) - Did yesterday's standings load?
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

### Weekly Quality Check
```bash
# Monday morning routine
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql
bq query --use_legacy_sql=false < conference_standings_check.sql
bq query --use_legacy_sql=false < data_quality_check.sql
```

### After Backfill
```bash
# 1. Check season coverage
bq query --use_legacy_sql=false < season_coverage_check.sql

# 2. If gaps found, identify specific dates
bq query --use_legacy_sql=false < find_missing_dates.sql
```

---

## 📊 Query Details

### 1. Daily Check Yesterday
**File:** `daily_check_yesterday.sql`
**Purpose:** Automated daily monitoring of standings snapshots

**Schedule:** Run daily at 9 AM (after overnight processing)

**Output Columns:**
- `check_date` - Date being validated
- `team_count` - Number of teams (expected: 30)
- `conferences` - Number of conferences (expected: 2)
- `east_teams` - Teams in Eastern Conference (expected: 15)
- `west_teams` - Teams in Western Conference (expected: 15)
- `status` - Health indicator

**Status Codes:**
- ✅ Complete - 30 teams with proper conference split
- ⚪ No data - Offseason, no standings scraped (normal June-September)
- ⚠️ WARNING - Wrong team count or conference imbalance
- 🔴 CRITICAL - No data during NBA season (October-June)

**Alert Thresholds:**
- Team count ≠ 30 during season = alert
- Conference imbalance (not 15/15) = alert
- No data during season = critical alert
- No data during offseason = expected

**When to Run:** Daily at 9 AM

---

### 2. Weekly Check Last 7 Days
**File:** `weekly_check_last_7_days.sql`
**Purpose:** Trend analysis over past week

**Output Columns:**
- `date_recorded` - Date of snapshot
- `team_count` - Teams in snapshot
- `east_teams` / `west_teams` - Conference split
- `avg_games_played` - Average games per team (trend indicator)
- `status` - Daily health indicator

**Use Cases:**
- Identify missing days
- Verify scraper consistency
- Monitor data quality trends
- Generate weekly reports

**Expected During Season:**
- Daily snapshots (7 days = 7 rows)
- Consistent 30 teams per day
- 15/15 conference split
- Increasing avg_games_played (as season progresses)

**When to Run:** Monday mornings for previous week review

---

### 3. Season Coverage Check
**File:** `season_coverage_check.sql`
**Purpose:** Comprehensive season validation by month

**Output:**
- Monthly coverage statistics
- Team presence consistency
- Conference balance tracking
- Data completeness assessment

**Key Metrics:**
- `dates_with_data` - Days with standings in month
- `avg_teams_per_day` - Should be 30.0
- `unique_teams` - Should be 30 total
- `coverage_pct` - Percentage of month covered

**Expected Results:**
- ✅ October-June: Daily coverage (100% or near)
- ⚪ July-September: Sparse/no coverage (offseason normal)
- ✅ Consistent 30 teams across all snapshots
- ✅ 15 East / 15 West teams every day

**When to Run:** After backfills, monthly during season

---

### 4. Conference Standings Check
**File:** `conference_standings_check.sql`
**Purpose:** Validate conference ranking integrity

**Checks:**
- Conference ranks are consecutive (1-15, no gaps)
- No duplicate ranks within conference
- Rankings match win/loss records
- 15 teams per conference

**Output:**
- Latest standings with validation flags
- Ranking anomalies highlighted
- Win percentage vs rank correlation

**Status Indicators:**
- ✅ Valid - Ranks 1-15, no gaps, no duplicates
- ⚠️ WARNING - Duplicate ranks or gaps detected
- 🔴 CRITICAL - Team count ≠ 15 per conference

**When to Run:** Weekly, after standings updates

---

### 5. Data Quality Check
**File:** `data_quality_check.sql`
**Purpose:** Mathematical validation of standings data

**Validates:**
- `wins + losses = games_played` ✓
- `win_percentage = wins / games_played` ✓
- Conference/division win totals ≤ overall wins ✓
- Home + road wins = total wins ✓
- Ranking order matches win percentage order ✓

**Output:**
- Teams with calculation mismatches
- Severity of discrepancies
- Affected fields

**Discrepancy Types:**
- Games played mismatch
- Win percentage calculation error
- Record string parsing failure
- Ranking inconsistency

**When to Run:** Weekly, after major backfills

---

### 6. Find Missing Dates
**File:** `find_missing_dates.sql`
**Purpose:** Identify specific dates without standings during NBA season

**Instructions:**
1. Update date range for season (lines 12-13)
2. Run query during season to find gaps
3. Export results to create scraper backfill list

**Output:**
- `missing_date` - Date without standings
- `day_of_week` - Day name
- `season_phase` - Regular season, playoffs, offseason

**Expected Gaps:**
- None during regular season (October-April)
- None during playoffs (April-June)
- Normal during offseason (June-September)

**When to Use:**
- After scraper failures
- Creating backfill plans
- Investigating data gaps

---

## 🚨 Common Issues & Solutions

### Issue: Team count ≠ 30
**Solution:**
1. Check scraper logs for that date
2. Verify Ball Don't Lie API returned all teams
3. Re-run scraper for affected date
4. Re-run processor

### Issue: Conference imbalance (not 15/15)
**Solution:**
1. Run `conference_standings_check.sql` to identify teams
2. Check if team moved conferences (rare but possible)
3. Verify team abbreviation mapping in processor
4. Check BDL API response for team conference assignments

### Issue: Missing dates during season
**Solution:**
1. Run `find_missing_dates.sql` to identify specific dates
2. Check if scraper ran for those dates
3. Check GCS for missing files
4. Re-run scraper for missing dates
5. Re-run processor

### Issue: Ranking gaps or duplicates
**Solution:**
1. Run `conference_standings_check.sql` for details
2. Verify Ball Don't Lie API ranking logic
3. Check if processor correctly parsed conference_rank
4. Re-scrape and re-process affected date

### Issue: Win/loss math doesn't add up
**Solution:**
1. Run `data_quality_check.sql` to find affected teams
2. Check if record string parsing failed (conference_record, etc.)
3. Verify Ball Don't Lie API data quality
4. Report to BDL if systematic issue
5. Re-scrape if transient issue

---

## 🔄 Validation Workflow

### Initial Backfill
```bash
# 1. Check season coverage
bq query --use_legacy_sql=false < season_coverage_check.sql

# 2. If gaps found, identify missing dates
bq query --use_legacy_sql=false < find_missing_dates.sql

# 3. Validate conference rankings
bq query --use_legacy_sql=false < conference_standings_check.sql

# 4. Check data quality
bq query --use_legacy_sql=false < data_quality_check.sql
```

### Daily Production
```bash
# Morning (9 AM)
bq query --use_legacy_sql=false < daily_check_yesterday.sql

# Alert if not "✅ Complete" (unless offseason)
```

### Weekly Review
```bash
# Monday morning
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql
bq query --use_legacy_sql=false < conference_standings_check.sql
bq query --use_legacy_sql=false < data_quality_check.sql
```

---

## 📝 Data Characteristics

### Scraper Behavior
- **Frequency:** Daily at 8 AM PT (Morning Operations workflow)
- **Coverage:** Year-round (including offseason)
- **Structure:** One snapshot per day, 30 teams per snapshot
- **Storage:** GCS path: `ball-dont-lie/standings/{season}/{date}/{timestamp}.json`

### Processing Strategy
- **Method:** MERGE_UPDATE (replaces existing data for same date)
- **Deduplication:** By (season_year, date_recorded, team_abbr)
- **Record Parsing:** Converts "W-L" strings to separate integer fields

### Expected Patterns
- **October-June (Season):** Daily snapshots, 30 teams each
- **July-September (Offseason):** Sparse snapshots, showing end-of-season final standings
- **Conference Split:** Always 15 East / 15 West
- **Rankings:** Conference ranks 1-15, Division ranks 1-5

### Current Coverage (as of Oct 2025)
- **Dates:** 2 offseason snapshots (Aug 22-24, 2025)
- **Season:** 2024-25 final standings
- **Status:** Awaiting 2025-26 season start for regular collection

---

## 🎯 Success Criteria

### ✅ Healthy System (During Season)
- Daily check: "✅ Complete" every day
- Weekly check: All 7 days present with 30 teams each
- Season coverage: 100% of season days covered
- Conference rankings: Valid (1-15, no gaps/duplicates)
- Data quality: Zero calculation mismatches

### ⚠️ Needs Attention
- 1-2 missing days in a month (investigate scraper)
- Occasional conference rank duplicates (BDL API issue)
- Minor win percentage rounding differences (<0.001)

### ❌ Critical Issues
- Multiple consecutive days missing (scraper down)
- Team count ≠ 30 (systematic issue)
- Conference imbalance ≠ 15/15 (data corruption)
- Persistent ranking gaps (API issue)
- Multiple teams with calculation errors (processor bug)

---

## 🔗 Related Documentation

- **Processor Reference:** `NBA Processors Reference Documentation` (section 10)
- **Processor Code:** `data_processors/raw/balldontlie/bdl_standings_processor.py`
- **Master Validation Guide:** `NBA_DATA_VALIDATION_MASTER_GUIDE.md`

---

## 📌 Important Notes

### Offseason Behavior
During June-September, missing days are **NORMAL**. The scraper may run but Ball Don't Lie API returns final season standings. Don't alert on missing offseason dates.

### Conference Realignment
If NBA ever realigns conferences, update expected counts in queries:
- Currently: 15 East / 15 West
- If changed: Update all conference count checks

### Ranking Ties
Teams with identical records may have same rank in Ball Don't Lie data. This is expected behavior - use tiebreaker logic if exact rankings needed.

---

**Last Updated:** 2025-10-13  
**Query Version:** 1.0  
**Data Source:** Ball Don't Lie API  
**Current Coverage:** 2024-25 season (2 offseason snapshots)  
**Expected Growth:** Daily collection October 2025 onwards
