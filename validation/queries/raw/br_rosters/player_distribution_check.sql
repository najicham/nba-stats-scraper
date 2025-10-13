-- ============================================================================
-- File: validation/queries/raw/br_rosters/player_distribution_check.sql
-- Purpose: Validate player counts and identify multi-team scenarios
-- Usage: Run to understand roster patterns and validate trade tracking
-- ============================================================================
-- Expected Results:
--   - Most teams have 15-25 players per season
--   - Multi-team players (trades) are NORMAL - expect 70-80+ per season
--   - Position distribution should be reasonable
-- ============================================================================
-- Instructions:
--   This query provides insights into roster patterns, not strict pass/fail
--   validation. Use it to understand normal ranges for your data.
-- ============================================================================

WITH
roster_data AS (
  SELECT
    season_year,
    season_display,
    team_abbrev,
    player_full_name,
    player_lookup,
    position,
    jersey_number,
    experience_years
  FROM `nba-props-platform.nba_raw.br_rosters_current`
  WHERE season_year BETWEEN 2021 AND 2024
),

-- Players per team distribution
team_player_counts AS (
  SELECT
    season_display,
    team_abbrev,
    COUNT(DISTINCT player_lookup) as player_count,
    COUNT(DISTINCT CASE WHEN position LIKE '%G%' THEN player_lookup END) as guards,
    COUNT(DISTINCT CASE WHEN position LIKE '%F%' THEN player_lookup END) as forwards,
    COUNT(DISTINCT CASE WHEN position LIKE '%C%' THEN player_lookup END) as centers,
    COUNT(DISTINCT CASE WHEN experience_years = 0 THEN player_lookup END) as rookies
  FROM roster_data
  GROUP BY season_display, team_abbrev
),

-- League-wide stats per season
season_summary AS (
  SELECT
    t.season_display,
    COUNT(DISTINCT t.team_abbrev) as teams,
    (SELECT COUNT(DISTINCT player_lookup) FROM roster_data r WHERE r.season_display = t.season_display) as unique_players,
    SUM(t.player_count) as total_roster_spots,
    ROUND(AVG(t.player_count), 1) as avg_players_per_team,
    MIN(t.player_count) as min_players,
    MAX(t.player_count) as max_players,
    APPROX_QUANTILES(t.player_count, 100)[OFFSET(50)] as median_players
  FROM team_player_counts t
  GROUP BY t.season_display
),

-- Multi-team players (trades)
multi_team_players AS (
  SELECT
    season_display,
    player_lookup,
    STRING_AGG(DISTINCT team_abbrev ORDER BY team_abbrev) as teams,
    COUNT(DISTINCT team_abbrev) as team_count
  FROM roster_data
  GROUP BY season_display, player_lookup
  HAVING COUNT(DISTINCT team_abbrev) > 1
),

-- Summary of multi-team players
multi_team_summary AS (
  SELECT
    season_display,
    COUNT(*) as players_traded,
    COUNT(CASE WHEN team_count = 2 THEN 1 END) as traded_once,
    COUNT(CASE WHEN team_count = 3 THEN 1 END) as traded_twice,
    COUNT(CASE WHEN team_count >= 4 THEN 1 END) as traded_3_plus_times
  FROM multi_team_players
  GROUP BY season_display
)

-- Season-level summary
SELECT
  'SEASON_SUMMARY' as report_section,
  s.season_display,
  CAST(s.teams AS STRING) as teams,
  CAST(s.unique_players AS STRING) as unique_players,
  CAST(s.total_roster_spots AS STRING) as total_spots,
  CAST(s.avg_players_per_team AS STRING) as avg_per_team,
  CAST(s.min_players AS STRING) as min,
  CAST(s.max_players AS STRING) as max,
  CAST(s.median_players AS STRING) as median,
  CAST(COALESCE(m.players_traded, 0) AS STRING) as players_traded,
  'Teams | Unique players | Roster spots | Avg/team | Min | Max | Median | Traded' as description
FROM season_summary s
LEFT JOIN multi_team_summary m ON s.season_display = m.season_display

UNION ALL

-- Multi-team trade details
SELECT
  'TRADE_DETAILS' as report_section,
  m.season_display,
  CAST(m.players_traded AS STRING) as teams,
  CAST(m.traded_once AS STRING) as unique_players,
  CAST(m.traded_twice AS STRING) as total_spots,
  CAST(m.traded_3_plus_times AS STRING) as avg_per_team,
  '' as min,
  '' as max,
  '' as median,
  '' as players_traded,
  'Season | Total traded | Once (2 teams) | Twice (3 teams) | 3+ times' as description
FROM multi_team_summary m

UNION ALL

-- Teams with unusual roster sizes
SELECT
  'OUTLIERS' as report_section,
  t.season_display,
  t.team_abbrev as teams,
  CAST(t.player_count AS STRING) as unique_players,
  CAST(t.guards AS STRING) as total_spots,
  CAST(t.forwards AS STRING) as avg_per_team,
  CAST(t.centers AS STRING) as min,
  CAST(t.rookies AS STRING) as max,
  CASE
    WHEN t.player_count < 13 THEN '⚠️ Very small'
    WHEN t.player_count > 32 THEN '⚠️ Very large'
    ELSE ''
  END as median,
  '' as players_traded,
  'Season | Team | Players | Guards | Forwards | Centers | Rookies | Status' as description
FROM team_player_counts t
WHERE t.player_count < 13 OR t.player_count > 32

ORDER BY
  report_section,
  season_display DESC;