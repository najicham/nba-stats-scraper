-- File: schemas/bigquery/nba_reference/nba_players_registry_table.sql
-- Description: NBA players registry table for authoritative player validation
-- Created: 2025-01-20
-- Updated: 2025-10-04 - Added activity date tracking for data protection
-- Purpose: Authoritative registry of valid NBA players built from gamebook data

-- =============================================================================
-- Table: NBA Players Registry - Authoritative player validation
-- =============================================================================
-- This table maintains the authoritative record of NBA players with:
-- - Universal player identification across data sources
-- - Game participation tracking (from gamebook)
-- - Roster information (jersey, position)
-- - Multi-processor tracking with data protection
-- - Activity date tracking for freshness validation
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.nba_players_registry` (
    -- =============================================================================
    -- PLAYER IDENTIFICATION
    -- =============================================================================
    
    universal_player_id STRING,            -- Universal player ID (e.g., "kjmartin_001")
    player_name STRING NOT NULL,           -- Official NBA.com name
    player_lookup STRING NOT NULL,         -- Normalized lookup key
    team_abbr STRING NOT NULL,             -- Team affiliation
    season STRING NOT NULL,                -- "2023-24" format
    
    -- =============================================================================
    -- GAME PARTICIPATION (Gamebook Processor Authority)
    -- =============================================================================
    
    first_game_date DATE,                  -- First game played this season/team
    last_game_date DATE,                   -- Most recent game
    games_played INT64,                    -- Total games this season/team
    total_appearances INT64,               -- All appearances including inactive/dnp
    inactive_appearances INT64,            -- Count of inactive appearances
    dnp_appearances INT64,                 -- Count of DNP appearances
    
    -- =============================================================================
    -- ROSTER INFORMATION (Roster Processor Preferred)
    -- =============================================================================
    
    jersey_number INT64,                   -- Current jersey number
    position STRING,                       -- Listed position
    
    -- =============================================================================
    -- DATA SOURCE TRACKING
    -- =============================================================================
    
    source_priority STRING,                -- 'nba_gamebook', 'roster_nba_com', 'roster_espn', 'roster_br'
    confidence_score FLOAT64,              -- Data quality confidence (0.0-1.0)
    
    -- =============================================================================
    -- PROCESSOR TRACKING (Multi-Processor Conflict Prevention)
    -- =============================================================================
    
    last_processor STRING,                 -- Which processor last updated ('gamebook' or 'roster')
    
    -- Processor update timestamps
    last_gamebook_update TIMESTAMP,        -- When gamebook processor last updated this record
    last_roster_update TIMESTAMP,          -- When roster processor last updated this record
    
    -- Processor update counters
    gamebook_update_count INT64 DEFAULT 0, -- Number of times gamebook processor updated
    roster_update_count INT64 DEFAULT 0,   -- Number of times roster processor updated
    update_sequence_number INT64,          -- Monotonic sequence for update ordering
    
    -- =============================================================================
    -- ACTIVITY DATE TRACKING (Data Freshness Protection)
    -- =============================================================================
    -- These fields track WHEN the data in this record is valid as of, not when
    -- the processor ran. Used to prevent overwriting fresh data with stale data.
    
    last_gamebook_activity_date DATE,      -- Date of most recent game processed for this record
                                           -- Set by gamebook processor to last_game_date
                                           -- Used to check if gamebook data is fresher than incoming roster data
    
    last_roster_activity_date DATE,        -- Date of roster snapshot that created/updated this record
                                           -- Set by roster processor to the data_date being processed
                                           -- Used to check if roster data is fresher than what's stored
    
    -- =============================================================================
    -- METADATA
    -- =============================================================================
    
    created_by STRING NOT NULL,            -- Run ID that created this record
    created_at TIMESTAMP NOT NULL,         -- When record first created
    processed_at TIMESTAMP NOT NULL        -- When record last updated (by any processor)
)
CLUSTER BY universal_player_id, player_lookup, season, team_abbr
OPTIONS (
  description = "Authoritative registry of valid NBA players with universal IDs, multi-processor tracking, and data protection via activity date tracking"
);

-- =============================================================================
-- DATA PROTECTION RULES
-- =============================================================================
-- This schema supports multiple protection mechanisms:
--
-- 1. TEAM ASSIGNMENT AUTHORITY:
--    - Gamebook processor has authority after games_played > 0
--    - Roster processor can only set team_abbr when games_played = 0
--
-- 2. FRESHNESS VALIDATION:
--    - Gamebook: Check last_gamebook_activity_date before updating
--    - Roster: Check last_roster_activity_date before updating
--    - Only allow updates if new data_date >= existing activity_date
--
-- 3. FIELD OWNERSHIP:
--    - Gamebook owns: games_played, first_game_date, last_game_date, team_abbr (after games)
--    - Roster owns: jersey_number, position
--    - Shared: team_abbr (conditional), source_priority, confidence_score
--
-- 4. CURRENT TEAM IDENTIFICATION:
--    For players on multiple teams in same season, current team is determined by:
--    MAX(COALESCE(last_gamebook_activity_date, last_roster_activity_date))
--
-- =============================================================================

-- =============================================================================
-- EXAMPLE QUERIES
-- =============================================================================

-- Get existing record with protection fields
-- SELECT 
--   player_lookup, team_abbr, season,
--   games_played,
--   last_processor,
--   last_gamebook_activity_date,
--   last_roster_activity_date
-- FROM `nba-props-platform.nba_reference.nba_players_registry`
-- WHERE player_lookup = 'lebronjames'
--   AND season = '2024-25';

-- Find current team for a player (most recent activity)
-- SELECT 
--   player_lookup, team_abbr,
--   GREATEST(
--     COALESCE(last_gamebook_activity_date, DATE '1900-01-01'),
--     COALESCE(last_roster_activity_date, DATE '1900-01-01')
--   ) as most_recent_activity
-- FROM `nba-props-platform.nba_reference.nba_players_registry`
-- WHERE player_lookup = 'lebronjames'
--   AND season = '2024-25'
-- ORDER BY most_recent_activity DESC
-- LIMIT 1;

-- Check processor activity summary
-- SELECT 
--   COUNT(*) as total_records,
--   COUNT(DISTINCT universal_player_id) as unique_players,
--   COUNTIF(last_processor = 'gamebook') as gamebook_records,
--   COUNTIF(last_processor = 'roster') as roster_records,
--   MAX(last_gamebook_update) as last_gamebook_update,
--   MAX(last_roster_update) as last_roster_update,
--   COUNT(last_gamebook_activity_date) as records_with_games,
--   COUNT(last_roster_activity_date) as records_with_roster_data
-- FROM `nba-props-platform.nba_reference.nba_players_registry`;

-- Identify stale records (no recent activity)
-- SELECT 
--   player_lookup, team_abbr, season,
--   last_gamebook_activity_date,
--   last_roster_activity_date,
--   DATE_DIFF(CURRENT_DATE(), 
--     GREATEST(
--       COALESCE(last_gamebook_activity_date, DATE '1900-01-01'),
--       COALESCE(last_roster_activity_date, DATE '1900-01-01')
--     ), DAY) as days_stale
-- FROM `nba-props-platform.nba_reference.nba_players_registry`
-- WHERE season = '2024-25'
--   AND DATE_DIFF(CURRENT_DATE(), 
--     GREATEST(
--       COALESCE(last_gamebook_activity_date, DATE '1900-01-01'),
--       COALESCE(last_roster_activity_date, DATE '1900-01-01')
--     ), DAY) > 30
-- ORDER BY days_stale DESC;