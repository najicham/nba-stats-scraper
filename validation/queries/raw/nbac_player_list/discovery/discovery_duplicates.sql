-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/discovery/discovery_duplicates.sql
-- Discovery Query 3: Duplicate Detection & Data Quality
-- Purpose: Find any duplicate player_lookup values or data quality issues
-- ============================================================================

WITH player_counts AS (
  SELECT 
    player_lookup,
    COUNT(*) as occurrence_count,
    STRING_AGG(DISTINCT team_abbr ORDER BY team_abbr) as teams,
    STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name) as names
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
  GROUP BY player_lookup
  HAVING COUNT(*) > 1  -- Only show duplicates
)

SELECT 
  player_lookup,
  occurrence_count,
  teams as appears_on_teams,
  names as full_names
FROM player_counts
ORDER BY occurrence_count DESC, player_lookup;

-- Expected: Should return 0 rows (no duplicates on primary key)