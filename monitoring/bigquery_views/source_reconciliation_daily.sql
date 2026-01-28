-- ============================================================================
-- View: source_reconciliation_daily
-- Purpose: Cross-source reconciliation comparing NBA.com vs BDL stats
-- ============================================================================
-- Compares official NBA.com stats against Ball Don't Lie (BDL) for yesterday.
-- Flags discrepancies that could indicate data quality issues or source problems.
--
-- Health Status Levels:
--   MATCH         - Stats match exactly (expected 95%+ of cases)
--   MINOR_DIFF    - Difference of 1-2 points in any stat (acceptable <5%)
--   WARNING       - Difference >2 in assists/rebounds (investigate)
--   CRITICAL      - Difference >2 points (immediate investigation)
--
-- Usage:
--   -- Check yesterday's reconciliation
--   SELECT * FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
--   WHERE health_status IN ('WARNING', 'CRITICAL')
--   ORDER BY point_diff DESC;
--
--   -- Summary of reconciliation health
--   SELECT
--     health_status,
--     COUNT(*) as player_count,
--     ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
--   GROUP BY health_status
--   ORDER BY FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH');
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.source_reconciliation_daily` AS

WITH yesterday_date AS (
  SELECT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as target_date
),

-- NBA.com stats (official source of truth)
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
    minutes,
    field_goals_made,
    field_goals_attempted,
    three_pointers_made,
    free_throws_made,
    steals,
    blocks,
    turnovers
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date = (SELECT target_date FROM yesterday_date)
    AND points IS NOT NULL  -- Exclude DNPs
),

-- BDL stats for comparison
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
    minutes_played,
    field_goals_made,
    field_goals_attempted,
    three_pointers_made,
    free_throws_made,
    steals,
    blocks,
    turnovers
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = (SELECT target_date FROM yesterday_date)
    AND points IS NOT NULL  -- Exclude DNPs
),

-- Join on player_lookup and game_date (both use normalized player names)
comparison AS (
  SELECT
    n.game_date,
    n.game_id,
    n.player_lookup,
    n.player_full_name as nbac_player_name,
    b.player_full_name as bdl_player_name,
    n.team_abbr,
    n.starter,

    -- NBA.com stats (source of truth)
    n.points as nbac_points,
    n.assists as nbac_assists,
    n.total_rebounds as nbac_rebounds,
    n.field_goals_made as nbac_fgm,
    n.three_pointers_made as nbac_3pm,
    n.steals as nbac_steals,
    n.blocks as nbac_blocks,
    n.turnovers as nbac_turnovers,

    -- BDL stats
    b.points as bdl_points,
    b.assists as bdl_assists,
    b.total_rebounds as bdl_rebounds,
    b.field_goals_made as bdl_fgm,
    b.three_pointers_made as bdl_3pm,
    b.steals as bdl_steals,
    b.blocks as bdl_blocks,
    b.turnovers as bdl_turnovers,

    -- Calculate differences
    ABS(COALESCE(n.points, 0) - COALESCE(b.points, 0)) as point_diff,
    ABS(COALESCE(n.assists, 0) - COALESCE(b.assists, 0)) as assist_diff,
    ABS(COALESCE(n.total_rebounds, 0) - COALESCE(b.total_rebounds, 0)) as rebound_diff,
    ABS(COALESCE(n.field_goals_made, 0) - COALESCE(b.field_goals_made, 0)) as fgm_diff,
    ABS(COALESCE(n.three_pointers_made, 0) - COALESCE(b.three_pointers_made, 0)) as threepm_diff,
    ABS(COALESCE(n.steals, 0) - COALESCE(b.steals, 0)) as steal_diff,
    ABS(COALESCE(n.blocks, 0) - COALESCE(b.blocks, 0)) as block_diff,
    ABS(COALESCE(n.turnovers, 0) - COALESCE(b.turnovers, 0)) as turnover_diff,

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

SELECT
  game_date,
  game_id,
  player_lookup,
  COALESCE(nbac_player_name, bdl_player_name) as player_name,
  team_abbr,
  starter,
  presence_status,

  -- NBA.com stats (official source)
  nbac_points,
  nbac_assists,
  nbac_rebounds,
  nbac_fgm,
  nbac_3pm,
  nbac_steals,
  nbac_blocks,
  nbac_turnovers,

  -- BDL stats
  bdl_points,
  bdl_assists,
  bdl_rebounds,
  bdl_fgm,
  bdl_3pm,
  bdl_steals,
  bdl_blocks,
  bdl_turnovers,

  -- Differences
  point_diff,
  assist_diff,
  rebound_diff,
  fgm_diff,
  threepm_diff,
  steal_diff,
  block_diff,
  turnover_diff,

  -- Health Status Classification
  CASE
    -- Critical: Points difference >2 (affects prop settlement)
    WHEN point_diff > 2 THEN 'CRITICAL'

    -- Warning: Assists or rebounds difference >2
    WHEN assist_diff > 2 OR rebound_diff > 2 THEN 'WARNING'

    -- Minor: Any stat difference of 1-2
    WHEN point_diff BETWEEN 1 AND 2
      OR assist_diff BETWEEN 1 AND 2
      OR rebound_diff BETWEEN 1 AND 2
      OR fgm_diff > 0
      OR threepm_diff > 0
      OR steal_diff > 0
      OR block_diff > 0
      OR turnover_diff > 0
      THEN 'MINOR_DIFF'

    -- Match: All stats identical
    ELSE 'MATCH'
  END as health_status,

  -- Issue summary for quick triage
  CONCAT(
    CASE WHEN point_diff > 0 THEN CONCAT('PTS:', CAST(point_diff AS STRING), ' ') ELSE '' END,
    CASE WHEN assist_diff > 0 THEN CONCAT('AST:', CAST(assist_diff AS STRING), ' ') ELSE '' END,
    CASE WHEN rebound_diff > 0 THEN CONCAT('REB:', CAST(rebound_diff AS STRING), ' ') ELSE '' END,
    CASE WHEN fgm_diff > 0 THEN CONCAT('FGM:', CAST(fgm_diff AS STRING), ' ') ELSE '' END,
    CASE WHEN threepm_diff > 0 THEN CONCAT('3PM:', CAST(threepm_diff AS STRING), ' ') ELSE '' END
  ) as discrepancy_summary,

  -- Full stat comparison for debugging
  CONCAT(
    'NBA.com: ', COALESCE(CAST(nbac_points AS STRING), '-'), 'pts ',
    COALESCE(CAST(nbac_assists AS STRING), '-'), 'ast ',
    COALESCE(CAST(nbac_rebounds AS STRING), '-'), 'reb | ',
    'BDL: ', COALESCE(CAST(bdl_points AS STRING), '-'), 'pts ',
    COALESCE(CAST(bdl_assists AS STRING), '-'), 'ast ',
    COALESCE(CAST(bdl_rebounds AS STRING), '-'), 'reb'
  ) as stat_comparison,

  CURRENT_TIMESTAMP() as checked_at

FROM comparison

-- Order by severity first (critical issues first), then by point difference
ORDER BY
  FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH'),
  point_diff DESC,
  assist_diff DESC,
  rebound_diff DESC,
  player_name;

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- 1. Get critical and warning discrepancies only
-- SELECT
--   player_name,
--   team_abbr,
--   health_status,
--   discrepancy_summary,
--   stat_comparison
-- FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
-- WHERE health_status IN ('CRITICAL', 'WARNING')
-- ORDER BY health_status, point_diff DESC;

-- 2. Daily reconciliation health summary
-- SELECT
--   health_status,
--   COUNT(*) as player_count,
--   ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage,
--   STRING_AGG(player_name, ', ' ORDER BY point_diff DESC LIMIT 5) as top_players
-- FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
-- GROUP BY health_status
-- ORDER BY FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH');

-- 3. Players only in one source (data completeness check)
-- SELECT
--   player_name,
--   team_abbr,
--   presence_status,
--   nbac_points,
--   bdl_points
-- FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
-- WHERE presence_status != 'in_both'
-- ORDER BY presence_status, team_abbr, player_name;

-- 4. Alert if critical discrepancies exceed threshold (1%)
-- WITH summary AS (
--   SELECT
--     COUNTIF(health_status = 'CRITICAL') as critical_count,
--     COUNT(*) as total_players,
--     ROUND(COUNTIF(health_status = 'CRITICAL') * 100.0 / COUNT(*), 2) as critical_pct
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
-- )
-- SELECT
--   *,
--   CASE WHEN critical_pct > 1.0 THEN 'ALERT: High critical discrepancy rate' ELSE 'OK' END as alert
-- FROM summary;
