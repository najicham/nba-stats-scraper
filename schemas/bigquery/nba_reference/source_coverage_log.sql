-- File: schemas/bigquery/nba_reference/source_coverage_log.sql
-- Description: Source coverage event log for tracking data availability, fallbacks, and quality events
-- Created: 2025-11-26
-- Purpose: Comprehensive audit log of all source coverage events across the pipeline

-- ============================================================================
-- SOURCE COVERAGE LOG TABLE
-- ============================================================================
-- Grain: One row per event (game, player, or field-level)
-- Volume: Normal: ~50 game-level events/day
--         Source outage: ~500+ player-level events (15 games x 26 players)
--         Use batch_id to group related events from same processor run
-- Retention: 2 years (auto-expire via partition_expiration_days)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.source_coverage_log` (
    -- Event identification
    event_id STRING NOT NULL,
    event_timestamp TIMESTAMP NOT NULL,

    -- Event classification
    event_type STRING NOT NULL,
    -- Values: 'source_missing', 'fallback_used', 'reconstruction_applied',
    --         'quality_degradation', 'processing_skipped', 'manual_override',
    --         'insufficient_sample', 'thin_sample', 'silent_failure'

    severity STRING NOT NULL,
    -- Values: 'info', 'warning', 'critical'

    -- Processing context
    phase STRING,
    -- Values: 'phase_2', 'phase_3', 'phase_4', 'phase_5'

    table_name STRING,
    -- e.g., 'nba_analytics.player_game_summary'

    processor_name STRING,
    -- e.g., 'PlayerGameSummaryProcessor'

    -- Game/Entity context
    game_id STRING,
    game_date DATE,
    season STRING,
    player_id STRING,
    team_abbr STRING,

    -- Event details
    description STRING,

    -- Source tracking
    primary_source STRING,
    -- e.g., 'nba_raw.nbac_team_boxscore'

    primary_source_status STRING,
    -- Values: 'available', 'missing', 'stale', 'error'

    fallback_sources_tried ARRAY<STRING>,
    -- e.g., ['espn_team_boxscore', 'bdl_box_scores']

    -- Resolution
    resolution STRING,
    -- Values: 'used_primary', 'used_fallback', 'reconstructed', 'skipped', 'failed'

    resolution_details STRING,

    -- Quality impact
    quality_tier_before STRING,
    quality_tier_after STRING,
    quality_score_before FLOAT64,
    quality_score_after FLOAT64,
    downstream_impact STRING,
    -- e.g., 'predictions_blocked', 'confidence_reduced', 'none'

    -- Alerting
    requires_alert BOOL DEFAULT FALSE,
    alert_sent BOOL DEFAULT FALSE,
    alert_channel STRING,
    alert_sent_at TIMESTAMP,
    batch_id STRING,
    -- Group related events for alert deduplication

    -- Resolution tracking
    is_resolved BOOL DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolution_method STRING,
    -- Values: 'backfill', 'source_recovered', 'manual_entry', 'accepted_gap'
    resolved_by STRING,

    -- Metadata
    environment STRING DEFAULT 'prod',
    processor_run_id STRING,
    is_synthetic BOOL DEFAULT FALSE,
    -- TRUE if created by audit job, not processor
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY severity, event_type, game_id
OPTIONS (
    description = 'Event log for source coverage tracking. Logs all source availability issues, fallbacks, and quality events. Partitioned by event_timestamp, clustered by severity/event_type/game_id for efficient queries.',
    partition_expiration_days = 730,
    require_partition_filter = true
);


-- ============================================================================
-- GAME SOURCE COVERAGE SUMMARY VIEW
-- ============================================================================
-- Purpose: Convenient game-level summary of source coverage events
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_reference.game_source_coverage_summary` AS
SELECT
    -- Game identification
    game_id,
    game_date,
    season,

    -- Event summary
    ARRAY_AGG(DISTINCT event_type IGNORE NULLS) as event_types,
    COUNT(*) as total_events,
    COUNT(DISTINCT player_id) as players_affected,

    -- Audit flags
    LOGICAL_OR(is_synthetic) as has_synthetic_events,

    -- Severity tracking
    MAX(
        CASE severity
            WHEN 'critical' THEN 4
            WHEN 'warning' THEN 3
            WHEN 'info' THEN 2
            ELSE 1
        END
    ) as worst_severity_rank,
    MAX(severity) as worst_severity,
    COUNTIF(severity = 'critical') as critical_event_count,
    COUNTIF(severity = 'warning') as warning_event_count,
    COUNTIF(severity = 'info') as info_event_count,

    -- Resolution status
    LOGICAL_OR(NOT is_resolved) as has_unresolved_issues,
    COUNTIF(NOT is_resolved AND severity = 'critical') as unresolved_critical_count,

    -- Quality summary
    MIN(quality_score_after) as min_quality_score,
    MAX(quality_score_after) as max_quality_score,
    AVG(quality_score_after) as avg_quality_score,

    -- Overall tier (worst tier wins)
    CASE
        WHEN LOGICAL_OR(quality_tier_after = 'unusable') THEN 'unusable'
        WHEN LOGICAL_OR(quality_tier_after = 'poor') THEN 'poor'
        WHEN LOGICAL_OR(quality_tier_after = 'bronze') THEN 'bronze'
        WHEN LOGICAL_OR(quality_tier_after = 'silver') THEN 'silver'
        ELSE 'gold'
    END as overall_quality_tier,

    -- Source information
    ARRAY_AGG(DISTINCT primary_source IGNORE NULLS) as primary_sources_checked,
    ARRAY_AGG(DISTINCT
        CASE WHEN resolution = 'used_fallback' THEN primary_source END
        IGNORE NULLS
    ) as fallback_sources_used,
    LOGICAL_OR(resolution = 'reconstructed') as has_reconstruction,

    -- Timing
    MIN(event_timestamp) as first_event_at,
    MAX(event_timestamp) as last_event_at,
    MAX(resolved_at) as last_resolved_at

FROM `nba-props-platform.nba_reference.source_coverage_log`
GROUP BY game_id, game_date, season;
