-- ============================================================================
-- Prediction Performance Summary Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: prediction_performance_summary
-- Purpose: Pre-aggregated prediction performance by multiple dimensions
-- Created: 2025-12-17
-- ============================================================================
--
-- This table provides fast API access to prediction performance sliced by:
-- - Player (track record on specific players)
-- - Archetype (veteran_star, prime_star, young_star, ironman, role_player)
-- - Situation (bounce_back, home, away, rest_3plus, b2b, etc.)
-- - Confidence tier (high, medium, low)
-- - Time period (rolling_7d, rolling_30d, month, season)
--
-- Source: nba_predictions.prediction_accuracy (Phase 5B)
-- Refresh: Daily after Phase 5B grading completes
--
-- Design: Uses NULL to represent "all" for a dimension, enabling queries like:
-- - "Ensemble on LeBron": player_lookup = 'lebron-james', archetype IS NULL
-- - "Ensemble on veteran stars": archetype = 'veteran_star', player_lookup IS NULL
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_performance_summary` (
  -- Primary Key (composite)
  summary_key STRING NOT NULL,              -- Unique key for MERGE operations

  -- System dimension (always required)
  system_id STRING NOT NULL,                -- 'ensemble_v1', 'xgboost_v1', etc.

  -- Time dimension (always required)
  period_type STRING NOT NULL,              -- 'rolling_7d', 'rolling_30d', 'month', 'season'
  period_value STRING NOT NULL,             -- '2024-12-17' (for rolling), '2024-12' (month), '2024-25' (season)
  period_start_date DATE,                   -- First date in period
  period_end_date DATE,                     -- Last date in period

  -- Slicing dimensions (NULL = aggregate across all values)
  player_lookup STRING,                     -- Specific player or NULL for all players
  archetype STRING,                         -- 'veteran_star', 'prime_star', etc. or NULL
  confidence_tier STRING,                   -- 'high' (>=70), 'medium' (55-69), 'low' (<55), or NULL
  situation STRING,                         -- 'bounce_back', 'home', 'away', 'rest_3plus', 'b2b', or NULL

  -- Volume metrics
  total_predictions INT64,                  -- All predictions in this slice
  total_recommendations INT64,              -- OVER + UNDER (excludes PASS)
  over_recommendations INT64,               -- OVER calls only
  under_recommendations INT64,              -- UNDER calls only
  pass_recommendations INT64,               -- PASS calls only

  -- Accuracy metrics
  hits INT64,                               -- Correct OVER/UNDER recommendations
  misses INT64,                             -- Incorrect OVER/UNDER recommendations
  hit_rate FLOAT64,                         -- hits / total_recommendations
  over_hit_rate FLOAT64,                    -- Accuracy on OVER calls
  under_hit_rate FLOAT64,                   -- Accuracy on UNDER calls

  -- Error metrics
  mae FLOAT64,                              -- Mean Absolute Error
  avg_bias FLOAT64,                         -- Mean Signed Error (+ = over-predict)
  within_3_pct FLOAT64,                     -- % of predictions within 3 points
  within_5_pct FLOAT64,                     -- % of predictions within 5 points

  -- Confidence metrics
  avg_confidence FLOAT64,                   -- Average confidence score

  -- Sample quality
  unique_players INT64,                     -- Distinct players in this slice
  unique_games INT64,                       -- Distinct games in this slice

  -- Metadata
  computed_at TIMESTAMP NOT NULL,
  data_hash STRING                          -- For change detection
)
PARTITION BY DATE(computed_at)
CLUSTER BY system_id, period_type, archetype, player_lookup
OPTIONS (
  description = 'Pre-aggregated prediction performance by player, archetype, situation, confidence tier, and time period. Enables fast API queries for track record display.'
);

-- ============================================================================
-- Summary Key Format
-- ============================================================================
-- The summary_key uniquely identifies each aggregation slice:
-- Format: {system_id}|{period_type}|{period_value}|{player_lookup}|{archetype}|{confidence_tier}|{situation}
-- Example: ensemble_v1|rolling_30d|2024-12-17|lebron-james|NULL|NULL|NULL
-- Example: ensemble_v1|season|2024-25|NULL|veteran_star|high|NULL

-- ============================================================================
-- Example Queries
-- ============================================================================

-- Track record on specific player (for Player Modal)
-- SELECT hit_rate, hits, total_recommendations
-- FROM prediction_performance_summary
-- WHERE system_id = 'ensemble_v1'
--   AND period_type = 'season'
--   AND period_value = '2024-25'
--   AND player_lookup = 'lebron-james'
--   AND archetype IS NULL
--   AND confidence_tier IS NULL
--   AND situation IS NULL;

-- Performance on archetypes (for Trends Page - What Matters)
-- SELECT archetype, hit_rate, total_recommendations
-- FROM prediction_performance_summary
-- WHERE system_id = 'ensemble_v1'
--   AND period_type = 'rolling_30d'
--   AND player_lookup IS NULL
--   AND archetype IS NOT NULL
--   AND confidence_tier IS NULL
--   AND situation IS NULL
-- ORDER BY hit_rate DESC;

-- High confidence picks this month
-- SELECT hit_rate, hits, total_recommendations, avg_confidence
-- FROM prediction_performance_summary
-- WHERE system_id = 'ensemble_v1'
--   AND period_type = 'month'
--   AND period_value = '2024-12'
--   AND confidence_tier = 'high'
--   AND player_lookup IS NULL
--   AND archetype IS NULL;

-- Bounce-back situation performance
-- SELECT hit_rate, total_recommendations
-- FROM prediction_performance_summary
-- WHERE system_id = 'ensemble_v1'
--   AND period_type = 'rolling_30d'
--   AND situation = 'bounce_back'
--   AND player_lookup IS NULL;

-- ============================================================================
-- Aggregation Slices to Compute
-- ============================================================================
-- The aggregation job should compute these slices daily:
--
-- 1. OVERALL (no dimensions): system-wide performance
--    player_lookup=NULL, archetype=NULL, confidence_tier=NULL, situation=NULL
--
-- 2. BY PLAYER: For each player with >= 5 predictions
--    player_lookup={each}, archetype=NULL, confidence_tier=NULL, situation=NULL
--
-- 3. BY ARCHETYPE: For each archetype
--    player_lookup=NULL, archetype={each}, confidence_tier=NULL, situation=NULL
--
-- 4. BY CONFIDENCE TIER: high, medium, low
--    player_lookup=NULL, archetype=NULL, confidence_tier={each}, situation=NULL
--
-- 5. BY SITUATION: bounce_back, home, away, rest_3plus, b2b
--    player_lookup=NULL, archetype=NULL, confidence_tier=NULL, situation={each}
--
-- 6. CROSS: archetype x confidence_tier (for premium insights)
--    player_lookup=NULL, archetype={each}, confidence_tier={each}, situation=NULL
--
-- Time periods for each: rolling_7d, rolling_30d, current month, season

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (2025-12-17): Initial schema with multi-dimensional aggregation
--
-- Last Updated: December 2025
-- Status: New - Ready for implementation
-- ============================================================================
