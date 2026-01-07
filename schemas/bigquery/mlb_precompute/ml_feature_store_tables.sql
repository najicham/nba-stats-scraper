-- ============================================================================
-- MLB Props Platform - ML Feature Store Tables
-- Pre-computed features for strikeout prediction models
-- File: schemas/bigquery/mlb_precompute/ml_feature_store_tables.sql
-- ============================================================================
--
-- PHASE 4 PRECOMPUTE PROCESSOR
-- Computes and caches ML features for fast prediction serving
--
-- Features Vector (35 dimensions - V2):
-- 0-4:   Recent performance (last 3/5/10 games)
-- 5-9:   Season baseline stats
-- 10-14: Split adjustments (home/away, day/night)
-- 15-19: Matchup context (opponent K rate, ballpark)
-- 20-24: Workload/fatigue indicators
-- 25-29: V1 MLB-specific (bottom-up K, platoon, umpire, innings)
-- 30-34: V2 Advanced metrics (velocity, whiff, put-away, weak spots, edge)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_precompute.pitcher_ml_features` (
  -- ============================================================================
  -- IDENTIFIERS
  -- ============================================================================
  player_lookup STRING NOT NULL,              -- Pitcher identifier
  game_date DATE NOT NULL,                    -- Date of prediction
  game_id STRING NOT NULL,                    -- Game identifier
  opponent_team_abbr STRING NOT NULL,         -- Opponent team
  season_year INT64 NOT NULL,

  -- ============================================================================
  -- FEATURE VECTOR (25 features)
  -- ============================================================================
  -- Recent Performance (0-4)
  f00_k_avg_last_3 NUMERIC(6,3),              -- Strikeouts avg last 3 games
  f01_k_avg_last_5 NUMERIC(6,3),              -- Strikeouts avg last 5 games
  f02_k_avg_last_10 NUMERIC(6,3),             -- Strikeouts avg last 10 games
  f03_k_std_last_10 NUMERIC(6,3),             -- Strikeouts std dev last 10 (consistency)
  f04_ip_avg_last_5 NUMERIC(6,3),             -- Innings avg last 5 (workload proxy)

  -- Season Baseline (5-9)
  f05_season_k_per_9 NUMERIC(6,3),            -- Season K/9 rate
  f06_season_era NUMERIC(6,3),                -- Season ERA
  f07_season_whip NUMERIC(6,3),               -- Season WHIP
  f08_season_games INT64,                     -- Games started this season
  f09_season_k_total INT64,                   -- Season total strikeouts

  -- Split Adjustments (10-14)
  f10_is_home NUMERIC(6,3),                   -- 1.0 = home, 0.0 = away
  f11_home_away_k_diff NUMERIC(6,3),          -- Home K/9 minus Away K/9
  f12_is_day_game NUMERIC(6,3),               -- 1.0 = day, 0.0 = night
  f13_day_night_k_diff NUMERIC(6,3),          -- Day K/9 minus Night K/9
  f14_vs_opponent_k_rate NUMERIC(6,3),        -- Historical K rate vs this opponent

  -- Matchup Context (15-19)
  f15_opponent_team_k_rate NUMERIC(6,3),      -- How often opponent Ks (league relative)
  f16_opponent_obp NUMERIC(6,3),              -- Opponent on-base percentage
  f17_ballpark_k_factor NUMERIC(6,3),         -- Ballpark effect on Ks
  f18_game_total_line NUMERIC(6,3),           -- Vegas game total (scoring environment)
  f19_team_implied_runs NUMERIC(6,3),         -- Team implied runs (game script proxy)

  -- Workload/Fatigue (20-24)
  f20_days_rest INT64,                        -- Days since last start
  f21_games_last_30_days INT64,               -- Workload indicator
  f22_pitch_count_avg NUMERIC(6,3),           -- Average pitch count (fatigue)
  f23_season_ip_total NUMERIC(6,3),           -- Season workload
  f24_is_postseason NUMERIC(6,3),             -- 1.0 = postseason, 0.0 = regular

  -- V1 Features: MLB-Specific (25-29)
  f25_bottom_up_k_expected NUMERIC(6,3),      -- THE KEY: Sum of batter K probs
  f26_lineup_k_vs_hand NUMERIC(6,4),          -- Lineup K rate vs pitcher's hand
  f27_platoon_advantage NUMERIC(6,4),         -- Platoon advantage (+/-)
  f28_umpire_k_factor NUMERIC(6,3),           -- Umpire K adjustment (+/-)
  f29_projected_innings NUMERIC(6,3),         -- Expected IP

  -- V2 Features: Advanced Metrics (30-34)
  f30_velocity_trend NUMERIC(6,3),            -- Velocity change from baseline
  f31_whiff_rate NUMERIC(6,4),                -- Overall swing-and-miss rate
  f32_put_away_rate NUMERIC(6,4),             -- K rate with 2 strikes
  f33_lineup_weak_spots NUMERIC(6,3),         -- Count of high-K batters
  f34_matchup_edge NUMERIC(6,3),              -- Composite advantage (-3 to +3)

  -- ============================================================================
  -- FEATURE ARRAY (for model input)
  -- ============================================================================
  feature_vector ARRAY<FLOAT64>,              -- All 35 features as array

  -- ============================================================================
  -- TARGET VARIABLE (for training data)
  -- ============================================================================
  actual_strikeouts INT64,                    -- Actual strikeouts (NULL for predictions)
  strikeouts_line NUMERIC(4,1),               -- Betting line
  bottom_up_k_expected NUMERIC(6,3),          -- Legacy field (same as f25)

  -- ============================================================================
  -- GRADING SUPPORT (for rate-adjusted evaluation)
  -- ============================================================================
  actual_innings NUMERIC(6,3),                -- Actual IP pitched
  actual_k_per_9 NUMERIC(6,3),                -- Actual K/9 rate

  -- ============================================================================
  -- METADATA
  -- ============================================================================
  feature_version STRING NOT NULL,            -- Feature engineering version
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, season_year
OPTIONS (
  description = "MLB pitcher ML features for strikeout prediction. 35-dimension feature vector (V2) with MLB-specific bottom-up model features.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Training data (historical with actuals)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_precompute.pitcher_training_data` AS
SELECT
  player_lookup,
  game_date,
  feature_vector,
  actual_strikeouts,
  strikeouts_line,
  actual_innings,
  actual_k_per_9
FROM `nba-props-platform.mlb_precompute.pitcher_ml_features`
WHERE actual_strikeouts IS NOT NULL
  AND ARRAY_LENGTH(feature_vector) IN (25, 35)  -- Support both V1 and V2
ORDER BY game_date DESC;

-- Prediction features (today's games)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_precompute.pitcher_prediction_features` AS
SELECT
  player_lookup,
  game_id,
  opponent_team_abbr,
  feature_vector,
  strikeouts_line,
  f01_k_avg_last_5,
  f05_season_k_per_9,
  f10_is_home,
  f15_opponent_team_k_rate,
  f25_bottom_up_k_expected,
  f29_projected_innings,
  f31_whiff_rate,
  f34_matchup_edge
FROM `nba-props-platform.mlb_precompute.pitcher_ml_features`
WHERE game_date = CURRENT_DATE()
  AND actual_strikeouts IS NULL;

-- Feature quality monitoring
CREATE OR REPLACE VIEW `nba-props-platform.mlb_precompute.pitcher_feature_quality` AS
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNT(CASE WHEN ARRAY_LENGTH(feature_vector) = 35 THEN 1 END) as v2_features,
  COUNT(CASE WHEN ARRAY_LENGTH(feature_vector) = 25 THEN 1 END) as v1_features,
  AVG(f01_k_avg_last_5) as avg_recent_k,
  AVG(f25_bottom_up_k_expected) as avg_bottom_up_k,
  COUNT(CASE WHEN f14_vs_opponent_k_rate IS NOT NULL THEN 1 END) as has_opponent_history,
  COUNT(CASE WHEN f31_whiff_rate > 0 THEN 1 END) as has_arsenal_data
FROM `nba-props-platform.mlb_precompute.pitcher_ml_features`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
