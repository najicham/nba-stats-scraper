-- ============================================================================
-- File: validation/queries/raw/nbac_player_boxscores/cross_validate_with_bdl.sql
-- Purpose: Compare NBA.com official stats against BDL (primary validation)
-- Usage: Run daily/weekly to verify data consistency between sources
-- ============================================================================
-- ⚠️ NOTE: Table is currently empty (awaiting NBA season start)
-- This query is ready to execute once data arrives
-- ============================================================================
-- Expected Results:
--   - Most players should show "✅ Perfect Match" for all stats
--   - Points discrepancies are CRITICAL (affect prop settlement)
--   - Assists/rebounds discrepancies are concerning but less critical
--   - Missing players should be investigated
--   - NBA.com is official source of truth when discrepancies exist
-- ============================================================================

WITH
-- Check if tables have data
data_check AS (
  SELECT 
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.nbac_player_boxscores` 
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)) as nbac_records,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)) as bdl_records
),

-- Get NBA.com stats (official source of truth)
nbac_stats AS (
  SELECT
    game_date,
    game_id,
    player_lookup,
    player_full_name,
    team_abbr,
    nba_player_id,
    starter,
    points,
    assists,
    total_rebounds,
    field_goals_made,
    three_pointers_made,
    free_throws_made,
    steals,
    blocks,
    turnovers,
    plus_minus
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND points IS NOT NULL
),

-- Get BDL stats for comparison
bdl_stats AS (
  SELECT
    game_date,
    game_id,
    player_lookup,
    player_full_name,
    team_abbr,
    points,
    assists,
    rebounds as total_rebounds,
    field_goals_made,
    three_pointers_made,
    free_throws_made,
    steals,
    blocks,
    turnovers
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND points IS NOT NULL
),

-- Full outer join to catch missing players in either source
comparison AS (
  SELECT
    COALESCE(n.game_date, b.game_date) as game_date,
    COALESCE(n.game_id, b.game_id) as game_id,
    COALESCE(n.player_lookup, b.player_lookup) as player_lookup,
    COALESCE(n.player_full_name, b.player_full_name) as player_name,
    COALESCE(n.team_abbr, b.team_abbr) as team_abbr,

    -- NBA.com stats (official source)
    n.nba_player_id,
    n.starter,
    n.points as nbac_points,
    n.assists as nbac_assists,
    n.total_rebounds as nbac_rebounds,
    n.field_goals_made as nbac_fgm,
    n.three_pointers_made as nbac_3pm,
    n.free_throws_made as nbac_ftm,
    n.steals as nbac_steals,
    n.blocks as nbac_blocks,
    n.turnovers as nbac_turnovers,
    n.plus_minus as nbac_plus_minus,

    -- BDL stats
    b.points as bdl_points,
    b.assists as bdl_assists,
    b.total_rebounds as bdl_rebounds,
    b.field_goals_made as bdl_fgm,
    b.three_pointers_made as bdl_3pm,
    b.free_throws_made as bdl_ftm,
    b.steals as bdl_steals,
    b.blocks as bdl_blocks,
    b.turnovers as bdl_turnovers,

    -- Presence flags
    CASE
      WHEN n.player_lookup IS NOT NULL AND b.player_lookup IS NOT NULL THEN 'in_both'
      WHEN n.player_lookup IS NOT NULL THEN 'nbac_only'
      WHEN b.player_lookup IS NOT NULL THEN 'bdl_only'
    END as presence_status

  FROM nbac_stats n
  FULL OUTER JOIN bdl_stats b
    ON n.game_date = b.game_date
    AND n.game_id = b.game_id
    AND n.player_lookup = b.player_lookup
)

-- No data message
SELECT
  '⚪ No Data Available' as status,
  CURRENT_DATE() as report_date,
  CONCAT('NBA.com player boxscores: ', CAST((SELECT nbac_records FROM data_check) AS STRING), ' records') as message,
  CONCAT('Ball Don', "'", 't Lie boxscores: ', CAST((SELECT bdl_records FROM data_check) AS STRING), ' records') as bdl_message,
  NULL as game_date,
  NULL as player_name,
  NULL as team_abbr,
  NULL as presence_status,
  NULL as nbac_points,
  NULL as bdl_points,
  NULL as point_diff,
  NULL as issue_details
FROM data_check
WHERE nbac_records = 0 OR bdl_records = 0

UNION ALL

-- Actual comparison results
SELECT
  -- Issue severity
  CASE
    -- Critical issues (affect prop settlement)
    WHEN presence_status = 'nbac_only' THEN '🟡 INFO: In NBA.com only'
    WHEN presence_status = 'bdl_only' THEN '⚠️ WARNING: Missing from NBA.com'
    WHEN ABS(COALESCE(nbac_points, 0) - COALESCE(bdl_points, 0)) > 2
      THEN '🔴 CRITICAL: Point discrepancy >2'
    WHEN ABS(COALESCE(nbac_points, 0) - COALESCE(bdl_points, 0)) > 0
      THEN '⚠️ WARNING: Point discrepancy'

    -- Moderate issues
    WHEN ABS(COALESCE(nbac_assists, 0) - COALESCE(bdl_assists, 0)) > 2
      THEN '⚠️ WARNING: Assist discrepancy >2'
    WHEN ABS(COALESCE(nbac_rebounds, 0) - COALESCE(bdl_rebounds, 0)) > 2
      THEN '⚠️ WARNING: Rebound discrepancy >2'
    WHEN ABS(COALESCE(nbac_fgm, 0) - COALESCE(bdl_fgm, 0)) > 2
      THEN '⚠️ WARNING: FGM discrepancy >2'

    -- All stats match
    ELSE '✅ Perfect Match'
  END as status,

  CURRENT_DATE() as report_date,
  CONCAT('Points: ', COALESCE(CAST(nbac_points AS STRING), 'NULL'), ' vs ', 
         COALESCE(CAST(bdl_points AS STRING), 'NULL')) as message,
  CONCAT('Rebounds: ', COALESCE(CAST(nbac_rebounds AS STRING), 'NULL'), ' vs ', 
         COALESCE(CAST(bdl_rebounds AS STRING), 'NULL')) as bdl_message,
  game_date,
  player_name,
  team_abbr,
  presence_status,
  nbac_points,
  bdl_points,
  ABS(COALESCE(nbac_points, 0) - COALESCE(bdl_points, 0)) as point_diff,

  -- Detailed breakdown
  CONCAT(
    'NBA.com: ', COALESCE(CAST(nbac_points AS STRING), '-'), 'pts ',
    COALESCE(CAST(nbac_assists AS STRING), '-'), 'ast ',
    COALESCE(CAST(nbac_rebounds AS STRING), '-'), 'reb | ',
    'BDL: ', COALESCE(CAST(bdl_points AS STRING), '-'), 'pts ',
    COALESCE(CAST(bdl_assists AS STRING), '-'), 'ast ',
    COALESCE(CAST(bdl_rebounds AS STRING), '-'), 'reb'
  ) as issue_details

FROM comparison
CROSS JOIN data_check
WHERE data_check.nbac_records > 0 
  AND data_check.bdl_records > 0

-- Show issues first, then perfect matches
ORDER BY
  CASE status
    WHEN '⚪ No Data Available' THEN 0
    WHEN '🔴 CRITICAL: Point discrepancy >2' THEN 1
    WHEN '⚠️ WARNING: Missing from NBA.com' THEN 2
    WHEN '⚠️ WARNING: Point discrepancy' THEN 3
    WHEN '⚠️ WARNING: Assist discrepancy >2' THEN 4
    WHEN '⚠️ WARNING: Rebound discrepancy >2' THEN 5
    WHEN '⚠️ WARNING: FGM discrepancy >2' THEN 6
    WHEN '🟡 INFO: In NBA.com only' THEN 7
    ELSE 8
  END,
  game_date DESC,
  player_name;