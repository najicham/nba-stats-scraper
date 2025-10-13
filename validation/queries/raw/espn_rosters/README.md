# ESPN Team Rosters Validation Queries

**File: validation/queries/raw/espn_rosters/README.md**

## Data Source Overview

**Table:** `nba-props-platform.nba_raw.espn_team_rosters`  
**Purpose:** Backup validation source for player roster data  
**Coverage:** Limited (2 dates as of Oct 2025)  
**Update Frequency:** Daily at 8 AM PT  
**Business Role:** Backup when NBA.com or Ball Don't Lie unavailable  
**⚠️ PARTITION REQUIRED:** All queries must include `roster_date >= 'YYYY-MM-DD'` filter

## Actual Coverage

```
Date Range: 2025-08-22 to 2025-10-03 (2 dates)
Total Records: 623 player records
Teams: 30 (complete league coverage)
Players: 606 unique players
Scrape Hour: 8 AM PT only
```

**⚠️ IMPORTANT:** This is a backup data source with minimal historical data, NOT a primary source with multi-season coverage.

## Available Queries

### Daily Monitoring (Run These Daily)

1. **daily_freshness_check.sql** - Did we get yesterday's roster update?
   - Run: Every morning at 10 AM
   - Alert: If status != "✅ Complete"
   - Purpose: Ensures daily scraper executed successfully

2. **team_coverage_check.sql** - Are all 30 teams present?
   - Run: Daily or after data issues
   - Expected: 30 teams with 15-23 players each
   - Purpose: Detects partial scraper failures

3. **cross_validate_with_nbac.sql** - Compare with NBA.com (primary source)
   - Run: Daily or weekly
   - Expected: >90% match rate
   - Purpose: Identifies timing differences and potential trades

### Analysis Queries

4. **player_count_distribution.sql** - Roster size patterns
   - Run: Ad-hoc for analysis
   - Shows: Distribution of team roster sizes
   - Purpose: Understanding normal roster patterns

## Quick Start

```bash
# Daily morning check (most important!)
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/daily_freshness_check.sql

# Team coverage verification
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/team_coverage_check.sql

# Cross-source validation
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/cross_validate_with_nbac.sql
```

## Expected Results

### Normal Patterns
- ✅ All 30 teams present daily
- ✅ 15-23 players per team
- ✅ >90% match with NBA.com Player List
- ✅ Single scrape per day at 8 AM PT

### Alert Conditions
- 🔴 Missing teams (< 30 teams)
- 🔴 No data collected (<450 total players)
- 🟡 Low player counts (<15 per team)
- ⚠️ Team mismatches with NBA.com (possible trades)

## Data Quality Notes

1. **Backup Source Only:** ESPN rosters are NOT the primary data source
2. **Primary Sources:** NBA.com Player List, Ball Don't Lie Active Players
3. **Use Case:** Validate when primary sources unavailable
4. **Timing Differences:** ESPN may update at different times than NBA.com
5. **Trade Timing:** Mismatches often due to trade announcement timing

## Troubleshooting

### Partition filter error
**Error:** "Cannot query over table without a filter over column(s) 'roster_date'"

**Solution:** All queries must include a roster_date filter for partition elimination:
```sql
WHERE roster_date >= '2025-01-01'  -- Required!
```

This is a BigQuery requirement for partitioned tables. Use a date range that covers your data.

### No data for yesterday
- Check if scraper ran (should run at 8 AM PT)
- Verify GCS bucket has new files: `gs://nba-scraped-data/espn/rosters/`
- Check processor logs for errors

### Missing teams
- Partial scraper failure
- Check error logs for specific teams
- May need to re-run scraper for missing teams

### Team mismatches with NBA.com
- Usually timing differences (ESPN faster/slower than NBA.com)
- Recent trades may appear in one source first
- Cross-check NBA.com Player Movement table for trade confirmation

### Player count anomalies
- <15 players: Verify team hasn't been hit by major injuries
- >23 players: Training camp invites or exhibit 10 contracts
- Compare with NBA.com Player List for verification

## Integration with Other Validation

ESPN rosters work in concert with:
- **NBA.com Player List** - Primary current roster source
- **Ball Don't Lie Active Players** - Secondary validation
- **NBA.com Player Movement** - Trade tracking
- **Basketball Reference Rosters** - Historical seasonal rosters

## Discovery Queries Used

The following discovery queries were run to understand the data:

```sql
-- 1. Actual date range
SELECT MIN(roster_date), MAX(roster_date), COUNT(*) 
FROM nba_raw.espn_team_rosters;

-- 2. Team coverage
SELECT team_abbr, COUNT(*) 
FROM nba_raw.espn_team_rosters 
GROUP BY team_abbr;

-- 3. Scrape hour patterns
SELECT scrape_hour, COUNT(*) 
FROM nba_raw.espn_team_rosters 
GROUP BY scrape_hour;
```

## Future Enhancements

When ESPN rosters become a more comprehensive source:
- Add season completeness queries (if multi-season data collected)
- Create historical comparison queries
- Build CLI tool for automated validation

---

**Last Updated:** October 13, 2025  
**Pattern:** Time-Series (Current State Only)  
**Status:** Production Ready - Backup Source