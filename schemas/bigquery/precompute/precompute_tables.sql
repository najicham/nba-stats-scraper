-- ============================================================================
-- NBA Props Platform - Phase 4 Precompute Tables
-- File: schemas/bigquery/precompute/precompute_tables.sql
-- Purpose: Pre-computed aggregations and composite factors for predictions
-- Update: Daily overnight (11 PM - 6 AM) + real-time updates when context changes
-- Retention: 90 days for most tables, longer for critical analysis tables
-- 
-- Related Documents:
-- - Document 2: Similarity Matching Engine
-- - Document 3: Composite Factor Calculations
-- - Document 4: Prediction System Framework
-- ============================================================================

-- ============================================================================
-- Table 1: player_shot_zone_analysis
-- ============================================================================
-- Player's shot distribution and efficiency by court zone
-- Updated: Nightly after games complete
-- Used by: Shot zone mismatch calculation, player reports
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_shot_zone_analysis` (
  -- Identifiers (3 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,                       -- Universal player ID from registry
  analysis_date DATE NOT NULL,                      -- Date this analysis represents (partition key)
  
  -- Shot distribution - Last 10 games (6 fields)
  paint_rate_last_10 NUMERIC(5,2),                  -- % of shots in paint
  mid_range_rate_last_10 NUMERIC(5,2),              -- % of shots mid-range
  three_pt_rate_last_10 NUMERIC(5,2),               -- % of shots from three
  total_shots_last_10 INT64,                        -- Total shots in sample
  games_in_sample_10 INT64,                         -- Number of games (max 10)
  sample_quality_10 STRING,                         -- 'excellent', 'good', 'limited'
  
  -- Efficiency by zone - Last 10 games (3 fields)
  paint_pct_last_10 NUMERIC(5,3),                   -- FG% in paint
  mid_range_pct_last_10 NUMERIC(5,3),               -- FG% mid-range
  three_pt_pct_last_10 NUMERIC(5,3),                -- 3PT%
  
  -- Volume by zone - Last 10 games (3 fields)
  paint_attempts_per_game NUMERIC(4,1),             -- Paint attempts per game
  mid_range_attempts_per_game NUMERIC(4,1),         -- Mid-range attempts per game
  three_pt_attempts_per_game NUMERIC(4,1),          -- Three-point attempts per game
  
  -- Shot distribution - Last 20 games (4 fields)
  paint_rate_last_20 NUMERIC(5,2),                  -- Broader trend
  paint_pct_last_20 NUMERIC(5,3),                   -- Broader efficiency
  games_in_sample_20 INT64,                         -- Number of games (max 20)
  sample_quality_20 STRING,                         -- 'excellent', 'good', 'limited'
  
  -- Shot creation (2 fields)
  assisted_rate_last_10 NUMERIC(5,2),               -- % of made FGs that were assisted
  unassisted_rate_last_10 NUMERIC(5,2),             -- % of made FGs unassisted (shot creation)
  
  -- Player characteristics (2 fields)
  player_position STRING,                           -- G, F, C
  primary_scoring_zone STRING,                      -- 'paint', 'mid_range', 'perimeter', 'balanced'
  
  -- Data quality (2 fields)
  data_quality_tier STRING,                         -- 'high', 'medium', 'low'
  calculation_notes STRING,                         -- Any issues or warnings
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY player_lookup, universal_player_id, analysis_date
OPTIONS(
  description="Player shot distribution and efficiency by court zone. Updated nightly. Used for shot zone mismatch calculations.",
  partition_expiration_days=90
);

-- ============================================================================
-- Table 2: team_defense_zone_analysis
-- ============================================================================
-- Team's defensive performance by shot zone
-- Updated: Nightly after games complete
-- Used by: Shot zone mismatch calculation, opponent defense analysis
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.team_defense_zone_analysis` (
  -- Identifiers (2 fields)
  team_abbr STRING NOT NULL,
  analysis_date DATE NOT NULL,                      -- Date this analysis represents (partition key)
  
  -- Paint defense - Last 15 games (5 fields)
  paint_pct_allowed_last_15 NUMERIC(5,3),           -- FG% allowed in paint
  paint_attempts_allowed_per_game NUMERIC(5,1),     -- Paint attempts allowed per game
  paint_points_allowed_per_game NUMERIC(5,1),       -- Paint points allowed per game
  paint_blocks_per_game NUMERIC(4,1),               -- Paint blocks per game
  paint_defense_vs_league_avg NUMERIC(5,2),         -- Percentage points vs league average
  
  -- Mid-range defense - Last 15 games (4 fields)
  mid_range_pct_allowed_last_15 NUMERIC(5,3),       -- FG% allowed mid-range
  mid_range_attempts_allowed_per_game NUMERIC(5,1), -- Mid-range attempts per game
  mid_range_blocks_per_game NUMERIC(4,1),           -- Mid-range blocks per game
  mid_range_defense_vs_league_avg NUMERIC(5,2),     -- Percentage points vs league average
  
  -- Three-point defense - Last 15 games (4 fields)
  three_pt_pct_allowed_last_15 NUMERIC(5,3),        -- 3PT% allowed
  three_pt_attempts_allowed_per_game NUMERIC(5,1),  -- Three-point attempts per game
  three_pt_blocks_per_game NUMERIC(4,1),            -- Three-point blocks per game
  three_pt_defense_vs_league_avg NUMERIC(5,2),      -- Percentage points vs league average
  
  -- Overall defensive metrics - Last 15 games (4 fields)
  defensive_rating_last_15 NUMERIC(6,2),            -- Points allowed per 100 possessions
  opponent_points_per_game NUMERIC(5,1),            -- Total points allowed per game
  opponent_pace NUMERIC(5,1),                       -- Pace allowed to opponents
  games_in_sample INT64,                            -- Number of games (max 15)
  
  -- Defensive strengths/weaknesses (2 fields)
  strongest_zone STRING,                            -- 'paint', 'mid_range', 'perimeter'
  weakest_zone STRING,                              -- 'paint', 'mid_range', 'perimeter'
  
  -- Data quality (2 fields)
  data_quality_tier STRING,                         -- 'high', 'medium', 'low'
  calculation_notes STRING,                         -- Any issues or warnings
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY team_abbr, analysis_date
OPTIONS(
  description="Team defensive performance by shot zone. Updated nightly. Used for identifying favorable matchups.",
  partition_expiration_days=90
);

-- ============================================================================
-- Table 3: player_composite_factors
-- ============================================================================
-- Pre-calculated composite scores for all adjustment factors
-- Updated: Nightly (6 AM) + real-time when context changes
-- Used by: All prediction systems for calculating adjustments
-- CRITICAL TABLE - This is the heart of the prediction adjustments
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_composite_factors` (
  -- Identifiers (4 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  
  -- Composite Scores (8 fields)
  -- These are the pre-calculated scores from Document 3
  fatigue_score INT64,                              -- 0-100 (100 = fresh, 0 = exhausted)
  shot_zone_mismatch_score NUMERIC(4,1),            -- -10.0 to +10.0
  referee_favorability_score NUMERIC(3,1),          -- -5.0 to +5.0
  look_ahead_pressure_score NUMERIC(3,1),           -- -5.0 to +5.0
  pace_score NUMERIC(3,1),                          -- -3.0 to +3.0
  usage_spike_score NUMERIC(3,1),                   -- -3.0 to +3.0
  matchup_history_score INT64,                      -- -2 to +2 (NULL if insufficient history)
  momentum_score INT64,                             -- -2 to +2
  
  -- Point Adjustments (9 fields)
  -- These convert scores to actual point impacts
  fatigue_adjustment NUMERIC(5,2),                  -- Expected points impact from fatigue
  shot_zone_adjustment NUMERIC(5,2),                -- Expected points impact from matchup
  referee_adjustment NUMERIC(5,2),                  -- Expected points impact from referee
  look_ahead_adjustment NUMERIC(5,2),               -- Expected points impact from schedule
  pace_adjustment NUMERIC(5,2),                     -- Expected points impact from pace
  usage_spike_adjustment NUMERIC(5,2),              -- Expected points impact from role change
  home_away_adjustment NUMERIC(5,2),                -- Expected points impact from venue
  matchup_history_adjustment NUMERIC(5,2),          -- Expected points impact from history
  momentum_adjustment NUMERIC(5,2),                 -- Expected points impact from streaks
  
  -- Supporting Detail (stored as JSON for flexibility) (5 fields)
  fatigue_factors JSON,                             -- Breakdown: {games_7d: 4, minutes_7d: 252, ...}
  shot_zone_matchup JSON,                           -- Details: {player_paint: 52%, opp_paint: 61%, ...}
  referee_details JSON,                             -- Details: {chief: "Scott Foster", avg_points: 229.4, ...}
  look_ahead_details JSON,                          -- Details: {next_rest: 0, next_opp_pct: 0.650, ...}
  usage_spike_details JSON,                         -- Details: {teammates_out: 1, usage_change: +4.7%, ...}
  
  -- Data Quality Flags (3 fields)
  data_completeness_pct NUMERIC(5,2),               -- % of expected fields populated
  has_warnings BOOLEAN,                             -- TRUE if any calculation had issues
  warning_messages JSON,                            -- Array of warning strings
  
  -- Update Tracking (3 fields)
  calculation_version STRING,                       -- Version of calculation code used
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP                              -- When last updated (for real-time changes)
)
PARTITION BY game_date
CLUSTER BY player_lookup, universal_player_id, game_date
OPTIONS(
  description="Pre-calculated composite factors and adjustments. Updated nightly and when context changes. Core table for prediction adjustments.",
  partition_expiration_days=365  -- Keep longer for analysis
);

-- ============================================================================
-- Table 4: player_daily_cache
-- ============================================================================
-- Player-level data that won't change throughout the day
-- Updated: Once per day at 6 AM
-- Used by: Fast prediction regeneration when lines change
-- PERFORMANCE OPTIMIZATION - Prevents recalculating static data
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_daily_cache` (
  -- Identifiers (3 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  cache_date DATE NOT NULL,                         -- Date this cache is valid for (partition key)
  
  -- Shot Zone Data (cached from player_shot_zone_analysis) (6 fields)
  paint_rate_last_10 NUMERIC(5,2),
  paint_pct_last_10 NUMERIC(5,3),
  mid_range_rate_last_10 NUMERIC(5,2),
  three_pt_rate_last_10 NUMERIC(5,2),
  paint_attempts_per_game NUMERIC(4,1),
  primary_scoring_zone STRING,
  
  -- Fatigue Metrics (won't change during day) (6 fields)
  games_in_last_7_days INT64,
  games_in_last_14_days INT64,
  minutes_in_last_7_days INT64,
  minutes_in_last_14_days INT64,
  back_to_backs_last_14_days INT64,
  days_since_2_plus_days_rest INT64,
  
  -- Recent Form (won't change during day) (5 fields)
  points_avg_last_5 NUMERIC(5,1),
  points_avg_last_10 NUMERIC(5,1),
  points_std_dev_last_10 NUMERIC(5,2),
  shooting_pct_last_5 NUMERIC(5,3),
  usage_rate_last_7 NUMERIC(5,2),
  
  -- Player Characteristics (static or slow-changing) (4 fields)
  player_age INT64,
  years_in_league INT64,
  player_position STRING,
  season_avg_points NUMERIC(5,1),
  
  -- Similarity Candidates (pre-filtered list) (2 fields)
  similarity_candidates JSON,                       -- Array of game_ids that could be similar (~100-200)
  similarity_candidates_count INT64,                -- Count of candidates
  
  -- Cache Metadata (3 fields)
  valid_until TIMESTAMP,                            -- When cache expires (next game completion)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY cache_date
CLUSTER BY player_lookup, universal_player_id
OPTIONS(
  description="Player data that won't change during the day. Cached for fast prediction updates when betting lines change. Updated once daily at 6 AM.",
  partition_expiration_days=30
);

-- ============================================================================
-- Table 5: similarity_match_cache (OPTIONAL)
-- ============================================================================
-- Pre-calculated similarity matches for common scenarios
-- Created: Only if similarity queries take >2 seconds
-- Updated: Nightly
-- Used by: Similarity matching engine for performance boost
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.similarity_match_cache` (
  -- Identifiers (3 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  
  -- Pre-calculated similar games (2 fields)
  similar_game_ids JSON,                            -- Array of similar game_ids with scores
  similar_games_count INT64,                        -- Number of similar games found
  
  -- Baseline prediction (pre-calculated) (5 fields)
  weighted_avg_points NUMERIC(5,1),                 -- Weighted average from similar games
  simple_avg_points NUMERIC(5,1),                   -- Simple average for comparison
  points_std_dev NUMERIC(5,2),                      -- Variance in similar games
  historical_over_rate NUMERIC(5,3),                -- Over rate in similar situations
  avg_margin_vs_line NUMERIC(5,2),                  -- Average margin vs line
  
  -- Similarity Quality Metrics (4 fields)
  avg_similarity_score NUMERIC(5,2),                -- Average similarity score of matches
  min_similarity_score NUMERIC(5,2),                -- Lowest similarity score included
  max_similarity_score NUMERIC(5,2),                -- Highest similarity score
  similarity_threshold_used INT64,                  -- Threshold used for matching
  
  -- Cache Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  expires_at TIMESTAMP                              -- When cache should be refreshed
)
PARTITION BY game_date
CLUSTER BY player_lookup, game_date
OPTIONS(
  description="OPTIONAL: Pre-calculated similarity matches. Only create if similarity queries take >2 seconds. Provides performance boost.",
  partition_expiration_days=30
);

-- ============================================================================
-- Helper Views for Precompute Tables
-- ============================================================================

-- View: Today's composite factors with quality flags
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.todays_composite_factors` AS
SELECT 
  player_lookup,
  game_id,
  fatigue_score,
  shot_zone_mismatch_score,
  referee_favorability_score,
  look_ahead_pressure_score,
  fatigue_adjustment,
  shot_zone_adjustment,
  data_completeness_pct,
  has_warnings,
  CASE 
    WHEN fatigue_score < 40 THEN 'EXTREME_FATIGUE'
    WHEN ABS(shot_zone_mismatch_score) > 7 THEN 'STRONG_MATCHUP'
    WHEN has_warnings THEN 'DATA_QUALITY_ISSUE'
    ELSE 'NORMAL'
  END as alert_flag
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
ORDER BY 
  CASE 
    WHEN fatigue_score < 40 THEN 1
    WHEN ABS(shot_zone_mismatch_score) > 7 THEN 2
    WHEN has_warnings THEN 3
    ELSE 4
  END;

-- View: Shot zone mismatches (favorable and unfavorable)
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.shot_zone_mismatches` AS
SELECT 
  p.player_lookup,
  p.game_date,
  p.primary_scoring_zone,
  t.weakest_zone as opponent_weakest_zone,
  pcf.shot_zone_mismatch_score,
  pcf.shot_zone_adjustment,
  CASE 
    WHEN pcf.shot_zone_mismatch_score >= 7 THEN 'EXTREME_FAVORABLE'
    WHEN pcf.shot_zone_mismatch_score >= 5 THEN 'VERY_FAVORABLE'
    WHEN pcf.shot_zone_mismatch_score >= 2 THEN 'FAVORABLE'
    WHEN pcf.shot_zone_mismatch_score <= -5 THEN 'VERY_UNFAVORABLE'
    WHEN pcf.shot_zone_mismatch_score <= -2 THEN 'UNFAVORABLE'
    ELSE 'NEUTRAL'
  END as matchup_rating
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis` p
JOIN `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
  ON p.player_lookup = upg.player_lookup
  AND p.analysis_date = upg.game_date
JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` t
  ON upg.opponent_team_abbr = t.team_abbr
  AND upg.game_date = t.analysis_date
JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
  ON p.player_lookup = pcf.player_lookup
  AND p.analysis_date = pcf.game_date
WHERE p.analysis_date = CURRENT_DATE()
  AND ABS(pcf.shot_zone_mismatch_score) >= 2
ORDER BY ABS(pcf.shot_zone_mismatch_score) DESC;

-- View: Extreme fatigue alerts
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.fatigue_alerts` AS
SELECT 
  pcf.player_lookup,
  pcf.game_date,
  pcf.fatigue_score,
  pcf.fatigue_adjustment,
  pdc.games_in_last_7_days,
  pdc.minutes_in_last_7_days,
  pdc.back_to_backs_last_14_days,
  CASE 
    WHEN pcf.fatigue_score < 35 THEN 'CRITICAL'
    WHEN pcf.fatigue_score < 50 THEN 'HIGH'
    WHEN pcf.fatigue_score < 65 THEN 'MODERATE'
    ELSE 'NORMAL'
  END as fatigue_level
FROM `nba-props-platform.nba_precompute.player_composite_factors` pcf
JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
  ON pcf.player_lookup = pdc.player_lookup
  AND pcf.game_date = pdc.cache_date
WHERE pcf.game_date = CURRENT_DATE()
  AND pcf.fatigue_score < 65
ORDER BY pcf.fatigue_score ASC;

-- ============================================================================
-- Usage Notes
-- ============================================================================
-- 
-- UPDATE SCHEDULE:
-- 1. Nightly (11 PM - 6 AM): Update all tables after Phase 3 analytics complete
-- 2. Morning (6 AM): Finalize player_daily_cache for today's games
-- 3. Real-time (9 AM - Game Time): Update player_composite_factors when context changes
--
-- REGENERATION:
-- All tables can be regenerated from Phase 3 analytics if needed:
-- - player_shot_zone_analysis: Query player_game_summary shot zone fields
-- - team_defense_zone_analysis: Query team_defense_game_summary
-- - player_composite_factors: Run composite factor calculations
-- - player_daily_cache: Aggregate from various Phase 3 tables
-- - similarity_match_cache: Run similarity queries
--
-- PERFORMANCE:
-- - player_daily_cache speeds up line change updates (5x faster)
-- - similarity_match_cache speeds up similarity queries (only if needed)
-- - player_composite_factors centralizes all adjustments (critical for consistency)
--
-- RELATED DOCUMENTS:
-- - Document 2: Similarity Matching Engine
-- - Document 3: Composite Factor Calculations  
-- - Document 4: Prediction System Framework
-- ============================================================================
