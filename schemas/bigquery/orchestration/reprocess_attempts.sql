-- ============================================================================
-- NBA Props Platform - Reprocess Attempts Tracking
-- Circuit Breaker Implementation for Historical Completeness Checking
-- ============================================================================
-- Table: nba_orchestration.reprocess_attempts
-- Purpose: Track reprocessing attempts per entity to prevent oscillation
-- Update: On-demand during processor runs
-- Retention: 365 days
--
-- Version: 1.0 (Initial implementation)
-- Date: November 2025
-- Status: Production-Ready
--
-- Related Documents:
-- - historical-dependency-checking-plan.md (full implementation guide)
-- - 11-phase3-phase4-completeness-implementation-plan.md (detailed plan)
-- ============================================================================

-- ============================================================================
-- TABLE DEFINITION
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.reprocess_attempts` (
  -- ============================================================================
  -- IDENTIFIERS (4 fields)
  -- ============================================================================
  processor_name STRING NOT NULL,                   -- Name of processor
                                                     -- Examples: 'team_defense_zone_analysis',
                                                     --           'player_daily_cache',
                                                     --           'upcoming_player_game_context'

  entity_id STRING NOT NULL,                        -- Entity being processed
                                                     -- Team: 'LAL', 'GSW', etc.
                                                     -- Player: 'LeBron James' (player_lookup)
                                                     -- Example: 'LAL'

  analysis_date DATE NOT NULL,                      -- Date being processed (partition key)
                                                     -- Example: '2024-11-22'

  attempt_number INT64 NOT NULL,                    -- Attempt sequence number
                                                     -- 1 = first retry
                                                     -- 2 = second retry
                                                     -- 3 = third retry (circuit breaker trips)
                                                     -- Example: 2

  -- ============================================================================
  -- ATTEMPT DETAILS (3 fields)
  -- ============================================================================
  attempted_at TIMESTAMP NOT NULL,                  -- When this attempt occurred
                                                     -- Example: '2025-11-22T23:00:00Z'

  completeness_pct FLOAT64,                         -- Completeness at time of attempt
                                                     -- Range: 0.0-100.0
                                                     -- Example: 73.3 (11/15 games)

  skip_reason STRING,                               -- Why processing was skipped
                                                     -- Examples: 'incomplete_upstream_data',
                                                     --           'circuit_breaker_active',
                                                     --           'early_season_placeholder'
                                                     -- NULL = processing succeeded
                                                     -- Example: 'incomplete_upstream_data'

  -- ============================================================================
  -- CIRCUIT BREAKER (3 fields)
  -- ============================================================================
  circuit_breaker_tripped BOOLEAN NOT NULL,         -- Did this attempt trip circuit breaker?
                                                     -- TRUE = attempt_number >= 3
                                                     -- FALSE = can still retry
                                                     -- Example: FALSE

  circuit_breaker_until TIMESTAMP,                  -- When circuit breaker expires
                                                     -- NULL = circuit breaker not tripped
                                                     -- Set to: attempted_at + 7 days
                                                     -- Example: '2025-11-29T23:00:00Z'

  manual_override_applied BOOLEAN,                  -- Was manual override used?
                                                     -- TRUE = admin manually reset circuit breaker
                                                     -- FALSE or NULL = normal processing
                                                     -- Example: FALSE

  -- ============================================================================
  -- METADATA (2 fields)
  -- ============================================================================
  notes STRING,                                      -- Optional notes about this attempt
                                                     -- Example: "Upstream missing games 2024-11-05, 2024-11-12"

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- Row creation timestamp
)
PARTITION BY analysis_date
CLUSTER BY processor_name, entity_id, analysis_date
OPTIONS(
  description="Tracks reprocessing attempts per entity for circuit breaker pattern. Prevents reprocessing oscillation by limiting max attempts to 3, with 7-day cooldown period. Updated on-demand during processor runs.",
  partition_expiration_days=365
);

-- ============================================================================
-- PRIMARY KEY CONSTRAINT
-- ============================================================================
-- Unique constraint: (processor_name, entity_id, analysis_date, attempt_number)
-- Enforced at application level (BigQuery doesn't support PRIMARY KEY)

-- ============================================================================
-- SCHEMA UPDATES (If Table Already Exists)
-- ============================================================================
-- No ALTER statements needed - this is a new table

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 12
--   - Identifiers: 4
--   - Attempt details: 3
--   - Circuit breaker: 3
--   - Metadata: 2

-- ============================================================================
-- SAMPLE ROW (First Attempt - Incomplete Data)
-- ============================================================================
/*
{
  -- Identifiers
  "processor_name": "team_defense_zone_analysis",
  "entity_id": "LAL",
  "analysis_date": "2024-11-22",
  "attempt_number": 1,

  -- Attempt details
  "attempted_at": "2024-11-22T23:00:00Z",
  "completeness_pct": 73.3,
  "skip_reason": "incomplete_upstream_data",

  -- Circuit breaker
  "circuit_breaker_tripped": false,
  "circuit_breaker_until": null,
  "manual_override_applied": false,

  -- Metadata
  "notes": "Missing 4 of 15 games from team_defense_game_summary",
  "created_at": "2024-11-22T23:00:05Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Third Attempt - Circuit Breaker Tripped)
-- ============================================================================
/*
{
  -- Identifiers
  "processor_name": "team_defense_zone_analysis",
  "entity_id": "LAL",
  "analysis_date": "2024-11-22",
  "attempt_number": 3,

  -- Attempt details
  "attempted_at": "2024-11-25T23:00:00Z",
  "completeness_pct": 80.0,
  "skip_reason": "incomplete_upstream_data",

  -- Circuit breaker (TRIPPED)
  "circuit_breaker_tripped": true,
  "circuit_breaker_until": "2024-12-02T23:00:00Z",  -- 7 days from now
  "manual_override_applied": false,

  -- Metadata
  "notes": "Circuit breaker TRIPPED - manual intervention required",
  "created_at": "2024-11-25T23:00:05Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Manual Override Applied)
-- ============================================================================
/*
{
  -- Identifiers
  "processor_name": "team_defense_zone_analysis",
  "entity_id": "LAL",
  "analysis_date": "2024-11-22",
  "attempt_number": 4,  -- After manual override

  -- Attempt details
  "attempted_at": "2024-12-03T10:00:00Z",
  "completeness_pct": 100.0,
  "skip_reason": null,  -- Processing succeeded

  -- Circuit breaker
  "circuit_breaker_tripped": false,
  "circuit_breaker_until": null,
  "manual_override_applied": true,

  -- Metadata
  "notes": "Manual override applied by admin after upstream data fixed",
  "created_at": "2024-12-03T10:00:05Z"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Active circuit breakers
-- Expected: 0 rows in normal operation
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  attempted_at,
  completeness_pct,
  circuit_breaker_until,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), HOUR) as hours_until_retry
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY circuit_breaker_until ASC;

-- Query 2: Recent reprocessing attempts
-- Shows all retry activity in last 7 days
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  attempted_at,
  completeness_pct,
  skip_reason,
  circuit_breaker_tripped
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY attempted_at DESC
LIMIT 100;

-- Query 3: Entities approaching circuit breaker
-- Expected: Few rows (ideally 0)
SELECT
  processor_name,
  entity_id,
  analysis_date,
  MAX(attempt_number) as max_attempts,
  MAX(completeness_pct) as latest_completeness,
  MAX(attempted_at) as last_attempt_at
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = FALSE
GROUP BY processor_name, entity_id, analysis_date
HAVING MAX(attempt_number) >= 2  -- 2 attempts, close to triggering
ORDER BY max_attempts DESC, last_attempt_at DESC;

-- Query 4: Circuit breaker trip rate
-- Shows how often circuit breakers are triggered
SELECT
  processor_name,
  COUNT(DISTINCT CONCAT(entity_id, '_', analysis_date)) as entities_processed,
  COUNTIF(circuit_breaker_tripped) as circuit_breakers_tripped,
  ROUND(COUNTIF(circuit_breaker_tripped) / COUNT(DISTINCT CONCAT(entity_id, '_', analysis_date)) * 100, 2) as trip_rate_pct
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY processor_name
ORDER BY trip_rate_pct DESC;

-- Query 5: Manual override history
-- Shows when admins had to intervene
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  attempted_at,
  completeness_pct,
  notes
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE manual_override_applied = TRUE
ORDER BY attempted_at DESC
LIMIT 50;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Current circuit breaker status per entity
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_circuit_breaker_status` AS
WITH latest_attempts AS (
  SELECT
    processor_name,
    entity_id,
    analysis_date,
    MAX(attempt_number) as max_attempt,
    ARRAY_AGG(
      STRUCT(
        attempt_number,
        attempted_at,
        completeness_pct,
        circuit_breaker_tripped,
        circuit_breaker_until
      )
      ORDER BY attempt_number DESC
      LIMIT 1
    )[OFFSET(0)] as latest
  FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
  GROUP BY processor_name, entity_id, analysis_date
)
SELECT
  processor_name,
  entity_id,
  analysis_date,
  max_attempt,
  latest.attempted_at as last_attempt_at,
  latest.completeness_pct as latest_completeness,
  latest.circuit_breaker_tripped as circuit_breaker_active,
  latest.circuit_breaker_until,
  CASE
    WHEN latest.circuit_breaker_tripped AND latest.circuit_breaker_until > CURRENT_TIMESTAMP()
    THEN TRUE
    ELSE FALSE
  END as currently_blocked,
  CASE
    WHEN latest.circuit_breaker_tripped AND latest.circuit_breaker_until > CURRENT_TIMESTAMP()
    THEN TIMESTAMP_DIFF(latest.circuit_breaker_until, CURRENT_TIMESTAMP(), HOUR)
    ELSE 0
  END as hours_until_retry
FROM latest_attempts
WHERE latest.circuit_breaker_tripped = TRUE
   OR max_attempt >= 2  -- Include entities with 2+ attempts
ORDER BY currently_blocked DESC, max_attempt DESC, last_attempt_at DESC;

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- CIRCUIT BREAKER LOGIC:
--   - Attempt 1: Retry allowed, no cooldown
--   - Attempt 2: Retry allowed, no cooldown
--   - Attempt 3: Circuit breaker TRIPS, 7-day cooldown enforced
--   - Manual override: Admin can reset circuit breaker before cooldown expires
--
-- PROCESSOR INTEGRATION:
--   Before processing each entity:
--   1. Query latest attempt for (processor, entity, date)
--   2. If attempt_number >= 3 AND circuit_breaker_until > NOW: SKIP
--   3. If processing fails: INSERT new attempt row
--   4. If attempt_number == 3: Set circuit_breaker_tripped = TRUE
--
-- MONITORING:
--   - Alert if any circuit breakers tripped (manual intervention needed)
--   - Alert if trip_rate > 5% (systemic upstream data issues)
--   - Alert if same entity has 2+ attempts across multiple dates
--
-- MANUAL OVERRIDE PROCESS:
--   1. Admin investigates why circuit breaker tripped
--   2. Admin fixes upstream data issue
--   3. Admin triggers manual reprocessing with override flag
--   4. System inserts attempt_number = N+1 with manual_override_applied = TRUE
--
-- CLEANUP:
--   - Partition expiration: 365 days
--   - Old circuit breakers automatically expire after cooldown period
--   - Historical attempts preserved for audit trail
--
-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
