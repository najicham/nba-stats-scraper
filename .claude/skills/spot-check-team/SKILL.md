# /spot-check-team - Team Roster Audit

Check all rostered players for a specific team across their recent schedule. Useful for verifying team-level data completeness.

**Related skills**: See `/spot-check-overview` for workflow and when to use each skill.

## When to Use

- After trades affecting a team's roster
- When investigating team-specific data issues
- Verifying a team's data before analysis or reports
- Checking coverage for teams with many roster moves

## Usage

```
/spot-check-team <team_abbr> [num_games]
```

Examples:
- `/spot-check-team LAL` - Check Lakers last 10 games (default)
- `/spot-check-team GSW 20` - Check Warriors last 20 games
- `/spot-check-team MIA 30` - Check Heat last 30 games (post-trade audit)

## What This Skill Does

### Step 1: Get Team's Recent Schedule

```sql
SELECT
    game_date,
    game_id,
    CASE
        WHEN home_team_tricode = @team THEN away_team_tricode
        ELSE home_team_tricode
    END as opponent,
    CASE
        WHEN home_team_tricode = @team THEN 'home' ELSE 'away'
    END as location,
    CASE
        WHEN home_team_tricode = @team THEN home_score ELSE away_score
    END as team_score
FROM nba_raw.v_nbac_schedule_latest
WHERE (home_team_tricode = @team OR away_team_tricode = @team)
  AND game_status = 3
ORDER BY game_date DESC
LIMIT @num_games
```

### Step 2: Get All Players Who've Played for Team

```sql
SELECT DISTINCT
    player_lookup,
    player_full_name,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game,
    COUNT(*) as games_played
FROM nba_analytics.player_game_summary
WHERE team_abbr = @team
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
GROUP BY player_lookup, player_full_name
ORDER BY games_played DESC
```

### Step 3: Build Completeness Matrix

For each player and each game, check if record exists:

```sql
WITH team_games AS (...),
team_players AS (...),
player_game_matrix AS (
    SELECT
        p.player_lookup,
        p.player_full_name,
        g.game_date,
        pgs.game_date IS NOT NULL as has_record,
        pgs.points,
        ir.injury_status,
        b.minutes as boxscore_minutes
    FROM team_players p
    CROSS JOIN team_games g
    LEFT JOIN nba_analytics.player_game_summary pgs
        ON p.player_lookup = pgs.player_lookup AND g.game_date = pgs.game_date
    LEFT JOIN nba_raw.nbac_injury_report ir
        ON p.player_lookup = ir.player_lookup AND g.game_date = ir.game_date
    LEFT JOIN nba_raw.bdl_player_boxscores b
        ON p.player_lookup = b.player_lookup AND g.game_date = b.game_date
    -- Only check games during player's tenure
    WHERE g.game_date BETWEEN p.first_game AND COALESCE(p.last_game, CURRENT_DATE())
)
SELECT * FROM player_game_matrix
```

### Step 4: Generate Report

```
=== SPOT CHECK TEAM: Los Angeles Lakers (LAL) ===
Period: Last 10 games (2026-01-16 to 2026-01-26)

SCHEDULE:
| Date       | Opponent | Location | Score |
|------------|----------|----------|-------|
| 2026-01-26 | GSW      | away     | 108   |
| 2026-01-24 | PHX      | home     | 115   |
| 2026-01-22 | DEN      | home     | 102   |
...

ROSTER COVERAGE:
| Player          | Games | Records | DNP | Injury | Errors |
|-----------------|-------|---------|-----|--------|--------|
| LeBron James    | 10    | 9       | 0   | 1      | 0      |
| Anthony Davis   | 10    | 8       | 0   | 2      | 0      |
| D'Angelo Russell| 10    | 7       | 3   | 0      | 0      |
| Austin Reaves   | 10    | 10      | 0   | 0      | 0      |
| [New Player]    | 3     | 2       | 0   | 0      | 1      | <-- ISSUE

DETAILED ISSUES:
- [New Player] on 2026-01-24: Has 15 min in boxscore, missing from analytics
  Status: ERROR - Needs investigation

RECENT ROSTER CHANGES:
| Player          | Joined     | Left       | Type    |
|-----------------|------------|------------|---------|
| [Traded Player] | -          | 2026-01-15 | Trade   |
| [New Player]    | 2026-01-20 | -          | Trade   |

SUMMARY:
- Active roster: 15 players
- Full coverage: 12 players (80%)
- Partial coverage: 2 players (trades/injuries)
- Errors: 1 player (needs fix)
```

## Coverage Expectations

| Player Type | Expected Coverage |
|-------------|-------------------|
| Starters | 90-100% (minus load management) |
| Rotation players | 80-100% |
| Bench warmers | Variable (many DNPs expected) |
| Recent acquisitions | May have gaps during transition |
| Two-way players | May have G-League gaps |

## Flags to Watch For

| Flag | Meaning | Priority |
|------|---------|----------|
| ERROR | Has boxscore minutes but no analytics | HIGH - Fix required |
| LOW_COVERAGE | Player missing many games unexplained | MEDIUM - Investigate |
| TRADE_GAP | Gap around known trade date | LOW - Expected |
| G_LEAGUE | Possible G-League assignment | LOW - Verify |

## Implementation Notes

1. Get team schedule first to establish game list
2. Get all players who've appeared for team in window
3. For each player, only check games during their tenure
4. Cross-reference with injury reports and boxscores
5. Flag any records where boxscore shows minutes but analytics missing

## Related Skills

| Need | Use |
|------|-----|
| Deep dive on one player | `/spot-check-player <name>` |
| Check specific date | `/spot-check-date <date>` |
| System-wide audit | `/spot-check-gaps` |

## Data Limitations

- Injury data only available from Dec 19, 2025+
- Player movement data outdated (through Aug 2025)
- Two-way contracts and G-League assignments may not be fully tracked
