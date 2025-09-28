-- File: schemas/bigquery/nba_reference/nba_players_registry_table.sql
-- Description: NBA players registry table for authoritative player validation
-- Created: 2025-01-20
-- Updated: 2025-09-28 - Added processor tracking fields for conflict prevention
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
    
    -- Data source tracking
    source_priority STRING,                -- 'nba_gamebook', 'br_roster', 'espn_roster'
    confidence_score FLOAT64,              -- Data quality confidence (0.0-1.0)
    
    -- Processor tracking (for conflict prevention)
    last_processor STRING,                 -- Which processor last updated ('gamebook' or 'roster')
    last_gamebook_update TIMESTAMP,        -- When gamebook processor last updated this record
    last_roster_update TIMESTAMP,          -- When roster processor last updated this record (converted from DATE)
    gamebook_update_count INT64 DEFAULT 0, -- Number of times gamebook processor updated this record
    roster_update_count INT64 DEFAULT 0,   -- Number of times roster processor updated this record
    update_sequence_number INT64,          -- Sequence number for ordering updates
    
    -- Metadata
    created_by STRING NOT NULL,
    created_at TIMESTAMP NOT NULL,         -- When record first created
    processed_at TIMESTAMP NOT NULL       -- When record last updated
)
CLUSTER BY universal_player_id, player_lookup, season, team_abbr
OPTIONS (
  description = "Authoritative registry of valid NBA players with universal IDs and processor tracking for cross-table identification"
);

-- =============================================================================
-- Index suggestions for processor tracking queries
-- =============================================================================

-- Query to check recent processor activity (used for conflict prevention)
-- SELECT last_processor, MAX(processed_at) as last_update_time, COUNT(*) as records_updated
-- FROM `nba-props-platform.nba_reference.nba_players_registry`
-- WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
-- GROUP BY last_processor;

-- Query to get processor update statistics
-- SELECT 
--   COUNT(*) as total_records,
--   COUNT(DISTINCT universal_player_id) as unique_players,
--   COUNTIF(last_processor = 'gamebook') as gamebook_records,
--   COUNTIF(last_processor = 'roster') as roster_records,
--   MAX(last_gamebook_update) as last_gamebook_update,
--   MAX(last_roster_update) as last_roster_update
-- FROM `nba-props-platform.nba_reference.nba_players_registry`;