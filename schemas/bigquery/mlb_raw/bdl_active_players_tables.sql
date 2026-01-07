-- ============================================================================
-- MLB Ball Don't Lie Active Players Tables
-- Current active MLB player roster
-- File: schemas/bigquery/mlb_raw/bdl_active_players_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/players/active
-- Scraper: scrapers/mlb/balldontlie/mlb_active_players.py
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_active_players` (
  -- ============================================================================
  -- PLAYER IDENTIFICATION
  -- ============================================================================
  bdl_player_id INT64 NOT NULL,               -- Ball Don't Lie player ID
  player_full_name STRING NOT NULL,           -- Full player name
  player_lookup STRING NOT NULL,              -- Normalized lookup key
  first_name STRING,                          -- First name
  last_name STRING,                           -- Last name

  -- ============================================================================
  -- PLAYER DETAILS
  -- ============================================================================
  position STRING,                            -- Position (Starting Pitcher, Relief Pitcher, etc.)
  jersey_number STRING,                       -- Jersey number
  bats_throws STRING,                         -- Batting/throwing hand (e.g., "Right/Right")
  height STRING,                              -- Height (e.g., "6' 4\"")
  weight STRING,                              -- Weight (e.g., "210 lbs")
  birth_date DATE,                            -- Date of birth
  age INT64,                                  -- Current age
  birth_place STRING,                         -- Birth city/country
  debut_year INT64,                           -- MLB debut year
  draft_info STRING,                          -- Draft round/pick info
  college STRING,                             -- College attended

  -- ============================================================================
  -- TEAM AFFILIATION
  -- ============================================================================
  team_id INT64,                              -- BDL team ID
  team_abbr STRING,                           -- Team abbreviation
  team_name STRING,                           -- Full team name
  league STRING,                              -- AL or NL
  division STRING,                            -- East, Central, West

  -- ============================================================================
  -- PITCHER FLAGS
  -- ============================================================================
  is_pitcher BOOL NOT NULL,                   -- Is a pitcher
  is_starting_pitcher BOOL,                   -- Is a starting pitcher
  is_relief_pitcher BOOL,                     -- Is a relief pitcher

  -- ============================================================================
  -- SNAPSHOT METADATA
  -- ============================================================================
  snapshot_date DATE NOT NULL,                -- Date of this snapshot
  source_file_path STRING NOT NULL,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY team_abbr, position, player_lookup
OPTIONS (
  description = "MLB active player roster from Ball Don't Lie API. Daily snapshots of player status and team affiliation.",
  require_partition_filter = true
);

-- Current pitchers view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_active_pitchers` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_active_players`
WHERE is_pitcher = TRUE
  AND snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_active_players`);

-- Current starting pitchers view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_starting_pitchers_roster` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_active_players`
WHERE is_starting_pitcher = TRUE
  AND snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_active_players`);
