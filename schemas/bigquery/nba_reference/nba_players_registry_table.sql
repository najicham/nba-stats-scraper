-- File: schemas/bigquery/nba_reference/nba_players_registry_table.sql
-- Description: NBA players registry table for authoritative player validation
-- Created: 2025-01-20
-- Updated: 2025-09-27 - Added universal_player_id for cross-table player identification
-- Purpose: Authoritative registry of valid NBA players built from gamebook data

-- =============================================================================
-- Table: NBA Players Registry - Authoritative player validation
-- =============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.nba_players_registry` (
    -- Universal player identification
    universal_player_id STRING,            -- Universal player ID (e.g., "kjmartin_001")
    
    -- Basic player identification  
    player_name STRING NOT NULL,           -- Official NBA.com name
    player_lookup STRING NOT NULL,         -- Normalized lookup key
    team_abbr STRING NOT NULL,             -- Team affiliation
    season STRING NOT NULL,                -- "2023-24" format
    
    -- Game participation (from gamebook data)
    first_game_date DATE,                  -- First game played this season/team
    last_game_date DATE,                   -- Most recent game
    games_played INT64,                    -- Total games this season/team
    total_appearances INT64,               -- All appearances including inactive/dnp
    inactive_appearances INT64,            -- Count of inactive appearances
    dnp_appearances INT64,                 -- Count of DNP appearances
    
    -- Roster enhancement (from morning scrapes)
    jersey_number INT64,                   -- Current jersey number
    position STRING,                       -- Listed position
    last_roster_update DATE,               -- When roster data was last updated
    
    -- Data source tracking
    source_priority STRING,                -- 'nba_gamebook', 'br_roster', 'espn_roster'
    confidence_score FLOAT64,              -- Data quality confidence (0.0-1.0)
    
    -- Metadata
    created_by STRING NOT NULL,
    created_at TIMESTAMP NOT NULL,         -- When record first created
    processed_at TIMESTAMP NOT NULL       -- When record last updated
)
CLUSTER BY universal_player_id, player_lookup, season, team_abbr
OPTIONS (
  description = "Authoritative registry of valid NBA players with universal IDs for cross-table identification"
);