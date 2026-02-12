-- @quality-filter: exempt
-- Reason: Vegas line coverage analysis, needs all predictions regardless of quality

-- ============================================================================
-- Vegas Line Source Coverage View (Session 152)
-- Shows daily distribution of which scrapers provided vegas line data.
-- Use to monitor scraper health and diagnose coverage gaps.
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_vegas_source_coverage` AS
SELECT
    game_date,
    COUNT(*) as total_players,
    COUNTIF(vegas_line_source = 'odds_api') as odds_api_only,
    COUNTIF(vegas_line_source = 'bettingpros') as bettingpros_only,
    COUNTIF(vegas_line_source = 'both') as both_sources,
    COUNTIF(vegas_line_source = 'none' OR vegas_line_source IS NULL) as no_source,
    ROUND(COUNTIF(vegas_line_source IS NOT NULL AND vegas_line_source != 'none') * 100.0 / COUNT(*), 1) as coverage_pct
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1;
