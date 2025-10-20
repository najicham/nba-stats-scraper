-- ============================================================================
-- NBA Props Platform - Travel Distances Table
-- File: schemas/bigquery/static/travel_distances_table.sql
-- Purpose: Pre-calculated distance matrix between all NBA teams
-- Update Frequency: Only when teams relocate (recalculate full matrix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_static.travel_distances` (
  -- Team identifiers
  from_team STRING NOT NULL,                        -- Origin team abbreviation
  to_team STRING NOT NULL,                          -- Destination team abbreviation
  from_city STRING NOT NULL,                        -- Origin city (for reference)
  to_city STRING NOT NULL,                          -- Destination city (for reference)
  
  -- Distance metrics
  distance_miles INT64 NOT NULL,                    -- Great circle distance using haversine formula
  
  -- Time zone and jet lag metrics
  time_zones_crossed INT64 NOT NULL,                -- Number of time zones crossed (0-4)
  travel_direction STRING NOT NULL,                 -- 'east', 'west', or 'neutral'
  jet_lag_factor FLOAT64 NOT NULL,                  -- Weighted impact: eastward=1.5x, westward=1.0x
  
  -- Processing metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY from_team, to_team
OPTIONS(
  description="Pre-calculated travel distances between all NBA teams (870 combinations = 30x29). Recalculated only when teams relocate using haversine formula."
);

-- ============================================================================
-- Data Population
-- ============================================================================
-- After creating this table, calculate and populate distances:
-- See: bin/static/calculate_travel_distances.py
--
-- This script:
-- 1. Reads team_locations table
-- 2. Calculates haversine distances for all team pairs
-- 3. Determines time zones crossed and jet lag factors
-- 4. Inserts 870 distance records (30 teams × 29 destinations)
-- ============================================================================
