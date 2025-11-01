-- ============================================================================
-- NBA Props Platform - Phase 4 Precompute: Player Composite Factors
-- ============================================================================
-- File: schemas/bigquery/precompute/player_composite_factors.sql
-- Purpose: Pre-calculated composite adjustment factors for player predictions
-- Update: Nightly at 11:30 PM (after zone analysis completes)
-- Entities: ~450 active NBA players with upcoming games
-- Duration: 10-15 minutes
-- 
-- Version: 1.0 (Week 1-4 Implementation: 4 Active Factors, 4 Deferred)
-- Date: October 30, 2025
-- Status: Production-Ready
--
-- Strategy: Start with 4 active factors, set 4 deferred factors to 0 (neutral).
--           After 3 months, analyze XGBoost feature importance to decide which
--           deferred factors to implement.
--
-- Dependencies:
--   Phase 3: nba_analytics.upcoming_player_game_context (CRITICAL)
--   Phase 3: nba_analytics.upcoming_team_game_context (CRITICAL)
--   Phase 4: nba_precompute.player_shot_zone_analysis (must complete first)
--   Phase 4: nba_precompute.team_defense_zone_analysis (must complete first)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_composite_factors` (
  -- ============================================================================
  -- IDENTIFIERS (4 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  universal_player_id STRING,                       -- Universal player ID from registry
  game_date DATE NOT NULL,                          -- Game date (partition key)
  game_id STRING NOT NULL,                          -- Unique game identifier
  
  -- ============================================================================
  -- ACTIVE COMPOSITE SCORES (Week 1-4 Implementation) - 4 fields
  -- ============================================================================
  
  -- Factor 1: Fatigue Score
  fatigue_score INT64,                              -- 0-100 (100 = fresh, 0 = exhausted)
                                                     -- Based on: days_rest, minutes, back_to_backs
                                                     -- Range: 0-100
                                                     -- Example: 85 (well-rested)
  
  -- Factor 2: Shot Zone Mismatch Score  
  shot_zone_mismatch_score NUMERIC(4,1),            -- -10.0 to +10.0
                                                     -- Positive = favorable matchup
                                                     -- Player's primary zone vs opponent's defense
                                                     -- Range: -10.0 to +10.0
                                                     -- Example: +4.3 (favorable paint matchup)
  
  -- Factor 3: Pace Score
  pace_score NUMERIC(3,1),                          -- -3.0 to +3.0
                                                     -- Expected game pace vs league average
                                                     -- High pace = more possessions
                                                     -- Range: -3.0 to +3.0
                                                     -- Example: +2.5 (fast game)
  
  -- Factor 4: Usage Spike Score
  usage_spike_score NUMERIC(3,1),                   -- -3.0 to +3.0
                                                     -- Recent usage change vs season average
                                                     -- Spike = more shots = more points
                                                     -- Range: -3.0 to +3.0
                                                     -- Example: +1.8 (teammate out, usage up)
  
  -- ============================================================================
  -- DEFERRED COMPOSITE SCORES (Set to 0 in Week 1-4) - 4 fields
  -- ============================================================================
  -- These fields exist in schema for future implementation
  -- Initial processors will set these to 0 (neutral)
  -- XGBoost will determine if they matter via feature importance
  
  referee_favorability_score NUMERIC(3,1),          -- -5.0 to +5.0 (PLACEHOLDER: returns 0.0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: foul calling tendencies
  
  look_ahead_pressure_score NUMERIC(3,1),           -- -5.0 to +5.0 (PLACEHOLDER: returns 0.0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: upcoming schedule pressure
  
  matchup_history_score INT64,                      -- -2 to +2 (PLACEHOLDER: returns 0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: player vs opponent history
  
  momentum_score INT64,                             -- -2 to +2 (PLACEHOLDER: returns 0)
                                                     -- TODO: Implement after 3 months if XGBoost shows >5% importance
                                                     -- Would track: recent performance trends
  
  -- ============================================================================
  -- POINT ADJUSTMENTS (Convert scores to point impacts) - 8 fields
  -- ============================================================================
  
  -- Active Adjustments (Weeks 1-4)
  fatigue_adjustment NUMERIC(5,2),                  -- Expected points impact from fatigue
                                                     -- Formula: (fatigue_score - 100) * 0.05
                                                     -- Range: 0.0 (fresh) to -5.0 (exhausted)
                                                     -- Example: -1.0 (slightly tired)
  
  shot_zone_adjustment NUMERIC(5,2),                -- Expected points impact from matchup
                                                     -- Direct conversion from score
                                                     -- Range: -10.0 to +10.0
                                                     -- Example: +4.3 (favorable matchup)
  
  pace_adjustment NUMERIC(5,2),                     -- Expected points impact from pace
                                                     -- Direct conversion from score
                                                     -- Range: -3.0 to +3.0
                                                     -- Example: +2.5 (fast game)
  
  usage_spike_adjustment NUMERIC(5,2),              -- Expected points impact from usage
                                                     -- Direct conversion from score
                                                     -- Range: -3.0 to +3.0
                                                     -- Example: +1.8 (usage boost)
  
  -- Deferred Adjustments (all 0 initially)
  referee_adjustment NUMERIC(5,2),                  -- PLACEHOLDER: returns 0.0
  look_ahead_adjustment NUMERIC(5,2),               -- PLACEHOLDER: returns 0.0
  matchup_history_adjustment NUMERIC(5,2),          -- PLACEHOLDER: returns 0.0
  momentum_adjustment NUMERIC(5,2),                 -- PLACEHOLDER: returns 0.0
  
  -- Total composite adjustment
  total_composite_adjustment NUMERIC(5,2),          -- Sum of all adjustments
                                                     -- Week 1-4: Only 4 active factors
                                                     -- Range: typically -15.0 to +15.0
                                                     -- Example: +7.6 (favorable game setup)
  
  -- ============================================================================
  -- IMPLEMENTATION TRACKING (3 fields)
  -- ============================================================================
  
  calculation_version STRING,                       -- "v1_4factors", "v2_8factors", etc.
                                                     -- Example: "v1_4factors"
  
  factors_active STRING,                            -- Comma-separated active factors
                                                     -- Example: "fatigue,shot_zone,pace,usage_spike"
  
  factors_deferred STRING,                          -- Comma-separated deferred factors
                                                     -- Example: "referee,look_ahead,matchup_history,momentum"
  
  -- ============================================================================
  -- SUPPORTING DATA & QUALITY (8 fields)
  -- ============================================================================
  
  -- Context that went into calculations (for debugging/transparency)
  fatigue_context JSON,                             -- {days_rest, minutes_last_7, back_to_backs, age}
                                                     -- Example: {"days_rest": 2, "minutes_last_7": 175.2, ...}
  
  shot_zone_context JSON,                           -- {player_primary_zone, opponent_weak_zone, mismatch_type}
                                                     -- Example: {"player_primary_zone": "paint", ...}
  
  pace_context JSON,                                -- {pace_differential, team_pace, opponent_pace}
                                                     -- Example: {"pace_differential": 5.2, ...}
  
  usage_context JSON,                               -- {projected_usage, recent_usage, usage_diff}
                                                     -- Example: {"projected_usage": 28.5, ...}
  
  -- Data quality & completeness
  data_completeness_pct NUMERIC(5,2),               -- % of required data available
                                                     -- 100 = all data present
                                                     -- Range: 0.00-100.00
                                                     -- Example: 100.00
  
  missing_data_fields STRING,                       -- Comma-separated list of missing fields
                                                     -- NULL if no missing data
                                                     -- Example: "projected_usage_rate"
  
  has_warnings BOOLEAN,                             -- TRUE if any calculation had warnings
                                                     -- Example: FALSE
  
  warning_details STRING,                           -- Description of warnings
                                                     -- NULL if no warnings
                                                     -- Example: "EXTREME_FATIGUE"
  
  -- ============================================================================
  -- v4.0 SOURCE TRACKING (12 fields: 3 per source × 4 sources)
  -- ============================================================================
  
  -- Source 1: nba_analytics.upcoming_player_game_context
  source_player_context_last_updated TIMESTAMP,     -- When source was last processed
  source_player_context_rows_found INT64,           -- Rows returned from query
  source_player_context_completeness_pct NUMERIC(5,2), -- % of expected data found
  
  -- Source 2: nba_analytics.upcoming_team_game_context
  source_team_context_last_updated TIMESTAMP,       -- When source was last processed
  source_team_context_rows_found INT64,             -- Rows returned from query
  source_team_context_completeness_pct NUMERIC(5,2), -- % of expected data found
  
  -- Source 3: nba_precompute.player_shot_zone_analysis
  source_player_shot_last_updated TIMESTAMP,        -- When source was last processed
  source_player_shot_rows_found INT64,              -- Rows returned from query
  source_player_shot_completeness_pct NUMERIC(5,2), -- % of expected data found
  
  -- Source 4: nba_precompute.team_defense_zone_analysis
  source_team_defense_last_updated TIMESTAMP,       -- When source was last processed
  source_team_defense_rows_found INT64,             -- Rows returned from query
  source_team_defense_completeness_pct NUMERIC(5,2), -- % of expected data found
  
  -- ============================================================================
  -- OPTIONAL: EARLY SEASON FIELDS (2 fields)
  -- ============================================================================
  
  early_season_flag BOOLEAN,                        -- TRUE when insufficient data
                                                     -- Set when zone analysis has early_season_flag
  
  insufficient_data_reason STRING,                  -- Why data was insufficient
                                                     -- Example: "Player shot zone analysis unavailable"
  
  -- ============================================================================
  -- PROCESSING METADATA (3 fields)
  -- ============================================================================
  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- Row creation timestamp
  updated_at TIMESTAMP,                             -- For tracking real-time updates
  processed_at TIMESTAMP                            -- When this calculation was performed
)
PARTITION BY game_date
CLUSTER BY player_lookup, universal_player_id, game_date
OPTIONS(
  description="Pre-calculated composite scores and point adjustments. CRITICAL TABLE. Week 1-4: 4 active factors (fatigue, shot_zone, pace, usage_spike), 4 deferred (set to 0). Source data from nba_analytics and nba_precompute tables. Updated nightly at 11:30 PM and on-demand at 6 AM + line changes. v4.0 dependency tracking (4 sources × 3 fields = 12 tracking fields).",
  partition_expiration_days=90
);

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 58
--   - Identifiers: 4
--   - Active scores: 4
--   - Deferred scores: 4
--   - Adjustments: 9 (8 factors + 1 total)
--   - Implementation tracking: 3
--   - Supporting data: 8
--   - Source tracking (v4.0): 12 (4 sources × 3 fields)
--   - Early season: 2
--   - Processing metadata: 3
--
-- Total tracking fields: 17 (12 source + 2 early season + 3 metadata)
-- Business fields: 28
-- Context fields: 13
-- ============================================================================

-- ============================================================================
-- SAMPLE ROW (Normal Season - Favorable Game Setup)
-- ============================================================================
/*
{
  -- Identifiers
  "player_lookup": "lebronjames",
  "universal_player_id": "lebronjames_001",
  "game_date": "2025-10-21",
  "game_id": "20251021LAL_GSW",
  
  -- Active Scores
  "fatigue_score": 82,
  "shot_zone_mismatch_score": 5.2,
  "pace_score": 2.6,
  "usage_spike_score": 1.5,
  
  -- Deferred Scores (all 0)
  "referee_favorability_score": 0.0,
  "look_ahead_pressure_score": 0.0,
  "matchup_history_score": 0,
  "momentum_score": 0,
  
  -- Active Adjustments
  "fatigue_adjustment": -0.9,
  "shot_zone_adjustment": 5.2,
  "pace_adjustment": 2.6,
  "usage_spike_adjustment": 1.5,
  
  -- Deferred Adjustments (all 0)
  "referee_adjustment": 0.0,
  "look_ahead_adjustment": 0.0,
  "matchup_history_adjustment": 0.0,
  "momentum_adjustment": 0.0,
  
  -- Total
  "total_composite_adjustment": 8.4,
  
  -- Implementation Tracking
  "calculation_version": "v1_4factors",
  "factors_active": "fatigue,shot_zone,pace,usage_spike",
  "factors_deferred": "referee,look_ahead,matchup_history,momentum",
  
  -- Supporting Context
  "fatigue_context": {
    "days_rest": 2,
    "back_to_back": false,
    "games_last_7": 3,
    "minutes_last_7": 175.2,
    "avg_mpg_last_7": 35.1,
    "player_age": 40,
    "penalties_applied": ["age_30+", "heavy_mpg"],
    "bonuses_applied": ["2_days_rest"]
  },
  "shot_zone_context": {
    "player_primary_zone": "paint",
    "primary_zone_frequency": 65.2,
    "opponent_weak_zone": "paint",
    "opponent_defense_vs_league": 4.3,
    "zone_weight": 1.0,
    "extreme_matchup": false,
    "mismatch_type": "favorable"
  },
  "pace_context": {
    "pace_differential": 5.2,
    "team_pace": 102.5,
    "opponent_pace_last_10": 97.3,
    "expected_game_pace": 99.9,
    "league_avg_pace": 100.0,
    "pace_environment": "slightly_fast"
  },
  "usage_context": {
    "projected_usage_rate": 28.5,
    "avg_usage_last_7": 24.2,
    "usage_differential": 4.3,
    "star_teammates_out": 1,
    "usage_boost_applied": true,
    "boost_multiplier": 1.15,
    "usage_trend": "spike"
  },
  
  -- Data Quality
  "data_completeness_pct": 100.00,
  "missing_data_fields": null,
  "has_warnings": false,
  "warning_details": null,
  
  -- Source Tracking (v4.0)
  "source_player_context_last_updated": "2025-10-20T22:00:00Z",
  "source_player_context_rows_found": 1,
  "source_player_context_completeness_pct": 100.00,
  
  "source_team_context_last_updated": "2025-10-20T22:05:00Z",
  "source_team_context_rows_found": 1,
  "source_team_context_completeness_pct": 100.00,
  
  "source_player_shot_last_updated": "2025-10-20T23:15:00Z",
  "source_player_shot_rows_found": 1,
  "source_player_shot_completeness_pct": 100.00,
  
  "source_team_defense_last_updated": "2025-10-20T23:10:00Z",
  "source_team_defense_rows_found": 1,
  "source_team_defense_completeness_pct": 100.00,
  
  -- Early Season (not applicable)
  "early_season_flag": null,
  "insufficient_data_reason": null,
  
  -- Processing Metadata
  "created_at": "2025-10-20T23:45:00Z",
  "updated_at": null,
  "processed_at": "2025-10-20T23:45:00Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Difficult Game Setup)
-- ============================================================================
/*
{
  -- Identifiers
  "player_lookup": "kevindurant",
  "universal_player_id": "kevindurant_001",
  "game_date": "2025-10-22",
  "game_id": "20251022PHX_BOS",
  
  -- Active Scores (challenging game)
  "fatigue_score": 68,                              -- Back-to-back, tired
  "shot_zone_mismatch_score": -3.5,                 -- Tough defense
  "pace_score": -1.8,                               -- Slow game
  "usage_spike_score": 0.0,                         -- Normal usage
  
  -- Deferred Scores (all 0)
  "referee_favorability_score": 0.0,
  "look_ahead_pressure_score": 0.0,
  "matchup_history_score": 0,
  "momentum_score": 0,
  
  -- Active Adjustments
  "fatigue_adjustment": -1.6,                       -- Negative impact
  "shot_zone_adjustment": -3.5,                     -- Negative impact
  "pace_adjustment": -1.8,                          -- Negative impact
  "usage_spike_adjustment": 0.0,                    -- No impact
  
  -- Deferred Adjustments (all 0)
  "referee_adjustment": 0.0,
  "look_ahead_adjustment": 0.0,
  "matchup_history_adjustment": 0.0,
  "momentum_adjustment": 0.0,
  
  -- Total (negative = challenging game)
  "total_composite_adjustment": -6.9,
  
  -- Implementation Tracking
  "calculation_version": "v1_4factors",
  "factors_active": "fatigue,shot_zone,pace,usage_spike",
  "factors_deferred": "referee,look_ahead,matchup_history,momentum",
  
  -- Data Quality
  "data_completeness_pct": 100.00,
  "missing_data_fields": null,
  "has_warnings": true,
  "warning_details": "EXTREME_FATIGUE",
  
  -- [Source tracking fields same as above...]
  
  -- Processing Metadata
  "processed_at": "2025-10-21T23:45:00Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Early Season - Placeholder)
-- ============================================================================
/*
{
  -- Identifiers
  "player_lookup": "victorwembanyama",
  "universal_player_id": "victorwembanyama_001",
  "game_date": "2024-10-28",
  "game_id": "20241028SAS_MEM",
  
  -- Active Scores (all NULL - insufficient data)
  "fatigue_score": null,
  "shot_zone_mismatch_score": null,
  "pace_score": null,
  "usage_spike_score": null,
  
  -- Deferred Scores
  "referee_favorability_score": 0.0,
  "look_ahead_pressure_score": 0.0,
  "matchup_history_score": 0,
  "momentum_score": 0,
  
  -- Adjustments (all NULL)
  "fatigue_adjustment": null,
  "shot_zone_adjustment": null,
  "pace_adjustment": null,
  "usage_spike_adjustment": null,
  
  "referee_adjustment": 0.0,
  "look_ahead_adjustment": 0.0,
  "matchup_history_adjustment": 0.0,
  "momentum_adjustment": 0.0,
  
  "total_composite_adjustment": null,
  
  -- Implementation Tracking
  "calculation_version": "v1_4factors",
  "factors_active": "fatigue,shot_zone,pace,usage_spike",
  "factors_deferred": "referee,look_ahead,matchup_history,momentum",
  
  -- Data Quality
  "data_completeness_pct": 50.0,
  "missing_data_fields": "player_shot_zone_analysis,team_defense_zone_analysis",
  "has_warnings": true,
  "warning_details": "INCOMPLETE_DATA",
  
  -- Source Tracking (still populated!)
  "source_player_context_last_updated": "2024-10-27T22:00:00Z",
  "source_player_context_rows_found": 1,
  "source_player_context_completeness_pct": 100.00,
  
  "source_team_context_last_updated": "2024-10-27T22:05:00Z",
  "source_team_context_rows_found": 1,
  "source_team_context_completeness_pct": 100.00,
  
  "source_player_shot_last_updated": "2024-10-27T23:15:00Z",
  "source_player_shot_rows_found": 0,
  "source_player_shot_completeness_pct": 0.0,
  
  "source_team_defense_last_updated": "2024-10-27T23:10:00Z",
  "source_team_defense_rows_found": 0,
  "source_team_defense_completeness_pct": 0.0,
  
  -- Early Season (SET)
  "early_season_flag": true,
  "insufficient_data_reason": "Player shot zone analysis has early_season_flag=true",
  
  -- Processing Metadata
  "processed_at": "2024-10-27T23:45:00Z"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Check all players processed today
-- Expected: ~100-150 players (those with games today)
SELECT 
  game_date,
  COUNT(*) as players_processed,
  COUNT(CASE WHEN early_season_flag = TRUE THEN 1 END) as placeholders,
  COUNT(CASE WHEN total_composite_adjustment IS NOT NULL THEN 1 END) as real_data,
  AVG(total_composite_adjustment) as avg_adjustment,
  MIN(total_composite_adjustment) as min_adjustment,
  MAX(total_composite_adjustment) as max_adjustment
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Query 2: Check source data quality
-- Expected: All completeness near 100%, all ages <24 hours
SELECT 
  game_date,
  COUNT(*) as players,
  
  -- Average completeness across all sources
  AVG(source_player_context_completeness_pct) as avg_player_context_completeness,
  AVG(source_team_context_completeness_pct) as avg_team_context_completeness,
  AVG(source_player_shot_completeness_pct) as avg_player_shot_completeness,
  AVG(source_team_defense_completeness_pct) as avg_team_defense_completeness,
  
  -- Minimum completeness (bottleneck)
  MIN(LEAST(
    source_player_context_completeness_pct,
    source_team_context_completeness_pct,
    source_player_shot_completeness_pct,
    source_team_defense_completeness_pct
  )) as worst_source_completeness,
  
  -- Max source age
  MAX(GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_shot_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_defense_last_updated, HOUR)
  )) as max_source_age_hours
  
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Query 3: Identify data quality issues
-- Expected: 0 rows (no problems)
SELECT 
  player_lookup,
  game_date,
  data_completeness_pct,
  missing_data_fields,
  has_warnings,
  warning_details,
  
  -- Identify which source is the problem
  CASE
    WHEN source_player_context_completeness_pct < 85 THEN 'player_context'
    WHEN source_team_context_completeness_pct < 85 THEN 'team_context'
    WHEN source_player_shot_completeness_pct < 85 THEN 'player_shot'
    WHEN source_team_defense_completeness_pct < 85 THEN 'team_defense'
    ELSE 'all_good'
  END as problem_source
  
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND data_completeness_pct < 85
ORDER BY data_completeness_pct ASC;

-- Query 4: Check for extreme adjustments (potential data issues)
-- Expected: 0 rows (all adjustments in reasonable range)
SELECT 
  player_lookup,
  game_date,
  total_composite_adjustment,
  fatigue_adjustment,
  shot_zone_adjustment,
  pace_adjustment,
  usage_spike_adjustment,
  warning_details
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND (
    ABS(total_composite_adjustment) > 15.0
    OR fatigue_adjustment < -5.0
    OR ABS(shot_zone_adjustment) > 10.0
    OR ABS(pace_adjustment) > 3.0
    OR ABS(usage_spike_adjustment) > 3.0
  )
ORDER BY ABS(total_composite_adjustment) DESC;

-- Query 5: Distribution of adjustments
-- Shows how many players have favorable vs unfavorable setups
SELECT 
  game_date,
  
  -- Categorize game setups
  COUNT(CASE WHEN total_composite_adjustment >= 5.0 THEN 1 END) as very_favorable,
  COUNT(CASE WHEN total_composite_adjustment BETWEEN 2.0 AND 4.9 THEN 1 END) as favorable,
  COUNT(CASE WHEN total_composite_adjustment BETWEEN -1.9 AND 1.9 THEN 1 END) as neutral,
  COUNT(CASE WHEN total_composite_adjustment BETWEEN -4.9 AND -2.0 THEN 1 END) as unfavorable,
  COUNT(CASE WHEN total_composite_adjustment <= -5.0 THEN 1 END) as very_unfavorable,
  
  -- Average by factor
  AVG(fatigue_adjustment) as avg_fatigue,
  AVG(shot_zone_adjustment) as avg_zone,
  AVG(pace_adjustment) as avg_pace,
  AVG(usage_spike_adjustment) as avg_usage,
  
  COUNT(*) as total_players
  
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND early_season_flag IS NULL
GROUP BY game_date
ORDER BY game_date DESC;

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Alert: Stale source data (>24 hours old)
SELECT 
  'player_composite_factors' as processor,
  game_date,
  MAX(GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_shot_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_defense_last_updated, HOUR)
  )) as max_age_hours
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_date
HAVING MAX(GREATEST(
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_context_last_updated, HOUR),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_context_last_updated, HOUR),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_shot_last_updated, HOUR),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_defense_last_updated, HOUR)
)) > 24;

-- Alert: Low completeness (<85%)
SELECT 
  'player_composite_factors' as processor,
  game_date,
  AVG(data_completeness_pct) as avg_completeness,
  MIN(data_completeness_pct) as min_completeness,
  COUNT(CASE WHEN data_completeness_pct < 85 THEN 1 END) as low_quality_count
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_date
HAVING MIN(data_completeness_pct) < 85;

-- Alert: Too few players processed (<50)
SELECT 
  'player_composite_factors' as processor,
  game_date,
  COUNT(*) as players_processed
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date
HAVING COUNT(*) < 50;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Latest composite factors for today's games
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_latest_composite_factors` AS
SELECT 
  player_lookup,
  universal_player_id,
  game_date,
  game_id,
  
  -- Scores
  fatigue_score,
  shot_zone_mismatch_score,
  pace_score,
  usage_spike_score,
  
  -- Adjustments
  fatigue_adjustment,
  shot_zone_adjustment,
  pace_adjustment,
  usage_spike_adjustment,
  total_composite_adjustment,
  
  -- Quality
  data_completeness_pct,
  has_warnings,
  warning_details,
  early_season_flag,
  
  processed_at
  
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND early_season_flag IS NULL
ORDER BY total_composite_adjustment DESC;

-- View: Players with extreme favorable/unfavorable setups
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_extreme_game_setups` AS
SELECT 
  player_lookup,
  game_date,
  
  -- Classification
  CASE 
    WHEN total_composite_adjustment >= 8.0 THEN 'VERY_FAVORABLE'
    WHEN total_composite_adjustment >= 5.0 THEN 'FAVORABLE'
    WHEN total_composite_adjustment <= -8.0 THEN 'VERY_UNFAVORABLE'
    WHEN total_composite_adjustment <= -5.0 THEN 'UNFAVORABLE'
    ELSE 'NEUTRAL'
  END as game_setup,
  
  total_composite_adjustment,
  
  -- Contributing factors
  fatigue_adjustment,
  shot_zone_adjustment,
  pace_adjustment,
  usage_spike_adjustment,
  
  -- Context
  fatigue_context,
  shot_zone_context,
  pace_context,
  usage_context
  
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND ABS(total_composite_adjustment) >= 5.0
  AND early_season_flag IS NULL
ORDER BY total_composite_adjustment DESC;

-- ============================================================================
-- USAGE IN PHASE 5 PREDICTIONS
-- ============================================================================
-- 
-- Basic Adjustment:
--   base_prediction = 25.0 points (player's recent average)
--   adjusted_prediction = base_prediction + total_composite_adjustment
--                      = 25.0 + 7.6 = 32.6 points
--
-- Factor-Specific Analysis:
--   - Similarity matching: Find games where fatigue_score was similar
--   - Zone matchup system: Weight by shot_zone_adjustment
--   - Composite factor system: Use total_composite_adjustment as predictor
--
-- Confidence Weighting:
--   - High data_completeness_pct = higher confidence
--   - has_warnings = TRUE = lower confidence
--   - early_season_flag = TRUE = skip or use with caution
--
-- ============================================================================

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_precompute dataset
-- [ ] Verify schema matches processor expectations
-- [ ] Set partition expiration (90 days)
-- [ ] Configure clustering for query performance
-- [ ] Test with sample data
-- [ ] Validate all tracking fields populate correctly
-- [ ] Test early season handling
-- [ ] Enable monitoring queries
-- [ ] Document alert thresholds
-- [ ] Create helper views
-- ============================================================================

-- ============================================================================
-- ALERT CONDITIONS
-- ============================================================================
-- Alert if:
-- 1. <50 players processed (should be ~100-150 on game days)
-- 2. Average completeness <85%
-- 3. Max source age >24 hours
-- 4. >5% of players with extreme adjustments (>15 or <-15)
-- 5. Processing time >20 minutes
-- ============================================================================

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================