-- ============================================================================
-- NBA Props Platform - Team Locations Table
-- File: schemas/bigquery/static/team_locations_table.sql
-- Purpose: Geographic reference data for all NBA teams
-- Update Frequency: Only when teams relocate or change arenas (~10+ years)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_static.team_locations` (
  -- Primary identifiers
  team_abbr STRING NOT NULL,                        -- NBA standard three-letter team abbreviation
  
  -- Geographic information
  city STRING NOT NULL,                             -- Team home city name
  state STRING NOT NULL,                            -- Team home state/province
  arena_name STRING NOT NULL,                       -- Current home arena/stadium name
  latitude FLOAT64 NOT NULL,                        -- Arena latitude for distance calculations
  longitude FLOAT64 NOT NULL,                       -- Arena longitude for distance calculations
  
  -- Travel information
  timezone STRING NOT NULL,                         -- Arena timezone (e.g., America/New_York)
  airport_code STRING NOT NULL,                     -- Nearest major airport code
  country STRING DEFAULT "USA",                     -- Country code (USA except TOR=CAN)
  
  -- Processing metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY team_abbr
OPTIONS(
  description="NBA team location reference data for travel distance and jet lag calculations. Updated only when teams relocate or change arenas (typically every 10+ years)."
);

-- ============================================================================
-- Data Population
-- ============================================================================
-- After creating this table, populate with team data:
-- See: bin/static/populate_team_locations.py
--
-- Or manually insert:
-- INSERT INTO `nba-props-platform.nba_static.team_locations` VALUES
-- ('ATL', 'Atlanta', 'Georgia', 'State Farm Arena', 33.7573, -84.3963, 
--  'America/New_York', 'ATL', 'USA', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
-- ...
-- ============================================================================
