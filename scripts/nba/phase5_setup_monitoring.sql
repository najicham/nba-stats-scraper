-- PHASE 5: LINE QUALITY MONITORING SETUP
-- Date: 2026-01-16
-- Purpose: Create views and alerts for ongoing line quality monitoring
-- Run this AFTER: Phases 1-4 complete

-- ============================================================================
-- STEP 1: CREATE LINE QUALITY DASHBOARD VIEW
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.line_quality_daily` AS
SELECT
    game_date,
    system_id,
    COUNT(*) as total_predictions,

    -- Line source breakdown
    COUNTIF(line_source = 'ACTUAL_PROP') as actual_prop,
    COUNTIF(line_source = 'ESTIMATED_AVG') as estimated,
    COUNTIF(line_source IS NULL) as missing_source,

    -- Placeholder detection
    COUNTIF(current_points_line = 20.0) as placeholders,
    COUNTIF(current_points_line IS NULL) as null_lines,

    -- Quality metrics
    ROUND(100.0 * COUNTIF(line_source = 'ACTUAL_PROP') / COUNT(*), 1) as actual_prop_pct,
    ROUND(100.0 * COUNTIF(current_points_line = 20.0) / COUNT(*), 1) as placeholder_pct,

    -- Line statistics
    ROUND(AVG(CASE WHEN line_source = 'ACTUAL_PROP' THEN current_points_line END), 1) as avg_actual_line,
    ROUND(STDDEV(CASE WHEN line_source = 'ACTUAL_PROP' THEN current_points_line END), 1) as stddev_actual_line,

    -- Sportsbook distribution
    COUNT(DISTINCT sportsbook) as sportsbooks_used,

    -- Timestamps
    MIN(created_at) as first_prediction_at,
    MAX(created_at) as last_prediction_at

FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)  -- Last 90 days
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id;

-- Verify view created
SELECT * FROM `nba-props-platform.nba_predictions.line_quality_daily`
WHERE game_date >= CURRENT_DATE() - 7
LIMIT 20;

-- ============================================================================
-- STEP 2: CREATE PLACEHOLDER ALERT VIEW
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.placeholder_alerts` AS
WITH recent_issues AS (
    SELECT
        game_date,
        system_id,
        player_lookup,
        current_points_line,
        line_source,
        prediction_id,
        created_at
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE
        -- Recent dates only (last 7 days)
        game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        -- Placeholder detection
        AND (
            current_points_line = 20.0
            OR line_source IS NULL
            OR line_source = 'NEEDS_BOOTSTRAP'
        )
)
SELECT
    game_date,
    system_id,
    COUNT(*) as issue_count,
    ARRAY_AGG(STRUCT(player_lookup, current_points_line, line_source) ORDER BY player_lookup LIMIT 10) as sample_issues,
    MIN(created_at) as first_seen,
    MAX(created_at) as last_seen
FROM recent_issues
GROUP BY game_date, system_id
ORDER BY game_date DESC, issue_count DESC;

-- Check current alerts
SELECT
    game_date,
    system_id,
    issue_count,
    first_seen,
    last_seen
FROM `nba-props-platform.nba_predictions.placeholder_alerts`
WHERE issue_count > 0;

-- Expected: 0 rows (no alerts)

-- ============================================================================
-- STEP 3: CREATE PERFORMANCE TRACKING VIEW (Real Lines Only)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.performance_valid_lines_only` AS
SELECT
    p.system_id,
    DATE_TRUNC(p.game_date, MONTH) as month,
    COUNT(*) as predictions,

    -- Only include predictions with real sportsbook lines
    COUNTIF(a.prediction_correct = TRUE) as wins,
    COUNTIF(a.prediction_correct = FALSE) as losses,
    COUNTIF(a.prediction_correct IS NULL) as pending,

    -- Win rate on valid lines only
    ROUND(100.0 * COUNTIF(a.prediction_correct = TRUE) / COUNTIF(a.prediction_correct IS NOT NULL), 1) as win_rate,

    -- Accuracy metrics
    ROUND(AVG(a.absolute_error), 2) as avg_error,
    ROUND(AVG(a.confidence_score) * 100, 1) as avg_confidence,

    -- Line quality
    ROUND(AVG(p.current_points_line), 1) as avg_line,
    COUNT(DISTINCT p.sportsbook) as sportsbooks

FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` a
    ON p.prediction_id = a.prediction_id

WHERE
    -- Only valid lines
    p.current_points_line IS NOT NULL
    AND p.current_points_line != 20.0
    AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API')
    AND p.has_prop_line = TRUE

    -- Recent season only
    AND p.game_date >= '2024-10-01'

GROUP BY p.system_id, month
ORDER BY p.system_id, month DESC;

-- Check recent performance
SELECT * FROM `nba-props-platform.nba_predictions.performance_valid_lines_only`
WHERE month >= DATE_TRUNC(CURRENT_DATE(), MONTH) - INTERVAL 3 MONTH
ORDER BY system_id, month DESC;

-- Expected: Win rates in 50-65% range

-- ============================================================================
-- STEP 4: CREATE DATA QUALITY SUMMARY VIEW
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.data_quality_summary` AS
SELECT
    'Overall' as scope,
    COUNT(*) as total_predictions,

    -- Quality breakdown
    COUNTIF(current_points_line IS NOT NULL AND current_points_line != 20.0) as valid_lines,
    COUNTIF(current_points_line = 20.0) as placeholder_lines,
    COUNTIF(current_points_line IS NULL) as null_lines,

    -- Percentages
    ROUND(100.0 * COUNTIF(current_points_line != 20.0 AND current_points_line IS NOT NULL) / COUNT(*), 1) as valid_pct,
    ROUND(100.0 * COUNTIF(current_points_line = 20.0) / COUNT(*), 1) as placeholder_pct,

    -- Line sources
    COUNTIF(line_source = 'ACTUAL_PROP') as actual_prop_count,
    COUNTIF(line_source = 'ESTIMATED_AVG') as estimated_count,
    COUNTIF(line_source IS NULL) as unknown_source,

    -- Date range
    MIN(game_date) as first_date,
    MAX(game_date) as last_date,
    COUNT(DISTINCT game_date) as dates_covered

FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-01';  -- Current season

-- View summary
SELECT * FROM `nba-props-platform.nba_predictions.data_quality_summary`;

-- ============================================================================
-- STEP 5: SCHEDULED QUERY FOR DAILY SLACK ALERTS
-- ============================================================================

-- This query should be scheduled to run daily at 19:00 UTC (after enrichment)
-- Configure in BigQuery Scheduled Queries or Cloud Scheduler + Cloud Function

-- Query: Daily Line Quality Check
/*
SELECT
    game_date,
    SUM(total_predictions) as total_predictions,
    SUM(placeholders) as total_placeholders,
    ROUND(100.0 * SUM(placeholders) / SUM(total_predictions), 1) as placeholder_pct,
    ARRAY_AGG(STRUCT(system_id, placeholders) ORDER BY placeholders DESC LIMIT 5) as top_issues
FROM `nba-props-platform.nba_predictions.line_quality_daily`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date
HAVING total_placeholders > 0;  -- Only alert if issues found
*/

-- If this query returns rows, trigger Slack alert via Cloud Function

-- ============================================================================
-- STEP 6: VALIDATION QUERY TEMPLATES
-- ============================================================================

-- Template 1: Daily Health Check
-- Run this every morning to verify yesterday's predictions
/*
SELECT
    system_id,
    COUNT(*) as predictions,
    COUNTIF(current_points_line = 20.0) as placeholders,
    COUNTIF(line_source = 'ACTUAL_PROP') as actual_props,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE() - 1
GROUP BY system_id
ORDER BY system_id;
*/

-- Template 2: Weekly Trend Analysis
-- Run this weekly to track data quality trends
/*
SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    SUM(total_predictions) as predictions,
    ROUND(AVG(actual_prop_pct), 1) as avg_actual_prop_pct,
    SUM(placeholders) as total_placeholders
FROM `nba-props-platform.nba_predictions.line_quality_daily`
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY week
ORDER BY week DESC;
*/

-- Template 3: System Comparison
-- Run this monthly to compare systems
/*
SELECT
    system_id,
    COUNT(*) as predictions,
    ROUND(100.0 * COUNTIF(line_source = 'ACTUAL_PROP') / COUNT(*), 1) as actual_prop_pct,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
    COUNT(DISTINCT sportsbook) as sportsbooks_used
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_TRUNC(CURRENT_DATE(), MONTH)
GROUP BY system_id
ORDER BY actual_prop_pct DESC;
*/

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Check all views created successfully
SELECT
    table_name,
    table_type,
    creation_time
FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.TABLES`
WHERE table_name IN (
    'line_quality_daily',
    'placeholder_alerts',
    'performance_valid_lines_only',
    'data_quality_summary'
)
ORDER BY table_name;

-- Expected: 4 views

PRINT('✅ Phase 5 monitoring setup complete');
PRINT('');
PRINT('Views created:');
PRINT('  1. line_quality_daily - Daily line quality metrics');
PRINT('  2. placeholder_alerts - Recent placeholder detections');
PRINT('  3. performance_valid_lines_only - Win rates on valid lines');
PRINT('  4. data_quality_summary - Overall data quality');
PRINT('');
PRINT('Next steps:');
PRINT('  1. Configure scheduled query for daily alerts');
PRINT('  2. Create Looker Studio dashboard using these views');
PRINT('  3. Add line quality check to R-009 validation');
PRINT('  4. Document monitoring procedures');

-- ============================================================================
-- END OF PHASE 5
-- ============================================================================
