-- ============================================================================
-- MIGRATION: Create precompute_processor_runs table
-- Phase 4 Processor Execution Tracking
-- ============================================================================
-- Purpose: Track Phase 4 precompute processor execution for monitoring and debugging
--          (Currently precompute_base.py tries to write to this table but it doesn't exist!)
--
-- Usage: bq query --use_legacy_sql=false < monitoring/schemas/create_precompute_processor_runs_table.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_processor_runs` (
  -- Execution identifiers
  processor_name STRING NOT NULL,                   -- Name of the precompute processor
  run_id STRING NOT NULL,                           -- Unique run identifier
  run_date TIMESTAMP NOT NULL,                      -- When the processor was executed

  -- Execution results
  success BOOLEAN NOT NULL,                         -- TRUE if processor completed successfully
  duration_seconds FLOAT64,                         -- Total execution time

  -- Data processing scope (Phase 4 uses single analysis_date)
  analysis_date DATE,                               -- Date being analyzed
  records_processed INT64,                          -- Number of records processed
  records_inserted INT64,                           -- Number of new records inserted
  records_updated INT64,                            -- Number of existing records updated
  records_skipped INT64,                            -- Number of records skipped (duplicates, etc.)

  -- Dependency tracking (Phase 4 specific)
  dependency_check_passed BOOLEAN,                  -- TRUE if all dependencies met
  data_completeness_pct FLOAT64,                    -- Percentage of expected upstream data present (0-100)
  upstream_data_age_hours FLOAT64,                  -- Hours since upstream data was last updated

  -- Error tracking
  errors_json STRING,                               -- JSON array of error messages
  warning_count INT64,                              -- Number of non-fatal warnings

  -- Resource usage
  bytes_processed INT64,                            -- Bytes of source data processed
  slot_ms INT64,                                    -- BigQuery slot milliseconds used

  -- Processing metadata
  processor_version STRING,                         -- Version of processor code
  config_hash STRING,                               -- Hash of processor configuration

  -- Pattern support (Pattern #1: Smart Skip, Pattern #3: Early Exit)
  skip_reason STRING,                               -- Why processing was skipped (e.g., 'no_games', 'irrelevant_source', 'offseason', 'historical')

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- When record was created
)
PARTITION BY DATE(run_date)
CLUSTER BY processor_name, success, run_date
OPTIONS (
  description = "Precompute processor execution logs and performance tracking (Phase 4)",
  partition_expiration_days = 365  -- 1 year retention for processing logs
);

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT
  table_name,
  CONCAT('Created at: ', CAST(creation_time AS STRING)) as status
FROM `nba-props-platform.nba_processing.INFORMATION_SCHEMA.TABLES`
WHERE table_name = 'precompute_processor_runs';
