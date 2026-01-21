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

-- Phase 2B: Backfill ALL historical data
-- Maps existing model_version strings to system_id
-- Note: All existing data is from backfills (Jan 2026), so backfill everything
UPDATE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
SET system_id = CASE
    -- V1 baseline (exact match)
    WHEN model_version = 'mlb_pitcher_strikeouts_v1_20260107' THEN 'v1_baseline'
    -- V1.4 baseline (pattern match for other V1.4 versions)
    WHEN model_version LIKE '%v1_4%' THEN 'v1_baseline'
    -- V1.6 rolling (exact match)
    WHEN model_version = 'mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149' THEN 'v1_6_rolling'
    -- V1.6 rolling (pattern match for other V1.6 versions)
    WHEN model_version LIKE '%v1_6%' THEN 'v1_6_rolling'
    -- Ensemble (if any exist)
    WHEN model_version LIKE '%ensemble%' THEN 'ensemble_v1'
    -- Default fallback for unknown versions
    ELSE 'unknown'
END
WHERE system_id IS NULL;

-- Phase 4: Make system_id required (run after dual-write period)
-- IMPORTANT: Only run this after 30 days of dual-write (both system_id and model_version populated)
-- ALTER TABLE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
-- ALTER COLUMN system_id SET NOT NULL;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- 1. Verify system_id distribution across ALL data
SELECT
    system_id,
    COUNT(*) as prediction_count,
    COUNT(DISTINCT pitcher_lookup) as unique_pitchers,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date,
    COUNT(DISTINCT game_date) as total_days
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY system_id
ORDER BY prediction_count DESC;

-- 2. Check for NULL or 'unknown' system_ids (should be 0)
SELECT
    COALESCE(system_id, 'NULL') as system_id_status,
    COUNT(*) as count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id IS NULL OR system_id = 'unknown'
GROUP BY system_id;

-- 3. Verify model_version → system_id mapping
SELECT
    model_version,
    system_id,
    COUNT(*) as count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY model_version, system_id
ORDER BY count DESC;

-- 4. Check if pitchers have multiple systems (from backfills)
SELECT
    game_date,
    pitcher_lookup,
    COUNT(DISTINCT system_id) as system_count,
    STRING_AGG(DISTINCT system_id ORDER BY system_id) as systems
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= '2025-09-20'  -- Recent games
GROUP BY game_date, pitcher_lookup
HAVING COUNT(DISTINCT system_id) > 1
ORDER BY game_date DESC, pitcher_lookup
LIMIT 20;

-- 5. Summary statistics
SELECT
    'Total Predictions' as metric,
    CAST(COUNT(*) AS STRING) as value
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
UNION ALL
SELECT
    'With system_id',
    CAST(COUNT(*) AS STRING)
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id IS NOT NULL
UNION ALL
SELECT
    'Unique Systems',
    CAST(COUNT(DISTINCT system_id) AS STRING)
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id IS NOT NULL;
