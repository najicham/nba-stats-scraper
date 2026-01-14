-- Add failure_category field to processor_run_history
-- Purpose: Categorize failures to distinguish expected (no_data_available) from real errors
-- This enables filtering out expected failures from monitoring alerts, reducing noise by 90%+
--
-- Created: 2026-01-14
-- Session: 35
--
-- Categories:
--   - no_data_available: Expected scenario - no games scheduled, off-season, etc.
--   - upstream_failure: Dependency failed or missing
--   - processing_error: Real error in processing logic
--   - timeout: Operation timed out
--   - configuration_error: Missing required options or invalid configuration
--   - unknown: Default for backward compatibility / unclassified errors

-- Step 1: Add the failure_category column
ALTER TABLE `nba-props-platform.nba_reference.processor_run_history`
ADD COLUMN IF NOT EXISTS failure_category STRING
OPTIONS(description='Category of failure: no_data_available, upstream_failure, processing_error, timeout, configuration_error, unknown. Used to filter expected failures from monitoring alerts.');

-- Step 2: Backfill existing failed records with 'unknown' category
-- This ensures backward compatibility - existing failures are categorized but not filtered out
UPDATE `nba-props-platform.nba_reference.processor_run_history`
SET failure_category = 'unknown'
WHERE failure_category IS NULL
  AND status = 'failed';

-- Step 3: Verify the migration
SELECT
  failure_category,
  COUNT(*) as count
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
GROUP BY failure_category
ORDER BY count DESC;
