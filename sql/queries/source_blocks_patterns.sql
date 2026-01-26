-- Source Block Patterns Over Time
--
-- Analyzes blocking patterns to identify systemic issues.
-- Shows: which sources block most, which resources, when blocks occur.
-- Useful for: Identifying if specific sources/resources are problematic.

SELECT
  source_system,
  resource_type,
  COUNT(DISTINCT resource_id) as unique_resources_blocked,
  COUNT(DISTINCT game_date) as days_affected,
  SUM(verification_count) as total_verifications,
  STRING_AGG(DISTINCT block_type, ', ') as block_types,
  MIN(first_detected_at) as earliest_block,
  MAX(last_verified_at) as latest_verification,
  SUM(CASE WHEN is_resolved THEN 1 ELSE 0 END) as resolved_count,
  SUM(CASE WHEN is_resolved THEN 0 ELSE 1 END) as active_count
FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
WHERE first_detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY source_system, resource_type
ORDER BY unique_resources_blocked DESC, days_affected DESC;
