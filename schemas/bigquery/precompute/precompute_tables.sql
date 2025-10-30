-- ============================================================================
-- NBA Props Platform - Phase 4 Precompute Tables (Version 2)
-- ============================================================================
-- File: phase4_precompute_schema_v2.sql
-- Purpose: Pre-computed aggregations and composite factors for predictions
-- Update: Daily overnight (11 PM - 6 AM) + real-time updates when context changes
-- Retention: 90 days for most tables, longer for critical analysis tables
-- 
-- UPDATED: January 2025
-- Changes from V1:
--   - Added factor_implementation_status tracking
--   - Documented deferred composite factors (set to 0 in initial implementation)
--   - Commented out similarity_match_cache (calculate on-demand initially)
--   - Added calculation_version field
--
-- Related Documents:
-- - phase5_infrastructure_architecture.md
-- - phase5_implementation_timeline.md
-- - architecture_decisions.md
-- ============================================================================

-- ============================================================================
-- CREATE DATASET
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_precompute`
OPTIONS (
  description = "Phase 4: Pre-computed aggregations, shot zone analysis, and composite factors for prediction systems. Updated nightly and on-demand.",
  location = "US"
);

-- ============================================================================
-- Table 1: player_shot_zone_analysis
-- ============================================================================
-- Player's shot distribution and efficiency by court zone
-- Updated: Nightly after games complete
-- Used by: zone_matchup_v1 system, shot zone mismatch calculations
-- Priority: HIGH - Required for Week 1 predictions
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_shot_zone_analysis` (
  -- Identifiers (3 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,                       -- Universal player ID from registry
  analysis_date DATE NOT NULL,                      -- Date this analysis represents (partition key)
  
  -- Shot distribution - Last 10 games (6 fields)
  paint_rate_last_10 NUMERIC(5,2),                  -- % of shots in paint (≤8 feet)
  mid_range_rate_last_10 NUMERIC(5,2),              -- % of shots mid-range (9+ feet, 2PT)
  three_pt_rate_last_10 NUMERIC(5,2),               -- % of shots from three
  total_shots_last_10 INT64,                        -- Total shots in sample
  games_in_sample_10 INT64,                         -- Number of games (max 10)
  sample_quality_10 STRING,                         -- 'excellent' (10 games), 'good' (7-9), 'limited' (<7)
  
  -- Efficiency by zone - Last 10 games (3 fields)
  paint_pct_last_10 NUMERIC(5,3),                   -- FG% in paint
  mid_range_pct_last_10 NUMERIC(5,3),               -- FG% mid-range
  three_pt_pct_last_10 NUMERIC(5,3),                -- 3PT%
  
  -- Volume by zone - Last 10 games (3 fields)
  paint_attempts_per_game NUMERIC(4,1),             -- Paint attempts per game
  mid_range_attempts_per_game NUMERIC(4,1),         -- Mid-range attempts per game
  three_pt_attempts_per_game NUMERIC(4,1),          -- Three-point attempts per game
  
  -- Shot distribution - Last 20 games (4 fields)
  -- Broader trend for stability
  paint_rate_last_20 NUMERIC(5,2),                  
  paint_pct_last_20 NUMERIC(5,3),                   
  games_in_sample_20 INT64,                         
  sample_quality_20 STRING,                         
  
  -- Shot creation (2 fields)
  assisted_rate_last_10 NUMERIC(5,2),               -- % of made FGs that were assisted
  unassisted_rate_last_10 NUMERIC(5,2),             -- % of made FGs unassisted (shot creation)
  
  -- Player characteristics (2 fields)
  player_position STRING,                           -- G, F, C (from registry or inferred)
  primary_scoring_zone STRING,                      -- 'paint', 'mid_range', 'perimeter', 'balanced'
  
  -- Data quality (2 fields)
  data_quality_tier STRING,                         -- 'high' (10+ games), 'medium' (5-9), 'low' (<5)
  calculation_notes STRING,                         -- Any issues or warnings
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY player_lookup, universal_player_id, analysis_date
OPTIONS(
  description="Player shot distribution and efficiency by court zone. Source data from nba_analytics.player_game_summary. Updated nightly. Required for zone_matchup_v1 prediction system.",
  partition_expiration_days=90
);

-- ============================================================================
-- Table 2: team_defense_zone_analysis
-- ============================================================================
-- Team's defensive performance by shot zone
-- Updated: Nightly after games complete
-- Used by: zone_matchup_v1 system, shot zone mismatch calculations
-- Priority: HIGH - Required for Week 1 predictions
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
  paint_defense_vs_league_avg NUMERIC(5,2),         -- Percentage points vs league average (negative = better)
  
  -- Mid-range defense - Last 15 games (4 fields)
  mid_range_pct_allowed_last_15 NUMERIC(5,3),       -- FG% allowed mid-range
  mid_range_attempts_allowed_per_game NUMERIC(5,1), -- Mid-range attempts per game
  mid_range_blocks_per_game NUMERIC(4,1),           -- Mid-range blocks per game
  mid_range_defense_vs_league_avg NUMERIC(5,2),     -- Percentage points vs league average
  
  -- Three-point defense - Last 15 games (4 fields)
  three_pt_pct_allowed_last_15 NUMERIC(5,3),        -- 3PT% allowed
  three_pt_attempts_allowed_per_game NUMERIC(5,1),  -- Three-point attempts per game
  three_pt_blocks_per_game NUMERIC(4,1),            -- Three-point blocks per game (rare but tracked)
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
  data_quality_tier STRING,                         -- 'high' (15 games), 'medium' (10-14), 'low' (<10)
  calculation_notes STRING,                         -- Any issues or warnings
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY team_abbr, analysis_date
OPTIONS(
  description="Team defensive performance by shot zone. Source data from nba_analytics.team_defense_game_summary. Updated nightly. Used for identifying favorable matchups.",
  partition_expiration_days=90
);

-- ============================================================================
-- Table 3: player_composite_factors
-- ============================================================================
-- Pre-calculated composite scores for all adjustment factors
-- Updated: Nightly (11 PM) + real-time when context changes (6 AM, line changes)
-- Used by: ALL prediction systems for calculating adjustments
-- Priority: CRITICAL - This is the heart of the prediction adjustments
--
-- IMPLEMENTATION STRATEGY (Week 1-4):
--   ACTIVE (4 factors):   fatigue, shot_zone_mismatch, pace, usage_spike
--   DEFERRED (4 factors): referee_favorability, look_ahead_pressure, 
--                         matchup_history, momentum (all set to 0)
--
-- After 3 months: Analyze XGBoost feature importance
--   - If deferred factor shows >5% importance → Implement properly
--   - If <5% importance → Keep as neutral or remove
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_composite_factors` (
  -- Identifiers (4 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  
  -- ============================================================================
  -- ACTIVE COMPOSITE SCORES (Week 1-4 Implementation)
  -- ============================================================================
  
  -- ✅ ACTIVE: Fatigue Score
  fatigue_score INT64,                              -- 0-100 (100 = fresh, 0 = exhausted)
                                                     -- Based on: games_last_7, minutes_last_7, 
                                                     --          back_to_backs, days_rest
  
  -- ✅ ACTIVE: Shot Zone Mismatch Score  
  shot_zone_mismatch_score NUMERIC(4,1),            -- -10.0 to +10.0
                                                     -- Positive = favorable matchup
                                                     -- Player's primary zone vs opponent's weak zone
  
  -- ✅ ACTIVE: Pace Score
  pace_score NUMERIC(3,1),                          -- -3.0 to +3.0
                                                     -- Expected game pace vs league average
                                                     -- High pace = more possessions = more points
  
  -- ✅ ACTIVE: Usage Spike Score
  usage_spike_score NUMERIC(3,1),                   -- -3.0 to +3.0
                                                     -- Recent usage change vs season average
                                                     -- Spike = more shots = more points
  
  -- ============================================================================
  -- DEFERRED COMPOSITE SCORES (Set to 0 in Week 1-4)
  -- ============================================================================
  -- These fields exist in schema for future implementation
  -- Initial processors will set these to 0 (neutral)
  -- XGBoost will determine if they matter via feature importance
  
  -- ❌ DEFERRED: Referee Favorability (returns 0)
  referee_favorability_score NUMERIC(3,1),          -- -5.0 to +5.0 (PLACEHOLDER: returns 0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: foul calling tendencies, FT opportunities
  
  -- ❌ DEFERRED: Look-Ahead Pressure (returns 0)
  look_ahead_pressure_score NUMERIC(3,1),           -- -5.0 to +5.0 (PLACEHOLDER: returns 0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: upcoming schedule difficulty, rest days ahead
  
  -- ❌ DEFERRED: Matchup History (returns 0)
  matchup_history_score INT64,                      -- -2 to +2 (PLACEHOLDER: returns 0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: player vs specific opponent historical performance
  
  -- ❌ DEFERRED: Momentum Score (returns 0)
  momentum_score INT64,                             -- -2 to +2 (PLACEHOLDER: returns 0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: recent performance trends, confidence
  
  -- ============================================================================
  -- POINT ADJUSTMENTS (Convert scores to point impacts)
  -- ============================================================================
  
  -- Active Adjustments (Weeks 1-4)
  fatigue_adjustment NUMERIC(5,2),                  -- Expected points impact from fatigue
                                                     -- Formula: (100 - fatigue_score) * -0.05
                                                     -- Range: 0 (fresh) to -5.0 (exhausted)
  
  shot_zone_adjustment NUMERIC(5,2),                -- Expected points impact from matchup
                                                     -- Direct conversion from score
                                                     -- Range: -10.0 to +10.0
  
  pace_adjustment NUMERIC(5,2),                     -- Expected points impact from pace
                                                     -- Direct conversion from score
                                                     -- Range: -3.0 to +3.0
  
  usage_spike_adjustment NUMERIC(5,2),              -- Expected points impact from usage change
                                                     -- Direct conversion from score
                                                     -- Range: -3.0 to +3.0
  
  -- Deferred Adjustments (all 0 initially)
  referee_adjustment NUMERIC(5,2),                  -- PLACEHOLDER: returns 0
  look_ahead_adjustment NUMERIC(5,2),               -- PLACEHOLDER: returns 0
  matchup_history_adjustment NUMERIC(5,2),          -- PLACEHOLDER: returns 0
  momentum_adjustment NUMERIC(5,2),                 -- PLACEHOLDER: returns 0
  
  -- Total composite adjustment
  total_composite_adjustment NUMERIC(5,2),          -- Sum of all active adjustments (Week 1-4: only 4 factors)
  
  -- ============================================================================
  -- IMPLEMENTATION TRACKING
  -- ============================================================================
  
  calculation_version STRING,                       -- "v1_4factors", "v2_8factors", etc.
  factors_active STRING,                            -- Comma-separated: "fatigue,shot_zone,pace,usage_spike"
  factors_deferred STRING,                          -- Comma-separated: "referee,look_ahead,matchup_history,momentum"
  
  -- ============================================================================
  -- SUPPORTING DATA & QUALITY
  -- ============================================================================
  
  -- Context that went into calculations (for debugging/transparency)
  fatigue_context JSON,                             -- {games_last_7, minutes_last_7, back_to_backs, days_rest}
  shot_zone_context JSON,                           -- {player_primary_zone, opponent_weak_zone, mismatch_type}
  pace_context JSON,                                -- {team_pace, opponent_pace, game_pace_estimate}
  usage_context JSON,                               -- {recent_usage, season_usage, usage_diff}
  
  -- Data quality & completeness
  data_completeness_pct NUMERIC(5,2),               -- % of required data available (100 = all data present)
  missing_data_fields STRING,                       -- Comma-separated list of missing fields
  has_warnings BOOLEAN,                             -- True if any calculation had warnings
  warning_details STRING,                           -- Description of warnings
  
  -- Processing metadata (3 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP,                             -- For tracking real-time updates
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, universal_player_id, game_date
OPTIONS(
  description="Pre-calculated composite scores and point adjustments. CRITICAL TABLE. Week 1-4: 4 active factors (fatigue, shot_zone, pace, usage_spike), 4 deferred (set to 0). Source data from nba_analytics and nba_precompute tables. Updated nightly at 11 PM and on-demand at 6 AM + line changes.",
  partition_expiration_days=90
);

-- ============================================================================
-- Table 4: player_daily_cache
-- ============================================================================
-- Daily snapshot of player data that won't change during the day
-- Updated: Once daily at 6 AM
-- Used by: All prediction systems for fast re-prediction when lines change
-- Priority: MEDIUM - Optimization, not critical for Week 1
-- Purpose: Speeds up line change updates 5x (avoids re-querying Phase 3 tables)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_daily_cache` (
  -- Identifiers (3 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  cache_date DATE NOT NULL,                         -- Date this cache represents (partition key)
  
  -- Recent performance - Won't change during the day (8 fields)
  points_avg_last_5 NUMERIC(5,1),                   -- Already in upcoming_player_game_context
  points_avg_last_10 NUMERIC(5,1),                  -- Already in upcoming_player_game_context
  points_avg_season NUMERIC(5,1),                   -- Season average
  points_std_last_10 NUMERIC(5,2),                  -- Volatility indicator
  minutes_avg_last_10 NUMERIC(5,1),                 -- Playing time trend
  usage_rate_last_10 NUMERIC(5,2),                  -- Shot volume trend
  ts_pct_last_10 NUMERIC(5,3),                      -- Efficiency trend
  games_played_season INT64,                        -- Sample size
  
  -- Team context - Won't change during the day (3 fields)
  team_pace_last_10 NUMERIC(5,1),                   -- Team's recent pace
  team_off_rating_last_10 NUMERIC(6,2),             -- Team's offensive efficiency
  player_usage_rate_season NUMERIC(5,2),            -- Season usage rate
  
  -- Fatigue metrics - Won't change during the day (7 fields)
  games_in_last_7_days INT64,
  games_in_last_14_days INT64,
  minutes_in_last_7_days INT64,
  minutes_in_last_14_days INT64,
  back_to_backs_last_14_days INT64,
  avg_minutes_per_game_last_7 NUMERIC(5,1),
  fourth_quarter_minutes_last_7 INT64,
  
  -- Shot zone tendencies - Won't change during the day (4 fields)
  primary_scoring_zone STRING,                      -- From player_shot_zone_analysis
  paint_rate_last_10 NUMERIC(5,2),                  
  three_pt_rate_last_10 NUMERIC(5,2),
  assisted_rate_last_10 NUMERIC(5,2),
  
  -- Player status (2 fields)
  player_position STRING,
  player_age INT64,
  
  -- Cache metadata (3 fields)
  cache_version STRING,                             -- "v1", "v2", etc.
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY cache_date
CLUSTER BY player_lookup, universal_player_id
OPTIONS(
  description="Daily snapshot of player data that won't change intraday. Updated once at 6 AM. Speeds up line change re-predictions 5x by caching stable data. Source: nba_analytics tables.",
  partition_expiration_days=30
);

-- ============================================================================
-- Table 5: similarity_match_cache (COMMENTED OUT - Calculate On-Demand)
-- ============================================================================
-- DECISION: Skip this table initially. Calculate similarity on-demand instead.
-- 
-- REASONING:
--   - On-demand queries cost ~$10-15/month (acceptable)
--   - Cache adds complexity without major benefit
--   - Similarity queries run in 1-2 seconds (acceptable latency)
--   - Can always add cache later if needed
--
-- RECONSIDER IF:
--   - Similarity queries consistently take >3 seconds
--   - Query costs exceed $50/month
--   - Real-time similarity updates become critical
--
-- To enable this table in the future, see original phase4_precompute_schema.sql
-- ============================================================================

/*
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.similarity_match_cache` (
  -- This table is intentionally commented out
  -- Calculate similarity on-demand via SQL query in similarity_balanced_v1 system
  ...
);
*/

-- ============================================================================
-- Helper Views for Precompute Tables
-- ============================================================================

-- View: Today's composite factors with quality flags
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_todays_composite_factors` AS
SELECT 
  player_lookup,
  universal_player_id,
  game_id,
  game_date,
  
  -- Active scores
  fatigue_score,
  shot_zone_mismatch_score,
  pace_score,
  usage_spike_score,
  
  -- Active adjustments
  fatigue_adjustment,
  shot_zone_adjustment,
  pace_adjustment,
  usage_spike_adjustment,
  total_composite_adjustment,
  
  -- Deferred scores (should all be 0 in v1)
  referee_favorability_score,
  look_ahead_pressure_score,
  matchup_history_score,
  momentum_score,
  
  -- Implementation tracking
  calculation_version,
  factors_active,
  factors_deferred,
  
  -- Quality metrics
  data_completeness_pct,
  has_warnings,
  warning_details,
  
  -- Alert flags
  CASE 
    WHEN fatigue_score < 40 THEN 'EXTREME_FATIGUE'
    WHEN ABS(shot_zone_mismatch_score) > 7 THEN 'STRONG_MATCHUP'
    WHEN has_warnings THEN 'DATA_QUALITY_ISSUE'
    ELSE 'NORMAL'
  END as alert_flag,
  
  processed_at
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
ORDER BY 
  CASE 
    WHEN fatigue_score < 40 THEN 1
    WHEN ABS(shot_zone_mismatch_score) > 7 THEN 2
    WHEN has_warnings THEN 3
    ELSE 4
  END,
  player_lookup;

-- View: Shot zone mismatches (favorable and unfavorable)
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_shot_zone_mismatches` AS
SELECT 
  p.player_lookup,
  p.universal_player_id,
  p.analysis_date as game_date,
  p.primary_scoring_zone,
  t.weakest_zone as opponent_weakest_zone,
  t.strongest_zone as opponent_strongest_zone,
  pcf.shot_zone_mismatch_score,
  pcf.shot_zone_adjustment,
  CASE 
    WHEN pcf.shot_zone_mismatch_score >= 7 THEN 'EXTREME_FAVORABLE'
    WHEN pcf.shot_zone_mismatch_score >= 5 THEN 'VERY_FAVORABLE'
    WHEN pcf.shot_zone_mismatch_score >= 2 THEN 'FAVORABLE'
    WHEN pcf.shot_zone_mismatch_score <= -5 THEN 'VERY_UNFAVORABLE'
    WHEN pcf.shot_zone_mismatch_score <= -2 THEN 'UNFAVORABLE'
    ELSE 'NEUTRAL'
  END as matchup_rating,
  upg.opponent_team_abbr,
  upg.game_id
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
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_fatigue_alerts` AS
SELECT 
  pcf.player_lookup,
  pcf.universal_player_id,
  pcf.game_date,
  pcf.game_id,
  pcf.fatigue_score,
  pcf.fatigue_adjustment,
  pdc.games_in_last_7_days,
  pdc.minutes_in_last_7_days,
  pdc.back_to_backs_last_14_days,
  upg.opponent_team_abbr,
  upg.back_to_back,
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
JOIN `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
  ON pcf.player_lookup = upg.player_lookup
  AND pcf.game_date = upg.game_date
WHERE pcf.game_date = CURRENT_DATE()
  AND pcf.fatigue_score < 65
ORDER BY pcf.fatigue_score ASC;

-- ============================================================================
-- Usage Notes & Update Schedule
-- ============================================================================
-- 
-- UPDATE SCHEDULE:
-- 1. Nightly (11 PM - 6 AM): Update all tables after Phase 3 analytics complete
--    - player_shot_zone_analysis: Recalculate from last N games
--    - team_defense_zone_analysis: Recalculate from last N games
--    - player_composite_factors: Calculate for tomorrow's games
--    - player_daily_cache: Prepare cache for tomorrow
--
-- 2. Morning (6 AM): Finalize for today's games
--    - player_composite_factors: Final update with latest context
--    - player_daily_cache: Lock cache for the day
--
-- 3. Real-time (9 AM - Game Time): Update only when needed
--    - player_composite_factors: When betting lines change significantly
--    - Other tables: No intraday updates (cached for speed)
--
-- REGENERATION:
-- All tables can be regenerated from Phase 3 analytics if needed:
-- - player_shot_zone_analysis: Query player_game_summary shot zone fields
-- - team_defense_zone_analysis: Query team_defense_game_summary
-- - player_composite_factors: Run composite factor calculations
-- - player_daily_cache: Aggregate from various Phase 3 tables
--
-- PERFORMANCE:
-- - player_daily_cache speeds up line change updates (5x faster)
-- - player_composite_factors centralizes all adjustments (critical for consistency)
-- - Shot zone tables enable fast matchup analysis
--
-- DATA FLOW:
-- Phase 3 (nba_analytics) → Phase 4 (nba_precompute) → Phase 5 (nba_predictions)
--
-- RELATED DOCUMENTS:
-- - architecture_decisions.md: Why we chose this approach
-- - phase5_infrastructure_architecture.md: How Phase 5 uses this data
-- - phase5_implementation_timeline.md: When to implement each piece
-- ============================================================================

-- ============================================================================
-- IMPLEMENTATION CHECKLIST
-- ============================================================================
--
-- Week 1: Core Tables
-- [ ] Create player_shot_zone_analysis table
-- [ ] Create team_defense_zone_analysis table
-- [ ] Create player_composite_factors table
-- [ ] Create player_daily_cache table
-- [ ] Create helper views
--
-- Week 1: Initial Processors
-- [ ] PlayerShotZoneProcessor (analytics processor, Flask service)
-- [ ] TeamDefenseZoneProcessor (analytics processor, Flask service)
-- [ ] PlayerCompositeFactorsProcessor - Implement 4 active factors only
-- [ ] PlayerDailyCacheProcessor
--
-- Week 1: Validation
-- [ ] Verify fatigue_score calculations (should be 0-100)
-- [ ] Verify shot_zone_mismatch_score calculations (should be -10 to +10)
-- [ ] Verify pace_score calculations (should be -3 to +3)
-- [ ] Verify usage_spike_score calculations (should be -3 to +3)
-- [ ] Confirm deferred factors are all 0
-- [ ] Check calculation_version = "v1_4factors"
-- [ ] Check factors_active = "fatigue,shot_zone,pace,usage_spike"
-- [ ] Check factors_deferred = "referee,look_ahead,matchup_history,momentum"
--
-- Week 2-4: Backfill
-- [ ] Backfill shot zone analysis (4 seasons)
-- [ ] Backfill team defense analysis (4 seasons)
-- [ ] Backfill composite factors (current season only)
-- [ ] Backfill daily cache (current season only)
--
-- Month 3: Feature Importance Analysis
-- [ ] Run XGBoost with all features
-- [ ] Check feature importance for deferred factors
-- [ ] If any deferred factor >5% importance → Plan implementation
-- [ ] If all deferred factors <5% importance → Keep as neutral
--
-- ============================================================================
-- END OF SCHEMA
-- ============================================================================