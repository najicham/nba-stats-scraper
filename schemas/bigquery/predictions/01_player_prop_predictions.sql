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
  confidence_score NUMERIC(5,2) NOT NULL,           -- Confidence (0-100)
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
--
-- Last Updated: January 2026
-- Status: Production Ready
-- ============================================================================
