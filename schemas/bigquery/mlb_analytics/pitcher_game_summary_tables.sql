-- ============================================================================
-- MLB Props Platform - Pitcher Game Summary Analytics Table
-- Complete pitcher performance with rolling stats and split adjustments
-- File: schemas/bigquery/mlb_analytics/pitcher_game_summary_tables.sql
-- ============================================================================
--
-- PHASE 3 ANALYTICS PROCESSOR
-- This is the main table for strikeout prediction features
--
-- Data Sources:
-- - mlb_raw.bdl_pitcher_stats (per-game pitching stats)
-- - mlb_raw.bdl_games (game context)
-- - mlb_raw.bdl_pitcher_season_stats (season baselines)
-- - mlb_raw.bdl_pitcher_splits (home/away, day/night adjustments)
-- - mlb_raw.bdl_injuries (availability filtering)
--
-- Key Output: Features for strikeout over/under prediction
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_analytics.pitcher_game_summary` (
  -- ============================================================================
  -- CORE IDENTIFIERS (7 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,              -- Normalized pitcher identifier (join key)
  universal_player_id STRING,                 -- Universal player ID from registry
  player_full_name STRING,                    -- Display name
  game_id STRING NOT NULL,                    -- Unique game identifier
  game_date DATE NOT NULL,                    -- Game date (partition key)
  team_abbr STRING NOT NULL,                  -- Pitcher's team abbreviation
  opponent_team_abbr STRING NOT NULL,         -- Opposing team abbreviation
  season_year INT64 NOT NULL,                 -- Season year

  -- ============================================================================
  -- GAME CONTEXT (6 fields)
  -- ============================================================================
  is_home BOOL NOT NULL,                      -- Home game flag
  is_day_game BOOL,                           -- Day game flag (before 5pm local)
  is_postseason BOOL NOT NULL,                -- Playoff game flag
  venue STRING,                               -- Stadium name
  game_status STRING,                         -- Final, In Progress, etc.
  win_flag BOOL,                              -- Pitcher's team won

  -- ============================================================================
  -- ACTUAL PERFORMANCE - TARGET VARIABLES (10 fields)
  -- ============================================================================
  strikeouts INT64,                           -- ACTUAL STRIKEOUTS (primary target!)
  innings_pitched NUMERIC(4,1),               -- Actual innings pitched
  pitch_count INT64,                          -- Actual pitch count
  strikes INT64,                              -- Actual strikes
  walks_allowed INT64,                        -- Actual walks
  hits_allowed INT64,                         -- Actual hits allowed
  earned_runs INT64,                          -- Actual earned runs
  era_game NUMERIC(5,2),                      -- ERA for this game
  win BOOL,                                   -- Got the win
  quality_start BOOL,                         -- 6+ IP, 3 or fewer ER

  -- ============================================================================
  -- ROLLING PERFORMANCE STATS (12 fields) - Key ML Features
  -- ============================================================================
  k_avg_last_3 NUMERIC(4,2),                  -- Avg strikeouts last 3 games
  k_avg_last_5 NUMERIC(4,2),                  -- Avg strikeouts last 5 games
  k_avg_last_10 NUMERIC(4,2),                 -- Avg strikeouts last 10 games
  k_std_last_10 NUMERIC(4,2),                 -- Std dev of K last 10 games (volatility)
  ip_avg_last_5 NUMERIC(4,2),                 -- Avg innings last 5 games
  ip_avg_last_10 NUMERIC(4,2),                -- Avg innings last 10 games
  pitch_count_avg_last_5 NUMERIC(5,1),        -- Avg pitch count last 5
  era_rolling_10 NUMERIC(5,2),                -- Rolling ERA last 10 games
  whip_rolling_10 NUMERIC(4,2),               -- Rolling WHIP last 10 games
  k_per_9_rolling_10 NUMERIC(4,2),            -- Rolling K/9 last 10 games
  games_last_30_days INT64,                   -- Games in last 30 days (workload)
  days_rest INT64,                            -- Days since last start

  -- ============================================================================
  -- SEASON STATS (8 fields) - Baseline Performance
  -- ============================================================================
  season_strikeouts INT64,                    -- Season total strikeouts
  season_innings NUMERIC(6,1),                -- Season total innings
  season_k_per_9 NUMERIC(4,2),                -- Season K/9
  season_era NUMERIC(5,2),                    -- Season ERA
  season_whip NUMERIC(4,2),                   -- Season WHIP
  season_games_started INT64,                 -- Games started this season
  season_win_pct NUMERIC(4,3),                -- Win percentage
  season_quality_start_pct NUMERIC(4,3),      -- Quality start percentage

  -- ============================================================================
  -- SPLIT-BASED ADJUSTMENTS (8 fields) - Key for Predictions
  -- ============================================================================
  home_k_per_9 NUMERIC(4,2),                  -- K/9 at home
  away_k_per_9 NUMERIC(4,2),                  -- K/9 on road
  day_k_per_9 NUMERIC(4,2),                   -- K/9 in day games
  night_k_per_9 NUMERIC(4,2),                 -- K/9 in night games
  home_away_k_diff NUMERIC(4,2),              -- Home K/9 minus Away K/9
  day_night_k_diff NUMERIC(4,2),              -- Day K/9 minus Night K/9
  vs_opponent_k_per_9 NUMERIC(4,2),           -- K/9 vs this specific opponent (if available)
  vs_opponent_games INT64,                    -- Games vs this opponent this season

  -- ============================================================================
  -- MATCHUP CONTEXT (6 fields)
  -- ============================================================================
  opponent_team_k_rate NUMERIC(4,3),          -- Opponent team strikeout rate (how often they K)
  opponent_runs_per_game NUMERIC(4,2),        -- Opponent runs per game
  opponent_obp NUMERIC(4,3),                  -- Opponent on-base percentage
  ballpark_k_factor NUMERIC(4,2),             -- Ballpark strikeout factor (1.0 = neutral)
  game_total_line NUMERIC(4,1),               -- Over/under total for the game
  team_implied_runs NUMERIC(4,2),             -- Team implied run total from odds

  -- ============================================================================
  -- PROP BETTING DATA (6 fields)
  -- ============================================================================
  strikeouts_line NUMERIC(4,1),               -- Betting line for strikeouts prop
  strikeouts_over_odds INT64,                 -- Over odds (American format, e.g., -110)
  strikeouts_under_odds INT64,                -- Under odds
  over_under_result STRING,                   -- 'OVER', 'UNDER', 'PUSH', or NULL
  line_source STRING,                         -- Source of line (odds_api, etc.)
  line_timestamp TIMESTAMP,                   -- When line was captured

  -- ============================================================================
  -- DATA QUALITY FLAGS (5 fields)
  -- ============================================================================
  stats_source STRING,                        -- Primary stats source (bdl, etc.)
  splits_available BOOL,                      -- Whether split data was available
  rolling_stats_games INT64,                  -- Number of games used for rolling stats
  is_first_start BOOL,                        -- First start of season (limited history)
  data_completeness_score NUMERIC(3,2),       -- 0.0-1.0 completeness score

  -- ============================================================================
  -- PROCESSING METADATA (4 fields)
  -- ============================================================================
  source_files ARRAY<STRING>,                 -- GCS paths to source files
  data_hash STRING,                           -- Hash for idempotency
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, season_year
OPTIONS (
  description = "MLB pitcher game summary with rolling stats and split adjustments. Primary table for strikeout prediction ML features.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Recent pitcher performance (last 30 days)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_game_summary_recent` AS
SELECT *
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Starting pitchers with complete features (for ML training)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_ml_training_data` AS
SELECT *
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE innings_pitched >= 5.0
  AND rolling_stats_games >= 5
  AND is_first_start = FALSE
  AND data_completeness_score >= 0.8;

-- Today's starting pitchers with features
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.todays_starting_pitchers` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  opponent_team_abbr,
  is_home,
  is_day_game,
  k_avg_last_5,
  k_avg_last_10,
  season_k_per_9,
  home_away_k_diff,
  opponent_team_k_rate,
  strikeouts_line,
  days_rest
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date = CURRENT_DATE()
  AND innings_pitched IS NULL  -- Game hasn't happened yet
ORDER BY team_abbr;

-- Prediction accuracy tracking
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_prop_results` AS
SELECT
  game_date,
  player_lookup,
  player_full_name,
  team_abbr,
  opponent_team_abbr,
  strikeouts,
  strikeouts_line,
  over_under_result,
  k_avg_last_5,
  k_avg_last_10,
  season_k_per_9
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE strikeouts_line IS NOT NULL
  AND strikeouts IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
ORDER BY game_date DESC;
