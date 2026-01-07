-- Emergency Operations Dashboard - BigQuery Monitoring Queries
-- Created: 2026-01-03 (Session 6)
-- Purpose: Production monitoring queries for ops dashboard
--
-- Usage:
--   Run these queries directly in BigQuery console or via bq CLI
--   Integrated into bin/operations/ops_dashboard.sh

-------------------------------------------------------------------------------
-- 1. PIPELINE HEALTH SUMMARY (Today)
-------------------------------------------------------------------------------

-- Quick check: How many player-games processed today across all phases
SELECT
    'Phase 3: Analytics' as phase,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_date) as unique_dates,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE('America/New_York')

UNION ALL

SELECT
    'Phase 4: Precompute' as phase,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_date) as unique_dates,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE('America/New_York')

ORDER BY phase;


-------------------------------------------------------------------------------
-- 2. DATA FRESHNESS CHECK
-------------------------------------------------------------------------------

-- When was data last updated in each critical table?
SELECT
    'player_game_summary' as table_name,
    MAX(game_date) as last_date,
    COUNT(DISTINCT game_date) as total_dates,
    DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_since_update
FROM `nba-props-platform.nba_analytics.player_game_summary`

UNION ALL

SELECT
    'player_composite_factors' as table_name,
    MAX(game_date) as last_date,
    COUNT(DISTINCT game_date) as total_dates,
    DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_since_update
FROM `nba-props-platform.nba_precompute.player_composite_factors`

UNION ALL

SELECT
    'team_offense_game_summary' as table_name,
    MAX(game_date) as last_date,
    COUNT(DISTINCT game_date) as total_dates,
    DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_since_update
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`

ORDER BY days_since_update DESC;


-------------------------------------------------------------------------------
-- 3. ML TRAINING DATA QUALITY
-------------------------------------------------------------------------------

-- Check feature completeness for ML training (2024-25 season)
SELECT
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as unique_dates,
    COUNT(DISTINCT universal_player_id) as unique_players,

    -- Critical features for ML
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 2) as minutes_played_pct,
    ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 2) as usage_rate_pct,
    ROUND(100.0 * COUNTIF(ts_pct IS NOT NULL) / COUNT(*), 2) as ts_pct_coverage,
    ROUND(100.0 * COUNTIF(efg_pct IS NOT NULL) / COUNT(*), 2) as efg_pct_coverage,
    ROUND(100.0 * COUNTIF(assists IS NOT NULL) / COUNT(*), 2) as assists_pct,

    -- Shot distribution features
    ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 2) as shot_zone_coverage_pct

FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2024-10-01'  -- Current season
  AND game_date <= CURRENT_DATE();


-------------------------------------------------------------------------------
-- 4. BACKFILL COVERAGE ANALYSIS
-------------------------------------------------------------------------------

-- Historical coverage by season for Phase 3 and Phase 4
WITH phase3_coverage AS (
    SELECT
        CASE
            WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
            WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
            WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
            WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
        END as season,
        COUNT(DISTINCT game_date) as phase3_dates,
        COUNT(*) as phase3_records
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= '2021-10-01'
    GROUP BY season
),
phase4_coverage AS (
    SELECT
        CASE
            WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
            WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
            WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
            WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
        END as season,
        COUNT(DISTINCT game_date) as phase4_dates,
        COUNT(*) as phase4_records
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    WHERE game_date >= '2021-10-01'
    GROUP BY season
)
SELECT
    COALESCE(p3.season, p4.season) as season,
    COALESCE(p3.phase3_dates, 0) as phase3_dates,
    COALESCE(p3.phase3_records, 0) as phase3_records,
    COALESCE(p4.phase4_dates, 0) as phase4_dates,
    COALESCE(p4.phase4_records, 0) as phase4_records,
    ROUND(100.0 * COALESCE(p4.phase4_dates, 0) / NULLIF(COALESCE(p3.phase3_dates, 0), 0), 2) as phase4_coverage_pct
FROM phase3_coverage p3
FULL OUTER JOIN phase4_coverage p4 ON p3.season = p4.season
ORDER BY season;


-------------------------------------------------------------------------------
-- 5. RECENT PROCESSOR FAILURES (if table exists)
-------------------------------------------------------------------------------

-- Find recent processor failures from validation table
-- Note: This table may not exist if validation not enabled
SELECT
    processor_name,
    game_date,
    issue_type,
    severity,
    reason,
    timestamp
FROM `nba-props-platform.nba_orchestration.processor_output_validation`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND severity IN ('ERROR', 'CRITICAL')
ORDER BY timestamp DESC
LIMIT 50;


-------------------------------------------------------------------------------
-- 6. DAILY PROCESSING STATS (Last 7 Days)
-------------------------------------------------------------------------------

-- How many records are we processing per day?
SELECT
    game_date,
    COUNT(*) as player_games,
    COUNT(DISTINCT universal_player_id) as unique_players,
    ROUND(AVG(minutes_played), 1) as avg_minutes,
    ROUND(AVG(points), 1) as avg_points
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;


-------------------------------------------------------------------------------
-- 7. PHASE 4 PROCESSING HEALTH
-------------------------------------------------------------------------------

-- Check Phase 4 has data for recent Phase 3 dates
WITH phase3_dates AS (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
      AND game_date >= '2024-10-15'  -- After bootstrap period
),
phase4_dates AS (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
    p3.game_date,
    CASE WHEN p4.game_date IS NOT NULL THEN 'PROCESSED' ELSE 'MISSING' END as phase4_status
FROM phase3_dates p3
LEFT JOIN phase4_dates p4 ON p3.game_date = p4.game_date
ORDER BY p3.game_date DESC
LIMIT 30;


-------------------------------------------------------------------------------
-- 8. DATA QUALITY REGRESSION DETECTION
-------------------------------------------------------------------------------

-- Compare this week vs last week to detect quality regressions
WITH this_week AS (
    SELECT
        COUNT(*) as records,
        ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 2) as minutes_pct,
        ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 2) as usage_pct,
        ROUND(AVG(points), 2) as avg_points
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
last_week AS (
    SELECT
        COUNT(*) as records,
        ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 2) as minutes_pct,
        ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 2) as usage_pct,
        ROUND(AVG(points), 2) as avg_points
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
      AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
    'This Week' as period,
    tw.records,
    tw.minutes_pct,
    tw.usage_pct,
    tw.avg_points
FROM this_week tw

UNION ALL

SELECT
    'Last Week' as period,
    lw.records,
    lw.minutes_pct,
    lw.usage_pct,
    lw.avg_points
FROM last_week lw;


-------------------------------------------------------------------------------
-- 9. TOP PLAYERS BY DATA VOLUME (Debug/Validation)
-------------------------------------------------------------------------------

-- Which players have the most games in our system?
SELECT
    player_lookup,
    player_full_name,
    COUNT(*) as total_games,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game,
    ROUND(AVG(points), 1) as avg_points,
    ROUND(AVG(minutes_played), 1) as avg_minutes
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2024-10-01'
GROUP BY player_lookup, player_full_name
ORDER BY total_games DESC
LIMIT 20;


-------------------------------------------------------------------------------
-- 10. SYSTEM HEALTH SCORECARD
-------------------------------------------------------------------------------

-- Single-row summary for dashboard display
SELECT
    -- Phase 3 metrics
    (SELECT COUNT(DISTINCT game_date) FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '2024-10-01') as phase3_dates_current_season,

    -- Phase 4 metrics
    (SELECT COUNT(DISTINCT game_date) FROM `nba-props-platform.nba_precompute.player_composite_factors`
     WHERE game_date >= '2024-10-01') as phase4_dates_current_season,

    -- Data freshness
    (SELECT DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
     FROM `nba-props-platform.nba_analytics.player_game_summary`) as days_since_phase3_update,

    -- Feature quality (minutes_played)
    (SELECT ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 2)
     FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '2024-10-01') as minutes_played_coverage_pct,

    -- Feature quality (usage_rate)
    (SELECT ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 2)
     FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '2024-10-01') as usage_rate_coverage_pct,

    -- Historical coverage
    (SELECT COUNT(DISTINCT game_date) FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '2021-10-01') as total_historical_dates_phase3,

    (SELECT COUNT(DISTINCT game_date) FROM `nba-props-platform.nba_precompute.player_composite_factors`
     WHERE game_date >= '2021-10-01') as total_historical_dates_phase4;
