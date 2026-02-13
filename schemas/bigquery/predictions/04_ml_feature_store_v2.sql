-- @quality-filter: exempt
-- Reason: Table creation DDL, not a query view

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
  -- HISTORICAL COMPLETENESS TRACKING (Data Cascade Architecture)
  -- Tracks whether rolling window calculations had all required historical data.
  -- Different from schedule completeness (expected_games_count/actual_games_count above)
  -- which tracks if TODAY's games were processed.
  --
  -- This tracks: "Did the last-10-games rolling average have all 10 games?"
  -- ========================================================================
  historical_completeness STRUCT<
    games_found INT64,                              -- Actual games found in rolling window
    games_expected INT64,                           -- Expected games (min of available, window_size=10)
    is_complete BOOL,                               -- games_found >= games_expected
    is_bootstrap BOOL,                              -- games_expected < 10 (player has limited history)
    contributing_game_dates ARRAY<DATE>             -- Dates of games used (for cascade detection)
  >,

  -- ========================================================================
  -- PROCESSING METADATA (2 fields)
  -- ========================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP,

  -- ========================================================================
  -- FEATURE QUALITY VISIBILITY (120 new fields + 2 reused = 122 total - Session 134/137)
  -- Hybrid schema: flat columns for critical fields, JSON for details
  -- Design: docs/08-projects/current/feature-quality-visibility/07-FINAL-HYBRID-SCHEMA.md
  --
  -- NOTE: feature_quality_score (above) is reused as aggregate quality score.
  -- NOTE: is_production_ready (above) is UNCHANGED (completeness-based).
  -- NOTE: is_quality_ready (below) is the NEW quality-based gate:
  --   TRUE if quality_tier in ('gold','silver','bronze')
  --   AND feature_quality_score >= 70 AND matchup_quality_pct >= 50
  -- ========================================================================

  -- Section 1: Aggregate Quality (9 new fields)
  quality_tier STRING OPTIONS(
    description='Overall tier: gold (>95), silver (85-95), bronze (70-85), poor (50-70), critical (<50). Lowercase matches Phase 3.'
  ),
  quality_alert_level STRING OPTIONS(
    description='Alert priority: green (healthy), yellow (degraded), red (critical). For real-time monitoring.'
  ),
  quality_alerts ARRAY<STRING> OPTIONS(
    description='Specific alerts triggered, e.g. all_matchup_features_defaulted, high_default_rate_20pct.'
  ),
  default_feature_count INT64 OPTIONS(
    description='Total count of features using defaults (includes optional vegas features).'
  ),
  required_default_count INT64 OPTIONS(
    description='Session 145: Count of REQUIRED features using defaults (excludes optional vegas 25-27). Used for zero-tolerance gating.'
  ),
  default_feature_indices ARRAY<INT64> OPTIONS(
    description='Session 142: Indices of features using default/fallback values (empty = all real data).'
  ),
  phase4_feature_count INT64 OPTIONS(
    description='Count of features from Phase 4 precompute (highest quality). Target: 25+ of 37.'
  ),
  phase3_feature_count INT64 OPTIONS(
    description='Count of features from Phase 3 analytics (good quality fallback).'
  ),
  calculated_feature_count INT64 OPTIONS(
    description='Count of features calculated on-the-fly (acceptable quality).'
  ),
  is_training_ready BOOL OPTIONS(
    description='TRUE if meets training quality bar (stricter): quality_tier in (gold, silver), matchup >= 70, history >= 80.'
  ),
  training_quality_feature_count INT64 OPTIONS(
    description='Count of features meeting training quality bar. Filter: WHERE training_quality_feature_count >= 30.'
  ),
  is_quality_ready BOOL OPTIONS(
    description='TRUE if meets quality gate: quality_tier in (gold, silver, bronze) AND score >= 70 AND matchup >= 50. Separate from is_production_ready (completeness-based).'
  ),

  -- Section 2: Category Quality (18 fields)
  -- 5 categories covering all 54 features: matchup(6), player_history(20), team_context(3), vegas(4), game_context(19)
  matchup_quality_pct FLOAT64 OPTIONS(
    description='Quality % for matchup features (5-8, 13-14). 0=all defaults, 100=all high quality.'
  ),
  player_history_quality_pct FLOAT64 OPTIONS(
    description='Quality % for player history features (0-4, 29-36). 13 features. Typically 90-100%.'
  ),
  team_context_quality_pct FLOAT64 OPTIONS(
    description='Quality % for team context features (22-24). Usually 95-100%.'
  ),
  vegas_quality_pct FLOAT64 OPTIONS(
    description='Quality % for vegas features (25-28). Expected 40-60% (not all players have lines - NORMAL).'
  ),
  game_context_quality_pct FLOAT64 OPTIONS(
    description='Quality % for game context features (9-12, 15-21): rest, schedule, injury, starting status. 11 features.'
  ),
  matchup_default_count INT64 OPTIONS(
    description='Count of matchup features (6 total: 5-8, 13-14) using defaults.'
  ),
  player_history_default_count INT64 OPTIONS(
    description='Count of player history features using defaults.'
  ),
  team_context_default_count INT64 OPTIONS(
    description='Count of team context features using defaults.'
  ),
  vegas_default_count INT64 OPTIONS(
    description='Count of vegas features using defaults. High count is NORMAL.'
  ),
  game_context_default_count INT64 OPTIONS(
    description='Count of game context features (11 total: 9-12, 15-21) using defaults.'
  ),
  has_composite_factors BOOL OPTIONS(
    description='TRUE if composite factors (features 5-8) available from Phase 4.'
  ),
  has_opponent_defense BOOL OPTIONS(
    description='TRUE if opponent defense data (features 13-14) available from Phase 3.'
  ),
  has_vegas_line BOOL OPTIONS(
    description='TRUE if vegas line available. FALSE is normal for low-volume props.'
  ),
  vegas_line_source STRING OPTIONS(
    description='Session 152: Which source provided vegas line data. Values: odds_api, bettingpros, both, none. NULL for pre-Session-152 data.'
  ),
  critical_features_training_quality BOOL OPTIONS(
    description='TRUE if ALL critical features (matchup 5-8, defense 13-14) meet training quality bar.'
  ),
  critical_feature_count INT64 OPTIONS(
    description='Count of CRITICAL features present with high quality.'
  ),
  optional_feature_count INT64 OPTIONS(
    description='Count of optional features present. Missing optional = acceptable.'
  ),
  matchup_quality_tier STRING OPTIONS(
    description='Matchup category tier: gold, silver, bronze, poor, critical. Derived from matchup_quality_pct.'
  ),
  game_context_quality_tier STRING OPTIONS(
    description='Game context category tier: gold, silver, bronze, poor, critical. Derived from game_context_quality_pct.'
  ),

  -- Section 3: Per-Feature Quality Scores (54 fields)
  -- Quality score 0-100 for each of 54 features. Direct column access for fast debugging.
  -- Feature names match FEATURE_NAMES in ml_feature_store_processor.py (source of truth)
  feature_0_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 0 (points_avg_last_5)'),
  feature_1_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 1 (points_avg_last_10)'),
  feature_2_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 2 (points_avg_season)'),
  feature_3_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 3 (points_std_last_10)'),
  feature_4_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 4 (games_in_last_7_days)'),
  feature_5_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 5 (fatigue_score - CRITICAL)'),
  feature_6_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 6 (shot_zone_mismatch_score - CRITICAL)'),
  feature_7_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 7 (pace_score - CRITICAL)'),
  feature_8_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 8 (usage_spike_score - CRITICAL)'),
  feature_9_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 9 (rest_advantage)'),
  feature_10_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 10 (injury_risk)'),
  feature_11_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 11 (recent_trend)'),
  feature_12_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 12 (minutes_change)'),
  feature_13_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 13 (opponent_def_rating - CRITICAL)'),
  feature_14_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 14 (opponent_pace - CRITICAL)'),
  feature_15_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 15 (home_away)'),
  feature_16_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 16 (back_to_back)'),
  feature_17_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 17 (playoff_game)'),
  feature_18_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 18 (pct_paint)'),
  feature_19_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 19 (pct_mid_range)'),
  feature_20_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 20 (pct_three)'),
  feature_21_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 21 (pct_free_throw)'),
  feature_22_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 22 (team_pace)'),
  feature_23_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 23 (team_off_rating)'),
  feature_24_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 24 (team_win_pct)'),
  feature_25_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 25 (vegas_points_line)'),
  feature_26_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 26 (vegas_opening_line)'),
  feature_27_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 27 (vegas_line_move)'),
  feature_28_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 28 (has_vegas_line)'),
  feature_29_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 29 (avg_points_vs_opponent)'),
  feature_30_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 30 (games_vs_opponent)'),
  feature_31_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 31 (minutes_avg_last_10)'),
  feature_32_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 32 (ppm_avg_last_10)'),
  feature_33_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 33 (dnp_rate)'),
  feature_34_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 34 (pts_slope_10g)'),
  feature_35_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 35 (pts_vs_season_zscore)'),
  feature_36_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 36 (breakout_flag)'),
  feature_37_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 37 (star_teammates_out)'),
  feature_38_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 38 (game_total_line)'),
  feature_39_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 39 (days_rest)'),
  feature_40_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 40 (minutes_load_last_7d)'),
  feature_41_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 41 (spread_magnitude)'),
  feature_42_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 42 (implied_team_total)'),
  feature_43_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 43 (points_avg_last_3)'),
  feature_44_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 44 (scoring_trend_slope)'),
  feature_45_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 45 (deviation_from_avg_last3)'),
  feature_46_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 46 (consecutive_games_below_avg)'),
  feature_47_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 47 (teammate_usage_available)'),
  feature_48_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 48 (usage_rate_last_5)'),
  feature_49_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 49 (games_since_structural_change)'),
  feature_50_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 50 (multi_book_line_std)'),
  feature_51_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 51 (prop_over_streak)'),
  feature_52_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 52 (prop_under_streak)'),
  feature_53_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 53 (line_vs_season_avg)'),

  -- Section 4: Per-Feature Sources (54 fields)
  -- Source type for each feature. Direct column access for fast debugging.
  feature_0_source STRING OPTIONS(description='Source for feature 0 (points_avg_last_5): phase4, phase3, calculated, default'),
  feature_1_source STRING OPTIONS(description='Source for feature 1 (points_avg_last_10): phase4, phase3, calculated, default'),
  feature_2_source STRING OPTIONS(description='Source for feature 2 (points_avg_season): phase4, phase3, calculated, default'),
  feature_3_source STRING OPTIONS(description='Source for feature 3 (points_std_last_10): phase4, phase3, calculated, default'),
  feature_4_source STRING OPTIONS(description='Source for feature 4 (games_in_last_7_days): phase4, phase3, calculated, default'),
  feature_5_source STRING OPTIONS(description='Source for feature 5 (fatigue_score - CRITICAL): phase4, phase3, calculated, default'),
  feature_6_source STRING OPTIONS(description='Source for feature 6 (shot_zone_mismatch_score - CRITICAL): phase4, phase3, calculated, default'),
  feature_7_source STRING OPTIONS(description='Source for feature 7 (pace_score - CRITICAL): phase4, phase3, calculated, default'),
  feature_8_source STRING OPTIONS(description='Source for feature 8 (usage_spike_score - CRITICAL): phase4, phase3, calculated, default'),
  feature_9_source STRING OPTIONS(description='Source for feature 9 (rest_advantage): phase4, phase3, calculated, default'),
  feature_10_source STRING OPTIONS(description='Source for feature 10 (injury_risk): phase4, phase3, calculated, default'),
  feature_11_source STRING OPTIONS(description='Source for feature 11 (recent_trend): phase4, phase3, calculated, default'),
  feature_12_source STRING OPTIONS(description='Source for feature 12 (minutes_change): phase4, phase3, calculated, default'),
  feature_13_source STRING OPTIONS(description='Source for feature 13 (opponent_def_rating - CRITICAL): phase4, phase3, calculated, default'),
  feature_14_source STRING OPTIONS(description='Source for feature 14 (opponent_pace - CRITICAL): phase4, phase3, calculated, default'),
  feature_15_source STRING OPTIONS(description='Source for feature 15 (home_away): phase4, phase3, calculated, default'),
  feature_16_source STRING OPTIONS(description='Source for feature 16 (back_to_back): phase4, phase3, calculated, default'),
  feature_17_source STRING OPTIONS(description='Source for feature 17 (playoff_game): phase4, phase3, calculated, default'),
  feature_18_source STRING OPTIONS(description='Source for feature 18 (pct_paint): phase4, phase3, calculated, default'),
  feature_19_source STRING OPTIONS(description='Source for feature 19 (pct_mid_range): phase4, phase3, calculated, default'),
  feature_20_source STRING OPTIONS(description='Source for feature 20 (pct_three): phase4, phase3, calculated, default'),
  feature_21_source STRING OPTIONS(description='Source for feature 21 (pct_free_throw): phase4, phase3, calculated, default'),
  feature_22_source STRING OPTIONS(description='Source for feature 22 (team_pace): phase4, phase3, calculated, default'),
  feature_23_source STRING OPTIONS(description='Source for feature 23 (team_off_rating): phase4, phase3, calculated, default'),
  feature_24_source STRING OPTIONS(description='Source for feature 24 (team_win_pct): phase4, phase3, calculated, default'),
  feature_25_source STRING OPTIONS(description='Source for feature 25 (vegas_points_line): phase4, phase3, calculated, default'),
  feature_26_source STRING OPTIONS(description='Source for feature 26 (vegas_opening_line): phase4, phase3, calculated, default'),
  feature_27_source STRING OPTIONS(description='Source for feature 27 (vegas_line_move): phase4, phase3, calculated, default'),
  feature_28_source STRING OPTIONS(description='Source for feature 28 (has_vegas_line): phase4, phase3, calculated, default'),
  feature_29_source STRING OPTIONS(description='Source for feature 29 (avg_points_vs_opponent): phase4, phase3, calculated, default'),
  feature_30_source STRING OPTIONS(description='Source for feature 30 (games_vs_opponent): phase4, phase3, calculated, default'),
  feature_31_source STRING OPTIONS(description='Source for feature 31 (minutes_avg_last_10): phase4, phase3, calculated, default'),
  feature_32_source STRING OPTIONS(description='Source for feature 32 (ppm_avg_last_10): phase4, phase3, calculated, default'),
  feature_33_source STRING OPTIONS(description='Source for feature 33 (dnp_rate): phase4, phase3, calculated, default'),
  feature_34_source STRING OPTIONS(description='Source for feature 34 (pts_slope_10g): phase4, phase3, calculated, default'),
  feature_35_source STRING OPTIONS(description='Source for feature 35 (pts_vs_season_zscore): phase4, phase3, calculated, default'),
  feature_36_source STRING OPTIONS(description='Source for feature 36 (breakout_flag): phase4, phase3, calculated, default'),
  feature_37_source STRING OPTIONS(description='Source for feature 37 (star_teammates_out): phase4, phase3, calculated, default'),
  feature_38_source STRING OPTIONS(description='Source for feature 38 (game_total_line): phase4, phase3, calculated, default'),
  feature_39_source STRING OPTIONS(description='Source for feature 39 (days_rest): phase4, phase3, calculated, default'),
  feature_40_source STRING OPTIONS(description='Source for feature 40 (minutes_load_last_7d): phase4, phase3, calculated, default'),
  feature_41_source STRING OPTIONS(description='Source for feature 41 (spread_magnitude): phase4, phase3, calculated, default'),
  feature_42_source STRING OPTIONS(description='Source for feature 42 (implied_team_total): phase4, phase3, calculated, default'),
  feature_43_source STRING OPTIONS(description='Source for feature 43 (points_avg_last_3): phase4, phase3, calculated, default'),
  feature_44_source STRING OPTIONS(description='Source for feature 44 (scoring_trend_slope): phase4, phase3, calculated, default'),
  feature_45_source STRING OPTIONS(description='Source for feature 45 (deviation_from_avg_last3): phase4, phase3, calculated, default'),
  feature_46_source STRING OPTIONS(description='Source for feature 46 (consecutive_games_below_avg): phase4, phase3, calculated, default'),
  feature_47_source STRING OPTIONS(description='Source for feature 47 (teammate_usage_available): phase4, phase3, calculated, default'),
  feature_48_source STRING OPTIONS(description='Source for feature 48 (usage_rate_last_5): phase4, phase3, calculated, default'),
  feature_49_source STRING OPTIONS(description='Source for feature 49 (games_since_structural_change): phase4, phase3, calculated, default'),
  feature_50_source STRING OPTIONS(description='Source for feature 50 (multi_book_line_std): phase4, phase3, calculated, default'),
  feature_51_source STRING OPTIONS(description='Source for feature 51 (prop_over_streak): phase4, phase3, calculated, default'),
  feature_52_source STRING OPTIONS(description='Source for feature 52 (prop_under_streak): phase4, phase3, calculated, default'),
  feature_53_source STRING OPTIONS(description='Source for feature 53 (line_vs_season_avg): phase4, phase3, calculated, default'),

  -- Section 4b: Per-Feature Individual Values (54 fields) - Session 235
  -- NULL-able individual columns: NULL = no real data (was a hardcoded default), value = real data.
  -- Enables per-model gating and proper NULL handling (arrays cannot contain NULL).
  feature_0_value FLOAT64 OPTIONS(description='Value for feature 0 (points_avg_last_5). NULL if default.'),
  feature_1_value FLOAT64 OPTIONS(description='Value for feature 1 (points_avg_last_10). NULL if default.'),
  feature_2_value FLOAT64 OPTIONS(description='Value for feature 2 (points_avg_season). NULL if default.'),
  feature_3_value FLOAT64 OPTIONS(description='Value for feature 3 (points_std_last_10). NULL if default.'),
  feature_4_value FLOAT64 OPTIONS(description='Value for feature 4 (games_in_last_7_days). NULL if default.'),
  feature_5_value FLOAT64 OPTIONS(description='Value for feature 5 (fatigue_score). NULL if default.'),
  feature_6_value FLOAT64 OPTIONS(description='Value for feature 6 (shot_zone_mismatch_score). NULL if default.'),
  feature_7_value FLOAT64 OPTIONS(description='Value for feature 7 (pace_score). NULL if default.'),
  feature_8_value FLOAT64 OPTIONS(description='Value for feature 8 (usage_spike_score). NULL if default.'),
  feature_9_value FLOAT64 OPTIONS(description='Value for feature 9 (rest_advantage). NULL if default.'),
  feature_10_value FLOAT64 OPTIONS(description='Value for feature 10 (injury_risk). NULL if default.'),
  feature_11_value FLOAT64 OPTIONS(description='Value for feature 11 (recent_trend). NULL if default.'),
  feature_12_value FLOAT64 OPTIONS(description='Value for feature 12 (minutes_change). NULL if default.'),
  feature_13_value FLOAT64 OPTIONS(description='Value for feature 13 (opponent_def_rating). NULL if default.'),
  feature_14_value FLOAT64 OPTIONS(description='Value for feature 14 (opponent_pace). NULL if default.'),
  feature_15_value FLOAT64 OPTIONS(description='Value for feature 15 (home_away). NULL if default.'),
  feature_16_value FLOAT64 OPTIONS(description='Value for feature 16 (back_to_back). NULL if default.'),
  feature_17_value FLOAT64 OPTIONS(description='Value for feature 17 (playoff_game). NULL if default.'),
  feature_18_value FLOAT64 OPTIONS(description='Value for feature 18 (pct_paint). NULL if default.'),
  feature_19_value FLOAT64 OPTIONS(description='Value for feature 19 (pct_mid_range). NULL if default.'),
  feature_20_value FLOAT64 OPTIONS(description='Value for feature 20 (pct_three). NULL if default.'),
  feature_21_value FLOAT64 OPTIONS(description='Value for feature 21 (pct_free_throw). NULL if default.'),
  feature_22_value FLOAT64 OPTIONS(description='Value for feature 22 (team_pace). NULL if default.'),
  feature_23_value FLOAT64 OPTIONS(description='Value for feature 23 (team_off_rating). NULL if default.'),
  feature_24_value FLOAT64 OPTIONS(description='Value for feature 24 (team_win_pct). NULL if default.'),
  feature_25_value FLOAT64 OPTIONS(description='Value for feature 25 (vegas_points_line). NULL if default/missing.'),
  feature_26_value FLOAT64 OPTIONS(description='Value for feature 26 (vegas_opening_line). NULL if default/missing.'),
  feature_27_value FLOAT64 OPTIONS(description='Value for feature 27 (vegas_line_move). NULL if default/missing.'),
  feature_28_value FLOAT64 OPTIONS(description='Value for feature 28 (has_vegas_line). NULL if default.'),
  feature_29_value FLOAT64 OPTIONS(description='Value for feature 29 (avg_points_vs_opponent). NULL if default.'),
  feature_30_value FLOAT64 OPTIONS(description='Value for feature 30 (games_vs_opponent). NULL if default.'),
  feature_31_value FLOAT64 OPTIONS(description='Value for feature 31 (minutes_avg_last_10). NULL if default.'),
  feature_32_value FLOAT64 OPTIONS(description='Value for feature 32 (ppm_avg_last_10). NULL if default.'),
  feature_33_value FLOAT64 OPTIONS(description='Value for feature 33 (dnp_rate). NULL if default.'),
  feature_34_value FLOAT64 OPTIONS(description='Value for feature 34 (pts_slope_10g). NULL if default.'),
  feature_35_value FLOAT64 OPTIONS(description='Value for feature 35 (pts_vs_season_zscore). NULL if default.'),
  feature_36_value FLOAT64 OPTIONS(description='Value for feature 36 (breakout_flag). NULL if default.'),
  feature_37_value FLOAT64 OPTIONS(description='Value for feature 37 (star_teammates_out). NULL if default.'),
  feature_38_value FLOAT64 OPTIONS(description='Value for feature 38 (game_total_line). NULL if default/missing.'),
  feature_39_value FLOAT64 OPTIONS(description='Value for feature 39 (days_rest). NULL if default.'),
  feature_40_value FLOAT64 OPTIONS(description='Value for feature 40 (minutes_load_last_7d). NULL if default.'),
  feature_41_value FLOAT64 OPTIONS(description='Value for feature 41 (spread_magnitude). NULL if default (dead feature).'),
  feature_42_value FLOAT64 OPTIONS(description='Value for feature 42 (implied_team_total). NULL if default (dead feature).'),
  feature_43_value FLOAT64 OPTIONS(description='Value for feature 43 (points_avg_last_3). NULL if default.'),
  feature_44_value FLOAT64 OPTIONS(description='Value for feature 44 (scoring_trend_slope). NULL if default.'),
  feature_45_value FLOAT64 OPTIONS(description='Value for feature 45 (deviation_from_avg_last3). NULL if default.'),
  feature_46_value FLOAT64 OPTIONS(description='Value for feature 46 (consecutive_games_below_avg). NULL if default.'),
  feature_47_value FLOAT64 OPTIONS(description='Value for feature 47 (teammate_usage_available). NULL (dead feature, always default).'),
  feature_48_value FLOAT64 OPTIONS(description='Value for feature 48 (usage_rate_last_5). NULL if default.'),
  feature_49_value FLOAT64 OPTIONS(description='Value for feature 49 (games_since_structural_change). NULL if default.'),
  feature_50_value FLOAT64 OPTIONS(description='Value for feature 50 (multi_book_line_std). NULL (dead feature, always default).'),
  feature_51_value FLOAT64 OPTIONS(description='Value for feature 51 (prop_over_streak). NULL if default.'),
  feature_52_value FLOAT64 OPTIONS(description='Value for feature 52 (prop_under_streak). NULL if default.'),
  feature_53_value FLOAT64 OPTIONS(description='Value for feature 53 (line_vs_season_avg). NULL if default.'),

  -- Section 5: Per-Feature Details JSON (6 fields)
  -- Additional per-feature attributes as JSON strings. Used for deep investigation (~10% of queries).
  feature_fallback_reasons_json STRING OPTIONS(
    description='JSON map (sparse, only defaulted features): {"5":"composite_factors_missing",...}. Why defaults used.'
  ),
  feature_sample_sizes_json STRING OPTIONS(
    description='JSON map of sample sizes: {"0":5,"1":10,...}. For rolling-window features.'
  ),
  feature_expected_values_json STRING OPTIONS(
    description='JSON map of expected/default values: {"5":0.25,...}. Detect silent calculation failures.'
  ),
  feature_value_ranges_valid_json STRING OPTIONS(
    description='JSON map of range validation: {"0":true,"13":false,...}. TRUE if value within expected range.'
  ),
  feature_upstream_tables_json STRING OPTIONS(
    description='JSON map of upstream tables: {"0":"player_daily_cache","5":"player_composite_factors",...}.'
  ),
  feature_last_updated_json STRING OPTIONS(
    description='JSON map of last_updated timestamps: {"0":"2026-02-06T06:30:00Z",...}. Freshness per feature.'
  ),

  -- Section 6: Model Compatibility (4 fields)
  feature_schema_version STRING OPTIONS(
    description='Feature schema version: v2_33features, v3_37features. Validates model/data compatibility.'
  ),
  available_feature_names ARRAY<STRING> OPTIONS(
    description='List of feature names available in this record. Runtime validation before prediction.'
  ),
  breakout_model_compatible ARRAY<STRING> OPTIONS(
    description='Which breakout model versions this data supports: v2_14features, v3_13features.'
  ),
  breakout_v3_features_available BOOL OPTIONS(
    description='TRUE if V3 breakout features (star_teammate_out, fg_pct_last_game) populated.'
  ),

  -- Section 7: Traceability & Debugging (6 fields)
  upstream_processors_ran STRING OPTIONS(
    description='Comma-separated processors that ran: PlayerCompositeFactorsProcessor,MLFeatureStoreProcessor.'
  ),
  missing_processors STRING OPTIONS(
    description='Expected processors that DID NOT run. E.g. PlayerCompositeFactorsProcessor missing caused matchup defaults.'
  ),
  feature_store_age_hours FLOAT64 OPTIONS(
    description='Hours since feature store computed. For training data filtering: exclude > 48h.'
  ),
  upstream_data_freshness_hours FLOAT64 OPTIONS(
    description='Hours since upstream data (Phase 3/4) updated. Detect stale dependencies.'
  ),
  quality_computed_at TIMESTAMP OPTIONS(
    description='When quality fields computed. Detect stale quality data.'
  ),
  quality_schema_version STRING OPTIONS(
    description='Quality schema version: v1_hybrid_20260205. For handling quality field evolution.'
  ),

  -- Section 8: Legacy Quality Fields (3 fields - keep during 3-month migration)
  feature_sources STRING OPTIONS(
    description='DEPRECATED: Legacy JSON mapping. Use feature_N_source columns instead. Remove after 3 months.'
  ),
  primary_data_source STRING OPTIONS(
    description='DEPRECATED: Use feature_schema_version instead. Remove after 3 months.'
  ),
  matchup_data_status STRING OPTIONS(
    description='DEPRECATED: Use matchup_quality_pct and has_composite_factors instead. Remove after 3 months.'
  )
)
PARTITION BY game_date
CLUSTER BY player_lookup, feature_version, game_date
OPTIONS(
  description="ML feature store with flexible array-based features (v2.0). Includes v4.0 dependency tracking, smart patterns, and Session 134/137 feature quality visibility (120 new + 2 reused = 122 quality fields).",
  require_partition_filter=TRUE
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
-- Total fields: 168 (updated Feb 2026 - Session 134 Quality Visibility)
--   Identifiers: 4
--   Features (array-based): 4
--   Feature metadata: 2
--   Player context: 3
--   Data source: 1
--   Source tracking (Phase 4): 16 (4 fields × 4 sources)
--   Early season: 2
--   Schedule completeness: 14 (4 metrics + 2 readiness + 4 circuit breaker + 4 bootstrap)
--   Historical completeness: 1 (STRUCT with 5 nested fields)
--   Smart idempotency: 1 (data_hash)
--   Processing metadata: 2
--   --- Quality Visibility (Session 134) ---
--   Aggregate quality: 9 new (feature_quality_score + is_production_ready reused from above)
--   Category quality: 18 (5 categories × pct/count + flags + tiers)
--   Per-feature quality: 37 (feature_N_quality columns)
--   Per-feature source: 37 (feature_N_source columns)
--   Per-feature details: 6 (JSON strings for deep investigation)
--   Model compatibility: 4
--   Traceability: 6
--   Legacy quality: 3 (deprecated, remove after 3 months)
--
-- COMPLETENESS TRACKING NOTE:
--   - Schedule completeness (expected_games_count, actual_games_count, etc.):
--       Tracks "Did we get today's games from upstream?"
--   - Historical completeness (historical_completeness STRUCT):
--       Tracks "Did rolling window calculations have all required historical data?"
--       Enables cascade detection: "Which features need reprocessing after a backfill?"
-- ============================================================================

-- ============================================================================
-- MONITORING VIEW: Historical Completeness Summary
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_historical_completeness_daily` AS
SELECT
    game_date,
    COUNT(*) as total_features,
    COUNTIF(historical_completeness.is_complete) as complete_count,
    COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) as incomplete_count,
    COUNTIF(historical_completeness.is_bootstrap) as bootstrap_count,
    ROUND(COUNTIF(historical_completeness.is_complete) / COUNT(*) * 100, 1) as complete_pct,
    ROUND(COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) / COUNT(*) * 100, 1) as incomplete_pct,
    AVG(historical_completeness.games_found) as avg_games_found,
    AVG(historical_completeness.games_expected) as avg_games_expected
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND historical_completeness IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC;

-- ============================================================================
-- MONITORING VIEW: Incomplete Features (Not Bootstrap) - For Investigation
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_incomplete_features` AS
SELECT
    game_date,
    player_lookup,
    historical_completeness.games_found,
    historical_completeness.games_expected,
    historical_completeness.games_expected - historical_completeness.games_found as games_missing,
    historical_completeness.contributing_game_dates
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE NOT historical_completeness.is_complete
  AND NOT historical_completeness.is_bootstrap
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY game_date DESC, games_missing DESC;

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

-- Step 3: Add historical completeness column (Data Cascade Architecture - Jan 2026)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS historical_completeness STRUCT<
    games_found INT64 OPTIONS (description='Actual games found in rolling window'),
    games_expected INT64 OPTIONS (description='Expected games (min of available, window_size=10)'),
    is_complete BOOL OPTIONS (description='games_found >= games_expected'),
    is_bootstrap BOOL OPTIONS (description='games_expected < 10 (player has limited history)'),
    contributing_game_dates ARRAY<DATE> OPTIONS (description='Dates of games used for cascade detection')
>
OPTIONS (description='Historical completeness tracking for rolling window calculations. Enables cascade detection after backfills.');

-- Step 4: Add feature quality visibility columns (Session 134)
-- Aggregate quality (9 new fields - feature_quality_score and is_production_ready already exist)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS quality_tier STRING
  OPTIONS (description='Overall tier: gold (>95), silver (85-95), bronze (70-85), poor (50-70), critical (<50)'),
ADD COLUMN IF NOT EXISTS quality_alert_level STRING
  OPTIONS (description='Alert priority: green (healthy), yellow (degraded), red (critical)'),
ADD COLUMN IF NOT EXISTS quality_alerts ARRAY<STRING>
  OPTIONS (description='Specific alerts triggered'),
ADD COLUMN IF NOT EXISTS default_feature_count INT64
  OPTIONS (description='Total count of features using defaults'),
ADD COLUMN IF NOT EXISTS phase4_feature_count INT64
  OPTIONS (description='Count of features from Phase 4 precompute'),
ADD COLUMN IF NOT EXISTS phase3_feature_count INT64
  OPTIONS (description='Count of features from Phase 3 analytics'),
ADD COLUMN IF NOT EXISTS calculated_feature_count INT64
  OPTIONS (description='Count of features calculated on-the-fly'),
ADD COLUMN IF NOT EXISTS is_training_ready BOOL
  OPTIONS (description='TRUE if meets training quality bar'),
ADD COLUMN IF NOT EXISTS training_quality_feature_count INT64
  OPTIONS (description='Count of features meeting training quality bar'),
ADD COLUMN IF NOT EXISTS is_quality_ready BOOL
  OPTIONS (description='TRUE if meets quality gate: quality_tier in (gold, silver, bronze) AND score >= 70 AND matchup >= 50'),
ADD COLUMN IF NOT EXISTS default_feature_indices ARRAY<INT64>
  OPTIONS (description='Session 142: Indices of features using default/fallback values (empty = all real data)');

-- Category quality (18 fields)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS matchup_quality_pct FLOAT64
  OPTIONS (description='Quality % for matchup features (5-8, 13-14)'),
ADD COLUMN IF NOT EXISTS player_history_quality_pct FLOAT64
  OPTIONS (description='Quality % for player history features (0-4, 29-36). 13 features.'),
ADD COLUMN IF NOT EXISTS team_context_quality_pct FLOAT64
  OPTIONS (description='Quality % for team context features (22-24)'),
ADD COLUMN IF NOT EXISTS vegas_quality_pct FLOAT64
  OPTIONS (description='Quality % for vegas features (25-28)'),
ADD COLUMN IF NOT EXISTS game_context_quality_pct FLOAT64
  OPTIONS (description='Quality % for game context features (9-12, 15-21). 11 features.'),
ADD COLUMN IF NOT EXISTS matchup_default_count INT64
  OPTIONS (description='Count of matchup features using defaults'),
ADD COLUMN IF NOT EXISTS player_history_default_count INT64
  OPTIONS (description='Count of player history features using defaults'),
ADD COLUMN IF NOT EXISTS team_context_default_count INT64
  OPTIONS (description='Count of team context features using defaults'),
ADD COLUMN IF NOT EXISTS vegas_default_count INT64
  OPTIONS (description='Count of vegas features using defaults'),
ADD COLUMN IF NOT EXISTS game_context_default_count INT64
  OPTIONS (description='Count of game context features using defaults'),
ADD COLUMN IF NOT EXISTS has_composite_factors BOOL
  OPTIONS (description='TRUE if composite factors (features 5-8) available'),
ADD COLUMN IF NOT EXISTS has_opponent_defense BOOL
  OPTIONS (description='TRUE if opponent defense data (features 13-14) available'),
ADD COLUMN IF NOT EXISTS has_vegas_line BOOL
  OPTIONS (description='TRUE if vegas line available'),
ADD COLUMN IF NOT EXISTS critical_features_training_quality BOOL
  OPTIONS (description='TRUE if ALL critical features meet training quality bar'),
ADD COLUMN IF NOT EXISTS critical_feature_count INT64
  OPTIONS (description='Count of critical features present with high quality'),
ADD COLUMN IF NOT EXISTS optional_feature_count INT64
  OPTIONS (description='Count of optional features present'),
ADD COLUMN IF NOT EXISTS matchup_quality_tier STRING
  OPTIONS (description='Matchup category tier'),
ADD COLUMN IF NOT EXISTS game_context_quality_tier STRING
  OPTIONS (description='Game context category tier');

-- Per-feature quality scores (54 fields)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_0_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 0 (points_avg_last_5)'),
ADD COLUMN IF NOT EXISTS feature_1_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 1 (points_avg_last_10)'),
ADD COLUMN IF NOT EXISTS feature_2_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 2 (points_avg_season)'),
ADD COLUMN IF NOT EXISTS feature_3_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 3 (points_std_last_10)'),
ADD COLUMN IF NOT EXISTS feature_4_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 4 (games_in_last_7_days)'),
ADD COLUMN IF NOT EXISTS feature_5_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 5 (fatigue_score - CRITICAL)'),
ADD COLUMN IF NOT EXISTS feature_6_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 6 (shot_zone_mismatch_score - CRITICAL)'),
ADD COLUMN IF NOT EXISTS feature_7_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 7 (pace_score - CRITICAL)'),
ADD COLUMN IF NOT EXISTS feature_8_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 8 (usage_spike_score - CRITICAL)'),
ADD COLUMN IF NOT EXISTS feature_9_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 9 (rest_advantage)'),
ADD COLUMN IF NOT EXISTS feature_10_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 10 (injury_risk)'),
ADD COLUMN IF NOT EXISTS feature_11_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 11 (recent_trend)'),
ADD COLUMN IF NOT EXISTS feature_12_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 12 (minutes_change)'),
ADD COLUMN IF NOT EXISTS feature_13_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 13 (opponent_def_rating - CRITICAL)'),
ADD COLUMN IF NOT EXISTS feature_14_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 14 (opponent_pace - CRITICAL)'),
ADD COLUMN IF NOT EXISTS feature_15_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 15 (home_away)'),
ADD COLUMN IF NOT EXISTS feature_16_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 16 (back_to_back)'),
ADD COLUMN IF NOT EXISTS feature_17_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 17 (playoff_game)'),
ADD COLUMN IF NOT EXISTS feature_18_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 18 (pct_paint)'),
ADD COLUMN IF NOT EXISTS feature_19_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 19 (pct_mid_range)'),
ADD COLUMN IF NOT EXISTS feature_20_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 20 (pct_three)'),
ADD COLUMN IF NOT EXISTS feature_21_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 21 (pct_free_throw)'),
ADD COLUMN IF NOT EXISTS feature_22_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 22 (team_pace)'),
ADD COLUMN IF NOT EXISTS feature_23_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 23 (team_off_rating)'),
ADD COLUMN IF NOT EXISTS feature_24_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 24 (team_win_pct)'),
ADD COLUMN IF NOT EXISTS feature_25_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 25 (vegas_points_line)'),
ADD COLUMN IF NOT EXISTS feature_26_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 26 (vegas_opening_line)'),
ADD COLUMN IF NOT EXISTS feature_27_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 27 (vegas_line_move)'),
ADD COLUMN IF NOT EXISTS feature_28_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 28 (has_vegas_line)'),
ADD COLUMN IF NOT EXISTS feature_29_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 29 (avg_points_vs_opponent)'),
ADD COLUMN IF NOT EXISTS feature_30_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 30 (games_vs_opponent)'),
ADD COLUMN IF NOT EXISTS feature_31_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 31 (minutes_avg_last_10)'),
ADD COLUMN IF NOT EXISTS feature_32_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 32 (ppm_avg_last_10)'),
ADD COLUMN IF NOT EXISTS feature_33_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 33 (dnp_rate)'),
ADD COLUMN IF NOT EXISTS feature_34_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 34 (pts_slope_10g)'),
ADD COLUMN IF NOT EXISTS feature_35_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 35 (pts_vs_season_zscore)'),
ADD COLUMN IF NOT EXISTS feature_36_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 36 (breakout_flag)'),
ADD COLUMN IF NOT EXISTS feature_37_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 37 (star_teammates_out)'),
ADD COLUMN IF NOT EXISTS feature_38_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 38 (game_total_line)'),
ADD COLUMN IF NOT EXISTS feature_39_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 39 (days_rest)'),
ADD COLUMN IF NOT EXISTS feature_40_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 40 (minutes_load_last_7d)'),
ADD COLUMN IF NOT EXISTS feature_41_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 41 (spread_magnitude)'),
ADD COLUMN IF NOT EXISTS feature_42_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 42 (implied_team_total)'),
ADD COLUMN IF NOT EXISTS feature_43_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 43 (points_avg_last_3)'),
ADD COLUMN IF NOT EXISTS feature_44_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 44 (scoring_trend_slope)'),
ADD COLUMN IF NOT EXISTS feature_45_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 45 (deviation_from_avg_last3)'),
ADD COLUMN IF NOT EXISTS feature_46_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 46 (consecutive_games_below_avg)'),
ADD COLUMN IF NOT EXISTS feature_47_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 47 (teammate_usage_available)'),
ADD COLUMN IF NOT EXISTS feature_48_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 48 (usage_rate_last_5)'),
ADD COLUMN IF NOT EXISTS feature_49_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 49 (games_since_structural_change)'),
ADD COLUMN IF NOT EXISTS feature_50_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 50 (multi_book_line_std)'),
ADD COLUMN IF NOT EXISTS feature_51_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 51 (prop_over_streak)'),
ADD COLUMN IF NOT EXISTS feature_52_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 52 (prop_under_streak)'),
ADD COLUMN IF NOT EXISTS feature_53_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 53 (line_vs_season_avg)');

-- Per-feature sources (54 fields)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_0_source STRING OPTIONS (description='Source for feature 0 (points_avg_last_5): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_1_source STRING OPTIONS (description='Source for feature 1 (points_avg_last_10): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_2_source STRING OPTIONS (description='Source for feature 2 (points_avg_season): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_3_source STRING OPTIONS (description='Source for feature 3 (points_std_last_10): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_4_source STRING OPTIONS (description='Source for feature 4 (games_in_last_7_days): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_5_source STRING OPTIONS (description='Source for feature 5 (fatigue_score - CRITICAL): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_6_source STRING OPTIONS (description='Source for feature 6 (shot_zone_mismatch_score - CRITICAL): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_7_source STRING OPTIONS (description='Source for feature 7 (pace_score - CRITICAL): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_8_source STRING OPTIONS (description='Source for feature 8 (usage_spike_score - CRITICAL): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_9_source STRING OPTIONS (description='Source for feature 9 (rest_advantage): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_10_source STRING OPTIONS (description='Source for feature 10 (injury_risk): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_11_source STRING OPTIONS (description='Source for feature 11 (recent_trend): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_12_source STRING OPTIONS (description='Source for feature 12 (minutes_change): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_13_source STRING OPTIONS (description='Source for feature 13 (opponent_def_rating - CRITICAL): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_14_source STRING OPTIONS (description='Source for feature 14 (opponent_pace - CRITICAL): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_15_source STRING OPTIONS (description='Source for feature 15 (home_away): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_16_source STRING OPTIONS (description='Source for feature 16 (back_to_back): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_17_source STRING OPTIONS (description='Source for feature 17 (playoff_game): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_18_source STRING OPTIONS (description='Source for feature 18 (pct_paint): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_19_source STRING OPTIONS (description='Source for feature 19 (pct_mid_range): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_20_source STRING OPTIONS (description='Source for feature 20 (pct_three): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_21_source STRING OPTIONS (description='Source for feature 21 (pct_free_throw): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_22_source STRING OPTIONS (description='Source for feature 22 (team_pace): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_23_source STRING OPTIONS (description='Source for feature 23 (team_off_rating): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_24_source STRING OPTIONS (description='Source for feature 24 (team_win_pct): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_25_source STRING OPTIONS (description='Source for feature 25 (vegas_points_line): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_26_source STRING OPTIONS (description='Source for feature 26 (vegas_opening_line): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_27_source STRING OPTIONS (description='Source for feature 27 (vegas_line_move): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_28_source STRING OPTIONS (description='Source for feature 28 (has_vegas_line): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_29_source STRING OPTIONS (description='Source for feature 29 (avg_points_vs_opponent): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_30_source STRING OPTIONS (description='Source for feature 30 (games_vs_opponent): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_31_source STRING OPTIONS (description='Source for feature 31 (minutes_avg_last_10): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_32_source STRING OPTIONS (description='Source for feature 32 (ppm_avg_last_10): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_33_source STRING OPTIONS (description='Source for feature 33 (dnp_rate): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_34_source STRING OPTIONS (description='Source for feature 34 (pts_slope_10g): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_35_source STRING OPTIONS (description='Source for feature 35 (pts_vs_season_zscore): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_36_source STRING OPTIONS (description='Source for feature 36 (breakout_flag): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_37_source STRING OPTIONS (description='Source for feature 37 (star_teammates_out): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_38_source STRING OPTIONS (description='Source for feature 38 (game_total_line): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_39_source STRING OPTIONS (description='Source for feature 39 (days_rest): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_40_source STRING OPTIONS (description='Source for feature 40 (minutes_load_last_7d): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_41_source STRING OPTIONS (description='Source for feature 41 (spread_magnitude): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_42_source STRING OPTIONS (description='Source for feature 42 (implied_team_total): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_43_source STRING OPTIONS (description='Source for feature 43 (points_avg_last_3): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_44_source STRING OPTIONS (description='Source for feature 44 (scoring_trend_slope): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_45_source STRING OPTIONS (description='Source for feature 45 (deviation_from_avg_last3): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_46_source STRING OPTIONS (description='Source for feature 46 (consecutive_games_below_avg): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_47_source STRING OPTIONS (description='Source for feature 47 (teammate_usage_available): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_48_source STRING OPTIONS (description='Source for feature 48 (usage_rate_last_5): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_49_source STRING OPTIONS (description='Source for feature 49 (games_since_structural_change): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_50_source STRING OPTIONS (description='Source for feature 50 (multi_book_line_std): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_51_source STRING OPTIONS (description='Source for feature 51 (prop_over_streak): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_52_source STRING OPTIONS (description='Source for feature 52 (prop_under_streak): phase4, phase3, calculated, default'),
ADD COLUMN IF NOT EXISTS feature_53_source STRING OPTIONS (description='Source for feature 53 (line_vs_season_avg): phase4, phase3, calculated, default');

-- Per-feature details JSON (6 fields)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_fallback_reasons_json STRING
  OPTIONS (description='JSON map (sparse): why defaults used per feature'),
ADD COLUMN IF NOT EXISTS feature_sample_sizes_json STRING
  OPTIONS (description='JSON map: sample sizes for rolling-window features'),
ADD COLUMN IF NOT EXISTS feature_expected_values_json STRING
  OPTIONS (description='JSON map: expected/default values per feature'),
ADD COLUMN IF NOT EXISTS feature_value_ranges_valid_json STRING
  OPTIONS (description='JSON map: TRUE if value within expected range per feature'),
ADD COLUMN IF NOT EXISTS feature_upstream_tables_json STRING
  OPTIONS (description='JSON map: source table per feature'),
ADD COLUMN IF NOT EXISTS feature_last_updated_json STRING
  OPTIONS (description='JSON map: last_updated timestamps per feature');

-- Model compatibility (4 fields)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_schema_version STRING
  OPTIONS (description='Feature schema version: v2_33features, v3_37features'),
ADD COLUMN IF NOT EXISTS available_feature_names ARRAY<STRING>
  OPTIONS (description='List of feature names available in this record'),
ADD COLUMN IF NOT EXISTS breakout_model_compatible ARRAY<STRING>
  OPTIONS (description='Which breakout model versions this data supports'),
ADD COLUMN IF NOT EXISTS breakout_v3_features_available BOOL
  OPTIONS (description='TRUE if V3 breakout features populated');

-- Traceability (6 fields)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS upstream_processors_ran STRING
  OPTIONS (description='Comma-separated processors that ran for this date'),
ADD COLUMN IF NOT EXISTS missing_processors STRING
  OPTIONS (description='Expected processors that DID NOT run'),
ADD COLUMN IF NOT EXISTS feature_store_age_hours FLOAT64
  OPTIONS (description='Hours since feature store computed'),
ADD COLUMN IF NOT EXISTS upstream_data_freshness_hours FLOAT64
  OPTIONS (description='Hours since upstream data updated'),
ADD COLUMN IF NOT EXISTS quality_computed_at TIMESTAMP
  OPTIONS (description='When quality fields computed'),
ADD COLUMN IF NOT EXISTS quality_schema_version STRING
  OPTIONS (description='Quality schema version: v1_hybrid_20260205');

-- Legacy quality fields (3 fields - keep during 3-month migration)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_sources STRING
  OPTIONS (description='DEPRECATED: Legacy JSON mapping. Use feature_N_source columns. Remove after 3 months.'),
ADD COLUMN IF NOT EXISTS primary_data_source STRING
  OPTIONS (description='DEPRECATED: Use feature_schema_version. Remove after 3 months.'),
ADD COLUMN IF NOT EXISTS matchup_data_status STRING
  OPTIONS (description='DEPRECATED: Use matchup_quality_pct and has_composite_factors. Remove after 3 months.');

-- Session 146: Cache miss tracking
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS cache_miss_fallback_used BOOL
  OPTIONS (description='Session 146: TRUE if player_daily_cache had no entry and features were computed from last_10_games fallback. Use to investigate cache coverage gaps.');

-- Session 152: Vegas line source tracking
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS vegas_line_source STRING
  OPTIONS (description='Session 152: Which scraper source provided ML features 25-28. Values: odds_api, bettingpros, both, none. NULL for pre-Session-152 data.');

-- Session 235: Individual feature value columns (NULL-able, no fake defaults)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_0_value FLOAT64 OPTIONS (description='Value for feature 0 (points_avg_last_5). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_1_value FLOAT64 OPTIONS (description='Value for feature 1 (points_avg_last_10). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_2_value FLOAT64 OPTIONS (description='Value for feature 2 (points_avg_season). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_3_value FLOAT64 OPTIONS (description='Value for feature 3 (points_std_last_10). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_4_value FLOAT64 OPTIONS (description='Value for feature 4 (games_in_last_7_days). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_5_value FLOAT64 OPTIONS (description='Value for feature 5 (fatigue_score). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_6_value FLOAT64 OPTIONS (description='Value for feature 6 (shot_zone_mismatch_score). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_7_value FLOAT64 OPTIONS (description='Value for feature 7 (pace_score). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_8_value FLOAT64 OPTIONS (description='Value for feature 8 (usage_spike_score). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_9_value FLOAT64 OPTIONS (description='Value for feature 9 (rest_advantage). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_10_value FLOAT64 OPTIONS (description='Value for feature 10 (injury_risk). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_11_value FLOAT64 OPTIONS (description='Value for feature 11 (recent_trend). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_12_value FLOAT64 OPTIONS (description='Value for feature 12 (minutes_change). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_13_value FLOAT64 OPTIONS (description='Value for feature 13 (opponent_def_rating). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_14_value FLOAT64 OPTIONS (description='Value for feature 14 (opponent_pace). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_15_value FLOAT64 OPTIONS (description='Value for feature 15 (home_away). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_16_value FLOAT64 OPTIONS (description='Value for feature 16 (back_to_back). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_17_value FLOAT64 OPTIONS (description='Value for feature 17 (playoff_game). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_18_value FLOAT64 OPTIONS (description='Value for feature 18 (pct_paint). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_19_value FLOAT64 OPTIONS (description='Value for feature 19 (pct_mid_range). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_20_value FLOAT64 OPTIONS (description='Value for feature 20 (pct_three). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_21_value FLOAT64 OPTIONS (description='Value for feature 21 (pct_free_throw). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_22_value FLOAT64 OPTIONS (description='Value for feature 22 (team_pace). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_23_value FLOAT64 OPTIONS (description='Value for feature 23 (team_off_rating). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_24_value FLOAT64 OPTIONS (description='Value for feature 24 (team_win_pct). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_25_value FLOAT64 OPTIONS (description='Value for feature 25 (vegas_points_line). NULL if default/missing.'),
ADD COLUMN IF NOT EXISTS feature_26_value FLOAT64 OPTIONS (description='Value for feature 26 (vegas_opening_line). NULL if default/missing.'),
ADD COLUMN IF NOT EXISTS feature_27_value FLOAT64 OPTIONS (description='Value for feature 27 (vegas_line_move). NULL if default/missing.'),
ADD COLUMN IF NOT EXISTS feature_28_value FLOAT64 OPTIONS (description='Value for feature 28 (has_vegas_line). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_29_value FLOAT64 OPTIONS (description='Value for feature 29 (avg_points_vs_opponent). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_30_value FLOAT64 OPTIONS (description='Value for feature 30 (games_vs_opponent). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_31_value FLOAT64 OPTIONS (description='Value for feature 31 (minutes_avg_last_10). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_32_value FLOAT64 OPTIONS (description='Value for feature 32 (ppm_avg_last_10). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_33_value FLOAT64 OPTIONS (description='Value for feature 33 (dnp_rate). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_34_value FLOAT64 OPTIONS (description='Value for feature 34 (pts_slope_10g). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_35_value FLOAT64 OPTIONS (description='Value for feature 35 (pts_vs_season_zscore). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_36_value FLOAT64 OPTIONS (description='Value for feature 36 (breakout_flag). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_37_value FLOAT64 OPTIONS (description='Value for feature 37 (star_teammates_out). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_38_value FLOAT64 OPTIONS (description='Value for feature 38 (game_total_line). NULL if default/missing.'),
ADD COLUMN IF NOT EXISTS feature_39_value FLOAT64 OPTIONS (description='Value for feature 39 (days_rest). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_40_value FLOAT64 OPTIONS (description='Value for feature 40 (minutes_load_last_7d). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_41_value FLOAT64 OPTIONS (description='Value for feature 41 (spread_magnitude). NULL if default (dead feature).'),
ADD COLUMN IF NOT EXISTS feature_42_value FLOAT64 OPTIONS (description='Value for feature 42 (implied_team_total). NULL if default (dead feature).'),
ADD COLUMN IF NOT EXISTS feature_43_value FLOAT64 OPTIONS (description='Value for feature 43 (points_avg_last_3). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_44_value FLOAT64 OPTIONS (description='Value for feature 44 (scoring_trend_slope). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_45_value FLOAT64 OPTIONS (description='Value for feature 45 (deviation_from_avg_last3). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_46_value FLOAT64 OPTIONS (description='Value for feature 46 (consecutive_games_below_avg). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_47_value FLOAT64 OPTIONS (description='Value for feature 47 (teammate_usage_available). NULL (dead feature).'),
ADD COLUMN IF NOT EXISTS feature_48_value FLOAT64 OPTIONS (description='Value for feature 48 (usage_rate_last_5). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_49_value FLOAT64 OPTIONS (description='Value for feature 49 (games_since_structural_change). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_50_value FLOAT64 OPTIONS (description='Value for feature 50 (multi_book_line_std). NULL (dead feature).'),
ADD COLUMN IF NOT EXISTS feature_51_value FLOAT64 OPTIONS (description='Value for feature 51 (prop_over_streak). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_52_value FLOAT64 OPTIONS (description='Value for feature 52 (prop_under_streak). NULL if default.'),
ADD COLUMN IF NOT EXISTS feature_53_value FLOAT64 OPTIONS (description='Value for feature 53 (line_vs_season_avg). NULL if default.');

-- ============================================================================
-- MONITORING VIEW: Feature Quality Unpivot (Session 134)
-- Unpivots 37 per-feature quality/source columns into rows for easy aggregation.
-- ============================================================================
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_feature_quality_unpivot` AS
SELECT player_lookup, game_date, 0 as feature_index, 'points_avg_last_5' as feature_name, feature_0_quality as quality, feature_0_source as source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 1, 'points_avg_last_10', feature_1_quality, feature_1_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 2, 'points_avg_season', feature_2_quality, feature_2_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 3, 'points_std_last_10', feature_3_quality, feature_3_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 4, 'games_in_last_7_days', feature_4_quality, feature_4_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 5, 'fatigue_score', feature_5_quality, feature_5_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 6, 'shot_zone_mismatch_score', feature_6_quality, feature_6_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 7, 'pace_score', feature_7_quality, feature_7_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 8, 'usage_spike_score', feature_8_quality, feature_8_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 9, 'rest_advantage', feature_9_quality, feature_9_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 10, 'injury_risk', feature_10_quality, feature_10_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 11, 'recent_trend', feature_11_quality, feature_11_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 12, 'minutes_change', feature_12_quality, feature_12_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 13, 'opponent_def_rating', feature_13_quality, feature_13_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 14, 'opponent_pace', feature_14_quality, feature_14_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 15, 'home_away', feature_15_quality, feature_15_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 16, 'back_to_back', feature_16_quality, feature_16_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 17, 'playoff_game', feature_17_quality, feature_17_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 18, 'pct_paint', feature_18_quality, feature_18_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 19, 'pct_mid_range', feature_19_quality, feature_19_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 20, 'pct_three', feature_20_quality, feature_20_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 21, 'pct_free_throw', feature_21_quality, feature_21_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 22, 'team_pace', feature_22_quality, feature_22_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 23, 'team_off_rating', feature_23_quality, feature_23_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 24, 'team_win_pct', feature_24_quality, feature_24_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 25, 'vegas_points_line', feature_25_quality, feature_25_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 26, 'vegas_opening_line', feature_26_quality, feature_26_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 27, 'vegas_line_move', feature_27_quality, feature_27_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 28, 'has_vegas_line', feature_28_quality, feature_28_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 29, 'avg_points_vs_opponent', feature_29_quality, feature_29_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 30, 'games_vs_opponent', feature_30_quality, feature_30_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 31, 'minutes_avg_last_10', feature_31_quality, feature_31_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 32, 'ppm_avg_last_10', feature_32_quality, feature_32_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 33, 'dnp_rate', feature_33_quality, feature_33_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 34, 'pts_slope_10g', feature_34_quality, feature_34_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 35, 'pts_vs_season_zscore', feature_35_quality, feature_35_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
UNION ALL SELECT player_lookup, game_date, 36, 'breakout_flag', feature_36_quality, feature_36_source FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Example: Find worst quality features across all players for a date
-- SELECT feature_name, AVG(quality) as avg_quality, COUNTIF(source = 'default') as default_count
-- FROM `nba-props-platform.nba_predictions.v_feature_quality_unpivot`
-- WHERE game_date = CURRENT_DATE()
-- GROUP BY feature_name
-- ORDER BY avg_quality ASC;

-- ============================================================================