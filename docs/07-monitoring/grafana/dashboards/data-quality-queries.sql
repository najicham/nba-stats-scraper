-- ============================================================================
-- DATA QUALITY MONITORING DASHBOARD
-- ============================================================================
-- Purpose: BigQuery queries for monitoring player name resolution and circuit breakers
-- Tables: nba_reference.unresolved_player_names, nba_orchestration.circuit_breaker_state
-- Last Updated: 2025-11-30
-- ============================================================================

-- ============================================================================
-- QUERY 1: Overall Data Quality Health Status
-- ============================================================================
-- Returns: HEALTHY, WARNING, or CRITICAL based on thresholds
-- Use for: Main health indicator stat panel
-- ============================================================================

WITH metrics AS (
  SELECT
    (SELECT COUNT(*) FROM `nba-props-platform.nba_reference.unresolved_player_names` WHERE status = 'pending') as unresolved_count,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_orchestration.circuit_breaker_state` WHERE state = 'OPEN') as open_breakers
)
SELECT
  CASE
    WHEN open_breakers > 5 OR unresolved_count > 100 THEN 'CRITICAL'
    WHEN open_breakers > 0 OR unresolved_count > 50 THEN 'WARNING'
    ELSE 'HEALTHY'
  END as health_status,
  unresolved_count,
  open_breakers
FROM metrics;


-- ============================================================================
-- QUERY 2: Unresolved Player Names Count
-- ============================================================================
-- Returns: Total count of pending unresolved names
-- Use for: Stat panel with trend
-- ============================================================================

SELECT COUNT(*) as unresolved_count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending' OR status IS NULL;


-- ============================================================================
-- QUERY 3: Circuit Breaker Counts by State
-- ============================================================================
-- Returns: Count of circuit breakers in each state
-- Use for: Multiple stat panels
-- ============================================================================

SELECT
  state,
  COUNT(*) as breaker_count
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
GROUP BY state
ORDER BY
  CASE state
    WHEN 'OPEN' THEN 1
    WHEN 'HALF_OPEN' THEN 2
    ELSE 3
  END;


-- ============================================================================
-- QUERY 4: Unresolved Names by Source
-- ============================================================================
-- Returns: Breakdown of unresolved names by data source
-- Use for: Table panel with source-level detail
-- ============================================================================

SELECT
  source,
  COUNT(*) as unresolved_count,
  COUNT(DISTINCT team_abbr) as teams_affected,
  MIN(first_seen_date) as earliest_seen,
  MAX(last_seen_date) as latest_seen,
  SUM(occurrences) as total_occurrences
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending' OR status IS NULL
GROUP BY source
ORDER BY unresolved_count DESC;


-- ============================================================================
-- QUERY 5: Circuit Breaker State Details
-- ============================================================================
-- Returns: Detailed view of circuit breakers with failures
-- Use for: Table panel showing non-healthy breakers
-- ============================================================================

SELECT
  processor_name,
  state,
  failure_count,
  success_count,
  last_failure,
  last_success,
  updated_at,
  SUBSTR(last_error_message, 1, 100) as last_error_preview,
  last_error_type
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE state != 'CLOSED' OR failure_count > 0
ORDER BY
  CASE state
    WHEN 'OPEN' THEN 1
    WHEN 'HALF_OPEN' THEN 2
    ELSE 3
  END,
  failure_count DESC
LIMIT 30;


-- ============================================================================
-- QUERY 6: New Unresolved Names Over Time
-- ============================================================================
-- Returns: Time series of new unresolved names by source
-- Use for: Stacked bar chart showing discovery trend
-- ============================================================================

SELECT
  TIMESTAMP(first_seen_date) as time,
  source as metric,
  COUNT(*) as value
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE first_seen_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY first_seen_date, source
ORDER BY time, source;


-- ============================================================================
-- QUERY 7: Unresolved Names Detail (Top by Occurrences)
-- ============================================================================
-- Returns: Detailed list of unresolved names sorted by impact
-- Use for: Table panel for manual review
-- ============================================================================

SELECT
  original_name,
  normalized_lookup,
  source,
  team_abbr,
  season,
  occurrences,
  first_seen_date,
  last_seen_date,
  status,
  notes
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending' OR status IS NULL
ORDER BY occurrences DESC, last_seen_date DESC
LIMIT 50;


-- ============================================================================
-- QUERY 8: Circuit Breaker State Changes Over Time
-- ============================================================================
-- Returns: Time series of circuit breaker state changes
-- Use for: Line chart showing stability
-- ============================================================================

SELECT
  TIMESTAMP_TRUNC(updated_at, DAY) as time,
  state as metric,
  COUNT(*) as value
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY TIMESTAMP_TRUNC(updated_at, DAY), state
ORDER BY time, state;


-- ============================================================================
-- QUERY 9: Resolution Activity (Last 30 Days)
-- ============================================================================
-- Returns: Names resolved by reviewer and resolution type
-- Use for: Table showing resolution progress
-- ============================================================================

SELECT
  COALESCE(reviewed_by, 'auto') as reviewer,
  resolution_type,
  COUNT(*) as resolved_count,
  MAX(reviewed_at) as last_resolved
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'resolved'
  AND reviewed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY reviewed_by, resolution_type
ORDER BY resolved_count DESC;


-- ============================================================================
-- QUERY 10: Name Resolution Summary
-- ============================================================================
-- Returns: Overall resolution statistics
-- Use for: Summary table with resolution rate
-- ============================================================================

WITH stats AS (
  SELECT
    COUNT(*) as total_names,
    COUNTIF(status = 'resolved') as resolved,
    COUNTIF(status = 'pending' OR status IS NULL) as pending,
    COUNTIF(status = 'ignored') as ignored,
    COUNTIF(status = 'snoozed') as snoozed
  FROM `nba-props-platform.nba_reference.unresolved_player_names`
)
SELECT
  total_names,
  resolved,
  pending,
  ignored,
  snoozed,
  ROUND(resolved * 100.0 / NULLIF(total_names, 0), 1) as resolution_rate
FROM stats;


-- ============================================================================
-- QUERY 11: Player Alias Coverage
-- ============================================================================
-- Returns: Count of player aliases by source
-- Use for: Understanding alias coverage
-- ============================================================================

SELECT
  COUNT(*) as total_aliases,
  COUNT(DISTINCT nba_canonical_lookup) as unique_players
FROM `nba-props-platform.nba_reference.player_aliases`;


-- ============================================================================
-- QUERY 12: Recent Name Discoveries (Last 7 Days)
-- ============================================================================
-- Returns: Newly discovered unresolved names
-- Use for: Monitoring new issues
-- ============================================================================

SELECT
  original_name,
  source,
  team_abbr,
  first_seen_date,
  occurrences
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE first_seen_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND (status = 'pending' OR status IS NULL)
ORDER BY first_seen_date DESC, occurrences DESC
LIMIT 20;


-- ============================================================================
-- ALERT QUERIES
-- ============================================================================

-- Alert 1: Critical Unresolved Count
-- Alert if pending unresolved names > 100
SELECT COUNT(*) as critical_count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending' OR status IS NULL
HAVING critical_count > 100;


-- Alert 2: Open Circuit Breakers
-- Alert if any circuit breakers are OPEN
SELECT COUNT(*) as open_count
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE state = 'OPEN'
HAVING open_count > 0;


-- Alert 3: High-Occurrence Unresolved Name
-- Alert if any single name has > 100 occurrences
SELECT original_name, occurrences
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE (status = 'pending' OR status IS NULL)
  AND occurrences > 100
LIMIT 5;


-- Alert 4: Stale Circuit Breaker
-- Alert if circuit breaker hasn't been updated in 24 hours
SELECT processor_name, state, updated_at
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE state IN ('OPEN', 'HALF_OPEN')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), updated_at, HOUR) > 24;


-- ============================================================================
-- EXPECTED PATTERNS
-- ============================================================================
--
-- Healthy State:
--   - Unresolved names < 50
--   - No OPEN circuit breakers
--   - Resolution rate > 90%
--
-- Warning State:
--   - Unresolved names 50-100
--   - 1-2 HALF_OPEN circuit breakers
--   - Resolution rate 80-90%
--
-- Critical State:
--   - Unresolved names > 100
--   - Any OPEN circuit breakers
--   - Resolution rate < 80%
--
-- Common Sources of Unresolved Names:
--   - nbac_gamebook: NBA.com player names with special characters
--   - bdl_boxscores: Ball Don't Lie API name variations
--   - espn_rosters: ESPN roster data with different naming
--   - br_season_roster: Basketball Reference name formats
--
-- ============================================================================
