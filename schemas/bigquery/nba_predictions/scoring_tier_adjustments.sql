-- scoring_tier_adjustments.sql
-- Phase 5C ML Feedback Table
-- Purpose: Store bias adjustments by scoring tier to correct systematic prediction errors
--
-- Key Finding: 30+ point scorers under-predicted by -12.6 points (excessive regression to mean)
-- This table stores adjustments to add to base predictions to correct the bias.
--
-- Usage:
--   adjusted_prediction = base_prediction + (recommended_adjustment * application_factor)
--   where application_factor = 0.5 to 1.0 depending on confidence in the adjustment
--
-- Created: 2025-12-10
-- Author: Phase 5C Implementation

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.scoring_tier_adjustments` (
  -- Primary Keys
  system_id STRING NOT NULL,                    -- e.g., 'ensemble_v1'
  scoring_tier STRING NOT NULL,                 -- e.g., 'STAR_30PLUS', 'STARTER_20_29'
  as_of_date DATE NOT NULL,                     -- Date this adjustment was computed for

  -- Sample Information
  sample_size INTEGER,                          -- Number of predictions analyzed
  lookback_days INTEGER,                        -- How many days of data used (e.g., 30)

  -- Bias Metrics (from prediction_accuracy)
  avg_signed_error NUMERIC(5, 2),               -- Negative = under-predict, Positive = over-predict
  avg_absolute_error NUMERIC(5, 2),             -- MAE for this tier
  std_signed_error NUMERIC(5, 2),               -- Standard deviation of signed error

  -- Recommended Adjustment
  recommended_adjustment NUMERIC(5, 2),         -- Points to ADD to base prediction
  adjustment_confidence NUMERIC(4, 3),          -- 0.0-1.0 confidence in the adjustment

  -- Win Rate Impact
  current_win_rate NUMERIC(4, 3),               -- Win rate without adjustment
  projected_win_rate NUMERIC(4, 3),             -- Estimated win rate with adjustment

  -- Tier Definition
  tier_min_points NUMERIC(5, 1),                -- Lower bound of tier (e.g., 30.0)
  tier_max_points NUMERIC(5, 1),                -- Upper bound of tier (e.g., NULL for 30+)

  -- Metadata
  computed_at TIMESTAMP NOT NULL,               -- When this row was computed
  model_version STRING                          -- Version identifier
)
PARTITION BY as_of_date
CLUSTER BY system_id, scoring_tier
OPTIONS (
  require_partition_filter=TRUE
);

-- Tier Definitions:
-- STAR_30PLUS:     actual_points >= 30 (bias: -12.6)
-- STARTER_20_29:   actual_points >= 20 AND < 30 (bias: -7.2)
-- ROTATION_10_19:  actual_points >= 10 AND < 20 (bias: -3.1)
-- BENCH_0_9:       actual_points < 10 (bias: +1.6)
