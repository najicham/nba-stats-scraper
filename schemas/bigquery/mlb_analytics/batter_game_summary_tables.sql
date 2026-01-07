-- ============================================================================
-- MLB Props Platform - Batter Game Summary Analytics Table
-- Per-game batter performance with rolling K stats for bottom-up model
-- File: schemas/bigquery/mlb_analytics/batter_game_summary_tables.sql
-- ============================================================================
--
-- PHASE 3 ANALYTICS PROCESSOR
-- Critical table for bottom-up strikeout prediction model
--
-- Bottom-Up Model Insight:
--   Pitcher K's ~ Sum of individual batter K probabilities
--   If batter K lines don't sum to pitcher K line -> market inefficiency
--
-- Data Source: mlb_raw.bdl_batter_stats
--
-- Key Output: Batter strikeout rates for summing to predicted pitcher Ks
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_analytics.batter_game_summary` (
  -- ============================================================================
  -- CORE IDENTIFIERS (8 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,              -- Normalized batter identifier (join key)
  universal_player_id STRING,                 -- Universal player ID from registry
  player_full_name STRING,                    -- Display name
  game_id STRING NOT NULL,                    -- Unique game identifier
  game_date DATE NOT NULL,                    -- Game date (partition key)
  team_abbr STRING NOT NULL,                  -- Batter's team abbreviation
  opponent_team_abbr STRING NOT NULL,         -- Opposing team (pitcher's team)
  season_year INT64 NOT NULL,                 -- Season year

  -- ============================================================================
  -- GAME CONTEXT (6 fields)
  -- ============================================================================
  is_home BOOL NOT NULL,                      -- Home game flag
  is_postseason BOOL NOT NULL,                -- Playoff game flag
  venue STRING,                               -- Stadium name
  game_status STRING,                         -- Final, In Progress, etc.
  batting_order INT64,                        -- Lineup position (1-9)
  position STRING,                            -- Fielding position

  -- ============================================================================
  -- ACTUAL PERFORMANCE - TARGET VARIABLES (10 fields)
  -- ============================================================================
  strikeouts INT64,                           -- ACTUAL STRIKEOUTS (critical for bottom-up!)
  at_bats INT64,                              -- At bats
  hits INT64,                                 -- Hits
  walks INT64,                                -- Walks (BB)
  home_runs INT64,                            -- Home runs
  rbi INT64,                                  -- Runs batted in
  runs INT64,                                 -- Runs scored
  doubles INT64,                              -- Doubles
  triples INT64,                              -- Triples
  stolen_bases INT64,                         -- Stolen bases

  -- ============================================================================
  -- ROLLING K STATS (8 fields) - Key for Bottom-Up Model
  -- ============================================================================
  k_rate_last_5 NUMERIC(4,3),                 -- K/AB rate last 5 games
  k_rate_last_10 NUMERIC(4,3),                -- K/AB rate last 10 games
  k_avg_last_5 NUMERIC(4,2),                  -- Avg Ks per game last 5
  k_avg_last_10 NUMERIC(4,2),                 -- Avg Ks per game last 10
  k_std_last_10 NUMERIC(4,2),                 -- K volatility
  ab_avg_last_5 NUMERIC(4,2),                 -- Avg ABs last 5 (playing time)
  ab_avg_last_10 NUMERIC(4,2),                -- Avg ABs last 10
  games_last_30_days INT64,                   -- Games in last 30 days

  -- ============================================================================
  -- SEASON STATS (6 fields) - Baseline Performance
  -- ============================================================================
  season_strikeouts INT64,                    -- Season total Ks
  season_at_bats INT64,                       -- Season total ABs
  season_k_rate NUMERIC(4,3),                 -- Season K rate (K/AB)
  season_batting_avg NUMERIC(4,3),            -- Season batting average
  season_games INT64,                         -- Games played this season
  days_since_last_game INT64,                 -- Days rest

  -- ============================================================================
  -- VS PITCHER CONTEXT (4 fields) - Matchup Data
  -- ============================================================================
  opposing_pitcher_lookup STRING,             -- Who they're facing
  vs_pitcher_abs INT64,                       -- ABs vs this pitcher (career)
  vs_pitcher_ks INT64,                        -- Ks vs this pitcher (career)
  vs_pitcher_k_rate NUMERIC(4,3),             -- K rate vs this pitcher

  -- ============================================================================
  -- PROP BETTING DATA (4 fields)
  -- ============================================================================
  strikeouts_line NUMERIC(3,1),               -- Betting line for batter Ks prop
  strikeouts_over_odds INT64,                 -- Over odds
  strikeouts_under_odds INT64,                -- Under odds
  over_under_result STRING,                   -- 'OVER', 'UNDER', 'PUSH', or NULL

  -- ============================================================================
  -- DATA QUALITY FLAGS (4 fields)
  -- ============================================================================
  stats_source STRING,                        -- Primary stats source (bdl)
  rolling_stats_games INT64,                  -- Games used for rolling stats
  is_first_game_season BOOL,                  -- First game of season
  data_completeness_score NUMERIC(3,2),       -- 0.0-1.0 completeness

  -- ============================================================================
  -- PROCESSING METADATA (3 fields)
  -- ============================================================================
  data_hash STRING,                           -- Hash for idempotency
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, season_year
OPTIONS (
  description = "MLB batter game summary with rolling K stats. Critical for bottom-up strikeout prediction model - sum batter K rates to predict pitcher totals.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Recent batter performance (last 30 days)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.batter_game_summary_recent` AS
SELECT *
FROM `nba-props-platform.mlb_analytics.batter_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Batters with complete features (for ML)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.batter_ml_training_data` AS
SELECT *
FROM `nba-props-platform.mlb_analytics.batter_game_summary`
WHERE rolling_stats_games >= 5
  AND at_bats >= 2  -- Had meaningful ABs
  AND data_completeness_score >= 0.7;

-- High-K batters (strikeout prone)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.high_k_batters` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  game_date,
  strikeouts,
  at_bats,
  k_rate_last_10,
  season_k_rate
FROM `nba-props-platform.mlb_analytics.batter_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND season_k_rate >= 0.25  -- 25%+ K rate
ORDER BY season_k_rate DESC;

-- Team lineup K rates (for bottom-up aggregation)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.team_lineup_k_rates` AS
SELECT
  game_id,
  game_date,
  team_abbr,
  opponent_team_abbr,
  COUNT(DISTINCT player_lookup) as batters_in_lineup,
  SUM(at_bats) as team_at_bats,
  SUM(strikeouts) as team_strikeouts,
  ROUND(SAFE_DIVIDE(SUM(strikeouts), SUM(at_bats)), 3) as team_k_rate,
  AVG(k_rate_last_10) as avg_batter_k_rate_last_10,
  AVG(season_k_rate) as avg_batter_season_k_rate
FROM `nba-props-platform.mlb_analytics.batter_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND at_bats > 0
GROUP BY game_id, game_date, team_abbr, opponent_team_abbr
ORDER BY game_date DESC, game_id;

-- Expected team Ks (sum of individual K expectations for bottom-up model)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.expected_team_strikeouts` AS
SELECT
  game_id,
  game_date,
  team_abbr,
  opponent_team_abbr,
  COUNT(DISTINCT player_lookup) as batters,
  SUM(k_avg_last_10) as sum_expected_ks,  -- Bottom-up prediction!
  AVG(k_avg_last_10) as avg_expected_ks_per_batter,
  SUM(ab_avg_last_10) as sum_expected_abs,
  ROUND(SAFE_DIVIDE(SUM(k_avg_last_10), COUNT(DISTINCT player_lookup)) * 9, 2) as implied_team_ks_per_9_batters
FROM `nba-props-platform.mlb_analytics.batter_game_summary`
WHERE game_date = CURRENT_DATE()  -- Today's lineups
  AND strikeouts IS NULL  -- Game hasn't happened
GROUP BY game_id, game_date, team_abbr, opponent_team_abbr;
