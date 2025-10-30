-- ============================================================================
-- NBA Props Platform - Phase 4 Precompute: Player Shot Zone Analysis
-- ============================================================================
-- File: player_shot_zone_analysis.sql
-- Purpose: Player shot distribution and efficiency by court zone (last 10 games)
-- Update: Nightly at 11:15 PM (after team defense completes)
-- Entities: ~450 active NBA players
-- Duration: ~5-8 minutes
-- 
-- Version: 2.0 (Added v4.0 dependency tracking)
-- Changes from V1:
--   - Added source tracking fields for player_game_summary (3 fields)
--   - Added early season handling fields (2 fields)
--   - Added universal_player_id for stable identification
--   - Total tracking fields: 7 (3 source + 2 optional + 2 metadata)
--
-- Dependencies:
--   - nba_analytics.player_game_summary (Phase 3)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_shot_zone_analysis` (
  -- ============================================================================
  -- IDENTIFIERS (3 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  universal_player_id STRING,                       -- Universal player ID from registry
  analysis_date DATE NOT NULL,                      -- Date this analysis represents (partition key)
  
  -- ============================================================================
  -- SHOT DISTRIBUTION - Last 10 Games (6 fields)
  -- ============================================================================
  paint_rate_last_10 NUMERIC(5,2),                  -- % of shots in paint (≤8 feet)
  mid_range_rate_last_10 NUMERIC(5,2),              -- % of shots mid-range (9+ feet, 2PT)
  three_pt_rate_last_10 NUMERIC(5,2),               -- % of shots from three
  total_shots_last_10 INT64,                        -- Total shots in sample
  games_in_sample_10 INT64,                         -- Number of games (max 10)
  sample_quality_10 STRING,                         -- 'excellent' (10 games), 'good' (7-9), 'limited' (<7)
  
  -- ============================================================================
  -- EFFICIENCY BY ZONE - Last 10 Games (3 fields)
  -- ============================================================================
  paint_pct_last_10 NUMERIC(5,3),                   -- FG% in paint
  mid_range_pct_last_10 NUMERIC(5,3),               -- FG% mid-range
  three_pt_pct_last_10 NUMERIC(5,3),                -- 3PT%
  
  -- ============================================================================
  -- VOLUME BY ZONE - Last 10 Games (3 fields)
  -- ============================================================================
  paint_attempts_per_game NUMERIC(4,1),             -- Paint attempts per game
  mid_range_attempts_per_game NUMERIC(4,1),         -- Mid-range attempts per game
  three_pt_attempts_per_game NUMERIC(4,1),          -- Three-point attempts per game
  
  -- ============================================================================
  -- SHOT DISTRIBUTION - Last 20 Games (4 fields)
  -- Broader trend for stability comparison
  -- ============================================================================
  paint_rate_last_20 NUMERIC(5,2),                  -- % of shots in paint (20-game window)
  paint_pct_last_20 NUMERIC(5,3),                   -- FG% in paint (20-game window)
  games_in_sample_20 INT64,                         -- Number of games in 20-game sample
  sample_quality_20 STRING,                         -- 'excellent' (20), 'good' (15-19), 'limited' (<15)
  
  -- ============================================================================
  -- SHOT CREATION (2 fields)
  -- ============================================================================
  assisted_rate_last_10 NUMERIC(5,2),               -- % of made FGs that were assisted
  unassisted_rate_last_10 NUMERIC(5,2),             -- % of made FGs unassisted (shot creation)
  
  -- ============================================================================
  -- PLAYER CHARACTERISTICS (2 fields)
  -- ============================================================================
  player_position STRING,                           -- G, F, C (from registry or inferred)
  primary_scoring_zone STRING,                      -- 'paint', 'mid_range', 'perimeter', 'balanced'
  
  -- ============================================================================
  -- DATA QUALITY (2 fields)
  -- ============================================================================
  data_quality_tier STRING,                         -- 'high' (10+ games), 'medium' (5-9), 'low' (<5)
  calculation_notes STRING,                         -- Any issues or warnings
  
  -- ============================================================================
  -- v4.0 SOURCE TRACKING - player_game_summary (3 fields)
  -- ============================================================================
  source_player_game_last_updated TIMESTAMP,        -- When source was last processed
  source_player_game_rows_found INT64,              -- How many game records found
  source_player_game_completeness_pct NUMERIC(5,2), -- % of expected games found
  
  -- ============================================================================
  -- v4.0 EARLY SEASON HANDLING (2 fields)
  -- ============================================================================
  early_season_flag BOOLEAN,                        -- TRUE when <10 games available
  insufficient_data_reason STRING,                  -- Why data was insufficient
  
  -- ============================================================================
  -- PROCESSING METADATA (2 fields)
  -- ============================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY player_lookup, universal_player_id, analysis_date
OPTIONS(
  description="Player shot distribution and efficiency by court zone. Source: nba_analytics.player_game_summary (last 10 games). Updated nightly at 11:15 PM. v4.0 dependency tracking enabled.",
  partition_expiration_days=90
);

-- ============================================================================
-- SAMPLE DATA STRUCTURE
-- ============================================================================
-- Example row for LeBron James on 2025-10-30:
--
-- player_lookup: "lebronjames"
-- universal_player_id: "lebronjames_001"
-- analysis_date: "2025-10-30"
--
-- Shot Distribution (Last 10):
-- paint_rate_last_10: 45.2
-- mid_range_rate_last_10: 19.8
-- three_pt_rate_last_10: 35.0
-- total_shots_last_10: 181
-- games_in_sample_10: 10
-- sample_quality_10: "excellent"
--
-- Efficiency:
-- paint_pct_last_10: 0.623
-- mid_range_pct_last_10: 0.412
-- three_pt_pct_last_10: 0.367
--
-- Volume:
-- paint_attempts_per_game: 8.2
-- mid_range_attempts_per_game: 3.7
-- three_pt_attempts_per_game: 6.1
--
-- Shot Creation:
-- assisted_rate_last_10: 62.3
-- unassisted_rate_last_10: 37.7
--
-- Player Info:
-- player_position: "F"
-- primary_scoring_zone: "paint"
--
-- Data Quality:
-- data_quality_tier: "high"
-- calculation_notes: NULL
--
-- Source Tracking:
-- source_player_game_last_updated: "2025-10-30T10:00:00Z"
-- source_player_game_rows_found: 10
-- source_player_game_completeness_pct: 100.00
--
-- Early Season:
-- early_season_flag: FALSE
-- insufficient_data_reason: NULL
--
-- Processing:
-- processed_at: "2025-10-30T23:15:00Z"
-- created_at: "2025-10-30T23:15:00Z"
-- ============================================================================

-- ============================================================================
-- FIELD VALIDATION RANGES
-- ============================================================================
-- Shot rates: Should sum to ~100% (±2% for rounding)
--   paint_rate + mid_range_rate + three_pt_rate ≈ 100
--
-- Shooting percentages: Reasonable NBA ranges
--   paint_pct: 0.400 - 0.800 (40% - 80%)
--   mid_range_pct: 0.300 - 0.600 (30% - 60%)
--   three_pt_pct: 0.200 - 0.500 (20% - 50%)
--
-- Volume per game: NBA player ranges
--   paint_attempts_per_game: 0.0 - 15.0
--   mid_range_attempts_per_game: 0.0 - 10.0
--   three_pt_attempts_per_game: 0.0 - 15.0
--
-- Assisted rates: Should sum to ~100%
--   assisted_rate + unassisted_rate ≈ 100
--
-- Completeness: Should be high for active players
--   source_player_game_completeness_pct: ≥ 85% (good quality)
-- ============================================================================

-- ============================================================================
-- USAGE IN PHASE 5 PREDICTIONS
-- ============================================================================
-- Zone Matchup Analysis:
--   SELECT p.primary_scoring_zone, t.weakest_zone
--   FROM player_shot_zone_analysis p
--   JOIN team_defense_zone_analysis t
--   WHERE p.primary_scoring_zone = t.weakest_zone
--   -- Favorable matchup!
--
-- Volume Projection:
--   SELECT paint_attempts_per_game * expected_pace_factor
--   FROM player_shot_zone_analysis
--   -- Scale volume by game pace
--
-- Efficiency Baseline:
--   SELECT 
--     paint_pct_last_10,
--     opponent_paint_defense_rating
--   FROM player_shot_zone_analysis p
--   JOIN team_defense_zone_analysis t
--   -- Compare player efficiency vs opponent defense
-- ============================================================================

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Check data freshness for today's predictions
SELECT 
  COUNT(*) as players_processed,
  AVG(source_player_game_completeness_pct) as avg_completeness,
  MIN(source_player_game_completeness_pct) as min_completeness,
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    source_player_game_last_updated, 
    HOUR
  )) as max_source_age_hours
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();

-- Find players with low completeness (data quality issues)
SELECT 
  player_lookup,
  games_in_sample_10,
  source_player_game_rows_found,
  source_player_game_completeness_pct,
  data_quality_tier,
  TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    source_player_game_last_updated, 
    HOUR
  ) as source_age_hours
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND source_player_game_completeness_pct < 85
ORDER BY source_player_game_completeness_pct ASC;

-- Check for early season players (insufficient data)
SELECT 
  player_lookup,
  games_in_sample_10,
  early_season_flag,
  insufficient_data_reason,
  sample_quality_10
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag = TRUE;

-- Validate shot distribution sums (should be ~100%)
SELECT 
  player_lookup,
  paint_rate_last_10,
  mid_range_rate_last_10,
  three_pt_rate_last_10,
  (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10) as total_rate,
  ABS(100 - (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10)) as rate_error
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND ABS(100 - (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10)) > 2
ORDER BY rate_error DESC;

-- ============================================================================
-- ALERT CONDITIONS
-- ============================================================================
-- Alert if:
-- 1. <400 players processed (should be ~450)
-- 2. Average completeness <85%
-- 3. Max source age >72 hours
-- 4. >10% of players with early_season_flag = TRUE (outside first 2 weeks)
-- ============================================================================

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_precompute dataset
-- [ ] Verify schema matches processor expectations
-- [ ] Set partition expiration (90 days)
-- [ ] Configure clustering for query performance
-- [ ] Test with sample data
-- [ ] Backfill last 30 days (after processor ready)
-- [ ] Enable monitoring queries
-- [ ] Document alert thresholds
-- ============================================================================