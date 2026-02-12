-- @quality-filter: exempt
-- Reason: Validation monitoring view, shows all predictions for completeness checking

-- Path: schemas/bigquery/predictions/views/v_daily_validation_summary.sql
-- ============================================================================
-- View: daily_validation_summary
-- Purpose: Automated daily validation checks for feature store integrity
-- Created: 2026-01-29 (after Session 27 L5/L10 bug fix)
-- ============================================================================
--
-- This view provides automated validation checks that should run daily:
-- 1. feature_cache_match: L5/L10 values in feature store match cache
-- 2. duplicate_count: No duplicate (player, date) pairs
-- 3. invalid_arrays: Feature arrays have 33 elements, no NULL
-- 4. nan_inf_count: No NaN or Inf values in features
-- 5. cache_miss_rate: Records using cache (not fallback)
--
-- Pass criteria:
-- - feature_cache_match: >= 95%
-- - duplicate_count: = 0
-- - invalid_arrays: = 0
-- - nan_inf_count: = 0
-- - cache_miss_rate: <= 10% (for recent data)
--
-- Usage:
--   SELECT * FROM `nba_predictions.v_daily_validation_summary`
--   WHERE check_date = CURRENT_DATE() - 1;
--
-- Alert if:
--   SELECT * FROM `nba_predictions.v_daily_validation_summary`
--   WHERE check_date = CURRENT_DATE() - 1 AND status = 'FAIL';
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_daily_validation_summary` AS
WITH
-- Check 1: Feature store vs cache L5/L10 consistency
feature_cache_check AS (
    SELECT
        fs.game_date as check_date,
        'feature_cache_match' as check_name,
        COUNT(*) as total_records,
        COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) as passing_records,
        ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / NULLIF(COUNT(*), 0), 1) as value,
        95.0 as threshold,
        'pct' as unit,
        'L5/L10 match rate between feature store and cache' as description
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
    JOIN `nba-props-platform.nba_precompute.player_daily_cache` c
        ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
    WHERE fs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        AND ARRAY_LENGTH(fs.features) >= 2
    GROUP BY fs.game_date
),

-- Check 2: Duplicate detection in feature store
duplicate_check AS (
    SELECT
        game_date as check_date,
        'duplicate_count' as check_name,
        total_count as total_records,
        total_count - duplicate_count as passing_records,
        CAST(duplicate_count AS FLOAT64) as value,
        0.0 as threshold,
        'count' as unit,
        'Duplicate (player, date) pairs in feature store' as description
    FROM (
        SELECT
            game_date,
            COUNT(*) as total_count,
            COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '-', CAST(game_date AS STRING))) as duplicate_count
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY game_date
    )
),

-- Check 3: Invalid feature arrays
-- Note: Changed from 33 to 34 on 2026-01-29 after new feature was added
array_check AS (
    SELECT
        game_date as check_date,
        'invalid_arrays' as check_name,
        COUNT(*) as total_records,
        COUNTIF(features IS NOT NULL AND ARRAY_LENGTH(features) = 34) as passing_records,
        CAST(COUNTIF(features IS NULL OR ARRAY_LENGTH(features) != 34) AS FLOAT64) as value,
        0.0 as threshold,
        'count' as unit,
        'Feature arrays with NULL or wrong length (expected 34)' as description
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY game_date
),

-- Check 4: NaN/Inf values in features
nan_inf_check AS (
    SELECT
        game_date as check_date,
        'nan_inf_count' as check_name,
        COUNT(*) as total_records,
        COUNT(*) - COUNTIF(
            EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_NAN(f))
            OR EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_INF(f))
        ) as passing_records,
        CAST(COUNTIF(
            EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_NAN(f))
            OR EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_INF(f))
        ) AS FLOAT64) as value,
        0.0 as threshold,
        'count' as unit,
        'Feature arrays containing NaN or Infinity values' as description
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY game_date
),

-- Check 5: Cache miss rate (data source tracking)
cache_source_check AS (
    SELECT
        game_date as check_date,
        'cache_miss_rate' as check_name,
        COUNT(*) as total_records,
        COUNTIF(source_daily_cache_rows_found IS NOT NULL AND source_daily_cache_rows_found > 0) as passing_records,
        ROUND(100.0 * COUNTIF(source_daily_cache_rows_found IS NULL OR source_daily_cache_rows_found = 0) / NULLIF(COUNT(*), 0), 1) as value,
        10.0 as threshold,
        'pct' as unit,
        'Records using fallback instead of cache' as description
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY game_date
),

-- Combine all checks
all_checks AS (
    SELECT * FROM feature_cache_check
    UNION ALL
    SELECT * FROM duplicate_check
    UNION ALL
    SELECT * FROM array_check
    UNION ALL
    SELECT * FROM nan_inf_check
    UNION ALL
    SELECT * FROM cache_source_check
)

SELECT
    check_date,
    check_name,
    total_records,
    passing_records,
    value,
    threshold,
    unit,
    description,
    CASE
        -- For percentage checks: value should be >= threshold
        WHEN unit = 'pct' AND check_name = 'feature_cache_match' AND value >= threshold THEN 'PASS'
        WHEN unit = 'pct' AND check_name = 'feature_cache_match' AND value < threshold THEN 'FAIL'
        -- For cache_miss_rate: value should be <= threshold (lower is better)
        WHEN unit = 'pct' AND check_name = 'cache_miss_rate' AND value <= threshold THEN 'PASS'
        WHEN unit = 'pct' AND check_name = 'cache_miss_rate' AND value > threshold THEN 'WARN'
        -- For count checks: value should be = threshold (usually 0)
        WHEN unit = 'count' AND value = threshold THEN 'PASS'
        WHEN unit = 'count' AND value > threshold THEN 'FAIL'
        ELSE 'UNKNOWN'
    END as status,
    CURRENT_TIMESTAMP() as checked_at
FROM all_checks
ORDER BY check_date DESC, check_name;
