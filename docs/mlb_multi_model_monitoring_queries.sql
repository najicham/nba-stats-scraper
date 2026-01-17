-- ============================================================================
-- MLB Multi-Model Architecture - Monitoring Queries
-- Daily operational queries for system health and performance
-- ============================================================================
-- File: docs/mlb_multi_model_monitoring_queries.sql
-- Version: 2.0.0
-- Last Updated: 2026-01-17
-- ============================================================================

-- ============================================================================
-- DAILY CHECKS (Run every morning after predictions)
-- ============================================================================

-- 1. DAILY COVERAGE CHECK
-- Verifies all systems ran for each pitcher
-- Expected: min_systems_per_pitcher = max_systems_per_pitcher = 3
SELECT
    game_date,
    unique_pitchers,
    systems_per_date,
    systems_used,
    v1_count,
    v1_6_count,
    ensemble_count,
    min_systems_per_pitcher,  -- Should be 3
    max_systems_per_pitcher   -- Should be 3
FROM `nba-props-platform.mlb_predictions.daily_coverage`
WHERE game_date = CURRENT_DATE();

-- If min != max or either != 3, there's a coverage issue!
-- Check logs: gcloud logging read "textPayload=~'Prediction failed'"


-- 2. TODAY'S ENSEMBLE PICKS
-- View the final ensemble recommendations for today
SELECT
    pitcher_lookup,
    team_abbr,
    opponent_team_abbr,
    strikeouts_line,
    predicted_strikeouts,
    confidence,
    recommendation,
    edge,
    red_flags
FROM `nba-props-platform.mlb_predictions.todays_picks`
ORDER BY ABS(edge) DESC
LIMIT 20;


-- 3. SYSTEM COMPARISON FOR TODAY
-- See all 3 systems side-by-side
SELECT
    pitcher_lookup,
    strikeouts_line,
    -- V1 Baseline
    v1_prediction,
    v1_recommendation,
    -- V1.6 Rolling
    v1_6_prediction,
    v1_6_recommendation,
    -- Ensemble
    ensemble_prediction,
    ensemble_recommendation,
    -- Agreement
    agreement_level,
    v1_v1_6_diff
FROM `nba-props-platform.mlb_predictions.system_comparison`
ORDER BY pitcher_lookup
LIMIT 20;


-- 4. SYSTEM AGREEMENT CHECK
-- How often do systems agree vs disagree?
-- Expected: strong_agreement + moderate_agreement > 70%
SELECT
    game_date,
    total_comparisons,
    strong_agreement,        -- Diff < 1.0 K
    moderate_agreement,      -- Diff 1.0-2.0 K
    disagreement,           -- Diff > 2.0 K
    same_recommendation,
    different_recommendation,
    ROUND(100.0 * (strong_agreement + moderate_agreement) / total_comparisons, 1) as agreement_pct
FROM `nba-props-platform.mlb_predictions.system_agreement`
WHERE game_date = CURRENT_DATE();

-- If agreement_pct < 70%, investigate why systems are diverging


-- ============================================================================
-- WEEKLY PERFORMANCE REVIEW (Run every Monday)
-- ============================================================================

-- 5. SYSTEM PERFORMANCE COMPARISON (Last 30 Days)
-- Compare MAE and accuracy across all systems
SELECT
    system_id,
    total_predictions,
    actionable_predictions,
    graded_predictions,
    ROUND(mae, 2) as mae,
    recommendation_accuracy_pct,
    ROUND(avg_confidence, 1) as avg_confidence
FROM `nba-props-platform.mlb_predictions.system_performance`
ORDER BY recommendation_accuracy_pct DESC;

-- Expected: Ensemble accuracy ≥ V1.6 accuracy
-- Expected: Ensemble MAE ≤ best individual system MAE


-- 6. WEEKLY COVERAGE SUMMARY (Last 7 Days)
-- Ensure consistent coverage every day
SELECT
    game_date,
    unique_pitchers,
    systems_per_date,
    v1_count,
    v1_6_count,
    ensemble_count,
    CASE
        WHEN min_systems_per_pitcher = 3 AND max_systems_per_pitcher = 3 THEN '✓ Complete'
        ELSE '✗ Incomplete'
    END as coverage_status
FROM `nba-props-platform.mlb_predictions.daily_coverage`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;


-- 7. SYSTEM-SPECIFIC ACCURACY (Last 7 Days)
-- Deep dive into each system's performance
SELECT
    system_id,
    game_date,
    COUNT(*) as predictions,
    COUNT(CASE WHEN actual_strikeouts IS NOT NULL THEN 1 END) as graded,
    ROUND(AVG(CASE
        WHEN actual_strikeouts IS NOT NULL
        THEN ABS(predicted_strikeouts - actual_strikeouts)
    END), 2) as mae,
    ROUND(100.0 * COUNT(CASE
        WHEN actual_strikeouts IS NOT NULL
            AND ((recommendation = 'OVER' AND actual_strikeouts > strikeouts_line)
              OR (recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line))
        THEN 1
    END) / NULLIF(COUNT(CASE
        WHEN actual_strikeouts IS NOT NULL AND recommendation IN ('OVER', 'UNDER')
        THEN 1
    END), 0), 1) as accuracy_pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND system_id IS NOT NULL
GROUP BY system_id, game_date
ORDER BY game_date DESC, system_id;


-- ============================================================================
-- QUALITY ASSURANCE CHECKS
-- ============================================================================

-- 8. CHECK FOR MISSING SYSTEM_IDS
-- Should return 0 rows after migration complete
SELECT
    game_date,
    COUNT(*) as rows_without_system_id
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id IS NULL
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;


-- 9. CHECK FOR DUPLICATE PREDICTIONS
-- Should return 0 rows (each pitcher should have exactly 1 row per system)
SELECT
    game_date,
    pitcher_lookup,
    system_id,
    COUNT(*) as duplicate_count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date, pitcher_lookup, system_id
HAVING COUNT(*) > 1;


-- 10. CHECK FOR ORPHANED PREDICTIONS
-- Pitchers with some but not all systems (should be 0)
WITH pitcher_system_counts AS (
    SELECT
        game_date,
        pitcher_lookup,
        COUNT(DISTINCT system_id) as system_count
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = CURRENT_DATE()
        AND system_id IS NOT NULL
    GROUP BY game_date, pitcher_lookup
)
SELECT
    game_date,
    pitcher_lookup,
    system_count
FROM pitcher_system_counts
WHERE system_count != 3
ORDER BY game_date DESC, pitcher_lookup;

-- If any rows returned, some systems failed for specific pitchers
-- Check logs for those pitchers


-- ============================================================================
-- ENSEMBLE QUALITY CHECKS
-- ============================================================================

-- 11. ENSEMBLE VS COMPONENT PREDICTIONS
-- Verify ensemble is properly weighted averaging
SELECT
    pitcher_lookup,
    v1.predicted_strikeouts as v1_pred,
    v16.predicted_strikeouts as v16_pred,
    ens.predicted_strikeouts as ens_pred,
    -- Manual calculation: (V1 * 0.3) + (V1.6 * 0.5)
    ROUND((v1.predicted_strikeouts * 0.3) + (v16.predicted_strikeouts * 0.5), 2) as expected_weighted,
    ROUND(ABS(ens.predicted_strikeouts - ((v1.predicted_strikeouts * 0.3) + (v16.predicted_strikeouts * 0.5))), 2) as diff
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` v1
JOIN `nba-props-platform.mlb_predictions.pitcher_strikeouts` v16
    ON v1.game_date = v16.game_date
    AND v1.pitcher_lookup = v16.pitcher_lookup
    AND v16.system_id = 'v1_6_rolling'
JOIN `nba-props-platform.mlb_predictions.pitcher_strikeouts` ens
    ON v1.game_date = ens.game_date
    AND v1.pitcher_lookup = ens.pitcher_lookup
    AND ens.system_id = 'ensemble_v1'
WHERE v1.system_id = 'v1_baseline'
    AND v1.game_date = CURRENT_DATE()
ORDER BY diff DESC
LIMIT 10;

-- diff should be small (<0.5) for most pitchers
-- Larger diffs might indicate agreement bonuses/penalties


-- 12. ENSEMBLE CONFIDENCE DISTRIBUTION
-- Check that ensemble confidence is reasonable
SELECT
    FLOOR(confidence / 10) * 10 as confidence_bucket,
    COUNT(*) as count,
    ROUND(AVG(predicted_strikeouts), 2) as avg_prediction,
    ROUND(AVG(CASE WHEN actual_strikeouts IS NOT NULL
        THEN ABS(predicted_strikeouts - actual_strikeouts) END), 2) as avg_error
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id = 'ensemble_v1'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY confidence_bucket
ORDER BY confidence_bucket DESC;


-- ============================================================================
-- RED FLAG ANALYSIS
-- ============================================================================

-- 13. RED FLAG FREQUENCY
-- How often are predictions skipped/reduced?
SELECT
    system_id,
    recommendation,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY system_id), 1) as pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND system_id IS NOT NULL
GROUP BY system_id, recommendation
ORDER BY system_id, count DESC;


-- 14. COMMON RED FLAGS
-- Most frequent red flag reasons
WITH red_flag_records AS (
    SELECT
        system_id,
        game_date,
        pitcher_lookup,
        red_flags
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        AND red_flags IS NOT NULL
        AND ARRAY_LENGTH(red_flags) > 0
)
SELECT
    system_id,
    flag,
    COUNT(*) as frequency
FROM red_flag_records,
    UNNEST(red_flags) as flag
GROUP BY system_id, flag
ORDER BY system_id, frequency DESC;


-- ============================================================================
-- ALERTING QUERIES (For setting up Cloud Monitoring alerts)
-- ============================================================================

-- 15. CRITICAL: All Systems Failing
-- Returns 1 if ANY system has zero predictions today
SELECT
    CASE
        WHEN MIN(prediction_count) = 0 THEN 1
        ELSE 0
    END as alert
FROM (
    SELECT
        system_id,
        COUNT(*) as prediction_count
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = CURRENT_DATE()
    GROUP BY system_id
);


-- 16. WARNING: Low System Agreement
-- Returns 1 if agreement < 80%
SELECT
    CASE
        WHEN agreement_pct < 80 THEN 1
        ELSE 0
    END as alert,
    agreement_pct
FROM (
    SELECT
        ROUND(100.0 * (strong_agreement + moderate_agreement) / total_comparisons, 1) as agreement_pct
    FROM `nba-props-platform.mlb_predictions.system_agreement`
    WHERE game_date = CURRENT_DATE()
);


-- 17. WARNING: Incomplete Coverage
-- Returns 1 if any pitcher doesn't have all 3 systems
SELECT
    CASE
        WHEN min_systems_per_pitcher < 3 OR max_systems_per_pitcher < 3 THEN 1
        ELSE 0
    END as alert,
    min_systems_per_pitcher,
    max_systems_per_pitcher
FROM `nba-props-platform.mlb_predictions.daily_coverage`
WHERE game_date = CURRENT_DATE();


-- ============================================================================
-- HISTORICAL TRENDS
-- ============================================================================

-- 18. ENSEMBLE PERFORMANCE OVER TIME (Last 30 Days)
SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    COUNT(*) as predictions,
    ROUND(AVG(predicted_strikeouts), 2) as avg_prediction,
    ROUND(AVG(CASE WHEN actual_strikeouts IS NOT NULL
        THEN ABS(predicted_strikeouts - actual_strikeouts) END), 2) as mae,
    ROUND(100.0 * COUNT(CASE
        WHEN actual_strikeouts IS NOT NULL
            AND ((recommendation = 'OVER' AND actual_strikeouts > strikeouts_line)
              OR (recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line))
        THEN 1
    END) / NULLIF(COUNT(CASE
        WHEN actual_strikeouts IS NOT NULL AND recommendation IN ('OVER', 'UNDER')
        THEN 1
    END), 0), 1) as accuracy_pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE system_id = 'ensemble_v1'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY week
ORDER BY week DESC;


-- 19. SYSTEM WIN RATE COMPARISON (Last 30 Days)
SELECT
    system_id,
    COUNT(CASE WHEN recommendation = 'OVER' AND actual_strikeouts > strikeouts_line THEN 1 END) as over_wins,
    COUNT(CASE WHEN recommendation = 'OVER' THEN 1 END) as over_total,
    ROUND(100.0 * COUNT(CASE WHEN recommendation = 'OVER' AND actual_strikeouts > strikeouts_line THEN 1 END) /
        NULLIF(COUNT(CASE WHEN recommendation = 'OVER' THEN 1 END), 0), 1) as over_win_pct,

    COUNT(CASE WHEN recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line THEN 1 END) as under_wins,
    COUNT(CASE WHEN recommendation = 'UNDER' THEN 1 END) as under_total,
    ROUND(100.0 * COUNT(CASE WHEN recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line THEN 1 END) /
        NULLIF(COUNT(CASE WHEN recommendation = 'UNDER' THEN 1 END), 0), 1) as under_win_pct,

    ROUND(100.0 * COUNT(CASE
        WHEN (recommendation = 'OVER' AND actual_strikeouts > strikeouts_line)
          OR (recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line)
        THEN 1 END) /
        NULLIF(COUNT(CASE WHEN recommendation IN ('OVER', 'UNDER') THEN 1 END), 0), 1) as total_win_pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND actual_strikeouts IS NOT NULL
    AND system_id IS NOT NULL
GROUP BY system_id
ORDER BY total_win_pct DESC;


-- ============================================================================
-- QUICK REFERENCE COMMANDS
-- ============================================================================

/*
Run these queries via bq CLI:

# Daily coverage check
bq query --use_legacy_sql=false "$(cat query_01_daily_coverage.sql)"

# Today's ensemble picks
bq query --use_legacy_sql=false "$(cat query_02_todays_picks.sql)"

# System performance
bq query --use_legacy_sql=false "$(cat query_05_system_performance.sql)"
*/

-- ============================================================================
-- END OF MONITORING QUERIES
-- ============================================================================
