# NBA.com Referee Assignments Validation

Validation queries for `nba_raw.nbac_referee_game_assignments` table.

## Quick Start

```bash
# Run all validation queries
cd validation/queries/raw/nbac_referee
bq query --use_legacy_sql=false < season_completeness_check.sql
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

## Data Characteristics

**Pattern:** Pattern 1 - Game-Based (Fixed Records per Game)
- **Regular Season:** 3 officials per game
- **Playoffs:** 4 officials per game
- **Coverage:** 2024-01-01 to Present (1,613 games, 4,957 assignments, 83 officials)
- **Missing:** Full 2021-22, 2022-23, most of 2023-24 seasons need backfill
- **Partition:** BY `game_date` (⚠️ REQUIRED for all queries)

## Query Files

### Core Validation Queries

1. **`season_completeness_check.sql`**
   - Validates data coverage across all seasons and teams
   - Checks for correct official counts (3 vs 4)
   - Cross-validates with schedule table
   - **Run:** After backfills or weekly for historical validation

2. **`find_missing_regular_season_games.sql`**
   - Lists specific regular season games missing referee data
   - Identifies incomplete assignments (< 3 officials)
   - **Run:** When season_completeness shows gaps

3. **`verify_playoff_completeness.sql`**
   - Verifies all playoff games have 4 officials
   - Shows playoff round and official names
   - **Run:** During/after playoffs

### Daily Monitoring Queries

4. **`daily_check_yesterday.sql`**
   - Validates yesterday's referee assignments
   - Checks for correct official counts
   - **Run:** Every morning at 9 AM (automated)

5. **`weekly_check_last_7_days.sql`**
   - Shows 7-day trend of referee data collection
   - Monitors processing timestamps
   - **Run:** Weekly or when investigating issues

6. **`realtime_scraper_check.sql`**
   - Real-time scraper health monitoring
   - Checks today's and tomorrow's games
   - **Run:** During the day to verify scraper is running

### Referee-Specific Validation

7. **`official_count_validation.sql`**
   - Identifies games with wrong number of officials
   - Shows missing or extra official assignments
   - **Run:** When investigating data quality issues

## Expected Results

### Season Completeness Check
```
DIAGNOSTICS row should show:
- null_playoff_flag = 0
- failed_join_games = 0
- games_with_wrong_count = 0

Teams should show:
- Regular season: 82/82 games per team
- Playoffs: Variable based on actual playoff performance
```

### Daily Check
```
Status values:
✅ Complete - All games have correct official counts
✅ No games scheduled - Off day
⚠️ WARNING - Some games missing or incomplete
❌ CRITICAL - No referee data captured
```

### Official Count Validation
```
Regular Season: 3 officials (positions 1, 2, 3)
Playoffs: 4 officials (positions 1, 2, 3, 4)

Any deviation = data quality issue
```

## Common Issues

### Issue: Partition Filter Required
```sql
-- ❌ FAILS
SELECT * FROM nbac_referee_game_assignments

-- ✅ WORKS
SELECT * FROM nbac_referee_game_assignments
WHERE game_date >= '2024-01-01'
```

### Issue: Missing Historical Data
**Current Coverage:** 2024-01-01 forward
**Needed:** 2021-10-19 to 2023-12-31

Solution: Run scraper for historical dates

### Issue: Wrong Official Count
- Regular season game with 4 officials
- Playoff game with 3 officials

Solution: Check source data and reprocess

## Validation Schedule

### Daily (Automated)
```bash
# 9 AM - Check yesterday's games
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

### Weekly
```bash
# Review 7-day trend
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql

# Check for any data quality issues
bq query --use_legacy_sql=false < official_count_validation.sql
```

### After Backfills
```bash
# Verify complete season coverage
bq query --use_legacy_sql=false < season_completeness_check.sql

# Check playoffs
bq query --use_legacy_sql=false < verify_playoff_completeness.sql
```

## Data Quality Rules

1. ✅ **Every scheduled game** must have referee assignments
2. ✅ **Regular season games** must have exactly 3 officials
3. ✅ **Playoff games** must have exactly 4 officials
4. ✅ **Officials** must have valid positions (1, 2, 3, 4)
5. ✅ **Game dates** must match schedule table
6. ✅ **Team abbreviations** must match schedule (home_team_tricode, away_team_tricode)

## Related Tables

- **`nba_raw.nbac_schedule`** - Source of truth for scheduled games
- **`nba_raw.nbac_referee_replay_center`** - Replay center officials by date
- **`nba_raw.nbac_scoreboard_v2`** - Game results for context

## Notes

- Referee assignments are typically published 1 day before game
- All-Star weekend may have different official counts
- Preseason games excluded from validation
- Historical data before 2024-01-01 requires backfill

---

**Last Updated:** 2025-10-13  
**Pattern:** Pattern 1 (Game-Based - Fixed Records)  
**Status:** Production Ready - Partial Historical Coverage
