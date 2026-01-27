-- P0 Alert: Zero Predictions Detected
-- Trigger: 0 predictions for a game day after 6 PM local time
-- Action: Slack notification + PagerDuty
--
-- Context: This would have caught the 2026-01-26 incident where 0 predictions
-- were generated due to betting lines arriving after Phase 3 processed.
--
-- Usage:
--   bq query --use_legacy_sql=false --parameter=game_date:DATE:2026-01-26 < zero_predictions.sql

WITH prediction_counts AS (
    SELECT
        game_date,
        COUNT(DISTINCT player_lookup) as players_predicted,
        COUNT(DISTINCT CASE WHEN recommendation IN ('OVER', 'UNDER') THEN player_lookup END) as actionable_predictions,
        COUNTIF(has_prop_line = FALSE OR has_prop_line IS NULL) as no_line_count,
        COUNT(*) as total_predictions
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
        AND system_id = 'catboost_v8'
    GROUP BY game_date
),
expected_games AS (
    SELECT
        COUNT(DISTINCT game_id) as games_today,
        COUNT(DISTINCT player_lookup) as eligible_players
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date = @game_date
        AND (
            avg_minutes_per_game_last_7 >= 15
            OR current_points_line IS NOT NULL
        )
        AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
        AND is_production_ready = TRUE
)
SELECT
    @game_date as alert_date,
    CURRENT_TIMESTAMP() as check_timestamp,
    COALESCE(pc.players_predicted, 0) as players_predicted,
    COALESCE(pc.actionable_predictions, 0) as actionable_predictions,
    COALESCE(pc.no_line_count, 0) as no_line_count,
    eg.games_today,
    eg.eligible_players,

    -- Alert conditions
    CASE
        WHEN COALESCE(pc.players_predicted, 0) = 0 AND eg.games_today > 0 THEN 'CRITICAL'
        WHEN COALESCE(pc.players_predicted, 0) < 10 AND eg.games_today > 0 THEN 'WARNING'
        ELSE 'OK'
    END as alert_level,

    CASE
        WHEN COALESCE(pc.players_predicted, 0) = 0 AND eg.games_today > 0 THEN
            'ZERO PREDICTIONS: No predictions generated despite ' || CAST(eg.games_today AS STRING) || ' games scheduled. Check coordinator logs and Phase 3 timing.'
        WHEN COALESCE(pc.players_predicted, 0) < 10 AND eg.games_today > 0 THEN
            'LOW PREDICTIONS: Only ' || CAST(COALESCE(pc.players_predicted, 0) AS STRING) || ' players predicted for ' || CAST(eg.games_today AS STRING) || ' games. Expected ~' || CAST(eg.eligible_players AS STRING) || '.'
        ELSE 'Predictions OK'
    END as alert_message,

    -- Coverage metrics
    CASE
        WHEN eg.eligible_players > 0 THEN
            ROUND(COALESCE(pc.players_predicted, 0) / eg.eligible_players * 100, 2)
        ELSE 0
    END as coverage_percent,

    -- Root cause hints
    STRUCT(
        COALESCE(pc.no_line_count, 0) as no_line_count,
        CASE WHEN COALESCE(pc.no_line_count, 0) > 0 THEN 'Betting lines may have arrived late' ELSE NULL END as hint
    ) as diagnostics

FROM expected_games eg
LEFT JOIN prediction_counts pc ON TRUE
WHERE eg.games_today > 0  -- Only alert when there are actually games
