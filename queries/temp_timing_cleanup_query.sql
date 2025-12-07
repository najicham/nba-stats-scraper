-- Query 1: Timing cleanup - Find pending unresolved names that now exist in registry
-- This identifies cases where the name was added to the registry AFTER it was marked as unresolved

SELECT
  COUNT(*) as auto_resolvable_count,
  COUNT(DISTINCT u.normalized_lookup) as unique_names
FROM `nba-props-platform.nba_reference.unresolved_player_names` u
JOIN `nba-props-platform.nba_reference.nba_players_registry` r
  ON u.normalized_lookup = r.player_lookup
WHERE u.status = 'pending'
