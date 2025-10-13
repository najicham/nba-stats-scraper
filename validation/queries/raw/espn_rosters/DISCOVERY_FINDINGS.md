# ESPN Team Rosters - Discovery Findings

**File: validation/queries/raw/espn_rosters/DISCOVERY_FINDINGS.md**

**Discovery Date:** October 13, 2025  
**Table:** `nba-props-platform.nba_raw.espn_team_rosters`

---

## Summary

ESPN Team Rosters is a **backup data source** with minimal historical data. Not suitable for multi-season validation.

## Discovery Query Results

### Query 1: Actual Date Range

```
Earliest Date:       2025-08-22
Latest Date:         2025-10-03
Total Dates:         2
Total Records:       623
Unique Teams:        30
Unique Players:      606
Unique Scrape Hours: 1 (8 AM PT)
```

### Query 2: Record Volume by Date

```
Date         | Records | Teams | Players | Day
-------------|---------|-------|---------|--------
2025-10-03   | 606     | 30    | 606     | Friday
2025-08-22   | 17      | 1     | 17      | Friday
```

**Key Finding:** Oct 3 shows complete league coverage (all 30 teams), Aug 22 was a single-team test.

### Query 3: Team Coverage

```
All 30 NBA teams represented on 2025-10-03
Memphis Grizzlies: 2 dates (test + production)
Other 29 teams: 1 date each (2025-10-03 only)

Player Count Range: 17-23 players per team
Average: ~20 players per team
```

### Query 4: Scrape Hour Pattern

```
Scrape Hour | Dates | Teams | Records
------------|-------|-------|--------
8 AM PT     | 2     | 30    | 623
```

**Key Finding:** Single daily scrape at 8 AM PT. No intraday updates.

---

## Pattern Classification

**Pattern:** Time-Series (Current State Only)  
**Similar To:** NBA.com Player List, Ball Don't Lie Active Players

**NOT Pattern 3 (Game-Based)** because:
- No game-level granularity
- Current state snapshots only
- No historical seasonal data

---

## Coverage Assessment

### What We Have ✅
- Complete 30-team coverage as of Oct 3, 2025
- 606 unique players (near-complete league roster)
- Clean daily scrape schedule (8 AM PT)
- Proper team mapping (standard abbreviations)

### What We DON'T Have ❌
- Historical data (only 2 dates exist)
- Multi-season coverage (no 2021-2024 data)
- Intraday roster updates
- Historical roster changes over time

---

## Validation Strategy

### ✅ Queries to Create
1. **daily_freshness_check.sql** - Monitor daily scraper
2. **team_coverage_check.sql** - Ensure all 30 teams
3. **cross_validate_with_nbac.sql** - Compare with primary source
4. **player_count_distribution.sql** - Roster size analysis

### ❌ Queries NOT Applicable
- ~~season_completeness_check.sql~~ - No historical seasons
- ~~find_missing_regular_season_games.sql~~ - Not game-based
- ~~verify_playoff_completeness.sql~~ - Not game-based
- ~~weekly_check_last_7_days.sql~~ - Only 2 dates exist

---

## Business Context

### Primary Use Case
**Backup validation** when NBA.com Player List or Ball Don't Lie Active Players are unavailable.

### Data Hierarchy
1. **Primary:** NBA.com Player List (nba_raw.nbac_player_list_current)
2. **Secondary:** Ball Don't Lie Active Players (nba_raw.bdl_active_players_current)
3. **Backup:** ESPN Team Rosters (nba_raw.espn_team_rosters) ← This source

### Expected Validation Results
- 90%+ match rate with NBA.com Player List
- Team mismatches indicate timing differences (trades)
- Player-only mismatches indicate G-League/two-way movements

---

## Key Insights

1. **Limited Scope:** This is intentionally a backup source, not comprehensive
2. **Recent Implementation:** Processor deployed Sept 3, 2025 (very new)
3. **Test Period:** Aug 22 was single-team validation (Memphis)
4. **Production Start:** Oct 3, 2025 full league coverage
5. **No Backfill Plan:** Historical data not collected (by design)

---

## Recommendations

### Immediate
1. ✅ Create daily monitoring queries (freshness, coverage)
2. ✅ Set up automated daily validation at 10 AM PT
3. ✅ Create cross-validation with NBA.com Player List
4. ⚠️ Alert on <30 teams or <450 total players

### Future (If ESPN Becomes Primary Source)
- Expand to historical collection
- Add season completeness validation
- Build comprehensive CLI tool
- Implement historical comparison queries

---

## Date Ranges for Validation

```sql
-- Use these date ranges in queries
Full Range:       '2025-08-22' to '2025-10-03'
Production Only:  '2025-10-03' to CURRENT_DATE()
Current Season:   '2024-10-22' to '2025-06-20' (2024-25 NBA season)
```

**Important:** Don't filter on 4 seasons - only 2 dates exist!

---

## Discovery Query Templates

Save these for future use:

```sql
-- Check current coverage
SELECT MAX(roster_date), COUNT(DISTINCT team_abbr)
FROM nba_raw.espn_team_rosters;

-- Team-by-team breakdown
SELECT team_abbr, COUNT(*) as players
FROM nba_raw.espn_team_rosters
WHERE roster_date = (SELECT MAX(roster_date) FROM nba_raw.espn_team_rosters)
GROUP BY team_abbr
ORDER BY players DESC;

-- Scrape timing validation
SELECT roster_date, scrape_hour, COUNT(*) 
FROM nba_raw.espn_team_rosters
GROUP BY roster_date, scrape_hour
ORDER BY roster_date DESC;
```

---

**Created By:** NBA Props Platform Team  
**Review Date:** October 13, 2025  
**Next Review:** When historical data accumulates (6+ months)
