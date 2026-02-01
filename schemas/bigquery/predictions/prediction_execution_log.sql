-- Prediction Execution Log Table
-- Created: 2026-02-01 (Session 64)
-- Purpose: Audit trail for prediction runs to enable fast debugging
--
-- Key Use Cases:
-- 1. Find predictions made with specific code version (build_commit_sha)
-- 2. Identify runs with low feature quality (pct_with_vegas_line)
-- 3. Track execution timing and errors
-- 4. Correlate issues to specific deployment revisions
--
-- Session 64 Learning: Without this table, debugging the V8 hit rate collapse
-- took 2+ hours of manual investigation. With this table, it would take 5 minutes.

CREATE TABLE IF NOT EXISTS nba_predictions.prediction_execution_log (
  -- Execution identification
  execution_id STRING NOT NULL,           -- UUID for this run
  batch_id STRING,                         -- Links multiple runs in same batch

  -- Code version tracking
  build_commit_sha STRING NOT NULL,        -- Git commit that built the service
  deployment_revision STRING,              -- Cloud Run revision ID (K_REVISION)

  -- Timing
  execution_start_timestamp TIMESTAMP NOT NULL,
  execution_end_timestamp TIMESTAMP,
  duration_seconds FLOAT64,

  -- Scope
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,               -- 'catboost_v8', 'ensemble_v1_1', etc.
  players_requested INT64,
  players_predicted INT64,

  -- Status
  status STRING NOT NULL,                  -- 'started', 'completed', 'failed', 'partial'
  error_message STRING,
  error_count INT64,

  -- Feature Quality Metrics
  avg_feature_quality_score FLOAT64,
  pct_with_vegas_line FLOAT64,             -- % of players with Vegas data
  pct_with_ppm FLOAT64,                    -- % of players with PPM data
  pct_with_shot_zones FLOAT64,             -- % of players with shot zone data

  -- Context
  feature_store_snapshot_time TIMESTAMP,   -- When features were read from store
  feature_source_mode STRING,              -- 'daily' or 'backfill'
  orchestration_run_id STRING              -- Links to orchestration system
)
PARTITION BY DATE(execution_start_timestamp)
CLUSTER BY system_id, game_date
OPTIONS(
  description='Audit log for prediction execution runs. Tracks code version, feature quality, and timing for debugging.'
);

-- Example queries:

-- Find runs by code version
-- SELECT * FROM nba_predictions.prediction_execution_log
-- WHERE build_commit_sha = 'abc1234'
-- ORDER BY execution_start_timestamp DESC;

-- Find runs with low Vegas coverage
-- SELECT * FROM nba_predictions.prediction_execution_log
-- WHERE pct_with_vegas_line < 0.5
-- ORDER BY execution_start_timestamp DESC;

-- Find failed runs
-- SELECT game_date, system_id, error_message, players_requested, players_predicted
-- FROM nba_predictions.prediction_execution_log
-- WHERE status = 'failed'
-- ORDER BY execution_start_timestamp DESC;
