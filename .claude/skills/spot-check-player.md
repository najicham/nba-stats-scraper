# /spot-check-player - Player Game History Verification

Spot-check a player's recent game history to verify injury flags, DNP records, and identify data gaps.

## When to Use

- Verify injury flags are being captured from NBA.com
- Investigate why a player is missing from certain games
- Check for data quality issues before they affect predictions
- Validate the "last 10 games" display on the website

## Usage

```
/spot-check-player <player_lookup> [num_games]
```

Examples:
- `/spot-check-player lebron_james` - Check LeBron's last 10 games
- `/spot-check-player anthony_davis 20` - Check AD's last 20 games

## What This Skill Does

### 1. Get Player's Recent Games

Query `player_game_summary` for the player's actual game records:

```sql
SELECT
    game_date,
    team_abbr,
    opponent_team_abbr,
    points,
    minutes_played,
    is_active,
    player_status,
    primary_source_used
FROM nba_analytics.player_game_summary
WHERE player_lookup = @player_lookup
ORDER BY game_date DESC
LIMIT @num_games
```

### 2. Find Team's Scheduled Games

Get all games the player's team played in the same period:

```sql
WITH player_team AS (
    SELECT team_abbr
    FROM nba_analytics.player_game_summary
    WHERE player_lookup = @player_lookup
    ORDER BY game_date DESC
    LIMIT 1
),
team_games AS (
    SELECT DISTINCT game_date, game_id
    FROM nba_raw.v_nbac_schedule_latest
    WHERE (home_team_tricode = (SELECT team_abbr FROM player_team)
       OR away_team_tricode = (SELECT team_abbr FROM player_team))
      AND game_status = 3  -- Completed games
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    ORDER BY game_date DESC
    LIMIT @num_games * 2
)
SELECT * FROM team_games
```

### 3. Check Missing Games

For each team game where the player has NO record in `player_game_summary`:

**Step A: Check Injury Reports**
```sql
SELECT
    'nbac' as source,
    game_date,
    injury_status,
    reason,
    reason_category
FROM nba_raw.nbac_injury_report
WHERE player_lookup = @player_lookup
  AND game_date = @missing_date
QUALIFY ROW_NUMBER() OVER (ORDER BY report_hour DESC) = 1

UNION ALL

SELECT
    'bdl' as source,
    scrape_date as game_date,
    injury_status_normalized as injury_status,
    injury_description as reason,
    reason_category
FROM nba_raw.bdl_injuries
WHERE player_lookup = @player_lookup
  AND scrape_date = @missing_date
QUALIFY ROW_NUMBER() OVER (ORDER BY scrape_timestamp DESC) = 1
```

**Step B: Check Raw Boxscores**
```sql
-- Did they appear in raw boxscores with 0 minutes (DNP)?
SELECT
    game_date,
    player_lookup,
    minutes,
    team_abbr
FROM nba_raw.bdl_player_boxscores
WHERE player_lookup = @player_lookup
  AND game_date = @missing_date
```

**Step C: Check for Roster Changes**
```sql
-- Look for team changes in the period
SELECT DISTINCT team_abbr, MIN(game_date) as first_game
FROM nba_analytics.player_game_summary
WHERE player_lookup = @player_lookup
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY team_abbr
ORDER BY first_game DESC
```

### 4. Generate Report

Produce a summary like:

```
=== PLAYER SPOT CHECK: LeBron James ===
Team: LAL
Period: Last 10 games (2026-01-16 to 2026-01-26)

GAME HISTORY:
| Date       | Opp | Pts | Min  | Status | Injury Flag |
|------------|-----|-----|------|--------|-------------|
| 2026-01-26 | GSW | 28  | 35.2 | active | -           |
| 2026-01-24 | PHX | 31  | 36.1 | active | -           |
| 2026-01-22 | -   | -   | -    | OUT    | Knee (rest) |  <-- INJURY FLAGGED
| 2026-01-20 | DEN | 25  | 33.5 | active | -           |
...

MISSING GAME ANALYSIS:
- 2026-01-22 vs BOS: Player listed OUT (Knee - rest) in nbac_injury_report
  Status: EXPECTED - Injury properly flagged

POTENTIAL ISSUES:
- None found

DATA QUALITY:
- 9/10 games have records
- 1/10 games missing (injury - expected)
- Injury coverage: 100% (all absences have injury report)
```

## Scenarios to Detect

### 1. EXPECTED - Injury Flagged
Player missing from `player_game_summary` BUT has injury report entry.
**Status**: Working as expected.

### 2. WARNING - DNP Without Injury Flag
Player has 0 minutes in `bdl_player_boxscores` but NO injury report.
**Status**: May be missing injury data. Check if NBA.com source is being used.

### 3. ERROR - Data Gap
Player's team played, player NOT in injury report, player NOT in raw boxscores.
**Status**: Likely data collection issue. Check scrapers.

### 4. INFO - Trade/Roster Change
Player changed teams recently. Missing games may be due to trade window.
**Status**: Normal for mid-season acquisitions.

### 5. WARNING - Inconsistent Sources
Player has injury status in BDL but NOT in NBA.com (or vice versa).
**Status**: May indicate NBA.com scraper issue since that's our primary source.

## Implementation Notes

1. Use normalized `player_lookup` for all queries
2. Query both `nbac_injury_report` and `bdl_injuries` for cross-validation
3. Check `bdl_player_boxscores` for 0-minute entries (DNP confirmation)
4. Look for team changes to explain gaps during trade periods
5. Always show which data source was used for each record

## Success Criteria

After running this check, you should know:
- Whether all absences are properly explained (injury, trade, etc.)
- Whether injury flags from NBA.com are being captured
- Whether there are any unexplained data gaps to investigate
