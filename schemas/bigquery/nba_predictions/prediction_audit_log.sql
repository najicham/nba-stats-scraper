-- Prediction Audit Log
-- Complete audit trail of every prediction decision
--
-- Purpose: Track what data was available when predictions were made,
-- enable investigation of prediction quality issues, and support
-- automatic re-runs when better data becomes available.
--
-- Created: Session 39 (2026-01-30)

CREATE TABLE IF NOT EXISTS `nba_predictions.prediction_audit_log` (
    -- Identifiers
    audit_id STRING NOT NULL,
    prediction_id STRING,
    player_lookup STRING NOT NULL,
    game_date DATE NOT NULL,
    game_id STRING,
    prop_type STRING,

    -- Processing context
    processing_run_id STRING,
    processed_at TIMESTAMP NOT NULL,
    model_version STRING,
    model_id STRING,

    -- Data availability snapshot at processing time
    bdb_pbp_available BOOL,
    bdb_pbp_game_count INT64,
    nbac_pbp_available BOOL,
    gamebook_available BOOL,
    betting_data_available BOOL,

    -- Feature completeness
    total_features_expected INT64,
    total_features_available INT64,
    feature_completeness_pct FLOAT64,
    missing_features ARRAY<STRING>,

    -- Shot zone specific (critical for model)
    shot_zones_source STRING,  -- 'bigdataball', 'nbac_fallback', 'unavailable'
    paint_rate_available BOOL,
    three_pt_rate_available BOOL,
    mid_range_rate_available BOOL,

    -- Quality assessment
    data_quality_tier STRING,  -- 'gold', 'silver', 'bronze'
    quality_issues ARRAY<STRING>,
    quality_score FLOAT64,  -- 0-100 composite score

    -- Prediction output
    prediction_value FLOAT64,
    prediction_direction STRING,  -- 'over', 'under'
    confidence_score FLOAT64,
    line_value FLOAT64,

    -- Re-run tracking
    is_rerun BOOL DEFAULT FALSE,
    supersedes_audit_id STRING,
    rerun_reason STRING,
    rerun_triggered_at TIMESTAMP,

    -- Game timing (for re-run decisions)
    game_start_time TIMESTAMP,
    hours_until_game FLOAT64,
    rerun_allowed BOOL,  -- False if too close to game time

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, model_id;

-- Add table description
-- ALTER TABLE `nba_predictions.prediction_audit_log`
-- SET OPTIONS (
--   description = 'Audit trail of all predictions with data availability context'
-- );
