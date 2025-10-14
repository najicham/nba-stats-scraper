-- File: validation/queries/raw/nbac_play_by_play/player_coverage_validation.sql
-- ============================================================================
-- Player Coverage Validation
-- Purpose: Cross-validate play-by-play players against box scores and rosters
-- Ensures all participating players have play-by-play representation
-- ============================================================================

WITH pbp_players AS (
  SELECT DISTINCT
    p.game_date,
    p.game_id,
    p.player_1_lookup,
    p.player_1_team_abbr,
    COUNT(*) as pbp_events
  FROM `nba-props-platform.nba_raw.nbac_play_by_play` p
  WHERE p.game_date >= '2024-01-01'
    AND p.player_1_id IS NOT NULL
  GROUP BY p.game_date, p.game_id, p.player_1_lookup, p.player_1_team_abbr
),

boxscore_players AS (
  SELECT DISTINCT
    b.game_date,
    b.game_id,
    b.player_lookup,
    b.team_abbr,
    b.points as actual_points
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
  WHERE b.game_date >= '2024-01-01'
)

SELECT 
  b.game_date,
  b.game_id,
  b.team_abbr,
  b.player_lookup,
  b.actual_points,
  p.pbp_events,
  CASE 
    WHEN p.player_1_lookup IS NULL THEN '🔴 MISSING: No play-by-play events'
    WHEN p.pbp_events < 5 THEN '⚠️ WARNING: Very few events (<5)'
    WHEN p.pbp_events < 10 THEN '⚪ Low events (bench player likely)'
    ELSE '✅ Good coverage'
  END as coverage_status
FROM boxscore_players b
LEFT JOIN pbp_players p
  ON b.game_date = p.game_date
  AND b.game_id = p.game_id
  AND b.player_lookup = p.player_1_lookup
WHERE b.game_date >= '2024-01-01'
ORDER BY b.game_date DESC, b.team_abbr, b.actual_points DESC;
