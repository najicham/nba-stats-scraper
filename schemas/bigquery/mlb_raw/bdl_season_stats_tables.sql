-- ============================================================================
-- MLB Ball Don't Lie Season Stats Tables
-- Season aggregate statistics for pitchers
-- File: schemas/bigquery/mlb_raw/bdl_season_stats_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/season_stats
-- Scraper: scrapers/mlb/balldontlie/mlb_season_stats.py
--
-- Key metrics: K/9, ERA, WHIP for baseline performance
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_pitcher_season_stats` (
  -- ============================================================================
  -- IDENTIFIERS
  -- ============================================================================
  bdl_player_id INT64 NOT NULL,               -- Ball Don't Lie player ID
  player_full_name STRING NOT NULL,           -- Full player name
  player_lookup STRING NOT NULL,              -- Normalized lookup key
  season_year INT64 NOT NULL,                 -- Season year
  is_postseason BOOL NOT NULL,                -- Postseason stats flag

  -- ============================================================================
  -- TEAM INFO
  -- ============================================================================
  team_id INT64,                              -- BDL team ID
  team_abbr STRING,                           -- Team abbreviation

  -- ============================================================================
  -- CORE PITCHING STATS
  -- ============================================================================
  games INT64,                                -- Games appeared
  games_started INT64,                        -- Games started
  innings_pitched NUMERIC(6,1),               -- Total innings pitched
  strikeouts INT64,                           -- Total strikeouts
  walks INT64,                                -- Total walks
  hits_allowed INT64,                         -- Total hits allowed
  runs_allowed INT64,                         -- Total runs allowed
  earned_runs INT64,                          -- Total earned runs
  home_runs_allowed INT64,                    -- Total home runs allowed

  -- ============================================================================
  -- RATE STATS
  -- ============================================================================
  era NUMERIC(5,2),                           -- Earned Run Average
  whip NUMERIC(4,2),                          -- Walks + Hits per IP
  k_per_9 NUMERIC(4,2),                       -- Strikeouts per 9 innings
  bb_per_9 NUMERIC(4,2),                      -- Walks per 9 innings
  h_per_9 NUMERIC(4,2),                       -- Hits per 9 innings
  hr_per_9 NUMERIC(4,2),                      -- Home runs per 9 innings
  k_bb_ratio NUMERIC(4,2),                    -- Strikeout to walk ratio
  opponent_avg NUMERIC(4,3),                  -- Opponent batting average

  -- ============================================================================
  -- RESULTS
  -- ============================================================================
  wins INT64,                                 -- Total wins
  losses INT64,                               -- Total losses
  saves INT64,                                -- Total saves
  holds INT64,                                -- Total holds
  blown_saves INT64,                          -- Total blown saves
  complete_games INT64,                       -- Complete games
  shutouts INT64,                             -- Shutouts
  quality_starts INT64,                       -- Quality starts (6+ IP, 3 or fewer ER)

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  snapshot_date DATE NOT NULL,                -- Date stats were fetched
  source_file_path STRING NOT NULL,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY season_year, player_lookup, team_abbr
OPTIONS (
  description = "MLB pitcher season aggregate statistics from Ball Don't Lie API. Used for baseline performance metrics.",
  require_partition_filter = true
);

-- Current season leaders view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_season_k_leaders` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  games_started,
  innings_pitched,
  strikeouts,
  k_per_9,
  era,
  whip
FROM `nba-props-platform.mlb_raw.bdl_pitcher_season_stats`
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_pitcher_season_stats`)
  AND is_postseason = FALSE
  AND innings_pitched >= 50
ORDER BY strikeouts DESC
LIMIT 50;
