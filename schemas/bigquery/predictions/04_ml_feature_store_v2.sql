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
  features ARRAY<FLOAT64>,                          -- Array of feature values (25, 47, or any length)
  feature_names ARRAY<STRING>,                      -- Array of feature names for interpretability
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
  -- SOURCE TRACKING: Phase 4 Dependencies (16 fields)
  -- v4.0 Dependency Tracking - 4 fields per source (last_updated, rows_found, completeness_pct, hash)
  -- ========================================================================
  
  -- Source 1: player_daily_cache (Features 0-4, 18-20, 22-23)
  source_daily_cache_last_updated TIMESTAMP,        -- When daily cache was last updated
  source_daily_cache_rows_found INT64,              -- Number of rows found in cache
  source_daily_cache_completeness_pct NUMERIC(5,2), -- Percentage of expected data found
  source_daily_cache_hash STRING,                   -- Hash from player_daily_cache.data_hash for smart reprocessing
  
  -- Source 2: player_composite_factors (Features 5-8)
  source_composite_last_updated TIMESTAMP,          -- When composite factors were last updated
  source_composite_rows_found INT64,                -- Number of rows found
  source_composite_completeness_pct NUMERIC(5,2),   -- Percentage of expected data found
  source_composite_hash STRING,                     -- Hash from player_composite_factors.data_hash for smart reprocessing
  
  -- Source 3: player_shot_zone_analysis (Features 18-20)
  source_shot_zones_last_updated TIMESTAMP,         -- When shot zone analysis was last updated
  source_shot_zones_rows_found INT64,               -- Number of rows found
  source_shot_zones_completeness_pct NUMERIC(5,2),  -- Percentage of expected data found
  source_shot_zones_hash STRING,                    -- Hash from player_shot_zone_analysis.data_hash for smart reprocessing
  
  -- Source 4: team_defense_zone_analysis (Features 13-14)
  source_team_defense_last_updated TIMESTAMP,       -- When team defense was last updated
  source_team_defense_rows_found INT64,             -- Number of rows found
  source_team_defense_completeness_pct NUMERIC(5,2),-- Percentage of expected data found
  source_team_defense_hash STRING,                  -- Hash from team_defense_zone_analysis.data_hash for smart reprocessing
  
  -- ========================================================================
  -- EARLY SEASON HANDLING (2 fields)
  -- ========================================================================
  early_season_flag BOOLEAN,                        -- TRUE if insufficient historical data
  insufficient_data_reason STRING,                  -- Why data was insufficient (if early_season_flag = TRUE)

  -- ========================================================================
  -- COMPLETENESS CHECKING METADATA (14 fields) - Added Week 4
  -- ========================================================================

  -- Completeness Metrics (4 fields)
  expected_games_count INT64,                       -- Games expected from schedule
  actual_games_count INT64,                         -- Games actually found in upstream table
  completeness_percentage FLOAT64,                  -- Completeness percentage 0-100%
  missing_games_count INT64,                        -- Number of games missing from upstream

  -- Production Readiness (2 fields)
  is_production_ready BOOLEAN,                      -- TRUE if completeness >= 90% AND upstream complete
  data_quality_issues ARRAY<STRING>,                -- Specific quality issues found

  -- Circuit Breaker (4 fields)
  last_reprocess_attempt_at TIMESTAMP,              -- When reprocessing was last attempted
  reprocess_attempt_count INT64,                    -- Number of reprocess attempts
  circuit_breaker_active BOOLEAN,                   -- TRUE if max reprocess attempts reached
  circuit_breaker_until TIMESTAMP,                  -- When circuit breaker expires (7 days from last attempt)

  -- Bootstrap/Override (4 fields)
  manual_override_required BOOLEAN,                 -- TRUE if manual intervention needed
  season_boundary_detected BOOLEAN,                 -- TRUE if date near season start/end
  backfill_bootstrap_mode BOOLEAN,                  -- TRUE if first 30 days of season/backfill
  processing_decision_reason STRING,                -- Why record was processed or skipped

  -- ========================================================================
  -- SMART IDEMPOTENCY (Pattern #1)
  -- ========================================================================
  data_hash STRING,                                 -- SHA256 hash of feature array values for smart idempotency

  -- ========================================================================
  -- PROCESSING METADATA (2 fields)
  -- ========================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, feature_version, game_date
OPTIONS(
  description="ML feature store with flexible array-based features (v2.0). Supports evolving feature sets from 25 to 47+ features. Includes v4.0 dependency tracking for Phase 4 sources with smart patterns (Smart Idempotency + Smart Reprocessing).",
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
-- Total fields: 55 (updated Week 4)
--   Identifiers: 4
--   Features (array-based): 4
--   Feature metadata: 2
--   Player context: 3
--   Data source: 1
--   Source tracking (Phase 4): 16 (4 fields × 4 sources)
--   Early season: 2
--   Completeness checking: 14 (4 metrics + 2 readiness + 4 circuit breaker + 4 bootstrap)
--   Smart idempotency: 1 (data_hash)
--   Processing metadata: 2
--   Smart patterns enabled: Pattern #1 (Smart Idempotency), Pattern #3 (Smart Reprocessing), Completeness Checking
-- ============================================================================

-- ============================================================================
-- DEPLOYMENT: Add columns to existing table
-- ============================================================================

-- Step 1: Add hash columns (if not already added)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS source_daily_cache_hash STRING
  OPTIONS (description='Hash from player_daily_cache.data_hash for smart reprocessing'),
ADD COLUMN IF NOT EXISTS source_composite_hash STRING
  OPTIONS (description='Hash from player_composite_factors.data_hash for smart reprocessing'),
ADD COLUMN IF NOT EXISTS source_shot_zones_hash STRING
  OPTIONS (description='Hash from player_shot_zone_analysis.data_hash for smart reprocessing'),
ADD COLUMN IF NOT EXISTS source_team_defense_hash STRING
  OPTIONS (description='Hash from team_defense_zone_analysis.data_hash for smart reprocessing'),
ADD COLUMN IF NOT EXISTS data_hash STRING
  OPTIONS (description='SHA256 hash of feature array values for smart idempotency');

-- Step 2: Add completeness checking columns (Week 4)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS expected_games_count INT64
  OPTIONS (description='Games expected from schedule'),
ADD COLUMN IF NOT EXISTS actual_games_count INT64
  OPTIONS (description='Games actually found in upstream table'),
ADD COLUMN IF NOT EXISTS completeness_percentage FLOAT64
  OPTIONS (description='Completeness percentage 0-100%'),
ADD COLUMN IF NOT EXISTS missing_games_count INT64
  OPTIONS (description='Number of games missing from upstream'),

ADD COLUMN IF NOT EXISTS is_production_ready BOOLEAN
  OPTIONS (description='TRUE if completeness >= 90% AND upstream complete'),
ADD COLUMN IF NOT EXISTS data_quality_issues ARRAY<STRING>
  OPTIONS (description='Specific quality issues found'),

ADD COLUMN IF NOT EXISTS last_reprocess_attempt_at TIMESTAMP
  OPTIONS (description='When reprocessing was last attempted'),
ADD COLUMN IF NOT EXISTS reprocess_attempt_count INT64
  OPTIONS (description='Number of reprocess attempts'),
ADD COLUMN IF NOT EXISTS circuit_breaker_active BOOLEAN
  OPTIONS (description='TRUE if max reprocess attempts reached'),
ADD COLUMN IF NOT EXISTS circuit_breaker_until TIMESTAMP
  OPTIONS (description='When circuit breaker expires (7 days from last attempt)'),

ADD COLUMN IF NOT EXISTS manual_override_required BOOLEAN
  OPTIONS (description='TRUE if manual intervention needed'),
ADD COLUMN IF NOT EXISTS season_boundary_detected BOOLEAN
  OPTIONS (description='TRUE if date near season start/end'),
ADD COLUMN IF NOT EXISTS backfill_bootstrap_mode BOOLEAN
  OPTIONS (description='TRUE if first 30 days of season/backfill'),
ADD COLUMN IF NOT EXISTS processing_decision_reason STRING
  OPTIONS (description='Why record was processed or skipped');

-- ============================================================================