-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/discovery/discovery_date_range.sql
-- Discovery Query 1: Actual Date Range & Volume
-- Purpose: Understand what data actually exists in nbac_player_list_current
-- ============================================================================

SELECT 
  -- When was data last updated?
  MIN(last_seen_date) as earliest_seen,
  MAX(last_seen_date) as latest_seen,
  MAX(processed_at) as last_processed_timestamp,
  
  -- Data volume
  COUNT(*) as total_records,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT team_abbr) as unique_teams,
  COUNT(DISTINCT player_id) as unique_player_ids,
  
  -- Current season
  MIN(season_year) as min_season,
  MAX(season_year) as max_season,
  
  -- Active vs inactive
  COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_players,
  COUNT(CASE WHEN is_active = FALSE THEN 1 END) as inactive_players,
  
  -- Data quality checks
  COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as null_teams,
  COUNT(CASE WHEN player_lookup IS NULL THEN 1 END) as null_player_lookup,
  COUNT(CASE WHEN player_id IS NULL THEN 1 END) as null_player_id
  
FROM `nba-props-platform.nba_raw.nbac_player_list_current`
WHERE season_year >= 2024;  -- Partition filter for current data