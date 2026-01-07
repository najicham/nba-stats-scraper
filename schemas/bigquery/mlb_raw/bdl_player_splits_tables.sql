-- ============================================================================
-- MLB Ball Don't Lie Player Splits Tables
-- Performance splits by venue, time, opponent, etc.
-- File: schemas/bigquery/mlb_raw/bdl_player_splits_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/players/splits
-- Scraper: scrapers/mlb/balldontlie/mlb_player_splits.py
--
-- Critical for strikeout predictions: home/away, day/night performance
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_pitcher_splits` (
  -- ============================================================================
  -- IDENTIFIERS
  -- ============================================================================
  bdl_player_id INT64 NOT NULL,               -- Ball Don't Lie player ID
  player_full_name STRING NOT NULL,           -- Full player name
  player_lookup STRING NOT NULL,              -- Normalized lookup key
  season_year INT64 NOT NULL,                 -- Season year
  split_category STRING NOT NULL,             -- Category: home, away, day, night, vs_lhb, vs_rhb, etc.

  -- ============================================================================
  -- PITCHING STATS FOR THIS SPLIT
  -- ============================================================================
  games INT64,                                -- Games in this split
  innings_pitched NUMERIC(5,1),               -- Innings in this split
  strikeouts INT64,                           -- Strikeouts in this split
  walks INT64,                                -- Walks in this split
  hits_allowed INT64,                         -- Hits in this split
  earned_runs INT64,                          -- Earned runs in this split
  home_runs_allowed INT64,                    -- HRs in this split

  -- ============================================================================
  -- RATE STATS FOR THIS SPLIT
  -- ============================================================================
  era NUMERIC(5,2),                           -- ERA for this split
  whip NUMERIC(4,2),                          -- WHIP for this split
  k_per_9 NUMERIC(4,2),                       -- K/9 for this split
  avg_strikeouts_per_game NUMERIC(4,2),       -- Average Ks per game in this split

  -- ============================================================================
  -- RECENT FORM SPLITS (Last 7/15/30 days)
  -- ============================================================================
  is_recent_split BOOL,                       -- TRUE for last_7, last_15, last_30 splits
  recent_period_days INT64,                   -- 7, 15, or 30 for recent splits

  -- ============================================================================
  -- OPPONENT SPLIT DETAILS (when split_category = 'vs_team_XXX')
  -- ============================================================================
  opponent_team_abbr STRING,                  -- Opponent team for vs_team splits

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  snapshot_date DATE NOT NULL,                -- Date splits were fetched
  source_file_path STRING NOT NULL,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY player_lookup, split_category, season_year
OPTIONS (
  description = "MLB pitcher performance splits from Ball Don't Lie API. Used for home/away, day/night adjustments in predictions.",
  require_partition_filter = true
);

-- Home vs Away comparison view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_pitcher_home_away_splits` AS
SELECT
  h.player_lookup,
  h.player_full_name,
  h.season_year,
  h.k_per_9 as home_k_per_9,
  a.k_per_9 as away_k_per_9,
  h.avg_strikeouts_per_game as home_avg_k,
  a.avg_strikeouts_per_game as away_avg_k,
  h.era as home_era,
  a.era as away_era
FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits` h
JOIN `nba-props-platform.mlb_raw.bdl_pitcher_splits` a
  ON h.player_lookup = a.player_lookup
  AND h.season_year = a.season_year
  AND h.snapshot_date = a.snapshot_date
WHERE h.split_category = 'home'
  AND a.split_category = 'away'
  AND h.snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`);

-- Day vs Night comparison view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_pitcher_day_night_splits` AS
SELECT
  d.player_lookup,
  d.player_full_name,
  d.season_year,
  d.k_per_9 as day_k_per_9,
  n.k_per_9 as night_k_per_9,
  d.avg_strikeouts_per_game as day_avg_k,
  n.avg_strikeouts_per_game as night_avg_k
FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits` d
JOIN `nba-props-platform.mlb_raw.bdl_pitcher_splits` n
  ON d.player_lookup = n.player_lookup
  AND d.season_year = n.season_year
  AND d.snapshot_date = n.snapshot_date
WHERE d.split_category = 'day'
  AND n.split_category = 'night'
  AND d.snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`);

-- Recent form (last 7/15/30 days) view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_pitcher_recent_form` AS
SELECT
  player_lookup,
  player_full_name,
  season_year,
  split_category,
  recent_period_days,
  games,
  strikeouts,
  innings_pitched,
  avg_strikeouts_per_game,
  k_per_9,
  era
FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`
WHERE is_recent_split = TRUE
  AND snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`)
ORDER BY player_lookup, recent_period_days;
