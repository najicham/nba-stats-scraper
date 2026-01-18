-- ============================================================================
-- MLB Feature Coverage Monitoring Migration
-- Add feature_coverage_pct column to pitcher_strikeouts table
-- ============================================================================
--
-- This migration adds feature coverage tracking to provide visibility into
-- data quality for each prediction. Feature coverage measures the percentage
-- of expected features that are non-null for a given prediction.
--
-- Benefits:
-- - Detect low-data scenarios where predictions may be unreliable
-- - Track feature availability over time
-- - Alert on degrading data quality
-- - Improve confidence calibration
--
-- IMPORTANT: Run this migration before deploying optimized worker
-- ============================================================================

-- Phase 1: Add nullable feature_coverage_pct column
-- Safe to run while existing system is running
ALTER TABLE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
ADD COLUMN IF NOT EXISTS feature_coverage_pct FLOAT64
OPTIONS (description = "Percentage of expected features with non-null values (0-100). Higher = better data quality.");

-- Phase 2: Backfill historical data (optional)
-- Since historical data doesn't have this metric, we'll leave it NULL
-- New predictions will populate this field automatically

-- Phase 3: Create monitoring view for feature coverage
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.feature_coverage_monitoring` AS
WITH daily_coverage AS (
    SELECT
        game_date,
        system_id,
        COUNT(*) as prediction_count,
        AVG(feature_coverage_pct) as avg_coverage,
        MIN(feature_coverage_pct) as min_coverage,
        MAX(feature_coverage_pct) as max_coverage,
        -- Count low coverage predictions
        COUNTIF(feature_coverage_pct < 80.0) as low_coverage_count,
        COUNTIF(feature_coverage_pct < 60.0) as very_low_coverage_count,
        -- Calculate percentiles
        APPROX_QUANTILES(feature_coverage_pct, 100)[OFFSET(25)] as p25_coverage,
        APPROX_QUANTILES(feature_coverage_pct, 100)[OFFSET(50)] as p50_coverage,
        APPROX_QUANTILES(feature_coverage_pct, 100)[OFFSET(75)] as p75_coverage
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE feature_coverage_pct IS NOT NULL
    GROUP BY game_date, system_id
)
SELECT
    game_date,
    system_id,
    prediction_count,
    ROUND(avg_coverage, 1) as avg_coverage_pct,
    ROUND(min_coverage, 1) as min_coverage_pct,
    ROUND(max_coverage, 1) as max_coverage_pct,
    low_coverage_count,
    very_low_coverage_count,
    ROUND(100.0 * low_coverage_count / prediction_count, 1) as low_coverage_rate_pct,
    ROUND(p25_coverage, 1) as p25_coverage_pct,
    ROUND(p50_coverage, 1) as median_coverage_pct,
    ROUND(p75_coverage, 1) as p75_coverage_pct
FROM daily_coverage
ORDER BY game_date DESC, system_id;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- 1. Check feature coverage distribution across all systems
SELECT
    system_id,
    COUNT(*) as total_predictions,
    COUNT(feature_coverage_pct) as with_coverage_metric,
    ROUND(AVG(feature_coverage_pct), 1) as avg_coverage_pct,
    ROUND(MIN(feature_coverage_pct), 1) as min_coverage_pct,
    ROUND(MAX(feature_coverage_pct), 1) as max_coverage_pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY system_id
ORDER BY system_id;

-- 2. Identify low coverage predictions (past 7 days)
SELECT
    game_date,
    pitcher_lookup,
    system_id,
    ROUND(feature_coverage_pct, 1) as coverage_pct,
    ROUND(confidence, 1) as confidence,
    recommendation,
    predicted_strikeouts,
    strikeouts_line
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_coverage_pct < 80.0
ORDER BY feature_coverage_pct ASC, game_date DESC
LIMIT 50;

-- 3. Feature coverage trends over time (by system)
SELECT
    game_date,
    system_id,
    COUNT(*) as predictions,
    ROUND(AVG(feature_coverage_pct), 1) as avg_coverage_pct,
    COUNTIF(feature_coverage_pct < 80.0) as low_coverage_count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND feature_coverage_pct IS NOT NULL
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id;

-- 4. Correlation between feature coverage and confidence
SELECT
    CASE
        WHEN feature_coverage_pct >= 90 THEN '90-100%'
        WHEN feature_coverage_pct >= 80 THEN '80-89%'
        WHEN feature_coverage_pct >= 70 THEN '70-79%'
        WHEN feature_coverage_pct >= 60 THEN '60-69%'
        ELSE '<60%'
    END as coverage_bucket,
    COUNT(*) as prediction_count,
    ROUND(AVG(confidence), 1) as avg_confidence,
    ROUND(AVG(ABS(edge)), 2) as avg_abs_edge
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE feature_coverage_pct IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY coverage_bucket
ORDER BY coverage_bucket DESC;

-- 5. Recent predictions with coverage metrics
SELECT
    game_date,
    pitcher_lookup,
    system_id,
    ROUND(feature_coverage_pct, 1) as coverage_pct,
    ROUND(confidence, 1) as conf,
    recommendation as rec,
    ROUND(predicted_strikeouts, 1) as pred_k,
    strikeouts_line as line
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND feature_coverage_pct IS NOT NULL
ORDER BY game_date DESC, pitcher_lookup, system_id
LIMIT 30;

-- 6. Summary statistics
SELECT
    'Total Predictions' as metric,
    CAST(COUNT(*) AS STRING) as value
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
UNION ALL
SELECT
    'With Feature Coverage',
    CAST(COUNT(*) AS STRING)
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE feature_coverage_pct IS NOT NULL
UNION ALL
SELECT
    'Low Coverage (<80%)',
    CAST(COUNTIF(feature_coverage_pct < 80.0) AS STRING)
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE feature_coverage_pct IS NOT NULL
UNION ALL
SELECT
    'Very Low Coverage (<60%)',
    CAST(COUNTIF(feature_coverage_pct < 60.0) AS STRING)
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE feature_coverage_pct IS NOT NULL;
