-- ============================================================================
-- PRECOMPUTE FAILURES TABLE (ENHANCED)
-- ============================================================================
-- Location: schemas/bigquery/processing/precompute_failures_table.sql
-- Purpose: Track individual entity failures during Phase 3/4 processing
-- Created: 2025-12-05 (Session 37: Schema Fixes)
-- Updated: 2025-12-09 (Session 89: Enhanced Failure Tracking)
--
-- Enhancement: Added DNP vs Data Gap classification to support failure triage
-- Related: docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_failures` (
  -- Core identifiers
  processor_name STRING NOT NULL,           -- e.g., 'PlayerDailyCacheProcessor'
  run_id STRING NOT NULL,                   -- Unique run identifier
  analysis_date DATE NOT NULL,              -- Date being processed
  entity_id STRING NOT NULL,                -- player_lookup, team_abbr, or game_id

  -- Basic failure info (original columns)
  failure_category STRING NOT NULL,         -- 'INSUFFICIENT_DATA', 'INCOMPLETE_DATA', 'PROCESSING_ERROR', etc.
  failure_reason STRING NOT NULL,           -- Human-readable description
  can_retry BOOLEAN NOT NULL,               -- Whether the failure can be retried

  -- Enhanced classification (added 2025-12-09)
  failure_type STRING,                      -- 'PLAYER_DNP', 'DATA_GAP', 'PROCESSING_ERROR', 'MIXED', 'UNKNOWN'
  is_correctable BOOL,                      -- TRUE = can be fixed by re-ingesting data, FALSE = permanent (DNP)

  -- Game count context (added 2025-12-09)
  expected_game_count INT64,                -- Expected games from schedule
  actual_game_count INT64,                  -- Actual games found in data
  missing_game_dates STRING,                -- JSON array of missing dates: '["2021-12-19", "2021-12-20"]'
  raw_data_checked BOOL,                    -- Whether we checked raw box scores for DNP detection

  -- Resolution tracking (added 2025-12-09)
  resolution_status STRING DEFAULT 'UNRESOLVED',  -- 'UNRESOLVED', 'RESOLVED', 'PERMANENT', 'INVESTIGATING'
  resolved_at TIMESTAMP,                    -- When the issue was resolved

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY processor_name, failure_category, can_retry
OPTIONS (
  description = "Track individual entity failures during Phase 3/4 precompute processing. Enhanced with DNP vs Data Gap classification for failure triage. Categories: INSUFFICIENT_DATA, INCOMPLETE_DATA, EXPECTED_INCOMPLETE, INCOMPLETE_UPSTREAM, MISSING_DEPENDENCY, PROCESSING_ERROR, CIRCUIT_BREAKER_ACTIVE"
);
