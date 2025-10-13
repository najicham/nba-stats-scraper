-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/discovery/discovery_team_distribution.sql
-- Discovery Query 2: Team Distribution & Balance
-- Purpose: Understand player distribution across teams
-- ============================================================================

SELECT 
  team_abbr,
  COUNT(*) as total_players,
  COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_players,
  COUNT(CASE WHEN is_active = FALSE THEN 1 END) as inactive_players,
  COUNT(DISTINCT position) as unique_positions,
  
  -- Check for reasonable data
  MIN(last_seen_date) as oldest_update,
  MAX(last_seen_date) as newest_update,
  
  -- Status distribution
  STRING_AGG(DISTINCT roster_status ORDER BY roster_status) as roster_statuses
  
FROM `nba-props-platform.nba_raw.nbac_player_list_current`
WHERE season_year >= 2024  -- Partition filter
GROUP BY team_abbr
ORDER BY team_abbr;
