-- ============================================================================
-- PRECOMPUTE FAILURES TABLE
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/processing/precompute_failures_table.sql
-- Purpose: Track individual entity failures during Phase 3/4 processing
-- Created: 2025-12-05 (Session 37: Schema Fixes)

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_failures` (
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  analysis_date DATE NOT NULL,
  entity_id STRING NOT NULL,
  failure_category STRING NOT NULL,
  failure_reason STRING NOT NULL,
  can_retry BOOLEAN NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY processor_name, failure_category, can_retry
OPTIONS (
  description = "Track individual entity failures during Phase 3/4 processing for debugging and retry logic. Categories: PLAYER_NOT_IN_REGISTRY (Phase 3), INSUFFICIENT_DATA, INCOMPLETE_DATA, MISSING_DEPENDENCY, PROCESSING_ERROR"
);
