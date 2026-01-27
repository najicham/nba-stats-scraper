# /spot-check-player - Player Game History Verification

Spot-check a player's recent game history to verify injury flags, DNP records, and identify data gaps. Handles trades, two-way contracts, and G-League assignments.

**Related skills**: See `/spot-check-overview` for workflow and when to use each skill.

## When to Use

- Verify injury flags are being captured from NBA.com
- Investigate why a player is missing from certain games
- Check for data quality issues before they affect predictions
- Validate the "last 10 games" display on the website
- Verify traded player's full game history is intact

## Usage

```
/spot-check-player <player_lookup> [num_games]
```

Examples:
- `/spot-check-player lebron_james` - Check LeBron's last 10 games
- `/spot-check-player anthony_davis 20` - Check AD's last 20 games
- `/spot-check-player traeyoung 30` - Check traded player's history across teams

## What This Skill Does

### Step 1: Get Player's Team Stints

First, identify ALL teams the player has played for in the window:

```sql
-- Get all team stints for the player
SELECT
  team_abbr,
  MIN(game_date) as stint_start,
  MAX(game_date) as stint_end,
  COUNT(*) as games_played
FROM nba_analytics.player_game_summary
WHERE player_lookup = @player_lookup
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY team_abbr
ORDER BY stint_start
```

This handles:
- Players on one team (most common)
- Traded players (2+ teams)
- Two-way players shuttling between teams

### Step 2: Get Player's Game Records

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
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
ORDER BY game_date DESC
LIMIT @num_games
```

### Step 3: Get Team Schedules for Each Stint

For EACH team stint, get that team's schedule during that period:

```sql
-- For each stint, get team's games during that period
SELECT
    s.game_date,
    s.game_id,
    CASE
        WHEN s.home_team_tricode = @team_abbr THEN s.away_team_tricode
        ELSE s.home_team_tricode
    END as opponent,
    CASE
        WHEN s.home_team_tricode = @team_abbr THEN 'home'
        ELSE 'away'
    END as location
FROM nba_raw.v_nbac_schedule_latest s
WHERE (s.home_team_tricode = @team_abbr OR s.away_team_tricode = @team_abbr)
  AND s.game_status = 3  -- Completed games
  AND s.game_date BETWEEN @stint_start AND @stint_end
ORDER BY s.game_date
```

### Step 4: Find Gaps and Classify

Compare player games vs team schedules to find gaps:

**Gap Types:**

| Type | Description | Classification |
|------|-------------|----------------|
| Within-stint gap | Team played, player has no record during their stint | Needs investigation |
| Between-stint gap | Days between last game on Team A and first game on Team B | INFO - Trade transition |
| Pre-stint gap | Team games before player joined (trade/signing) | EXPECTED |
| Post-stint gap | Team games after player left (trade/waiver) | EXPECTED |

### Step 5: Check Registry Status

Before investigating gaps, verify the player is in the registry:

```sql
-- Check if player exists in registry
SELECT
    player_lookup,
    universal_player_id
FROM nba_reference.nba_players_registry
WHERE player_lookup = @player_lookup

-- Check if player has unresolved name issues
SELECT
    normalized_lookup,
    status,
    resolution_type,
    resolved_to_name,
    last_seen_date
FROM nba_reference.unresolved_player_names
WHERE normalized_lookup = @player_lookup
ORDER BY last_seen_date DESC
LIMIT 1
```

**Interpretation**:
- In registry → Good, proceed with gap analysis
- Not in registry but in unresolved (pending) → Add alias first
- Not in registry but in unresolved (resolved) → May need reprocessing
- Not in registry, not in unresolved → New player, needs registration

### Step 6: Investigate Within-Stint Gaps

For each gap WITHIN a stint, check these sources:

**A. Check Injury Reports**
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

**B. Check Raw Boxscores (DNP)**
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

**C. Check Player Movement (if available)**
```sql
SELECT
    transaction_date,
    transaction_type,
    team_abbr,
    transaction_description
FROM nba_raw.nbac_player_movement
WHERE player_lookup = @player_lookup
  AND transaction_date BETWEEN DATE_SUB(@missing_date, INTERVAL 7 DAY)
                           AND DATE_ADD(@missing_date, INTERVAL 7 DAY)
ORDER BY transaction_date
```

### Step 6: Generate Report

Produce a comprehensive summary:

```
=== PLAYER SPOT CHECK: Trae Young ===
Period: Last 30 games (2025-10-25 to 2026-01-26)

TEAM STINTS:
| Team | From       | To         | Games |
|------|------------|------------|-------|
| ATL  | 2025-10-25 | 2025-12-27 | 28    |
| WAS  | 2026-01-22 | 2026-01-22 | 1     |

BETWEEN-STINT GAPS:
- Dec 28 to Jan 21 (25 days): Trade transition ATL → WAS
  Status: INFO - Normal trade processing window

ATL STINT (Oct 25 - Dec 27):
| Date       | Opp | Pts | Min  | Status | Notes |
|------------|-----|-----|------|--------|-------|
| 2025-12-27 | MIA | 32  | 36.2 | active | Last ATL game |
| 2025-12-25 | NYK | 28  | 34.1 | active | -     |
| 2025-12-23 | -   | -   | -    | OUT    | Knee (rest) |
...

WAS STINT (Jan 22 - present):
| Date       | Opp | Pts | Min  | Status | Notes |
|------------|-----|-----|------|--------|-------|
| 2026-01-22 | CHI | 24  | 32.0 | active | First WAS game |

MISSING GAME ANALYSIS:
- 2025-12-23 (ATL vs BOS): Player listed OUT (Knee - rest) in nbac_injury_report
  Status: EXPECTED - Injury properly flagged

POTENTIAL ISSUES:
- None found

DATA QUALITY:
- ATL stint: 27/28 team games have player records (1 injury = expected)
- WAS stint: 1/1 team games have player records
- Overall: All absences explained
```

## Scenarios to Detect

### 1. EXPECTED - Injury Flagged
Player missing from `player_game_summary` BUT has injury report entry.
**Status**: Working as expected.

### 2. WARNING - DNP Without Injury Flag
Player has 0 minutes in `bdl_player_boxscores` but NO injury report.
**Status**: May be missing injury data. Check if NBA.com source is being used.

### 3. ERROR - Data Gap
Player's team played during their stint, player NOT in injury report, NOT in raw boxscores.
**Status**: Likely data collection issue. Check scrapers.

### 4. INFO - Trade Transition
Gap between stints on different teams.
**Status**: Normal for trades, signings, waiver claims.

### 5. INFO - G-League Assignment
Two-way player missing games, may be with G-League affiliate.
**Status**: Check if player is on two-way contract.

### 6. WARNING - Inconsistent Sources
Player has injury status in BDL but NOT in NBA.com (or vice versa).
**Status**: May indicate NBA.com scraper issue since that's our primary source.

## Implementation Notes

1. **Always get team stints first** - Don't assume player is on one team
2. Use normalized `player_lookup` for all queries
3. Query both `nbac_injury_report` and `bdl_injuries` for cross-validation
4. Check `bdl_player_boxscores` for 0-minute entries (DNP confirmation)
5. Gaps BETWEEN stints are normal; gaps WITHIN stints need investigation
6. Two-way players may have legitimate G-League gaps
7. `nbac_player_movement` data may not be current - fall back to team stint analysis

## Data Coverage Warnings

**IMPORTANT: Check data availability before interpreting results.**

### Injury Report Data
- **Available from**: December 19, 2025
- **Missing**: October 22 - December 18, 2025 (scraper bug, now fixed)
- **Impact**: Gaps before Dec 19 cannot be explained via injury reports
- **Workaround**: Use boxscore data (0 minutes = DNP)

### Player Movement Data
- **Last updated**: August 2025
- **Missing**: All 2025-26 season trades
- **Impact**: Cannot verify trades via movement table
- **Workaround**: Detect team changes from player_game_summary

### When analyzing results:
1. If date < Dec 19, 2025: Expect more "unexplained" gaps (no injury data)
2. For traded players: Use team stint analysis, not movement table
3. For two-way players: G-League assignments may not be tracked

## Known Limitations

- `nbac_player_movement` table may not have current season data (last update: Aug 2025)
- G-League assignments not always explicitly tracked
- Same-day trades may show player on both teams for one date
- Injury report scraper had bug from Nov 14 - Dec 18, 2025 (produced empty files)

## Success Criteria

After running this check, you should know:
- Whether all absences are properly explained (injury, trade, etc.)
- Whether injury flags from NBA.com are being captured
- Whether there are any unexplained data gaps to investigate
- Full game history across all teams the player has been on
