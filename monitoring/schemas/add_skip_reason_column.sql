-- ============================================================================
-- MIGRATION: Add skip_reason column to analytics_processor_runs
-- Pattern #1 (Smart Skip) and Pattern #3 (Early Exit)
-- ============================================================================
-- Purpose: Track why processing was skipped for Pattern #1 and #3
-- Applies to: Phase 3 (Analytics) processors
--
-- Usage: bq query --use_legacy_sql=false < monitoring/schemas/add_skip_reason_column.sql

ALTER TABLE `nba-props-platform.nba_processing.analytics_processor_runs`
ADD COLUMN IF NOT EXISTS skip_reason STRING;

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT
  column_name,
  data_type
FROM `nba-props-platform.nba_processing.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'analytics_processor_runs'
  AND column_name = 'skip_reason';
