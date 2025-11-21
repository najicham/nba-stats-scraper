-- ============================================================================
-- MIGRATION: Add skip_reason column to processor_runs
-- Pattern #1 (Smart Skip) and Pattern #3 (Early Exit)
-- ============================================================================
-- Purpose: Track why processing was skipped for Pattern #1 and #3
-- Applies to: Phase 2 (Raw) processors
--
-- Usage: bq query --use_legacy_sql=false < monitoring/schemas/add_skip_reason_to_processor_runs.sql

ALTER TABLE `nba-props-platform.nba_processing.processor_runs`
ADD COLUMN IF NOT EXISTS skip_reason STRING;

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT
  column_name,
  data_type
FROM `nba-props-platform.nba_processing.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'processor_runs'
  AND column_name = 'skip_reason';
