-- ============================================================================
-- MLB Multi-Model Architecture Migration
-- Add system_id column to pitcher_strikeouts table
-- ============================================================================
--
-- This migration adds support for multiple prediction systems running
-- concurrently (V1 baseline, V1.6 rolling, ensemble, etc.)
--
-- IMPORTANT: Run this migration before deploying multi-system worker
-- ============================================================================

-- Phase 2A: Add nullable system_id column
-- Safe to run while existing system is running
ALTER TABLE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
ADD COLUMN IF NOT EXISTS system_id STRING
OPTIONS (description = "Prediction system ID (v1_baseline, v1_6_rolling, ensemble_v1)");

-- Phase 2B: Backfill historical data (90 days)
-- Maps existing model_version strings to system_id
UPDATE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
SET system_id = CASE
    WHEN model_version LIKE '%v1_4%' THEN 'v1_baseline'
    WHEN model_version LIKE '%v1_6%' THEN 'v1_6_rolling'
    WHEN model_version LIKE '%ensemble%' THEN 'ensemble_v1'
    ELSE 'v1_baseline'  -- Default fallback
END
WHERE system_id IS NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY);

-- Phase 4: Make system_id required (run after dual-write period)
-- IMPORTANT: Only run this after 30 days of dual-write (both system_id and model_version populated)
-- ALTER TABLE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
-- ALTER COLUMN system_id SET NOT NULL;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify system_id distribution
SELECT
    system_id,
    COUNT(*) as prediction_count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY system_id
ORDER BY prediction_count DESC;

-- Check for NULL system_ids (should be empty after backfill)
SELECT COUNT(*) as null_system_ids
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id IS NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY);

-- Verify multiple systems per pitcher (Phase 2+)
SELECT
    game_date,
    pitcher_lookup,
    COUNT(DISTINCT system_id) as system_count,
    STRING_AGG(DISTINCT system_id ORDER BY system_id) as systems
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date, pitcher_lookup
HAVING COUNT(DISTINCT system_id) > 1
ORDER BY system_count DESC
LIMIT 10;
