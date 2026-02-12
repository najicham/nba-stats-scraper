-- ============================================================================
-- Table: player_prop_predictions
-- File: 01_player_prop_predictions.sql
-- Purpose: All predictions from all systems for all players (CRITICAL TABLE)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.player_prop_predictions` (
  -- Identifiers (7 fields)
  prediction_id STRING NOT NULL,                    -- Unique prediction ID (UUID)
  system_id STRING NOT NULL,                        -- Which system made this prediction
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  prediction_version INT64 NOT NULL DEFAULT 1,      -- Version (increments on updates)
  
  -- Core Prediction (4 fields - added has_prop_line in v3.2)
  predicted_points NUMERIC(5,1) NOT NULL,           -- Predicted points
  confidence_score NUMERIC(5,2) NOT NULL,           -- Confidence (0-100 scale)
  recommendation STRING NOT NULL,                   -- 'OVER', 'UNDER', 'PASS', 'NO_LINE' (v3.2)
  has_prop_line BOOLEAN DEFAULT TRUE,               -- TRUE if player had betting line when prediction was made (v3.2)
  
  -- Prediction Components (9 fields)
  -- What went into this prediction
  similarity_baseline NUMERIC(5,1),                 -- Baseline from similar games (rule-based only)
  fatigue_adjustment NUMERIC(5,2),                  -- Points adjustment from fatigue
  shot_zone_adjustment NUMERIC(5,2),                -- Points adjustment from matchup
  referee_adjustment NUMERIC(5,2),                  -- Points adjustment from referee
  look_ahead_adjustment NUMERIC(5,2),               -- Points adjustment from schedule
  pace_adjustment NUMERIC(5,2),                     -- Points adjustment from pace
  usage_spike_adjustment NUMERIC(5,2),              -- Points adjustment from role changes
  home_away_adjustment NUMERIC(5,2),                -- Points adjustment from venue
  other_adjustments NUMERIC(5,2),                   -- Sum of matchup_history + momentum
  
  -- Supporting Metadata (6 fields)
  similar_games_count INT64,                        -- Sample size (rule-based only)
  avg_similarity_score NUMERIC(5,2),                -- Quality of matches (rule-based only)
  min_similarity_score NUMERIC(5,2),                -- Minimum match quality
  current_points_line NUMERIC(4,1),                 -- Actual prop line at time of prediction (NULL if no prop)
  line_margin NUMERIC(5,2),                         -- predicted_points - current_points_line (NULL if no prop)
  ml_model_id STRING,                               -- Model used (ML systems only)

  -- Line Source Tracking (6 fields - v3.2 All-Player Predictions, v3.3 adds API/sportsbook)
  -- Tracks what line was used when making the prediction
  line_source STRING,                               -- 'ACTUAL_PROP' or 'ESTIMATED_AVG'
  estimated_line_value NUMERIC(4,1),                -- The estimated line used if no prop existed
  estimation_method STRING,                         -- 'points_avg_last_5', 'points_avg_last_10', 'default_15.5'
  line_source_api STRING,                           -- 'ODDS_API', 'BETTINGPROS', 'ESTIMATED' (v3.3)
  sportsbook STRING,                                -- 'DRAFTKINGS', 'FANDUEL', 'BETMGM', etc. (v3.3)
  was_line_fallback BOOLEAN DEFAULT FALSE,          -- TRUE if line came from fallback source (v3.3)

  -- Model Attribution Tracking (6 fields - v3.6 Session 84/85)
  -- Tracks which exact model file generated predictions for debugging and A/B testing
  model_file_name STRING,                           -- Model filename (e.g., "catboost_v9_feb_02_retrain.cbm")
  model_training_start_date DATE,                   -- Training period start date
  model_training_end_date DATE,                     -- Training period end date
  model_expected_mae FLOAT64,                       -- Expected mean absolute error from validation
  model_expected_hit_rate FLOAT64,                  -- Expected hit rate percentage from validation
  model_trained_at TIMESTAMP,                       -- When model was trained
  
  -- Multi-System Analysis (3 fields) - Added in migration
  prediction_variance NUMERIC(5,2),                 -- Variance across all active systems
  system_agreement_score NUMERIC(5,2),              -- 0-100 score (100 = perfect agreement)
  contributing_systems INT64,                       -- Count of systems that generated predictions
  
  -- Key Factors & Warnings (2 fields stored as JSON)
  key_factors JSON,                                 -- Important factors: {"extreme_fatigue": true, "paint_mismatch": +6.2}
  warnings JSON,                                    -- Warnings: ["low_sample_size", "high_variance"]

  -- Completeness Checking Metadata (14 fields) - Added Phase 5
  -- Tracks feature data quality from ml_feature_store_v2
  expected_games_count INT64,                       -- Games expected in feature window
  actual_games_count INT64,                         -- Games actually present
  completeness_percentage FLOAT64,                  -- Percentage of expected data present (0-100)
  missing_games_count INT64,                        -- Count of missing games
  is_production_ready BOOLEAN,                      -- TRUE if completeness >= 90% and upstream ready
  data_quality_issues ARRAY<STRING>,                -- List of quality issues detected
  last_reprocess_attempt_at TIMESTAMP,              -- Last time reprocessing was attempted
  reprocess_attempt_count INT64,                    -- Number of reprocessing attempts
  circuit_breaker_active BOOLEAN,                   -- TRUE if entity blocked from reprocessing
  circuit_breaker_until TIMESTAMP,                  -- When circuit breaker cooldown expires
  manual_override_required BOOLEAN,                 -- TRUE if manual intervention needed
  season_boundary_detected BOOLEAN,                 -- TRUE if processing near season start/end
  backfill_bootstrap_mode BOOLEAN,                  -- TRUE if processed in bootstrap mode
  processing_decision_reason STRING,                -- Why this decision was made

  -- Status (2 fields)
  is_active BOOLEAN NOT NULL DEFAULT TRUE,          -- FALSE when superseded by newer version
  superseded_by STRING,                             -- prediction_id that replaced this one

  -- Pre-game Injury Tracking (4 fields - v3.4)
  -- Captures injury status AT PREDICTION TIME for expected vs surprise void analysis
  injury_status_at_prediction STRING,               -- OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, or NULL if healthy
  injury_flag_at_prediction BOOLEAN,                -- TRUE if any injury concern (OUT/DOUBTFUL/QUESTIONABLE)
  injury_reason_at_prediction STRING,               -- Injury reason text (e.g., "Left Knee - Soreness")
  injury_checked_at TIMESTAMP,                      -- When injury status was checked

  -- Invalidation Tracking (2 fields - v3.5 Postponement Handling)
  -- Tracks when predictions are invalidated due to postponed/cancelled games
  invalidation_reason STRING,                   -- 'game_postponed', 'game_cancelled', 'player_inactive'
  invalidated_at TIMESTAMP,                     -- When prediction was invalidated

  -- Pre-game flag (Session 139)
  prediction_made_before_game BOOLEAN,            -- TRUE if made before game start, FALSE for backfills

  -- Feature completeness tracking (Session 142)
  default_feature_indices ARRAY<INT64>,           -- Indices of features using default/fallback values

  -- Timestamps (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup, confidence_score DESC, game_date
OPTIONS(
  description="All predictions from all systems. Multiple systems predict for same player, enabling comparison. Versioned for real-time updates.",
  partition_expiration_days=365,
  require_partition_filter=TRUE
);

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get today's predictions for a player (all systems)
-- SELECT 
--   system_id,
--   predicted_points,
--   confidence_score,
--   recommendation,
--   current_points_line,
--   line_margin
-- FROM `nba-props-platform.nba_predictions.player_prop_predictions`
-- WHERE game_date = CURRENT_DATE()
--   AND player_lookup = 'lebron-james'
--   AND is_active = TRUE
-- ORDER BY confidence_score DESC;

-- Get high confidence predictions for today
-- SELECT 
--   player_lookup,
--   system_id,
--   predicted_points,
--   confidence_score,
--   recommendation,
--   current_points_line
-- FROM `nba-props-platform.nba_predictions.player_prop_predictions`
-- WHERE game_date = CURRENT_DATE()
--   AND is_active = TRUE
--   AND confidence_score >= 85
-- ORDER BY confidence_score DESC;

-- Compare system predictions for a player
-- SELECT 
--   system_id,
--   predicted_points,
--   confidence_score,
--   fatigue_adjustment,
--   pace_adjustment,
--   shot_zone_adjustment
-- FROM `nba-props-platform.nba_predictions.player_prop_predictions`
-- WHERE game_date = '2025-01-15'
--   AND player_lookup = 'lebron-james'
--   AND is_active = TRUE
-- ORDER BY system_id;

-- Get predictions with high system agreement
-- SELECT
--   player_lookup,
--   COUNT(DISTINCT system_id) as system_count,
--   AVG(predicted_points) as avg_prediction,
--   STDDEV(predicted_points) as prediction_std,
--   AVG(system_agreement_score) as avg_agreement
-- FROM `nba-props-platform.nba_predictions.player_prop_predictions`
-- WHERE game_date = CURRENT_DATE()
--   AND is_active = TRUE
-- GROUP BY player_lookup
-- HAVING system_count >= 4
--   AND prediction_std <= 2.0  -- High agreement
-- ORDER BY avg_agreement DESC;

-- ============================================================================
-- DEPLOYMENT: Add all-player prediction columns (v3.2)
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS has_prop_line BOOLEAN
  OPTIONS (description='TRUE if player had betting line when prediction was made'),
ADD COLUMN IF NOT EXISTS line_source STRING
  OPTIONS (description='ACTUAL_PROP or ESTIMATED_AVG - indicates line source'),
ADD COLUMN IF NOT EXISTS estimated_line_value NUMERIC(4,1)
  OPTIONS (description='The estimated line used if no prop existed'),
ADD COLUMN IF NOT EXISTS estimation_method STRING
  OPTIONS (description='How line was estimated: points_avg_last_5, points_avg_last_10, default_15.5');

-- v3.3: Add line source API and sportsbook tracking (enables hit rate by source analysis)
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS line_source_api STRING
  OPTIONS (description='Line source API: ODDS_API, BETTINGPROS, or ESTIMATED'),
ADD COLUMN IF NOT EXISTS sportsbook STRING
  OPTIONS (description='Sportsbook name: DRAFTKINGS, FANDUEL, BETMGM, etc.'),
ADD COLUMN IF NOT EXISTS was_line_fallback BOOLEAN
  OPTIONS (description='TRUE if line came from fallback source (not primary)');

-- v3.4: Add pre-game injury status tracking (enables expected vs surprise void analysis)
-- Captures injury status AT PREDICTION TIME so we can distinguish:
-- - Expected voids: Player was flagged with injury concern before game (we had warning)
-- - Surprise voids: Player DNP'd without prior warning (late scratch)
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS injury_status_at_prediction STRING
  OPTIONS (description='Injury status when prediction was made: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, or NULL if healthy'),
ADD COLUMN IF NOT EXISTS injury_flag_at_prediction BOOLEAN
  OPTIONS (description='TRUE if player had any injury concern at prediction time (OUT/DOUBTFUL/QUESTIONABLE)'),
ADD COLUMN IF NOT EXISTS injury_reason_at_prediction STRING
  OPTIONS (description='Injury reason text at prediction time (e.g., "Left Knee - Soreness")'),
ADD COLUMN IF NOT EXISTS injury_checked_at TIMESTAMP
  OPTIONS (description='Timestamp when injury status was checked during prediction');

-- v3.5: Add invalidation tracking for postponed/cancelled games
-- When games are postponed, predictions need to be marked as invalid so they:
-- 1. Don't get graded (would skew accuracy metrics)
-- 2. Are excluded from downstream analysis
-- 3. Have an audit trail of why they were invalidated
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS invalidation_reason STRING
  OPTIONS (description='Reason prediction was invalidated: game_postponed, game_cancelled, player_inactive'),
ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMP
  OPTIONS (description='When prediction was invalidated');

-- v4.0: Add teammate impact and model metadata fields (Session 4 fix)
-- These fields exist in BigQuery (added at runtime) but were missing from schema SQL
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS feature_importance JSON
  OPTIONS (description='Feature importance scores from ML model'),
ADD COLUMN IF NOT EXISTS filter_reason STRING
  OPTIONS (description='Reason prediction was filtered out if applicable'),
ADD COLUMN IF NOT EXISTS is_actionable BOOLEAN
  OPTIONS (description='TRUE if prediction meets actionability thresholds'),
ADD COLUMN IF NOT EXISTS line_minutes_before_game INT64
  OPTIONS (description='Minutes before game when line was captured'),
ADD COLUMN IF NOT EXISTS model_version STRING
  OPTIONS (description='Version of the ML model used for prediction'),
ADD COLUMN IF NOT EXISTS teammate_opportunity_score FLOAT64
  OPTIONS (description='Score indicating opportunity from teammate absences'),
ADD COLUMN IF NOT EXISTS teammate_out_starters STRING
  OPTIONS (description='Comma-separated list of starters who are out'),
ADD COLUMN IF NOT EXISTS teammate_usage_boost FLOAT64
  OPTIONS (description='Expected usage boost from teammate absences');

-- v4.1: Add features_snapshot for debugging and reproducibility (Session 66)
-- Stores the actual feature values used when making the prediction
-- This prevents issues when feature store is backfilled with different values later
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS features_snapshot JSON
  OPTIONS (description='Snapshot of feature values used for prediction. Enables debugging when hit rates change unexpectedly.'),
ADD COLUMN IF NOT EXISTS feature_version STRING
  OPTIONS (description='Feature version used: v2_33features, v2_37features, etc.'),
ADD COLUMN IF NOT EXISTS feature_quality_score FLOAT64
  OPTIONS (description='Quality score of features at prediction time (0-100)');

-- Session 152: Vegas line source from feature store
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS vegas_line_source STRING
  OPTIONS (description='Session 152: Which scraper source provided ML features 25-28. Values: odds_api, bettingpros, both, none. Distinct from line_source_api which tracks the prediction line.');

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (Initial):       Core prediction fields
-- v3.2 (+all_players):  Added has_prop_line column for all-player predictions
--                       Added NO_LINE recommendation type
--                       Added line_source, estimated_line_value, estimation_method
--                       for tracking what line was used when no prop existed
--                       Now generates predictions for ALL players, not just prop-line players
-- v3.3 (+source_track): Added line_source_api, sportsbook, was_line_fallback
--                       Enables analysis of hit rate by API source and sportsbook
--                       Supports future fallback logic (DraftKings -> FanDuel -> BettingPros)
-- v3.4 (+injury_track): Added injury_status_at_prediction, injury_flag_at_prediction,
--                       injury_reason_at_prediction, injury_checked_at
--                       Enables distinguishing expected vs surprise voids
--                       Captures injury status AT PREDICTION TIME for better analysis
-- v3.5 (+invalidation): Added invalidation_reason, invalidated_at
--                       Tracks predictions invalidated due to postponed/cancelled games
--                       Ensures invalidated predictions are excluded from grading
-- v4.0 (+teammate):     Added feature_importance, filter_reason, is_actionable,
--                       line_minutes_before_game, model_version, teammate_opportunity_score,
--                       teammate_out_starters, teammate_usage_boost
--                       These fields existed in BigQuery (runtime) but were missing from SQL
-- v4.1 (+features):     Added features_snapshot JSON, feature_version, feature_quality_score
--                       Enables debugging when hit rates change unexpectedly
--                       Stores actual feature values used at prediction time
--                       Prevents issues when feature store is backfilled with different values
--
-- Last Updated: February 1, 2026
-- Status: Production Ready
-- ============================================================================

-- ============================================================================
-- Schema Migration: Add Missing Fields (Session 79)
-- Detected by pre-commit hook validate_schema_fields.py
-- ============================================================================

-- Session 64: Build & deployment tracking for debugging
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS build_commit_sha STRING OPTIONS(description="Git commit hash of deployed code (Session 64 traceability)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS deployment_revision STRING OPTIONS(description="Cloud Run revision name (Session 64 traceability)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMP OPTIONS(description="Exact timestamp when prediction was generated (Session 64)");

-- Session 76: Prediction run mode tracking
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS prediction_run_mode STRING OPTIONS(description="OVERNIGHT, EARLY, SAME_DAY - which prediction run generated this (Session 76)");

-- Session 79: Kalshi prediction market integration
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_available BOOLEAN OPTIONS(description="TRUE if Kalshi has a prediction market for this prop");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_line NUMERIC(4,1) OPTIONS(description="Kalshi prediction market line (points)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_yes_price NUMERIC(5,2) OPTIONS(description="Kalshi YES price (cents, 0-100)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_no_price NUMERIC(5,2) OPTIONS(description="Kalshi NO price (cents, 0-100)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_market_ticker STRING OPTIONS(description="Kalshi market ticker symbol");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_liquidity INT64 OPTIONS(description="Total contracts traded in Kalshi market");

-- Feature quality tracking
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS critical_features JSON OPTIONS(description="List of critical features that used fallback values");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS line_discrepancy NUMERIC(5,2) OPTIONS(description="Difference between multiple line sources (if applicable)");

-- Session 139: Quality visibility fields (from ml_feature_store_v2)
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS is_quality_ready BOOL OPTIONS(description="Session 139: Quality gate from feature store (gold/silver/bronze + score>=70 + matchup>=50)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS quality_alert_level STRING OPTIONS(description="Session 139: Quality alert level at prediction time: green, yellow, red");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS matchup_quality_pct FLOAT64 OPTIONS(description="Session 139: Matchup feature quality percentage (0-100) at prediction time");

-- Session 139: Track whether prediction was made before game started
-- FALSE for BACKFILL or post-game predictions (record-keeping only, not actionable)
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS prediction_made_before_game BOOL OPTIONS(description="Session 139: TRUE if made before game start, FALSE for backfills/post-game");

-- Session 141: Default feature count for audit trail (zero tolerance enforcement)
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS default_feature_count INT64 OPTIONS(description="Session 141: Number of features using default/fallback values (0 = all real data)");

-- Session 142: Default feature indices for per-feature audit trail
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS default_feature_indices ARRAY<INT64> OPTIONS(description="Session 142: Indices of features using default/fallback values (empty = all real data)");

