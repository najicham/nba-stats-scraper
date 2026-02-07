-- Session 152: Daily pipeline health dashboard view
--
-- Single view combining predictions, line sources, and feature quality
-- for the past 7 days. Use for morning monitoring and health dashboards.
--
-- Usage:
--   bq query --use_legacy_sql=false < schemas/bigquery/predictions/v_daily_pipeline_health.sql
--
-- Query:
--   SELECT * FROM nba_predictions.v_daily_pipeline_health
--   WHERE game_date = CURRENT_DATE()

CREATE OR REPLACE VIEW nba_predictions.v_daily_pipeline_health AS
WITH predictions AS (
    SELECT
        game_date,
        COUNT(*) as total_predictions,
        COUNTIF(is_active) as active_predictions,
        COUNTIF(superseded) as superseded_predictions,
        COUNTIF(current_points_line IS NOT NULL AND is_active) as with_lines,
        COUNTIF((current_points_line IS NULL) AND is_active) as without_lines,
        COUNTIF(vegas_line_source = 'odds_api' AND is_active) as vls_odds_api,
        COUNTIF(vegas_line_source = 'bettingpros' AND is_active) as vls_bettingpros,
        COUNTIF(vegas_line_source = 'both' AND is_active) as vls_both,
        COUNTIF((vegas_line_source = 'none' OR vegas_line_source IS NULL) AND is_active) as vls_none,
        COUNTIF(is_actionable AND is_active) as actionable,
        COUNTIF(ABS(predicted_points - current_points_line) >= 3 AND is_active) as medium_edge,
        COUNTIF(ABS(predicted_points - current_points_line) >= 5 AND is_active) as high_edge,
        AVG(CASE WHEN is_active THEN feature_quality_score END) as avg_quality,
        ARRAY_AGG(DISTINCT prediction_run_mode IGNORE NULLS) as run_modes,
    FROM nba_predictions.player_prop_predictions
    WHERE game_date >= CURRENT_DATE() - 7
    GROUP BY 1
),
feature_store AS (
    SELECT
        game_date,
        COUNT(*) as fs_players,
        COUNTIF(is_quality_ready) as fs_quality_ready,
        COUNTIF(default_feature_count = 0) as fs_zero_defaults,
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date >= CURRENT_DATE() - 7
    GROUP BY 1
)
SELECT
    p.game_date,
    p.total_predictions,
    p.active_predictions,
    p.superseded_predictions,
    p.with_lines,
    p.without_lines,
    p.vls_odds_api,
    p.vls_bettingpros,
    p.vls_both,
    p.vls_none,
    p.actionable,
    p.medium_edge,
    p.high_edge,
    ROUND(p.avg_quality, 1) as avg_quality,
    p.run_modes,
    f.fs_players,
    f.fs_quality_ready,
    f.fs_zero_defaults
FROM predictions p
LEFT JOIN feature_store f USING (game_date)
ORDER BY p.game_date DESC;
