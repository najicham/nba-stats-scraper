-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/player_status_validation.sql
-- Purpose: Validate player status logic and data integrity
-- Usage: Run to detect data quality issues with player statuses and stats
-- ============================================================================
-- Expected Results:
--   - Active players should have points/stats (minutes > 0)
--   - Inactive players should NOT have stats (all NULL or 0)
--   - DNP players should NOT have playing time
--   - Player counts per game should be reasonable (~30-35 total)
-- ============================================================================

WITH
status_stats AS (
  SELECT
    player_status,
    COUNT(*) as player_count,
    -- Active player checks
    COUNT(CASE WHEN player_status = 'active' AND (points IS NULL OR points = 0) THEN 1 END) as active_no_points,
    COUNT(CASE WHEN player_status = 'active' AND minutes IS NULL THEN 1 END) as active_no_minutes,
    COUNT(CASE WHEN player_status = 'active' AND minutes_decimal = 0 THEN 1 END) as active_zero_minutes,
    -- Inactive player checks (should have NO stats)
    COUNT(CASE WHEN player_status = 'inactive' AND points IS NOT NULL AND points > 0 THEN 1 END) as inactive_has_points,
    COUNT(CASE WHEN player_status = 'inactive' AND minutes IS NOT NULL THEN 1 END) as inactive_has_minutes,
    -- DNP player checks
    COUNT(CASE WHEN player_status = 'dnp' AND (points IS NOT NULL AND points > 0) THEN 1 END) as dnp_has_points,
    COUNT(CASE WHEN player_status = 'dnp' AND minutes_decimal > 0 THEN 1 END) as dnp_has_minutes
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY player_status
),

game_player_counts AS (
  SELECT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as total_players,
    COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_count,
    COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_count,
    COUNT(CASE WHEN player_status = 'dnp' THEN 1 END) as dnp_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
  HAVING total_players < 25 OR total_players > 45  -- Flag unusual player counts
),

data_quality_issues AS (
  SELECT
    game_date,
    game_id,
    player_name_original,
    team_abbr,
    player_status,
    points,
    minutes,
    minutes_decimal,
    CASE
      WHEN player_status = 'active' AND (points IS NULL OR points = 0) AND minutes_decimal > 5 
        THEN 'Active player with minutes but no points'
      WHEN player_status = 'active' AND minutes IS NULL 
        THEN 'Active player missing minutes data'
      WHEN player_status = 'inactive' AND (points IS NOT NULL AND points > 0) 
        THEN 'Inactive player has stats (should be NULL)'
      WHEN player_status = 'dnp' AND minutes_decimal > 0 
        THEN 'DNP player has playing time'
      ELSE 'Unknown issue'
    END as issue_type
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND (
      (player_status = 'active' AND (points IS NULL OR (points = 0 AND minutes_decimal > 5)))
      OR (player_status = 'active' AND minutes IS NULL)
      OR (player_status = 'inactive' AND points IS NOT NULL AND points > 0)
      OR (player_status = 'dnp' AND minutes_decimal > 0)
    )
  ORDER BY game_date DESC, issue_type
  LIMIT 100
)

-- Status summary with data quality flags
SELECT
  'STATUS SUMMARY' as report_type,
  player_status,
  CAST(player_count AS STRING) as total,
  CAST(active_no_points AS STRING) as active_no_points,
  CAST(active_no_minutes AS STRING) as active_no_minutes,
  CAST(inactive_has_points AS STRING) as inactive_has_points,
  CAST(dnp_has_points AS STRING) as dnp_has_points,
  CASE
    WHEN player_status = 'active' AND (active_no_points > 0 OR active_no_minutes > 0) THEN '⚠️ Issues detected'
    WHEN player_status = 'inactive' AND inactive_has_points > 0 THEN '🔴 Data error'
    WHEN player_status = 'dnp' AND dnp_has_points > 0 THEN '🔴 Data error'
    ELSE '✅ Clean'
  END as status
FROM status_stats

UNION ALL

-- Games with unusual player counts
SELECT
  'UNUSUAL COUNTS' as report_type,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as player_status,
  CAST(total_players AS STRING) as total,
  CAST(active_count AS STRING) as active_no_points,
  CAST(inactive_count AS STRING) as active_no_minutes,
  CAST(dnp_count AS STRING) as inactive_has_points,
  game_date as dnp_has_points,
  CASE
    WHEN total_players < 25 THEN '⚠️ Too few players'
    WHEN total_players > 45 THEN '⚠️ Too many players'
    ELSE '✅ Normal'
  END as status
FROM game_player_counts
ORDER BY total_players

UNION ALL

-- Data quality issues summary
SELECT
  'QUALITY ISSUES' as report_type,
  CAST(COUNT(*) AS STRING) as player_status,
  'Issues found' as total,
  '' as active_no_points,
  '' as active_no_minutes,
  '' as inactive_has_points,
  '' as dnp_has_points,
  CASE WHEN COUNT(*) = 0 THEN '✅ No issues' ELSE '⚠️ See details below' END as status
FROM data_quality_issues

ORDER BY report_type DESC;

-- Detailed quality issues
SELECT
  '--- DETAILED QUALITY ISSUES ---' as section,
  game_date,
  player_name_original,
  team_abbr,
  player_status,
  CAST(points AS STRING) as points,
  minutes,
  issue_type
FROM data_quality_issues;
