-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/season_completeness_check.sql
-- Purpose: Comprehensive season validation for NBA schedule data
-- Status: UPDATED - Excludes special event games (All-Star, exhibitions)
-- ============================================================================

WITH
schedule_with_season AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    home_team_name,
    away_team_name,
    is_playoffs,
    is_regular_season,
    playoff_round,
    -- Enhanced analytical fields
    is_primetime,
    has_national_tv,
    primary_network,
    is_christmas,
    is_mlk_day,
    is_emirates_cup,
    -- Season assignment
    CASE
      WHEN game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
      WHEN game_date BETWEEN '2025-10-21' AND '2026-06-20' THEN '2025-26'
    END as season
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2021-10-19' AND '2026-06-20'
    -- Exclude special event games (All-Star, exhibitions, international)
    AND home_team_tricode NOT IN ('BAR', 'DRT', 'IAH', 'LBN', 'PAY', 'WOR', 
                                   'DRN', 'GNS', 'JAS', 'JKM', 'PAU', 
                                   'DLF', 'EST')
    AND away_team_tricode NOT IN ('BAR', 'DRT', 'IAH', 'LBN', 'PAY', 'WOR',
                                   'DRN', 'GNS', 'JAS', 'JKM', 'PAU',
                                   'DLF', 'EST')
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT game_id) as total_games,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN game_id END) as null_playoff_flag,
    COUNT(DISTINCT CASE WHEN is_regular_season IS NULL THEN game_id END) as null_regular_season,
    COUNT(DISTINCT CASE WHEN home_team_tricode IS NULL THEN game_id END) as null_home_tricode,
    COUNT(DISTINCT CASE WHEN away_team_tricode IS NULL THEN game_id END) as null_away_tricode,
    COUNT(DISTINCT CASE WHEN is_primetime IS NULL THEN game_id END) as null_primetime,
    COUNT(DISTINCT CASE WHEN primary_network IS NULL AND has_national_tv = TRUE THEN game_id END) as missing_network,
    COUNT(DISTINCT home_team_tricode) as distinct_home_teams,
    COUNT(DISTINCT away_team_tricode) as distinct_away_teams
  FROM schedule_with_season
  WHERE season IS NOT NULL
),

-- Expand each game into home and away team rows
team_games AS (
  SELECT
    season,
    home_team_tricode as team,
    'home' as game_location,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    game_id
  FROM schedule_with_season
  WHERE season IS NOT NULL

  UNION ALL

  SELECT
    season,
    away_team_tricode as team,
    'away' as game_location,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    game_id
  FROM schedule_with_season
  WHERE season IS NOT NULL
),

-- Count games by team/season/playoff status
team_stats AS (
  SELECT
    season,
    team,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE THEN game_id END) as regular_season_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN game_id END) as playoff_games,
    COUNT(DISTINCT game_id) as total_games
  FROM team_games
  GROUP BY season, team
)

-- Output diagnostics first
SELECT
  row_type,
  CAST(total_games AS STRING) as season,
  'null_checks' as team,
  CAST(null_playoff_flag AS STRING) as regular_season,
  CAST(null_regular_season AS STRING) as playoffs,
  CAST(null_home_tricode AS STRING) as total,
  CAST(null_away_tricode AS STRING) as home_teams,
  CAST(null_primetime AS STRING) as away_teams,
  'All should be 0' as notes
FROM diagnostics

UNION ALL

SELECT
  row_type,
  'enhanced_fields' as season,
  'quality_check' as team,
  CAST(missing_network AS STRING) as regular_season,
  CAST(distinct_home_teams AS STRING) as playoffs,
  CAST(distinct_away_teams AS STRING) as total,
  '' as home_teams,
  '' as away_teams,
  'Expect 30 teams each' as notes
FROM diagnostics

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team,
  CAST(regular_season_games AS STRING) as regular_season,
  CAST(playoff_games AS STRING) as playoffs,
  CAST(total_games AS STRING) as total,
  '' as home_teams,
  '' as away_teams,
  CASE
    WHEN regular_season_games < 80 THEN '⚠️ Missing regular season games'
    WHEN regular_season_games > 84 THEN '⚠️ Extra regular season games'
    WHEN playoff_games > 28 THEN '⚠️ Too many playoff games'
    ELSE ''
  END as notes
FROM team_stats
ORDER BY
  row_type,
  season,
  playoffs DESC,
  team;
