-- Feature Store Gaps Tracking Table
-- Tracks when the ML feature store processor skips players, enabling
-- automatic detection and backfill of missing records.
--
-- Created: Session 144 (2026-02-07)
--
-- Usage: Query unresolved gaps to find records needing backfill:
--   SELECT game_date, reason, COUNT(*) as gap_count
--   FROM nba_predictions.feature_store_gaps
--   WHERE resolved_at IS NULL
--   GROUP BY 1, 2 ORDER BY 1 DESC;

CREATE TABLE IF NOT EXISTS `nba_predictions.feature_store_gaps` (
    -- Identifiers
    player_lookup STRING NOT NULL,
    game_date DATE NOT NULL,
    game_id STRING,

    -- Gap details
    reason STRING NOT NULL,  -- 'bootstrap', 'missing_phase4', 'missing_phase3', 'no_game_summary', 'upstream_incomplete', 'circuit_breaker', 'processing_error'
    reason_detail STRING,    -- Additional context (e.g., which Phase 4 processor is missing)

    -- Context
    team_abbr STRING,
    opponent_team_abbr STRING,
    season_year INT64,

    -- Tracking
    detected_at TIMESTAMP NOT NULL,
    detected_by STRING,      -- 'processor', 'backfill', 'coverage_audit'
    resolved_at TIMESTAMP,   -- NULL until backfilled
    resolved_by STRING,      -- 'backfill', 'manual', 'reprocessing'

    -- Metadata
    backfill_attempt_count INT64 DEFAULT 0,
    last_backfill_attempt_at TIMESTAMP,
    last_backfill_error STRING
)
PARTITION BY game_date
CLUSTER BY reason, player_lookup
OPTIONS (
    description = 'Tracks ML feature store gaps for automatic detection and backfill (Session 144)',
    labels = [("phase", "phase_4"), ("purpose", "gap_tracking")]
);
