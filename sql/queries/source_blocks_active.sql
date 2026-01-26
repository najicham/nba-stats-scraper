-- Active Source Blocks by Date
--
-- Shows all currently blocked resources (unresolved) grouped by date and type.
-- Useful for: Daily monitoring of what data is unavailable from sources.

SELECT
  game_date,
  resource_type,
  COUNT(*) as blocked_count,
  STRING_AGG(resource_id, ', ' ORDER BY resource_id) as blocked_resources,
  STRING_AGG(DISTINCT source_system, ', ') as sources
FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
WHERE is_resolved = FALSE
  AND game_date >= CURRENT_DATE() - 7
GROUP BY game_date, resource_type
ORDER BY game_date DESC, resource_type;
