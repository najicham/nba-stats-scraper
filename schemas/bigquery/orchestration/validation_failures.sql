-- ============================================================================
-- NBA Props Platform - Validation Failures Table
-- Data Quality Self-Healing System
-- ============================================================================
-- Table: nba_orchestration.validation_failures
-- Purpose: Records blocked by pre-write validation for investigation
-- Update: Real-time when validation blocks records
-- Retention: 90 days
--
-- Version: 1.0 (Initial implementation)
-- Date: January 2026
-- Status: Production-Ready
--
-- Related Documents:
-- - docs/08-projects/current/data-quality-self-healing/README.md
-- - shared/validation/pre_write_validator.py
-- ============================================================================

-- ============================================================================
-- TABLE DEFINITION
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.validation_failures` (
  -- ============================================================================
  -- IDENTIFIERS (2 fields)
  -- ============================================================================
  failure_id STRING NOT NULL,                       -- Unique failure ID (UUID)
                                                     -- Example: '550e8400-e29b-41d4-a716-446655440000'

  failure_timestamp TIMESTAMP NOT NULL,             -- When validation failed
                                                     -- Example: '2026-01-30T10:00:00Z'

  -- ============================================================================
  -- CONTEXT (5 fields)
  -- ============================================================================
  table_name STRING NOT NULL,                       -- Target table name
                                                     -- Example: 'player_game_summary'

  processor_name STRING,                            -- Processor class name
                                                     -- Example: 'PlayerGameSummaryProcessor'

  game_date DATE,                                   -- Game date if applicable
                                                     -- Example: '2026-01-22'

  player_lookup STRING,                             -- Player lookup if applicable
                                                     -- Example: 'LeBron James'

  game_id STRING,                                   -- Game ID if applicable
                                                     -- Example: '20260122_LAL_GSW'

  -- ============================================================================
  -- FAILURE DETAILS (2 fields)
  -- ============================================================================
  violations ARRAY<STRING>,                         -- List of rule violations
                                                     -- Example: ['dnp_null_points: DNP players must have NULL points']

  record_json STRING,                               -- Full record as JSON for debugging
                                                     -- Truncated to 10KB max
                                                     -- Example: '{"player_lookup": "LeBron James", "is_dnp": true, "points": 0}'

  -- ============================================================================
  -- METADATA (3 fields)
  -- ============================================================================
  session_id STRING,                                -- Processing session ID
                                                     -- Example: 'session_20260130_100000'

  environment STRING DEFAULT 'production',          -- Environment
                                                     -- Values: 'production', 'staging', 'dev'

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() -- Row creation timestamp
)
PARTITION BY DATE(failure_timestamp)
CLUSTER BY table_name, game_date
OPTIONS(
  description="Records blocked by pre-write validation. Used to investigate validation issues and tune rules.",
  partition_expiration_days=90
);

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Recent validation failures by table
SELECT
  DATE(failure_timestamp) as failure_date,
  table_name,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT violations[SAFE_OFFSET(0)] LIMIT 5) as sample_violations
FROM `nba-props-platform.nba_orchestration.validation_failures`
WHERE failure_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;

-- Query 2: Failure details for specific date
SELECT
  failure_timestamp,
  player_lookup,
  game_date,
  violations,
  JSON_EXTRACT_SCALAR(record_json, '$.is_dnp') as is_dnp,
  JSON_EXTRACT_SCALAR(record_json, '$.points') as points,
  JSON_EXTRACT_SCALAR(record_json, '$.minutes') as minutes
FROM `nba-props-platform.nba_orchestration.validation_failures`
WHERE game_date = @target_date
ORDER BY failure_timestamp DESC
LIMIT 100;

-- Query 3: Most common violations
SELECT
  violation,
  COUNT(*) as occurrence_count,
  ARRAY_AGG(DISTINCT table_name) as affected_tables
FROM `nba-props-platform.nba_orchestration.validation_failures`,
UNNEST(violations) as violation
WHERE failure_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY violation
ORDER BY occurrence_count DESC
LIMIT 20;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
