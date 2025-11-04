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
  
  -- Core Prediction (3 fields)
  predicted_points NUMERIC(5,1) NOT NULL,           -- Predicted points
  confidence_score NUMERIC(5,2) NOT NULL,           -- Confidence (0-100)
  recommendation STRING NOT NULL,                   -- 'OVER', 'UNDER', 'PASS'
  
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
  current_points_line NUMERIC(4,1),                 -- Line at time of prediction
  line_margin NUMERIC(5,2),                         -- predicted_points - current_points_line
  ml_model_id STRING,                               -- Model used (ML systems only)
  
  -- Multi-System Analysis (3 fields) - Added in migration
  prediction_variance NUMERIC(5,2),                 -- Variance across all active systems
  system_agreement_score NUMERIC(5,2),              -- 0-100 score (100 = perfect agreement)
  contributing_systems INT64,                       -- Count of systems that generated predictions
  
  -- Key Factors & Warnings (2 fields stored as JSON)
  key_factors JSON,                                 -- Important factors: {"extreme_fatigue": true, "paint_mismatch": +6.2}
  warnings JSON,                                    -- Warnings: ["low_sample_size", "high_variance"]
  
  -- Status (2 fields)
  is_active BOOLEAN NOT NULL DEFAULT TRUE,          -- FALSE when superseded by newer version
  superseded_by STRING,                             -- prediction_id that replaced this one
  
  -- Timestamps (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup, confidence_score DESC, game_date
OPTIONS(
  description="All predictions from all systems. Multiple systems predict for same player, enabling comparison. Versioned for real-time updates.",
  partition_expiration_days=365
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
