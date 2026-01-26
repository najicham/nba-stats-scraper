-- Source Block Resolution Tracking
--
-- Shows blocks that were resolved and how long they were blocked.
-- Useful for: Understanding if blocks are temporary or permanent.

SELECT
  resource_id,
  resource_type,
  game_date,
  source_system,
  block_type,
  first_detected_at,
  resolved_at,
  TIMESTAMP_DIFF(resolved_at, first_detected_at, HOUR) as hours_blocked,
  verification_count,
  resolution_notes,
  SUBSTR(notes, 1, 100) as original_notes
FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
WHERE is_resolved = TRUE
  AND resolved_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
ORDER BY resolved_at DESC
LIMIT 50;
