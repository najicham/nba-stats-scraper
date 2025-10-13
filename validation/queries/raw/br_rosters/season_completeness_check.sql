-- ============================================================================
-- File: validation/queries/raw/br_rosters/season_completeness_check.sql
-- Purpose: Comprehensive season validation for Basketball Reference roster data
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for nulls and quality issues
--   - Each team should appear once per season (30 teams × 4 seasons = 120 rows)
--   - Player counts should be reasonable (15-25 per team typical)
--   - Multi-team players are NORMAL (trades mid-season)
-- ============================================================================

WITH
roster_with_season AS (
  SELECT
    season_year,
    season_display,
    team_abbrev,
    player_full_name,
    player_last_name,
    player_normalized,
    player_lookup,
    position,
    jersey_number,
    first_seen_date,
    last_scraped_date
  FROM `nba-props-platform.nba_raw.br_rosters_current`
  WHERE season_year BETWEEN 2021 AND 2024
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    COUNT(*) as total_roster_spots,
    COUNT(DISTINCT CONCAT(CAST(season_year AS STRING), '-', team_abbrev, '-', player_full_name)) as unique_player_team_combos,
    COUNT(DISTINCT player_full_name) as unique_players,
    COUNT(CASE WHEN season_year IS NULL THEN 1 END) as null_season,
    COUNT(CASE WHEN team_abbrev IS NULL THEN 1 END) as null_team,
    COUNT(CASE WHEN player_full_name IS NULL THEN 1 END) as null_player_name,
    COUNT(CASE WHEN player_lookup IS NULL THEN 1 END) as null_player_lookup,
    COUNT(CASE WHEN position IS NULL THEN 1 END) as null_position,
    COUNT(DISTINCT season_year) as seasons_present,
    COUNT(DISTINCT team_abbrev) as teams_present
  FROM roster_with_season
),

-- Count players per team per season
team_stats AS (
  SELECT
    season_display,
    team_abbrev,
    COUNT(DISTINCT player_full_name) as unique_players,
    COUNT(*) as roster_spots,
    MIN(first_seen_date) as earliest_seen,
    MAX(last_scraped_date) as latest_scraped
  FROM roster_with_season
  GROUP BY season_display, team_abbrev
),

-- Find multi-team players (trades)
multi_team_players AS (
  SELECT
    season_display,
    COUNT(DISTINCT player_full_name) as players_on_multiple_teams
  FROM (
    SELECT
      season_display,
      player_full_name,
      COUNT(DISTINCT team_abbrev) as team_count
    FROM roster_with_season
    GROUP BY season_display, player_full_name
    HAVING COUNT(DISTINCT team_abbrev) > 1
  )
  GROUP BY season_display
)

-- Output diagnostics first
SELECT
  row_type,
  CAST(total_roster_spots AS STRING) as value1,
  CAST(unique_player_team_combos AS STRING) as value2,
  CAST(unique_players AS STRING) as value3,
  CAST(null_season AS STRING) as value4,
  CAST(null_team AS STRING) as value5,
  CAST(null_player_name AS STRING) as value6,
  CAST(null_player_lookup AS STRING) as value7,
  'Total roster spots | Unique combos | Unique players | Nulls (should be 0)' as description
FROM diagnostics

UNION ALL

SELECT
  'DIAGNOSTICS_2' as row_type,
  CAST(null_position AS STRING) as value1,
  CAST(seasons_present AS STRING) as value2,
  CAST(teams_present AS STRING) as value3,
  '' as value4,
  '' as value5,
  '' as value6,
  '' as value7,
  'Null positions | Seasons (expect 4) | Teams (expect 30)' as description
FROM diagnostics

UNION ALL

-- Season summary with multi-team players
SELECT
  'SEASON_SUMMARY' as row_type,
  t.season_display as value1,
  CAST(COUNT(DISTINCT t.team_abbrev) AS STRING) as value2,
  CAST(SUM(t.unique_players) AS STRING) as value3,
  CAST(SUM(t.roster_spots) AS STRING) as value4,
  CAST(ROUND(AVG(t.unique_players), 1) AS STRING) as value5,
  CAST(COALESCE(m.players_on_multiple_teams, 0) AS STRING) as value6,
  CASE
    WHEN COUNT(DISTINCT t.team_abbrev) < 30 THEN '⚠️ Missing teams'
    WHEN COUNT(DISTINCT t.team_abbrev) > 30 THEN '⚠️ Extra teams'
    ELSE '✅ Complete'
  END as value7,
  'Season | Teams | Players | Roster spots | Avg per team | Multi-team | Status' as description
FROM team_stats t
LEFT JOIN multi_team_players m ON t.season_display = m.season_display
GROUP BY t.season_display, m.players_on_multiple_teams

UNION ALL

-- Then individual team stats
SELECT
  'TEAM' as row_type,
  season_display as value1,
  team_abbrev as value2,
  CAST(unique_players AS STRING) as value3,
  CAST(roster_spots AS STRING) as value4,
  CAST(earliest_seen AS STRING) as value5,
  CAST(latest_scraped AS STRING) as value6,
  CASE
    WHEN unique_players < 13 THEN '⚠️ Very small roster'
    WHEN unique_players > 32 THEN '⚠️ Very large roster'
    WHEN unique_players != roster_spots THEN '⚠️ Duplicate players'
    ELSE ''
  END as value7,
  'Season | Team | Players | Spots | First seen | Last scraped | Notes' as description
FROM team_stats
ORDER BY
  row_type,
  value1,  -- season_display
  value3 DESC,  -- unique_players (to spot issues)
  value2;  -- team_abbrev