-- ============================================================================
-- Table: ml_experiments
-- File: schemas/bigquery/nba_predictions/ml_experiments.sql
-- Purpose: Registry and tracking of ML experiments (walk-forward, ensemble,
--          ablation, tier-based, etc.)
-- ============================================================================
--
-- This table tracks the full lifecycle of ML experiments:
-- 1. Planning - Define hypothesis and configuration
-- 2. Training - Run experiment with specified parameters
-- 3. Evaluation - Compare results against baseline
-- 4. Promotion - Graduate successful experiments to production
--
-- Experiment Types:
-- - walk_forward: Train on historical data, evaluate on forward period
-- - ensemble: Combine multiple models with learned weights
-- - ablation: Remove features to understand importance
-- - tier_based: Segment analysis by player tier (star/starter/role)
-- - hyperparameter: Grid/random search over model parameters
-- - feature: Test new feature additions
--
-- Workflow:
-- 1. Create experiment config YAML (ml/experiments/configs/)
-- 2. Run training script (train_walkforward.py, etc.)
-- 3. Script inserts experiment record with status='running'
-- 4. On completion, update with results and status='completed'
-- 5. Compare experiments via results_json metrics
-- 6. Promote winner by setting status='promoted'
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_experiments` (
  -- Identity (3 fields)
  experiment_id STRING NOT NULL,               -- UUID: '550e8400-e29b-41d4-a716-446655440000'
  experiment_name STRING NOT NULL,             -- Human-readable: 'JAN_DEC_WALKFORWARD_2026'
  hypothesis STRING,                           -- What we're testing: 'Recent data improves hit rate'

  -- Classification (2 fields)
  experiment_type STRING NOT NULL,             -- 'walk_forward', 'ensemble', 'ablation', 'tier_based', 'hyperparameter', 'feature'
  tags ARRAY<STRING>,                          -- Tags: ['production_candidate', 'recency_weighting', 'points_prop']

  -- Configuration (1 field)
  config_json JSON NOT NULL,                   -- Full experiment configuration (model, features, hyperparams)

  -- Training Period (1 STRUCT field with 3 sub-fields)
  train_period STRUCT<
    start_date DATE,                           -- Training data start: '2021-11-01'
    end_date DATE,                             -- Training data end: '2025-12-31'
    samples INT64                              -- Number of training samples
  >,

  -- Evaluation Period (1 STRUCT field with 3 sub-fields)
  eval_period STRUCT<
    start_date DATE,                           -- Evaluation start: '2026-01-01'
    end_date DATE,                             -- Evaluation end: '2026-01-29'
    samples INT64                              -- Number of evaluation samples
  >,

  -- Results (1 field)
  results_json JSON,                           -- Results: {mae, hit_rate, roi, by_tier, by_line_range}

  -- Model Storage (2 fields)
  model_path STRING,                           -- GCS or local path: 'gs://nba-props-platform-ml-models/exp_ABC123.cbm'
  git_commit STRING,                           -- Git commit hash for reproducibility

  -- Lineage (1 field)
  parent_experiment_id STRING,                 -- Parent experiment for iterative refinement

  -- Status (1 field)
  status STRING NOT NULL,                      -- 'pending', 'running', 'completed', 'failed', 'promoted', 'archived'

  -- Metadata (3 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  completed_at TIMESTAMP,                      -- When experiment finished
  created_by STRING                            -- Who created: 'claude_session_56', 'ml_pipeline'
)
PARTITION BY DATE(created_at)
OPTIONS(
  description="Registry and tracking of ML experiments with full configuration, results, and lineage."
);

-- ============================================================================
-- Indexes and Constraints (implemented via BQ best practices)
-- ============================================================================
-- Note: BigQuery doesn't have traditional indexes. For query optimization:
-- - Partition by DATE(created_at) for time-based queries
-- - Cluster by experiment_type, status for filtering
-- Consider adding clustering:
-- CLUSTER BY experiment_type, status

-- ============================================================================
-- Example Queries
-- ============================================================================

-- Get all completed walk-forward experiments
-- SELECT experiment_id, experiment_name, results_json
-- FROM `nba-props-platform.nba_predictions.ml_experiments`
-- WHERE experiment_type = 'walk_forward'
--   AND status = 'completed'
-- ORDER BY created_at DESC;

-- Get experiment lineage (parent-child chain)
-- WITH RECURSIVE lineage AS (
--   SELECT experiment_id, experiment_name, parent_experiment_id, 1 as depth
--   FROM `nba-props-platform.nba_predictions.ml_experiments`
--   WHERE experiment_id = 'TARGET_ID'
--   UNION ALL
--   SELECT e.experiment_id, e.experiment_name, e.parent_experiment_id, l.depth + 1
--   FROM `nba-props-platform.nba_predictions.ml_experiments` e
--   JOIN lineage l ON e.experiment_id = l.parent_experiment_id
-- )
-- SELECT * FROM lineage ORDER BY depth;

-- Compare experiments by MAE
-- SELECT
--   experiment_id,
--   experiment_name,
--   JSON_VALUE(results_json, '$.overall.mae') as mae,
--   JSON_VALUE(results_json, '$.overall.hit_rate') as hit_rate,
--   JSON_VALUE(results_json, '$.overall.roi') as roi
-- FROM `nba-props-platform.nba_predictions.ml_experiments`
-- WHERE experiment_type = 'walk_forward'
--   AND status = 'completed'
--   AND DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- ORDER BY CAST(JSON_VALUE(results_json, '$.overall.mae') AS FLOAT64) ASC;

-- Get promoted experiments (production candidates)
-- SELECT *
-- FROM `nba-props-platform.nba_predictions.ml_experiments`
-- WHERE status = 'promoted'
-- ORDER BY completed_at DESC;

-- ============================================================================
-- Example Insert (from training script)
-- ============================================================================

-- INSERT INTO `nba-props-platform.nba_predictions.ml_experiments`
-- (experiment_id, experiment_name, hypothesis, experiment_type, tags, config_json,
--  train_period, eval_period, status, git_commit, created_by)
-- VALUES (
--   GENERATE_UUID(),
--   'JAN_DEC_WALKFORWARD_2026',
--   'Training on Nov 2021 - Dec 2025 data improves January 2026 predictions',
--   'walk_forward',
--   ['production_candidate', 'recency_weighting', 'points_prop'],
--   JSON '{
--     "model": {"type": "catboost", "version": "v9"},
--     "features": {"version": "v2_37features", "count": 37},
--     "hyperparameters": {"depth": 6, "learning_rate": 0.07, "l2_leaf_reg": 3.8},
--     "recency": {"enabled": true, "half_life_days": 180}
--   }',
--   STRUCT(DATE '2021-11-01', DATE '2025-12-31', 180000),
--   STRUCT(DATE '2026-01-01', DATE '2026-01-29', 8500),
--   'running',
--   'abc123def',
--   'ml_training_session'
-- );

-- ============================================================================
-- Update Results on Completion
-- ============================================================================

-- UPDATE `nba-props-platform.nba_predictions.ml_experiments`
-- SET
--   results_json = JSON '{
--     "overall": {"mae": 5.23, "hit_rate": 0.564, "roi": 0.032, "samples": 8500},
--     "by_tier": {
--       "star": {"mae": 5.81, "hit_rate": 0.542, "samples": 1200},
--       "starter": {"mae": 5.15, "hit_rate": 0.571, "samples": 4100},
--       "role": {"mae": 5.02, "hit_rate": 0.576, "samples": 3200}
--     },
--     "by_line_range": {
--       "0_10": {"mae": 3.21, "hit_rate": 0.612, "samples": 2800},
--       "10_20": {"mae": 5.18, "hit_rate": 0.558, "samples": 3500},
--       "20_plus": {"mae": 7.42, "hit_rate": 0.531, "samples": 2200}
--     }
--   }',
--   model_path = 'gs://nba-props-platform-ml-models/exp_JAN_DEC_2026.cbm',
--   status = 'completed',
--   completed_at = CURRENT_TIMESTAMP()
-- WHERE experiment_id = 'TARGET_EXPERIMENT_ID';
