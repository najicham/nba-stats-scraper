-- @quality-filter: exempt
-- Reason: Debug view for pipeline monitoring, intentionally shows all predictions including low-quality

-- View: nba_predictions.v_prediction_coverage_gaps
-- Purpose: Track players with betting lines but no predictions made
--
-- This view identifies the coverage gap between available betting lines
-- and generated predictions, helping identify name resolution issues,
-- feature gaps, and other prediction failures.
--
-- Usage:
--   -- Today's gaps
--   SELECT * FROM `nba_predictions.v_prediction_coverage_gaps`
--   WHERE game_date = CURRENT_DATE()
--
--   -- High-priority gaps (high line value players)
--   SELECT * FROM `nba_predictions.v_prediction_coverage_gaps`
--   WHERE game_date = CURRENT_DATE()
--     AND line_value >= 20
--   ORDER BY line_value DESC

CREATE OR REPLACE VIEW `nba_predictions.v_prediction_coverage_gaps` AS

WITH betting_lines AS (
    -- All players with betting lines
    SELECT DISTINCT
        player_lookup,
        game_date,
        MAX(points_line) as line_value,
        MAX(bookmaker) as line_source,
        MAX(snapshot_timestamp) as line_timestamp
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY player_lookup, game_date
),

predictions_made AS (
    -- Players who got predictions
    SELECT DISTINCT
        player_lookup,
        game_date,
        MAX(created_at) as prediction_timestamp
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY player_lookup, game_date
),

player_context AS (
    -- Check if player is in upcoming context
    SELECT DISTINCT
        player_lookup,
        game_date,
        team_abbr,
        universal_player_id,
        current_points_line,
        days_rest
    FROM `nba_analytics.upcoming_player_game_context`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

feature_availability AS (
    -- Check if player has features
    SELECT DISTINCT
        player_lookup,
        game_date,
        feature_quality_score
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

registry_status AS (
    -- Check if player exists in registry
    SELECT DISTINCT player_lookup
    FROM `nba_reference.nba_players_registry`
),

unresolved_status AS (
    -- Check if player has unresolved name issues
    SELECT DISTINCT
        normalized_lookup as player_lookup,
        status as unresolved_status
    FROM `nba_reference.unresolved_player_names`
)

SELECT
    bl.player_lookup,
    bl.game_date,
    bl.line_value,
    bl.line_source,
    bl.line_timestamp,

    -- Prediction status
    pm.prediction_timestamp IS NOT NULL as has_prediction,
    pm.prediction_timestamp,

    -- Diagnostic fields
    pc.team_abbr,
    pc.universal_player_id,
    pc.current_points_line as context_line,
    pc.days_rest,

    fa.feature_quality_score as feature_quality,

    rs.player_lookup IS NOT NULL as in_registry,
    us.unresolved_status,

    -- Gap reason classification
    CASE
        WHEN pm.prediction_timestamp IS NOT NULL THEN 'HAS_PREDICTION'
        WHEN rs.player_lookup IS NULL THEN 'NOT_IN_REGISTRY'
        WHEN us.unresolved_status = 'pending' THEN 'NAME_UNRESOLVED'
        WHEN pc.player_lookup IS NULL THEN 'NOT_IN_PLAYER_CONTEXT'
        WHEN fa.player_lookup IS NULL THEN 'NO_FEATURES'
        WHEN fa.feature_quality_score < 50 THEN 'LOW_QUALITY_FEATURES'
        ELSE 'UNKNOWN_REASON'
    END as gap_reason

FROM betting_lines bl
LEFT JOIN predictions_made pm
    ON bl.player_lookup = pm.player_lookup
    AND bl.game_date = pm.game_date
LEFT JOIN player_context pc
    ON bl.player_lookup = pc.player_lookup
    AND bl.game_date = pc.game_date
LEFT JOIN feature_availability fa
    ON bl.player_lookup = fa.player_lookup
    AND bl.game_date = fa.game_date
LEFT JOIN registry_status rs
    ON bl.player_lookup = rs.player_lookup
LEFT JOIN unresolved_status us
    ON bl.player_lookup = us.player_lookup

WHERE pm.prediction_timestamp IS NULL  -- Only show gaps
;

-- Summary view for daily monitoring
CREATE OR REPLACE VIEW `nba_predictions.v_prediction_coverage_summary` AS

SELECT
    game_date,
    COUNT(*) as total_lines,
    COUNTIF(has_prediction) as with_predictions,
    COUNT(*) - COUNTIF(has_prediction) as coverage_gap,
    ROUND(COUNTIF(has_prediction) / COUNT(*) * 100, 1) as coverage_pct,

    -- Gap breakdown by reason
    COUNTIF(gap_reason = 'NOT_IN_REGISTRY') as gap_not_in_registry,
    COUNTIF(gap_reason = 'NAME_UNRESOLVED') as gap_name_unresolved,
    COUNTIF(gap_reason = 'NOT_IN_PLAYER_CONTEXT') as gap_no_context,
    COUNTIF(gap_reason = 'NO_FEATURES') as gap_no_features,
    COUNTIF(gap_reason = 'LOW_QUALITY_FEATURES') as gap_low_quality,
    COUNTIF(gap_reason = 'INJURED') as gap_injured,
    COUNTIF(gap_reason = 'LOW_MINUTES') as gap_low_minutes,
    COUNTIF(gap_reason = 'UNKNOWN_REASON') as gap_unknown

FROM `nba_predictions.v_prediction_coverage_gaps`
GROUP BY game_date
ORDER BY game_date DESC
;

-- Example queries:

-- 1. Today's high-value coverage gaps
-- SELECT player_lookup, line_value, gap_reason, team_abbr
-- FROM `nba_predictions.v_prediction_coverage_gaps`
-- WHERE game_date = CURRENT_DATE()
--   AND gap_reason != 'HAS_PREDICTION'
-- ORDER BY line_value DESC
-- LIMIT 20;

-- 2. Coverage trend
-- SELECT * FROM `nba_predictions.v_prediction_coverage_summary`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);

-- 3. Players frequently missing (name resolution issues)
-- SELECT player_lookup, COUNT(*) as missing_count, MAX(line_value) as max_line
-- FROM `nba_predictions.v_prediction_coverage_gaps`
-- WHERE gap_reason IN ('NOT_IN_REGISTRY', 'NAME_UNRESOLVED', 'NOT_IN_PLAYER_CONTEXT')
--   AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY player_lookup
-- HAVING COUNT(*) >= 3
-- ORDER BY missing_count DESC;
