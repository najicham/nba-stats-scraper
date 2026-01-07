-- ============================================================================
-- MLB Ball Don't Lie Injuries Tables
-- Current player injury reports
-- File: schemas/bigquery/mlb_raw/bdl_injuries_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/player_injuries
-- Scraper: scrapers/mlb/balldontlie/mlb_injuries.py
--
-- Important: Used to filter out injured pitchers from predictions
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_injuries` (
  -- ============================================================================
  -- PLAYER IDENTIFICATION
  -- ============================================================================
  bdl_player_id INT64 NOT NULL,               -- Ball Don't Lie player ID
  player_full_name STRING NOT NULL,           -- Full player name
  player_lookup STRING NOT NULL,              -- Normalized lookup key
  position STRING,                            -- Position
  is_pitcher BOOL,                            -- Is a pitcher

  -- ============================================================================
  -- TEAM INFO
  -- ============================================================================
  team_id INT64,                              -- BDL team ID
  team_abbr STRING,                           -- Team abbreviation
  team_name STRING,                           -- Full team name

  -- ============================================================================
  -- INJURY DETAILS
  -- ============================================================================
  injury_type STRING,                         -- Type of injury (e.g., "Elbow", "Shoulder")
  injury_description STRING,                  -- Detailed injury description
  injury_status STRING,                       -- IL status (10-Day IL, 15-Day IL, 60-Day IL)
  injury_date DATE,                           -- Date injury occurred
  expected_return_date DATE,                  -- Expected return date (if available)

  -- ============================================================================
  -- SNAPSHOT METADATA
  -- ============================================================================
  snapshot_date DATE NOT NULL,                -- Date of this injury report
  source_file_path STRING NOT NULL,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY team_abbr, is_pitcher, player_lookup
OPTIONS (
  description = "MLB player injury reports from Ball Don't Lie API. Critical for excluding injured pitchers from predictions.",
  require_partition_filter = true
);

-- Current injured pitchers view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_injured_pitchers` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_injuries`
WHERE is_pitcher = TRUE
  AND snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_injuries`);

-- Current IL list view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_current_il` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  position,
  injury_type,
  injury_status,
  expected_return_date,
  is_pitcher
FROM `nba-props-platform.mlb_raw.bdl_injuries`
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM `nba-props-platform.mlb_raw.bdl_injuries`)
ORDER BY is_pitcher DESC, team_abbr, player_full_name;
