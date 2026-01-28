-- P1 Alert: Low Usage Rate Coverage
-- Trigger: usage_rate coverage < 80% for completed game day
-- Action: Slack notification
--
-- Context: On 2026-01-26, 71% of records had NULL usage_rate, indicating
-- Phase 2 processed incomplete boxscores before they were updated.
--
-- Usage:
--   bq query --use_legacy_sql=false --parameter=game_date:DATE:2026-01-26 < low_usage_coverage.sql

WITH boxscore_stats AS (
    SELECT
        game_date,
        COUNT(*) as total_records,
        COUNTIF(usage_rate IS NOT NULL) as with_usage_rate,
        COUNTIF(usage_rate IS NULL) as null_usage_rate,
        COUNTIF(minutes_played IS NOT NULL) as with_minutes,
        COUNTIF(minutes_played IS NULL) as null_minutes,
        COUNT(DISTINCT game_id) as games_count,
        COUNT(DISTINCT player_lookup) as players_count
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = @game_date
    GROUP BY game_date
),
game_completion AS (
    SELECT
        game_date,
        COUNT(*) as total_games,
        COUNTIF(game_status_text = 'Final') as completed_games,
        MIN(last_updated_utc) as earliest_final,
        MAX(last_updated_utc) as latest_final
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_date = @game_date
    GROUP BY game_date
)
SELECT
    @game_date as alert_date,
    CURRENT_TIMESTAMP() as check_timestamp,
    bs.total_records,
    bs.with_usage_rate,
    bs.null_usage_rate,
    ROUND(bs.with_usage_rate / bs.total_records * 100, 2) as usage_rate_coverage_pct,
    bs.games_count,
    gc.completed_games,
    gc.total_games,

    -- Alert conditions
    CASE
        WHEN bs.total_records = 0 THEN 'WARNING'
        WHEN bs.with_usage_rate / bs.total_records < 0.80 AND gc.completed_games = gc.total_games THEN 'WARNING'
        WHEN bs.with_usage_rate / bs.total_records < 0.50 AND gc.completed_games = gc.total_games THEN 'CRITICAL'
        ELSE 'OK'
    END as alert_level,

    CASE
        WHEN bs.total_records = 0 THEN
            'NO DATA: player_game_summary has no records for ' || CAST(@game_date AS STRING)
        WHEN bs.with_usage_rate / bs.total_records < 0.50 AND gc.completed_games = gc.total_games THEN
            'CRITICAL: Only ' || CAST(ROUND(bs.with_usage_rate / bs.total_records * 100, 1) AS STRING) ||
            '% of records have usage_rate after all games completed. Boxscores may be incomplete.'
        WHEN bs.with_usage_rate / bs.total_records < 0.80 AND gc.completed_games = gc.total_games THEN
            'LOW COVERAGE: Only ' || CAST(ROUND(bs.with_usage_rate / bs.total_records * 100, 1) AS STRING) ||
            '% of records have usage_rate. Expected >80% after games complete.'
        ELSE 'Usage rate coverage is healthy'
    END as alert_message,

    -- Timing diagnostics
    STRUCT(
        gc.earliest_final as first_game_final,
        gc.latest_final as last_game_final,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), gc.latest_final, HOUR) as hours_since_last_final,
        CASE
            WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), gc.latest_final, HOUR) < 2 THEN
                'Games recently completed - may need more time for boxscore updates'
            ELSE NULL
        END as timing_hint
    ) as diagnostics

FROM boxscore_stats bs
LEFT JOIN game_completion gc ON bs.game_date = gc.game_date
WHERE bs.total_records > 0  -- Only alert if there's data
