-- ============================================================================
-- MLB Ball Don't Lie Batter Stats Tables
-- Per-game batting statistics for bottom-up strikeout model
-- File: schemas/bigquery/mlb_raw/bdl_batter_stats_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/stats
-- Scraper: scrapers/mlb/balldontlie/mlb_batter_stats.py
--
-- Key Fields for Bottom-Up Strikeout Model:
-- - strikeouts (k): Batter strikeouts (CRITICAL FOR MODEL)
-- - at_bats (ab): At bats
-- - hits (h): Hits
-- - walks (bb): Walks (bases on balls)
--
-- Bottom-Up Model Insight:
--   Pitcher K's ~ Sum of individual batter K probabilities
--   If batter K lines don't sum to pitcher K line -> market inefficiency
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_batter_stats` (
  -- ============================================================================
  -- CORE IDENTIFIERS
  -- ============================================================================
  game_id STRING NOT NULL,                    -- BDL game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)
  season_year INT64 NOT NULL,                 -- Season year (2024, 2025, etc.)
  is_postseason BOOL NOT NULL,                -- Playoff game flag

  -- ============================================================================
  -- GAME CONTEXT
  -- ============================================================================
  home_team_abbr STRING NOT NULL,             -- Home team abbreviation
  away_team_abbr STRING NOT NULL,             -- Away team abbreviation
  home_team_score INT64,                      -- Final home team score
  away_team_score INT64,                      -- Final away team score
  venue STRING,                               -- Stadium name
  game_status STRING,                         -- Game status (Final, In Progress, etc.)

  -- ============================================================================
  -- BATTER IDENTIFICATION
  -- ============================================================================
  bdl_player_id INT64 NOT NULL,               -- Ball Don't Lie player ID
  player_full_name STRING NOT NULL,           -- Full player name
  player_lookup STRING NOT NULL,              -- Normalized lookup key (lowercase, no spaces)
  team_abbr STRING NOT NULL,                  -- Batter's team abbreviation
  position STRING,                            -- Position (C, 1B, 2B, SS, 3B, OF, DH, etc.)
  jersey_number STRING,                       -- Jersey number
  batting_order INT64,                        -- Lineup position (1-9)

  -- ============================================================================
  -- BATTING STATS (CORE - for bottom-up model)
  -- ============================================================================
  strikeouts INT64,                           -- k: STRIKEOUTS (CRITICAL FOR BOTTOM-UP MODEL!)
  at_bats INT64,                              -- ab: At bats
  hits INT64,                                 -- h: Hits
  walks INT64,                                -- bb: Walks (bases on balls)

  -- ============================================================================
  -- BATTING STATS (EXTENDED)
  -- ============================================================================
  runs INT64,                                 -- r: Runs scored
  rbi INT64,                                  -- rbi: Runs batted in
  home_runs INT64,                            -- hr: Home runs
  doubles INT64,                              -- 2b: Doubles
  triples INT64,                              -- 3b: Triples
  stolen_bases INT64,                         -- sb: Stolen bases
  caught_stealing INT64,                      -- cs: Caught stealing
  hit_by_pitch INT64,                         -- hbp: Hit by pitch
  sacrifice_hits INT64,                       -- sac: Sacrifice hits/bunts
  sacrifice_flies INT64,                      -- sf: Sacrifice flies

  -- ============================================================================
  -- CALCULATED/DERIVED STATS
  -- ============================================================================
  batting_average NUMERIC(4,3),               -- AVG: Batting average (H/AB)
  on_base_pct NUMERIC(4,3),                   -- OBP: On-base percentage
  slugging_pct NUMERIC(4,3),                  -- SLG: Slugging percentage
  ops NUMERIC(4,3),                           -- OPS: On-base plus slugging

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  source_file_path STRING NOT NULL,           -- GCS path to source JSON
  data_hash STRING,                           -- SHA256 hash for idempotency
  created_at TIMESTAMP NOT NULL,              -- Record creation time
  processed_at TIMESTAMP NOT NULL             -- Processing timestamp
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date
OPTIONS (
  description = "MLB batter per-game statistics from Ball Don't Lie API. Critical for bottom-up strikeout prediction model - batter K rates sum to approximate pitcher K totals.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Recent batter stats (last 30 days)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_batter_stats_recent` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Batters with at-bats (exclude DNP)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_active_batters` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE at_bats > 0
  AND game_status = 'STATUS_FINAL';

-- Quality monitoring view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_batter_stats_quality` AS
SELECT
  game_date,
  COUNT(*) as total_batter_records,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT player_lookup) as unique_batters,
  SUM(at_bats) as total_at_bats,
  SUM(strikeouts) as total_strikeouts,
  ROUND(SAFE_DIVIDE(SUM(strikeouts), SUM(at_bats)), 3) as overall_k_rate,
  AVG(strikeouts) as avg_strikeouts_per_batter,
  COUNT(CASE WHEN strikeouts IS NULL THEN 1 END) as null_strikeouts_count
FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Batter strikeout leaders (high K rate batters)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_batter_k_leaders` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  COUNT(*) as games,
  SUM(at_bats) as total_at_bats,
  SUM(strikeouts) as total_strikeouts,
  AVG(strikeouts) as avg_strikeouts_per_game,
  ROUND(SAFE_DIVIDE(SUM(strikeouts), SUM(at_bats)), 3) as k_rate,
  AVG(hits) as avg_hits,
  ROUND(SAFE_DIVIDE(SUM(hits), SUM(at_bats)), 3) as batting_avg
FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  AND at_bats > 0
GROUP BY player_lookup, player_full_name, team_abbr
HAVING SUM(at_bats) >= 50  -- Minimum 50 ABs for stability
ORDER BY k_rate DESC;

-- Per-game team strikeout totals (for bottom-up validation)
-- This view aggregates batter Ks by team per game to compare vs pitcher Ks
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_team_game_strikeouts` AS
SELECT
  game_id,
  game_date,
  team_abbr,
  home_team_abbr,
  away_team_abbr,
  CASE WHEN team_abbr = home_team_abbr THEN 'HOME' ELSE 'AWAY' END as home_away,
  COUNT(DISTINCT player_lookup) as batters_used,
  SUM(at_bats) as team_at_bats,
  SUM(strikeouts) as team_strikeouts,
  ROUND(SAFE_DIVIDE(SUM(strikeouts), SUM(at_bats)), 3) as team_k_rate,
  SUM(hits) as team_hits,
  SUM(walks) as team_walks,
  SUM(runs) as team_runs
FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND game_status = 'STATUS_FINAL'
GROUP BY game_id, game_date, team_abbr, home_team_abbr, away_team_abbr
ORDER BY game_date DESC, game_id;
