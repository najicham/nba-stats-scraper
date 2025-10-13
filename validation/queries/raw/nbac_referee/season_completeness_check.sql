-- ============================================================================
-- File: validation/queries/raw/nbac_referee/season_completeness_check.sql
-- Purpose: Comprehensive season validation with diagnostics for referee assignments
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_playoff, failed_joins, wrong_official_count
--   - All teams should have 82/82 for regular season games
--   - Playoff games should match actual playoff results with 4 officials each
-- ============================================================================

WITH
refs_with_season_info AS (
  SELECT
    r.game_date,
    r.game_id as ref_game_id,
    r.home_team_abbr,
    r.away_team_abbr,
    r.official_code,
    r.official_name,
    r.official_position,
    s.is_playoffs,
    s.game_id as schedule_game_id,
    CASE
      WHEN r.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN r.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN r.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN r.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments` r
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON r.game_date = s.game_date
    AND r.home_team_abbr = s.home_team_tricode
    AND r.away_team_abbr = s.away_team_tricode
  WHERE r.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
),

-- Count officials per game to detect issues
game_official_counts AS (
  SELECT
    ref_game_id,
    season,
    is_playoffs,
    COUNT(DISTINCT official_code) as official_count
  FROM refs_with_season_info
  WHERE season IS NOT NULL
  GROUP BY ref_game_id, season, is_playoffs
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT ref_game_id) as total_games,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN ref_game_id END) as null_playoff_flag_games,
    COUNT(DISTINCT CASE WHEN schedule_game_id IS NULL THEN ref_game_id END) as failed_join_games,
    COUNT(DISTINCT CASE WHEN home_team_abbr IS NULL OR away_team_abbr IS NULL THEN ref_game_id END) as null_abbr_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN ref_game_id END) as playoff_games_found,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE THEN ref_game_id END) as regular_season_games_found
  FROM refs_with_season_info
  WHERE season IS NOT NULL
),

-- Check for wrong official counts (should be 3 for regular, 4 for playoffs)
wrong_counts AS (
  SELECT
    COUNT(DISTINCT ref_game_id) as games_with_wrong_count
  FROM game_official_counts
  WHERE (is_playoffs = FALSE AND official_count != 3)
     OR (is_playoffs = TRUE AND official_count != 4)
),

-- Count unique games per team
team_games AS (
  SELECT DISTINCT
    season,
    home_team_abbr as team,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    ref_game_id
  FROM refs_with_season_info
  WHERE season IS NOT NULL

  UNION DISTINCT

  SELECT DISTINCT
    season,
    away_team_abbr as team,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    ref_game_id
  FROM refs_with_season_info
  WHERE season IS NOT NULL
),

team_stats AS (
  SELECT
    season,
    team,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE THEN ref_game_id END) as reg_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN ref_game_id END) as playoff_games,
    COUNT(DISTINCT ref_game_id) as total_games
  FROM team_games
  GROUP BY season, team
)

-- Output diagnostics first
SELECT
  row_type,
  CAST(total_games AS STRING) as season,
  'null_playoff_flag' as team,
  CAST(null_playoff_flag_games AS STRING) as reg_games,
  CAST(failed_join_games AS STRING) as playoff_games,
  CAST(null_abbr_games AS STRING) as total,
  CONCAT('playoff=', CAST(playoff_games_found AS STRING), ' reg=', CAST(regular_season_games_found AS STRING)) as notes
FROM diagnostics

UNION ALL

-- Check wrong official counts
SELECT
  'DIAGNOSTICS' as row_type,
  'wrong_official_count' as season,
  'CHECK' as team,
  CAST(games_with_wrong_count AS STRING) as reg_games,
  '0' as playoff_games,
  '0' as total,
  'Should be 0 (3 refs regular, 4 playoff)' as notes
FROM wrong_counts

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team,
  CAST(reg_games AS STRING) as reg_games,
  CAST(playoff_games AS STRING) as playoff_games,
  CAST(total_games AS STRING) as total,
  CASE
    WHEN reg_games < 82 THEN CONCAT('⚠️ Missing ', CAST(82 - reg_games AS STRING), ' regular season games')
    ELSE ''
  END as notes
FROM team_stats
ORDER BY
  row_type,
  season,
  CAST(playoff_games AS INT64) DESC,
  team;
