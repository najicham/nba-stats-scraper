-- ============================================================================
-- MLB Ball Don't Lie Games Tables
-- Game schedule and scores
-- File: schemas/bigquery/mlb_raw/bdl_games_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/games
-- Scraper: scrapers/mlb/balldontlie/mlb_games.py
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_games` (
  -- ============================================================================
  -- CORE IDENTIFIERS
  -- ============================================================================
  game_id STRING NOT NULL,                    -- BDL game ID (primary key)
  game_date DATE NOT NULL,                    -- Game date (partition key)
  season_year INT64 NOT NULL,                 -- Season year
  is_postseason BOOL NOT NULL,                -- Playoff game flag

  -- ============================================================================
  -- TEAMS
  -- ============================================================================
  home_team_id INT64,                         -- BDL home team ID
  home_team_abbr STRING NOT NULL,             -- Home team abbreviation
  home_team_name STRING,                      -- Full home team name
  away_team_id INT64,                         -- BDL away team ID
  away_team_abbr STRING NOT NULL,             -- Away team abbreviation
  away_team_name STRING,                      -- Full away team name

  -- ============================================================================
  -- SCORES
  -- ============================================================================
  home_team_score INT64,                      -- Final home team score
  away_team_score INT64,                      -- Final away team score
  home_team_innings ARRAY<INT64>,             -- Inning-by-inning scores (home)
  away_team_innings ARRAY<INT64>,             -- Inning-by-inning scores (away)
  total_innings INT64,                        -- Total innings played (9, or extra)

  -- ============================================================================
  -- GAME DETAILS
  -- ============================================================================
  game_status STRING NOT NULL,                -- STATUS_SCHEDULED, STATUS_IN_PROGRESS, STATUS_FINAL
  venue STRING,                               -- Stadium name
  attendance INT64,                           -- Game attendance
  game_time TIMESTAMP,                        -- Scheduled game time (UTC)
  is_day_game BOOL,                           -- Day game flag (before 5pm local)
  is_doubleheader BOOL,                       -- Part of doubleheader
  doubleheader_game_num INT64,                -- Game 1 or 2 of doubleheader

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  source_file_path STRING NOT NULL,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr, game_date
OPTIONS (
  description = "MLB game schedule and scores from Ball Don't Lie API. Used for game context in predictions.",
  require_partition_filter = true
);

-- Today's games view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_games_today` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_games`
WHERE game_date = CURRENT_DATE();

-- Upcoming games (next 7 days)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_games_upcoming` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_games`
WHERE game_date BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date, game_time;
