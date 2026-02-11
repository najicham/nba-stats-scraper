-- Session 153: Materialized subset picks table
--
-- Stores the ACTUAL subset picks at the moment they were computed.
-- Each prediction batch creates a new version. This replaces the on-the-fly
-- computation that happened in AllSubsetsPicksExporter with a queryable entity.
--
-- Key benefits:
-- - Subsets are materialized when predictions are made (not at export time)
-- - Historical versions tracked via version_id (append-only, no UPDATEs)
-- - Grading uses actual subset membership, not retroactive recomputation
-- - Denormalized pick data avoids JOIN issues with superseded predictions
-- - Rich provenance: line_source, prediction_run_mode, quality fields
--
-- Design: APPEND-ONLY
--   Every materialization INSERTs a new set of rows with a new version_id.
--   No UPDATEs are ever performed (avoids BigQuery 90-min DML partition locks).
--   Consumers select the version they need:
--     - Exporter: MAX(version_id) for latest picks
--     - Grader:   MAX(version_id) WHERE computed_at < first_tip_time
--     - History:  All versions for time-series analysis
--
-- Usage:
--   bq query --use_legacy_sql=false < schemas/bigquery/predictions/06_current_subset_picks.sql

CREATE TABLE IF NOT EXISTS nba_predictions.current_subset_picks (
    -- Identity
    game_date DATE NOT NULL,
    subset_id STRING NOT NULL,
    player_lookup STRING NOT NULL,
    system_id STRING,                   -- Model that produced this pick (e.g., 'catboost_v9', 'catboost_v9_q43_train1102_0131')
    prediction_id STRING,               -- FK to player_prop_predictions
    game_id STRING,                     -- FK to nba_schedule for per-game analysis
    rank_in_subset INT64,               -- Position within subset (1=best, 2=second, etc.)

    -- Snapshot version (new version per materialization, append-only)
    version_id STRING NOT NULL,         -- e.g., "v_20260207_143022"
    computed_at TIMESTAMP NOT NULL,
    trigger_source STRING,              -- 'overnight', 'same_day', 'line_check', 'manual', 'export'
    batch_id STRING,                    -- prediction batch that triggered this

    -- Denormalized pick data (frozen at materialization time)
    player_name STRING,
    team STRING,
    opponent STRING,
    predicted_points FLOAT64,
    current_points_line FLOAT64,
    recommendation STRING,              -- 'OVER' or 'UNDER'
    confidence_score FLOAT64,
    edge FLOAT64,
    composite_score FLOAT64,

    -- Data quality provenance (from prediction at materialization time)
    feature_quality_score FLOAT64,      -- Overall quality 0-100
    default_feature_count INT64,        -- Should be 0 (zero tolerance), tracked for audit
    line_source STRING,                 -- 'ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS', 'ESTIMATED'
    prediction_run_mode STRING,         -- 'EARLY', 'OVERNIGHT', 'RETRY', 'LAST_CALL', 'LINE_CHECK', 'BACKFILL'
    prediction_made_before_game BOOL,   -- TRUE if made before game start
    quality_alert_level STRING,         -- 'green', 'yellow', 'red'

    -- Subset metadata (denormalized from definitions for historical accuracy)
    subset_name STRING,
    min_edge FLOAT64,
    min_confidence FLOAT64,
    top_n INT64,

    -- Version-level context (same for all picks in a version)
    daily_signal STRING,                -- GREEN/YELLOW/RED market signal at materialization time
    pct_over FLOAT64,                   -- % OVER signal at materialization time
    total_predictions_available INT64   -- How many predictions existed when this version was computed
)
PARTITION BY game_date
CLUSTER BY version_id, subset_id;
