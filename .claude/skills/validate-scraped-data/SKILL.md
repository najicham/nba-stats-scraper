---
name: validate-scraped-data
description: Validate scraped betting/odds data coverage against game schedule
---

# /validate-scraped-data - Scraped Data Coverage Audit

Audit betting/odds data coverage to identify gaps that need backfilling from historical APIs.

**Related skills**: See `/validate-historical` for processed data validation.

## When to Use

- Before ML model training (ensure training data is complete)
- After deploying new scrapers
- Periodic data completeness audits
- Before starting a backfill job (identify scope)
- When investigating missing odds data

## Usage

```
/validate-scraped-data [start_date] [end_date]
/validate-scraped-data --season 2025-26
```

Examples:
- `/validate-scraped-data` - Check current season (Oct to today)
- `/validate-scraped-data 2025-10-01 2025-12-31` - Specific date range
- `/validate-scraped-data --season 2024-25` - Last season

## What This Skill Does

### Step 1: Parse Date Range

Determine start and end dates:
- No params: Current season (Oct 1 of current season year to today)
- Two dates: Explicit range
- `--season YYYY-YY`: That season's dates

### Step 2: Check GCS Raw Data

Check what raw data exists in GCS (scraped but maybe not processed):

```bash
# Game lines
gcloud storage ls "gs://nba-scraped-data/odds-api/game-lines/" | grep "2025-"

# Player props
gcloud storage ls "gs://nba-scraped-data/odds-api/player-props/" | grep "2025-"

# BettingPros
gcloud storage ls "gs://nba-scraped-data/bettingpros/" | grep "2025-"
```

This distinguishes between:
- **In GCS but not in BQ**: Need to run processor (no scraping needed)
- **Not in GCS**: Need to scrape from API first, then process

### Step 3: Get Schedule Baseline

Query actual games played:

```sql
SELECT
    game_date,
    COUNT(*) as scheduled_games,
    COUNT(DISTINCT CONCAT(away_team_tricode, '_', home_team_tricode)) as unique_matchups
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_date BETWEEN @start_date AND @end_date
  AND game_status_text = 'Final'
GROUP BY game_date
ORDER BY game_date
```

### Step 3: Check Odds API Player Props Coverage

```sql
SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_with_props,
    COUNT(DISTINCT CASE WHEN LOWER(bookmaker) = 'draftkings' THEN player_lookup END) as dk_players,
    COUNT(DISTINCT CASE WHEN LOWER(bookmaker) = 'fanduel' THEN player_lookup END) as fd_players,
    COUNT(*) as total_records
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
```

### Step 4: Check BettingPros Player Props Coverage

```sql
SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_with_props,
    COUNT(DISTINCT CASE WHEN bookmaker = 'DraftKings' THEN player_lookup END) as dk_players,
    COUNT(DISTINCT CASE WHEN bookmaker = 'FanDuel' THEN player_lookup END) as fd_players,
    COUNT(DISTINCT CASE WHEN bookmaker = 'BettingPros Consensus' THEN player_lookup END) as consensus_players,
    COUNT(*) as total_records
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date BETWEEN @start_date AND @end_date
  AND market_type = 'points'
  AND bet_side = 'over'
GROUP BY game_date
```

### Step 5: Check Game Lines Coverage

```sql
SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_with_lines,
    COUNT(DISTINCT CASE WHEN market_key = 'spreads' THEN game_id END) as games_with_spreads,
    COUNT(DISTINCT CASE WHEN market_key = 'totals' THEN game_id END) as games_with_totals,
    COUNT(*) as total_records
FROM `nba-props-platform.nba_raw.odds_api_game_lines`
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
```

### Step 6: Generate Gap Analysis Report

```
=== SCRAPED DATA COVERAGE AUDIT ===
Period: 2025-10-01 to 2026-01-31
Project: nba-props-platform

SCHEDULE BASELINE:
- Total game days: 101
- Total games played: 728

=== PLAYER PROPS COVERAGE ===

ODDS API PROPS:
| Month    | Game Days | Days w/Data | Coverage | Avg Players/Day |
|----------|-----------|-------------|----------|-----------------|
| 2025-10  |        11 |          11 |    100%  |             230 |
| 2025-11  |        29 |          29 |    100%  |             285 |
| 2025-12  |        30 |          30 |    100%  |             280 |
| 2026-01  |        31 |          30 |     97%  |             320 |

Missing dates: 2026-01-31

BETTINGPROS PROPS:
| Month    | Game Days | Days w/Data | Coverage | Avg Players/Day |
|----------|-----------|-------------|----------|-----------------|
| 2025-10  |        11 |          10 |     91%  |             275 |
| 2025-11  |        29 |          28 |     97%  |             340 |
| 2025-12  |        30 |          30 |    100%  |             345 |
| 2026-01  |        31 |          28 |     90%  |             350 |

Missing dates: 2025-10-22, 2025-11-03, 2026-01-29, 2026-01-30, 2026-01-31

=== GAME LINES COVERAGE ===

| Month    | Schedule Games | Games w/Spreads | Games w/Totals | Coverage |
|----------|----------------|-----------------|----------------|----------|
| 2025-10  |             80 |               1 |              1 |     1.3% |  << CRITICAL
| 2025-11  |            219 |               0 |              0 |     0.0% |  << CRITICAL
| 2025-12  |            198 |             197 |            197 |    99.5% |
| 2026-01  |            231 |             163 |            163 |    70.6% |

CRITICAL GAPS FOUND:
1. Game lines missing Oct 2025: 79 games (98.7%)
2. Game lines missing Nov 2025: 219 games (100%)
3. Game lines partial Jan 2026: 68 games (29.4%)

=== GCS vs BIGQUERY COMPARISON ===

| Date Range | GCS Status | BigQuery Status | Action Needed |
|------------|------------|-----------------|---------------|
| Oct 22-31  | NOT SCRAPED | Missing | Scrape from historical API |
| Nov 1-13   | NOT SCRAPED | Missing | Scrape from historical API |
| Nov 14-30  | HAS DATA    | MISSING | Process GCS → BQ only |
| Dec 2025   | Has data    | OK (99.5%) | None |
| Jan 2026   | Has data    | Partial (70.6%) | Check recent |

=== BACKFILL RECOMMENDATIONS ===

Priority 1: Process GCS → BQ (NO SCRAPING NEEDED)
- Nov 14-30 game lines are in GCS but not in BigQuery
- Run: `python data_processors/raw/odds_api_game_lines_processor.py --start 2025-11-14 --end 2025-11-30`

Priority 2: Scrape Missing Dates (NEED HISTORICAL API)
- Oct 2025: Run oddsa_game_lines_his for 2025-10-22 to 2025-10-31
- Nov 1-13: Run oddsa_game_lines_his for 2025-11-01 to 2025-11-13

Priority 3: BettingPros Props (WARNING - NO HISTORICAL API)
- BettingPros has no historical API - can only scrape real-time
- Oct-Nov 2025 data may be unrecoverable

Priority 4: Odds API Props
- Mostly complete, verify 2026-01-31 when games complete

=== HISTORICAL API NOTES ===

Odds API Historical Endpoint Constraints:
- Events disappear from API when games start
- Safe to request: Within 5-10 min of discovery timestamp
- Max lookback: Check API documentation (typically 90 days)
- Cost: Historical API calls may count against quota

Backfill Command Example:
```bash
# For game lines
PYTHONPATH=. python scrapers/oddsapi/oddsa_game_lines_his.py \
    --start-date 2025-10-22 --end-date 2025-10-31
```
```

## Thresholds

| Data Type | Good | Warning | Critical |
|-----------|------|---------|----------|
| Player props (either source) | ≥95% | 80-94% | <80% |
| Game lines (spreads) | ≥90% | 70-89% | <70% |
| Game lines (totals) | ≥90% | 70-89% | <70% |

## Data Sources

### Odds API Tables
- `nba_raw.odds_api_player_points_props` - Player point props
- `nba_raw.odds_api_game_lines` - Game spreads and totals
- Bookmakers: `draftkings`, `fanduel` (lowercase)

### BettingPros Tables
- `nba_raw.bettingpros_player_points_props` - Player props (all markets)
- **IMPORTANT**: Filter by `market_type = 'points'` and `bet_side = 'over'`
- Bookmakers: `DraftKings`, `FanDuel`, `BettingPros Consensus` (mixed case)

### Schedule Reference
- `nba_raw.nbac_schedule` - Game schedule
- Filter: `game_status_text = 'Final'` for completed games

## Common Issues

### Game Lines Missing for Date Range
**Cause**: Scraper not running or API issues during that period
**Fix**: Run historical backfill scraper for missing dates
**Verify**: Check if Odds API historical endpoint has data for those dates

### BettingPros Props Missing
**Cause**: Website changes, scraper issues, or data not published
**Fix**: Re-run bp_player_props scraper for specific dates
**Note**: BettingPros doesn't have a historical API - must scrape in real-time

### Inconsistent Bookmaker Coverage
**Cause**: Some books don't offer props for all players
**Note**: This is expected - cascade handles fallback to other books

## Integration with Other Skills

| Skill | When to Use |
|-------|-------------|
| `/validate-scraped-data` | Find missing raw odds data |
| `/validate-historical` | Check processed data quality |
| `/spot-check-cascade` | Trace how missing data affects predictions |

## Workflow: After Finding Gaps

```
1. Run /validate-scraped-data      → Identify missing data
2. Check historical API availability → Can we backfill?
3. Run backfill scrapers           → oddsa_game_lines_his, etc.
4. Verify backfill success         → Re-run /validate-scraped-data
5. Reprocess Phase 3               → Regenerate upcoming_player_game_context
6. Verify downstream               → Run /validate-historical
```

## Implementation Notes

When implementing this skill:

1. **Always compare to schedule**: Use actual games played, not calendar days
2. **Handle preseason**: Oct often has preseason games - filter if needed
3. **Multiple sources**: Check both Odds API and BettingPros for props
4. **Bookmaker breakdown**: Show DraftKings vs FanDuel coverage separately
5. **Actionable output**: Include specific backfill commands

## Success Criteria

After running this skill, you should know:
- [ ] Which dates have complete odds data
- [ ] Which dates are missing player props (and from which source)
- [ ] Which dates are missing game lines (spreads/totals)
- [ ] Whether historical API can fill the gaps
- [ ] Specific backfill commands to run
- [ ] Priority order for backfills
