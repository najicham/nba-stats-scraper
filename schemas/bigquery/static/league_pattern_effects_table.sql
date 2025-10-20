-- ============================================================================
-- NBA Props Platform - League Pattern Effects Table
-- File: schemas/bigquery/static/league_pattern_effects_table.sql
-- Purpose: Historical league-wide pattern analysis (rest, travel, look-ahead)
-- Update Frequency: Seasonal (every 3-6 months after re-analyzing data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_static.league_pattern_effects` (
  -- Pattern identification
  pattern_name STRING NOT NULL,                     -- e.g., 'back_to_back_penalty'
  pattern_category STRING NOT NULL,                 -- 'rest', 'travel', 'look_ahead', 'opponent'
  effect_type STRING NOT NULL,                      -- 'team_points', 'player_points', 'usage_rate'
  
  -- Effect magnitude
  effect_size NUMERIC(5,2),                         -- Points adjustment (positive or negative)
  effect_pct NUMERIC(5,3),                          -- Percentage adjustment if applicable
  
  -- Statistical confidence
  sample_size INT64,                                -- Number of games in analysis
  std_dev NUMERIC(5,2),                             -- Standard deviation
  confidence_level NUMERIC(5,3),                    -- Statistical confidence (0.0-1.0)
  
  -- Context filters
  min_season_year INT64,                            -- Data from which seasons (e.g., 2020)
  max_season_year INT64,                            -- Data through which season (e.g., 2024)
  applicable_conditions JSON,                       -- When this effect applies (JSON)
  
  -- Metadata
  description STRING,                               -- Human-readable description
  calculation_method STRING,                        -- How effect was calculated
  last_updated TIMESTAMP,                           -- When analysis was run
  version STRING                                    -- Version of analysis (e.g., "v1.0")
)
CLUSTER BY pattern_category, pattern_name
OPTIONS(
  description="League-wide pattern effects calculated from historical data. Updated seasonally (every 3-6 months) when re-analyzing historical patterns. Used by Phase 4 and Phase 5 for prediction adjustments."
);

-- ============================================================================
-- Example Pattern Data
-- ============================================================================
-- Sample patterns to insert after historical analysis:
--
-- Back-to-back penalty (teams score less on B2B)
-- INSERT INTO `nba-props-platform.nba_static.league_pattern_effects` VALUES
-- ('back_to_back_penalty', 'rest', 'team_points', -2.3, NULL, 847, 1.2, 0.95, 
--  2020, 2024, JSON '{"back_to_back": true}', 
--  'Teams score 2.3 fewer points on back-to-back games',
--  'Averaged across all back-to-back games 2020-2024', 
--  CURRENT_TIMESTAMP(), 'v1.0');
--
-- Rest advantage (teams score more with 2+ days rest)
-- INSERT INTO `nba-props-platform.nba_static.league_pattern_effects` VALUES
-- ('rest_2plus_days_boost', 'rest', 'team_points', 1.8, NULL, 1203, 1.1, 0.97,
--  2020, 2024, JSON '{"days_rest": {"$gte": 2}}',
--  'Teams score 1.8 more points with 2+ days rest',
--  'Averaged across all games with 2+ rest days 2020-2024', 
--  CURRENT_TIMESTAMP(), 'v1.0');
--
-- Opponent back-to-back advantage
-- INSERT INTO `nba-props-platform.nba_static.league_pattern_effects` VALUES
-- ('vs_opponent_b2b_boost', 'opponent', 'team_points', 3.2, NULL, 731, 1.4, 0.94,
--  2020, 2024, JSON '{"opponent_back_to_back": true}',
--  'Teams score 3.2 more points when opponent is on back-to-back',
--  'Averaged across all games vs tired opponents 2020-2024', 
--  CURRENT_TIMESTAMP(), 'v1.0');
--
-- Look-ahead conservation (team has B2B tomorrow)
-- INSERT INTO `nba-props-platform.nba_static.league_pattern_effects` VALUES
-- ('back_to_back_tomorrow_penalty', 'look_ahead', 'team_points', -1.7, NULL, 423, 1.3, 0.89,
--  2020, 2024, JSON '{"next_game_back_to_back": true}',
--  'Teams score 1.7 fewer points when they have back-to-back tomorrow',
--  'Averaged across games before B2B 2020-2024', 
--  CURRENT_TIMESTAMP(), 'v1.0');
--
-- ============================================================================
-- Data Population Script
-- ============================================================================
-- See: bin/static/analyze_league_patterns.py
--
-- This script:
-- 1. Queries historical player_game_summary and team_game_summary tables
-- 2. Filters games by conditions (B2B, rest days, travel, etc.)
-- 3. Calculates effect sizes with statistical confidence
-- 4. Inserts/updates pattern effects table
-- 5. Run seasonally (every 3-6 months) to refresh patterns
-- ============================================================================
