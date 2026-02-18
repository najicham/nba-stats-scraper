# /spot-check-date - Single Date Player Audit

Check all players who should have played on a specific date. Useful for investigating game days after issues are reported.

**Related skills**: See `/spot-check-overview` for workflow and when to use each skill.

## When to Use

- After receiving reports of missing player data for a game
- Daily morning validation of yesterday's games
- Investigating specific dates flagged by `/spot-check-gaps`

## Usage

```
/spot-check-date <game_date>
```

Examples:
- `/spot-check-date 2026-01-25` - Check yesterday's games
- `/spot-check-date 2025-12-25` - Check Christmas day games

## What This Skill Does

### Step 1: Get All Games on Date

```sql
SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    home_score,
    away_score
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date = @date AND game_status = 3
ORDER BY game_id
```

### Step 2: Get Expected Players per Team

For each team playing, get players who should have records (played recently for that team):

```sql
WITH recent_players AS (
    SELECT DISTINCT
        player_lookup,
        player_full_name,
        team_abbr
    FROM nba_analytics.player_game_summary
    WHERE team_abbr = @team
      AND game_date BETWEEN DATE_SUB(@date, INTERVAL 14 DAY) AND @date
)
SELECT * FROM recent_players
```

### Step 3: Check Each Player

For each expected player, verify:

```sql
SELECT
    p.player_lookup,
    p.player_full_name,
    pgs.game_date IS NOT NULL as has_analytics_record,
    pgs.points,
    pgs.minutes_played,
    ir.injury_status,
    ir.reason,
    b.minutes as boxscore_minutes
FROM expected_players p
LEFT JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND pgs.game_date = @date
LEFT JOIN nba_raw.nbac_injury_report ir
    ON p.player_lookup = ir.player_lookup AND ir.game_date = @date
LEFT JOIN nba_raw.bdl_player_boxscores b
    ON p.player_lookup = b.player_lookup AND b.game_date = @date
```

### Step 4: Generate Report

```
=== SPOT CHECK DATE: 2026-01-25 ===

GAMES ON THIS DATE:
| Game ID | Matchup     | Score     |
|---------|-------------|-----------|
| 123456  | LAL @ GSW   | 112 - 108 |
| 123457  | BOS @ MIA   | 98 - 95   |
...

GAME: LAL @ GSW
| Player          | Analytics | Boxscore | Injury | Status      |
|-----------------|-----------|----------|--------|-------------|
| LeBron James    | 28 pts    | 35 min   | -      | OK          |
| Anthony Davis   | 32 pts    | 38 min   | -      | OK          |
| D'Angelo Russell| -         | 0 min    | -      | DNP (OK)    |
| Austin Reaves   | -         | -        | OUT    | INJURY (OK) |
| [New Player]    | -         | 12 min   | -      | ERROR       |

GAME: BOS @ MIA
...

SUMMARY:
- Total players expected: 156
- With analytics records: 142
- DNP (Coach Decision): 8
- Injury (Expected): 4
- ERRORS (Need fix): 2
```

## Status Classifications

| Status | Meaning | Action |
|--------|---------|--------|
| OK | Has analytics record with stats | None |
| DNP (OK) | 0 minutes in boxscore, no injury | None (Coach decision) |
| INJURY (OK) | Has injury report entry | None (Expected) |
| ERROR | Has boxscore minutes but no analytics | Fix required |
| MISSING | Not in boxscore or injury report | Investigate roster status |

## Implementation Notes

1. Get all games for the date first
2. Build expected player list from recent games (last 14 days per team)
3. Cross-reference against analytics, injury, and boxscore tables
4. Flag any player with boxscore minutes but no analytics as ERROR
5. Group results by game for easy review

## Related Skills

| After finding issues | Use |
|---------------------|-----|
| Deep dive on one player | `/spot-check-player <name>` |
| Check if systemic | `/spot-check-gaps` |
| Check specific team | `/spot-check-team <team>` |

## Actionable Next Steps

Based on findings, take these actions:

| Finding | Severity | Next Step |
|---------|----------|-----------|
| Player with minutes but no analytics | ERROR | `/spot-check-player <name>` to investigate |
| Multiple players missing for one game | ERROR | Check if scraper failed for that game |
| All players missing for date | ERROR | Check Phase 3 processor logs |
| DNP without injury flag | INFO | Expected for bench players |
| Injury properly flagged | OK | No action needed |

## Data Limitations

- Injury data only available from Dec 19, 2025+
- For earlier dates, cannot distinguish injury from DNP
- New call-ups may not appear in "expected players" list
