-- ============================================================================
-- MIGRATION: Fix precompute_processor_runs Schema
-- ============================================================================
-- Purpose: Change 'success' field from REQUIRED to NULLABLE
-- Issue: Schema mismatch causing warnings in processor logs
-- Created: 2025-12-05 (Session 37: Schema Fixes)
-- Approach: Backup -> Drop -> Recreate -> Restore
--
-- SAFETY: This migration uses a backup/restore approach to prevent data loss
-- ============================================================================

-- Step 1: Create backup table with all current data
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_processor_runs_backup` AS
SELECT * FROM `nba-props-platform.nba_processing.precompute_processor_runs`;

-- Step 2: Drop the original table
DROP TABLE IF EXISTS `nba-props-platform.nba_processing.precompute_processor_runs`;

-- Step 3: Recreate table with correct schema (success NULLABLE)
CREATE TABLE `nba-props-platform.nba_processing.precompute_processor_runs` (
  -- Execution identifiers
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  run_date TIMESTAMP NOT NULL,

  -- Execution results (success now NULLABLE instead of REQUIRED)
  success BOOLEAN,                                  -- TRUE if processor completed successfully (NULLABLE)
  duration_seconds FLOAT64,

  -- Data processing scope (Phase 4 uses single analysis_date)
  analysis_date DATE,
  records_processed INT64,
  records_inserted INT64,
  records_updated INT64,
  records_skipped INT64,

  -- Dependency tracking (Phase 4 specific)
  dependency_check_passed BOOLEAN,
  data_completeness_pct FLOAT64,
  upstream_data_age_hours FLOAT64,

  -- Error tracking
  errors_json STRING,
  warning_count INT64,

  -- Resource usage
  bytes_processed INT64,
  slot_ms INT64,

  -- Processing metadata
  processor_version STRING,
  config_hash STRING,

  -- Pattern support (Pattern #1: Smart Skip, Pattern #3: Early Exit)
  skip_reason STRING,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(run_date)
CLUSTER BY processor_name, success, run_date
OPTIONS (
  description = "Precompute processor execution logs and performance tracking (Phase 4)",
  partition_expiration_days = 365
);

-- Step 4: Restore data from backup
INSERT INTO `nba-props-platform.nba_processing.precompute_processor_runs`
SELECT * FROM `nba-props-platform.nba_processing.precompute_processor_runs_backup`;

-- Step 5: Verify data restoration (count should match)
-- Run this manually to verify:
-- SELECT COUNT(*) as backup_count FROM `nba-props-platform.nba_processing.precompute_processor_runs_backup`;
-- SELECT COUNT(*) as restored_count FROM `nba-props-platform.nba_processing.precompute_processor_runs`;

-- Step 6: Drop backup table (only after verification!)
-- Uncomment this line after verifying data restoration:
-- DROP TABLE IF EXISTS `nba-props-platform.nba_processing.precompute_processor_runs_backup`;
