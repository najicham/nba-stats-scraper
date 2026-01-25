-- Game ID Mappings View
-- Provides canonical mapping between NBA game_id format and BDL YYYYMMDD_AWAY_HOME format
--
-- Problem: Different data sources use different game_id formats:
--   - NBA Schedule: 0022500XXX (10-digit NBA official code)
--   - BDL Boxscores: YYYYMMDD_AWAY_HOME (e.g., 20260115_MEM_ORL)
--
-- This view creates a lookup between both formats for reliable cross-source joins.
--
-- Usage:
--   SELECT *
--   FROM `nba-props-platform.nba_raw.v_game_id_mappings`
--   WHERE game_date = '2026-01-15'
--
-- Join example:
--   SELECT b.*
--   FROM `nba_raw.bdl_player_boxscores` b
--   JOIN `nba_raw.v_game_id_mappings` m ON b.game_id = m.bdl_game_id
--   WHERE m.nba_game_id = '0022500578'
--
-- Created: 2026-01-25
-- Part of: Pipeline Resilience Improvements

CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.v_game_id_mappings` AS
SELECT
  -- NBA Official game_id (10-digit code)
  game_id AS nba_game_id,

  -- BDL format game_id (YYYYMMDD_AWAY_HOME)
  CONCAT(
    FORMAT_DATE('%Y%m%d', game_date),
    '_',
    away_team_tricode,
    '_',
    home_team_tricode
  ) AS bdl_game_id,

  -- Game identification fields
  game_date,
  game_code,
  away_team_tricode,
  home_team_tricode,
  away_team_id,
  home_team_id,
  away_team_name,
  home_team_name,

  -- Game metadata
  game_status,
  CASE game_status
    WHEN 1 THEN 'Scheduled'
    WHEN 2 THEN 'In Progress'
    WHEN 3 THEN 'Final'
    ELSE 'Unknown'
  END AS game_status_name,

  -- Season information
  season_year

FROM `nba-props-platform.nba_raw.v_nbac_schedule_latest`

-- Only include regular/playoff games (not preseason, all-star, etc.)
WHERE season_year >= 2024
;

-- Optional: Add a description
-- COMMENT ON VIEW `nba-props-platform.nba_raw.v_game_id_mappings` IS
--   'Canonical game ID mapping between NBA (0022500XXX) and BDL (YYYYMMDD_AWAY_HOME) formats';
