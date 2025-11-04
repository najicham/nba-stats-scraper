-- ============================================================================
-- Table: ml_feature_store_v2
-- File: 04_ml_feature_store_v2.sql
-- Purpose: Flexible array-based feature storage (25→47→more features)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_feature_store_v2` (
  -- Identifiers (4 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  
  -- FLEXIBLE FEATURES (Array-Based Design)
  features ARRAY<FLOAT64> NOT NULL,                 -- Array of feature values (25, 47, or any length)
  feature_names ARRAY<STRING> NOT NULL,             -- Array of feature names for interpretability
  feature_count INT64 NOT NULL,                     -- Explicit count (25 initially)
  feature_version STRING NOT NULL,                  -- Version identifier: "v1_baseline_25", "v2_enhanced_47"
  
  -- Feature Metadata (2 fields)
  feature_generation_time_ms INT64,                 -- How long to generate features
  feature_quality_score NUMERIC(5,2),               -- 0-100 quality score
  
  -- Player Context (3 fields)
  opponent_team_abbr STRING,
  is_home BOOLEAN,
  days_rest INT64,
  
  -- Data Source (1 field)
  data_source STRING NOT NULL,                      -- 'phase4' or 'mock'
  
  -- Processing Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, feature_version, game_date
OPTIONS(
  description="ML feature store with flexible array-based features. Supports evolving feature sets from 25 to 47+ features.",
  partition_expiration_days=365
);

-- ============================================================================
-- Backward Compatibility View
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.ml_feature_store` AS
SELECT 
  player_lookup,
  universal_player_id,
  game_date,
  game_id,
  features,
  feature_names,
  feature_count,
  feature_version,
  opponent_team_abbr,
  is_home,
  days_rest,
  data_source,
  created_at,
  updated_at
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE feature_version = 'v1_baseline_25';  -- Default to current version

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get features for a player on specific date
-- SELECT 
--   player_lookup,
--   feature_version,
--   feature_count,
--   data_source,
--   -- Access specific features by index
--   features[OFFSET(0)] as points_avg_last_5,
--   features[OFFSET(5)] as fatigue_score,
--   features[OFFSET(13)] as opponent_def_rating
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date = '2025-01-15'
--   AND player_lookup = 'lebron-james'
--   AND feature_version = 'v1_baseline_25';

-- Get all features with names for a player
-- SELECT 
--   player_lookup,
--   game_date,
--   feature_version,
--   ARRAY_TO_STRING(feature_names, ', ') as all_features,
--   ARRAY_LENGTH(features) as total_features
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date = CURRENT_DATE()
--   AND player_lookup = 'stephen-curry';

-- Check feature quality
-- SELECT 
--   player_lookup,
--   feature_count,
--   feature_quality_score,
--   feature_generation_time_ms,
--   data_source
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date = CURRENT_DATE()
--   AND feature_quality_score < 70  -- Flag low quality
-- ORDER BY feature_quality_score;

-- Compare feature versions
-- SELECT 
--   feature_version,
--   COUNT(*) as record_count,
--   AVG(feature_count) as avg_feature_count,
--   AVG(feature_quality_score) as avg_quality,
--   COUNT(DISTINCT player_lookup) as unique_players
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY feature_version
-- ORDER BY feature_version;

-- Get today's features for all players
-- SELECT 
--   player_lookup,
--   opponent_team_abbr,
--   is_home,
--   days_rest,
--   feature_count,
--   data_source,
--   features  -- Full array for ML model input
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date = CURRENT_DATE()
--   AND feature_version = 'v1_baseline_25'
-- ORDER BY player_lookup;
