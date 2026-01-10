-- Schema for nba_processing.reprocessing_runs
-- Tracks auto-reprocessing runs for observability and debugging
--
-- This table logs every reprocessing run, whether triggered automatically
-- after AI resolution or manually via CLI.

CREATE TABLE IF NOT EXISTS `nba_processing.reprocessing_runs` (
    -- Run identification
    run_id STRING NOT NULL,
    run_type STRING NOT NULL,  -- 'auto_after_resolution', 'manual_cli', 'scheduled'

    -- Timing
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds FLOAT64,

    -- Player-level metrics
    players_attempted INT64 DEFAULT 0,
    players_succeeded INT64 DEFAULT 0,
    players_failed INT64 DEFAULT 0,

    -- Game-level metrics
    games_attempted INT64 DEFAULT 0,
    games_succeeded INT64 DEFAULT 0,
    games_failed INT64 DEFAULT 0,

    -- Status flags
    circuit_breaker_triggered BOOL DEFAULT FALSE,
    failure_count INT64 DEFAULT 0,
    success_rate FLOAT64,  -- Percentage 0-100

    -- Metadata
    triggered_by STRING,  -- 'ai_resolution', 'cli', 'scheduler'
    notes STRING
)
PARTITION BY DATE(started_at)
CLUSTER BY run_type, circuit_breaker_triggered
OPTIONS (
    description = 'Logs reprocessing runs for registry failure recovery',
    labels = [("component", "registry"), ("type", "observability")]
);

-- Example queries for monitoring:

-- Recent runs summary
-- SELECT
--     DATE(started_at) as date,
--     run_type,
--     COUNT(*) as runs,
--     SUM(games_attempted) as total_games,
--     SUM(games_succeeded) as succeeded,
--     SUM(games_failed) as failed,
--     ROUND(AVG(success_rate), 1) as avg_success_rate,
--     COUNTIF(circuit_breaker_triggered) as circuit_breaks
-- FROM `nba_processing.reprocessing_runs`
-- WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY date, run_type
-- ORDER BY date DESC;

-- Failed runs needing investigation
-- SELECT *
-- FROM `nba_processing.reprocessing_runs`
-- WHERE circuit_breaker_triggered = TRUE
--    OR success_rate < 80
-- ORDER BY started_at DESC
-- LIMIT 10;
