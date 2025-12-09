-- ============================================================================
-- ENHANCED FAILURE TRACKING SCHEMA
-- ============================================================================
-- Location: schemas/bigquery/processing/enhanced_failure_tracking.sql
-- Purpose: Add DNP vs Data Gap classification to failure tracking
-- Created: 2025-12-09
-- Related: docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md

-- ============================================================================
-- PHASE 1: Update precompute_failures table with new columns
-- ============================================================================

-- Add failure_type column to distinguish DNP from data gaps
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS failure_type STRING;
-- Values: 'PLAYER_DNP', 'DATA_GAP', 'PROCESSING_ERROR', 'MIXED', 'UNKNOWN'

-- Add is_correctable flag
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS is_correctable BOOL;
-- TRUE = can be fixed by re-ingesting data
-- FALSE = permanent (DNP, player didn't play)

-- Add expected game count from schedule
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS expected_game_count INT64;

-- Add actual game count found
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS actual_game_count INT64;

-- Add missing game dates as JSON array
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS missing_game_dates STRING;
-- JSON array of dates: '["2021-12-19", "2021-12-20"]'

-- Add flag indicating if we checked raw box scores
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS raw_data_checked BOOL;

-- Add resolution status tracking
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS resolution_status STRING DEFAULT 'UNRESOLVED';
-- Values: 'UNRESOLVED', 'RESOLVED', 'PERMANENT', 'INVESTIGATING'

-- Add resolution timestamp
ALTER TABLE `nba-props-platform.nba_processing.precompute_failures`
ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;

-- ============================================================================
-- PHASE 2: Create Phase 3 (Analytics) failure tracking table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.analytics_failures` (
  -- Identifiers
  processor_name STRING NOT NULL,         -- e.g., 'PlayerGameSummaryProcessor'
  run_id STRING NOT NULL,                 -- Unique run identifier
  analysis_date DATE NOT NULL,            -- Date being processed
  entity_id STRING NOT NULL,              -- player_lookup, team_abbr, or game_id
  entity_type STRING NOT NULL,            -- 'PLAYER', 'TEAM', 'GAME'

  -- Failure classification
  failure_category STRING NOT NULL,       -- 'MISSING_RAW_DATA', 'PROCESSING_ERROR', 'VALIDATION_FAILED'
  failure_reason STRING NOT NULL,         -- Human-readable description
  failure_type STRING,                    -- 'DATA_GAP', 'EXPECTED_NO_DATA', 'BUG'
  is_correctable BOOL,                    -- TRUE = can be fixed by re-ingesting

  -- Context
  expected_record_count INT64,            -- Expected records from raw data
  actual_record_count INT64,              -- Actual records found
  missing_game_ids STRING,                -- JSON array of missing game IDs

  -- Resolution tracking
  can_retry BOOL NOT NULL,                -- Whether the failure can be retried
  resolution_status STRING DEFAULT 'UNRESOLVED',
  resolved_at TIMESTAMP,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY processor_name, failure_category, can_retry
OPTIONS (
  description = "Track individual entity failures during Phase 3 analytics processing"
);

-- ============================================================================
-- PHASE 3: Create Phase 5 (Predictions) failure tracking table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.prediction_failures` (
  -- Identifiers
  processor_name STRING NOT NULL,         -- e.g., 'PointsPredictionProcessor'
  run_id STRING NOT NULL,                 -- Unique run identifier
  prediction_date DATE NOT NULL,          -- Date of prediction
  entity_id STRING NOT NULL,              -- player_lookup

  -- Failure classification
  failure_category STRING NOT NULL,       -- 'MISSING_CACHE', 'STALE_CACHE', 'MODEL_ERROR'
  failure_reason STRING NOT NULL,         -- Human-readable description
  failure_type STRING,                    -- 'UPSTREAM_GAP', 'PROCESSING_ERROR'
  is_correctable BOOL,                    -- TRUE = can be fixed by reprocessing upstream

  -- Upstream dependencies
  missing_upstream_tables STRING,         -- JSON array of missing dependencies
  cache_age_hours FLOAT64,                -- How old the cache was (NULL = missing)

  -- Resolution tracking
  can_retry BOOL NOT NULL,
  resolution_status STRING DEFAULT 'UNRESOLVED',
  resolved_at TIMESTAMP,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY prediction_date
CLUSTER BY processor_name, failure_category, can_retry
OPTIONS (
  description = "Track individual entity failures during Phase 5 prediction processing"
);

-- ============================================================================
-- VIEWS FOR FAILURE TRIAGE
-- ============================================================================

-- View: Correctable failures that need investigation
CREATE OR REPLACE VIEW `nba-props-platform.nba_processing.correctable_failures` AS
SELECT
  processor_name,
  analysis_date,
  failure_type,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT entity_id LIMIT 10) as sample_entities
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE failure_type = 'DATA_GAP'
  AND is_correctable = TRUE
  AND resolution_status = 'UNRESOLVED'
GROUP BY processor_name, analysis_date, failure_type
ORDER BY analysis_date DESC;

-- View: Permanent failures (DNP - no action needed)
CREATE OR REPLACE VIEW `nba-props-platform.nba_processing.permanent_failures` AS
SELECT
  processor_name,
  analysis_date,
  failure_type,
  COUNT(*) as failure_count
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE failure_type = 'PLAYER_DNP'
  AND is_correctable = FALSE
GROUP BY processor_name, analysis_date, failure_type
ORDER BY analysis_date DESC;

-- View: Failure summary by date and type
CREATE OR REPLACE VIEW `nba-props-platform.nba_processing.failure_summary` AS
SELECT
  analysis_date,
  processor_name,
  failure_category,
  COALESCE(failure_type, 'UNKNOWN') as failure_type,
  COALESCE(is_correctable, TRUE) as is_correctable,
  COUNT(*) as failure_count,
  COUNTIF(resolution_status = 'RESOLVED') as resolved_count,
  COUNTIF(resolution_status = 'UNRESOLVED') as unresolved_count
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY analysis_date, processor_name, failure_category, failure_type, is_correctable
ORDER BY analysis_date DESC, processor_name;
