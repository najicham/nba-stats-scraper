-- Data Gaps Tracking Table
-- Tracks missing data from various sources and auto-retry status
-- Created: 2026-01-28

CREATE TABLE IF NOT EXISTS `nba_orchestration.data_gaps` (
    -- Game identification
    game_date DATE NOT NULL,
    game_id STRING NOT NULL,
    home_team STRING,
    away_team STRING,

    -- Source that's missing data
    source STRING NOT NULL,  -- 'bigdataball_pbp', 'gamebook', 'bref', 'nba_api', etc.

    -- Timing
    game_finished_at TIMESTAMP,    -- When game ended (from schedule)
    expected_at TIMESTAMP,         -- When we expected data to be available
    detected_at TIMESTAMP NOT NULL,-- When gap was first detected
    resolved_at TIMESTAMP,         -- When data finally appeared (NULL if still missing)

    -- Severity and status
    severity STRING NOT NULL,      -- 'warning' (6-24h), 'critical' (>24h)
    status STRING NOT NULL,        -- 'open', 'resolved', 'manual_review', 'postponed'

    -- Auto-retry tracking
    auto_retry_count INT64 DEFAULT 0,
    last_retry_at TIMESTAMP,
    next_retry_at TIMESTAMP,

    -- Resolution details
    resolution_type STRING,        -- 'auto_resolved', 'manual_backfill', 'marked_postponed'
    resolution_notes STRING,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Index for efficient querying
-- Note: BigQuery doesn't support traditional indexes, but clustering helps
-- ALTER TABLE `nba_orchestration.data_gaps`
-- CLUSTER BY game_date, source, status;
