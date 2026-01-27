-- P1 Alert: All Players Missing Prop Lines
-- Trigger: has_prop_line = FALSE for 100% of players after 5 PM
-- Action: Re-trigger Phase 3 automatically
--
-- Context: On 2026-01-26, betting lines arrived after Phase 3 processed,
-- resulting in has_prop_line = FALSE for all players and 0 predictions.
--
-- Usage:
--   bq query --use_legacy_sql=false --parameter=game_date:DATE:2026-01-26 < prop_lines_missing.sql

WITH prop_line_stats AS (
    SELECT
        game_date,
        COUNT(*) as total_players,
        COUNTIF(has_prop_line = TRUE) as players_with_lines,
        COUNTIF(has_prop_line = FALSE OR has_prop_line IS NULL) as players_without_lines,
        COUNTIF(current_points_line IS NOT NULL) as players_with_current_line,
        COUNT(DISTINCT game_id) as games_count,
        MIN(created_at) as earliest_context_created,
        MAX(created_at) as latest_context_created
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date = @game_date
        AND is_production_ready = TRUE
    GROUP BY game_date
),
prop_scraper_check AS (
    -- Check if prop scraper has run recently for this date
    SELECT
        COUNT(DISTINCT player_lookup) as props_scraped_count,
        MAX(scraped_at) as latest_props_scraped
    FROM `nba-props-platform.nba_raw.odds_api_player_props`
    WHERE game_date = @game_date
        AND scraped_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
),
phase3_run_time AS (
    -- Check when Phase 3 last ran
    SELECT
        MAX(processed_at) as last_phase3_run
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date = @game_date
)
SELECT
    @game_date as alert_date,
    CURRENT_TIMESTAMP() as check_timestamp,
    pls.total_players,
    pls.players_with_lines,
    pls.players_without_lines,
    ROUND(pls.players_with_lines / pls.total_players * 100, 2) as prop_line_coverage_pct,
    pls.games_count,
    psc.props_scraped_count,

    -- Alert conditions
    CASE
        WHEN pls.total_players = 0 THEN 'WARNING'
        WHEN pls.players_with_lines = 0 AND pls.total_players > 0 THEN 'CRITICAL'
        WHEN pls.players_with_lines / pls.total_players < 0.20 THEN 'CRITICAL'
        WHEN pls.players_with_lines / pls.total_players < 0.50 THEN 'WARNING'
        WHEN pls.players_with_lines / pls.total_players < 0.80 THEN 'INFO'
        ELSE 'OK'
    END as alert_level,

    CASE
        WHEN pls.total_players = 0 THEN
            'NO DATA: upcoming_player_game_context has no records for ' || CAST(@game_date AS STRING)
        WHEN pls.players_with_lines = 0 AND pls.total_players > 0 THEN
            'CRITICAL: 0% of ' || CAST(pls.total_players AS STRING) || ' players have prop lines. ' ||
            'Phase 3 likely ran before betting lines arrived. Auto-retriggering Phase 3.'
        WHEN pls.players_with_lines / pls.total_players < 0.20 THEN
            'CRITICAL: Only ' || CAST(ROUND(pls.players_with_lines / pls.total_players * 100, 1) AS STRING) ||
            '% of players have prop lines. Phase 3 may need to be re-run.'
        WHEN pls.players_with_lines / pls.total_players < 0.50 THEN
            'WARNING: Only ' || CAST(ROUND(pls.players_with_lines / pls.total_players * 100, 1) AS STRING) ||
            '% of players have prop lines. Check prop scraper timing.'
        WHEN pls.players_with_lines / pls.total_players < 0.80 THEN
            'LOW COVERAGE: ' || CAST(ROUND(pls.players_with_lines / pls.total_players * 100, 1) AS STRING) ||
            '% prop line coverage. Some players missing betting lines.'
        ELSE 'Prop line coverage is healthy'
    END as alert_message,

    -- Timing diagnostics
    STRUCT(
        p3rt.last_phase3_run as phase3_last_run,
        psc.latest_props_scraped as props_last_scraped,
        CASE
            WHEN psc.latest_props_scraped > p3rt.last_phase3_run THEN
                'Props arrived AFTER Phase 3 - need to re-run Phase 3'
            WHEN p3rt.last_phase3_run > psc.latest_props_scraped THEN
                'Phase 3 ran AFTER props scraped - may be timing issue'
            ELSE 'Cannot determine timing'
        END as timing_hint,
        TIMESTAMP_DIFF(psc.latest_props_scraped, p3rt.last_phase3_run, MINUTE) as minutes_between_scrape_and_phase3,
        CASE
            WHEN pls.players_with_lines = 0 THEN
                'gcloud scheduler jobs run phase3-trigger --location=us-west2'
            ELSE NULL
        END as recommended_action
    ) as diagnostics

FROM prop_line_stats pls
LEFT JOIN prop_scraper_check psc ON TRUE
LEFT JOIN phase3_run_time p3rt ON TRUE
WHERE pls.total_players > 0  -- Only alert if there's data
