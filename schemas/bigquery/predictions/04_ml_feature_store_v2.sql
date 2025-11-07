-- ============================================================================
-- Table: ml_feature_store_v2 (UPDATED with Dependency Tracking)
-- File: schemas/bigquery/predictions/04_ml_feature_store_v2.sql
-- Purpose: Flexible array-based feature storage with Phase 4 source tracking
-- Version: 2.0 (Added v4.0 dependency tracking)
-- Updated: November 2025
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_feature_store_v2` (
  -- ========================================================================
  -- IDENTIFIERS (4 fields)
  -- ========================================================================
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  
  -- ========================================================================
  -- FLEXIBLE FEATURES (Array-Based Design)
  -- ========================================================================
  features ARRAY<FLOAT64> NOT NULL,                 -- Array of feature values (25, 47, or any length)
  feature_names ARRAY<STRING> NOT NULL,             -- Array of feature names for interpretability
  feature_count INT64 NOT NULL,                     -- Explicit count (25 initially)
  feature_version STRING NOT NULL,                  -- Version identifier: "v1_baseline_25", "v2_enhanced_47"
  
  -- ========================================================================
  -- FEATURE METADATA (2 fields)
  -- ========================================================================
  feature_generation_time_ms INT64,                 -- How long to generate features
  feature_quality_score NUMERIC(5,2),               -- 0-100 quality score
  
  -- ========================================================================
  -- PLAYER CONTEXT (3 fields)
  -- ========================================================================
  opponent_team_abbr STRING,
  is_home BOOLEAN,
  days_rest INT64,
  
  -- ========================================================================
  -- DATA SOURCE (1 field)
  -- ========================================================================
  data_source STRING NOT NULL,                      -- 'phase4', 'phase3', 'mixed', 'early_season'
  
  -- ========================================================================
  -- SOURCE TRACKING: Phase 4 Dependencies (12 fields)
  -- v4.0 Dependency Tracking - 3 fields per source
  -- ========================================================================
  
  -- Source 1: player_daily_cache (Features 0-4, 18-20, 22-23)
  source_daily_cache_last_updated TIMESTAMP,        -- When daily cache was last updated
  source_daily_cache_rows_found INT64,              -- Number of rows found in cache
  source_daily_cache_completeness_pct NUMERIC(5,2), -- Percentage of expected data found
  
  -- Source 2: player_composite_factors (Features 5-8)
  source_composite_last_updated TIMESTAMP,          -- When composite factors were last updated
  source_composite_rows_found INT64,                -- Number of rows found
  source_composite_completeness_pct NUMERIC(5,2),   -- Percentage of expected data found
  
  -- Source 3: player_shot_zone_analysis (Features 18-20)
  source_shot_zones_last_updated TIMESTAMP,         -- When shot zone analysis was last updated
  source_shot_zones_rows_found INT64,               -- Number of rows found
  source_shot_zones_completeness_pct NUMERIC(5,2),  -- Percentage of expected data found
  
  -- Source 4: team_defense_zone_analysis (Features 13-14)
  source_team_defense_last_updated TIMESTAMP,       -- When team defense was last updated
  source_team_defense_rows_found INT64,             -- Number of rows found
  source_team_defense_completeness_pct NUMERIC(5,2),-- Percentage of expected data found
  
  -- ========================================================================
  -- EARLY SEASON HANDLING (2 fields)
  -- ========================================================================
  early_season_flag BOOLEAN,                        -- TRUE if insufficient historical data
  insufficient_data_reason STRING,                  -- Why data was insufficient (if early_season_flag = TRUE)
  
  -- ========================================================================
  -- PROCESSING METADATA (2 fields)
  -- ========================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, feature_version, game_date
OPTIONS(
  description="ML feature store with flexible array-based features (v2.0). Supports evolving feature sets from 25 to 47+ features. Includes v4.0 dependency tracking for Phase 4 sources.",
  partition_expiration_days=365
);

-- ============================================================================
-- INDEXES & VIEWS
-- ============================================================================

-- View: Recent features (last 30 days)
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.ml_feature_store_v2_recent` AS
SELECT *
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View: High quality features only (quality score >= 85)
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.ml_feature_store_v2_high_quality` AS
SELECT *
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE feature_quality_score >= 85.0
  AND early_season_flag IS NOT TRUE;

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Check source freshness
-- SELECT 
--   game_date,
--   COUNT(*) as total_players,
--   AVG(feature_quality_score) as avg_quality,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(source_daily_cache_last_updated), HOUR) as cache_age_hours,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(source_composite_last_updated), HOUR) as composite_age_hours
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY game_date
-- ORDER BY game_date DESC;

-- Check data completeness by source
-- SELECT 
--   game_date,
--   AVG(source_daily_cache_completeness_pct) as cache_completeness,
--   AVG(source_composite_completeness_pct) as composite_completeness,
--   AVG(source_shot_zones_completeness_pct) as shot_zones_completeness,
--   AVG(source_team_defense_completeness_pct) as team_defense_completeness,
--   MIN(LEAST(
--     source_daily_cache_completeness_pct,
--     source_composite_completeness_pct,
--     source_shot_zones_completeness_pct,
--     source_team_defense_completeness_pct
--   )) as worst_source_completeness
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY game_date
-- HAVING MIN(LEAST(
--     source_daily_cache_completeness_pct,
--     source_composite_completeness_pct,
--     source_shot_zones_completeness_pct,
--     source_team_defense_completeness_pct
--   )) < 85
-- ORDER BY game_date DESC;

-- Check early season records
-- SELECT 
--   game_date,
--   COUNT(*) as total_players,
--   SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_players,
--   ROUND(SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as early_season_pct
-- FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY game_date
-- ORDER BY game_date DESC;

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 35
--   Identifiers: 4
--   Features (array-based): 4
--   Feature metadata: 2
--   Player context: 3
--   Data source: 1
--   Source tracking (Phase 4): 12 (3 fields × 4 sources)
--   Early season: 2
--   Processing metadata: 2
--   Reserved for future: 5 (kept for schema evolution)
-- ============================================================================