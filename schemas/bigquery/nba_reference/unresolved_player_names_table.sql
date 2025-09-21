-- File: schemas/bigquery/nba_reference/unresolved_player_names_table.sql
-- Description: Unresolved player names table for manual review queue
-- Created: 2025-01-20
-- Purpose: Queue for manual review of unknown player names not used in production resolution

-- =============================================================================
-- Table: Unresolved Player Names - Manual review queue
-- =============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.unresolved_player_names` (
    source STRING NOT NULL,              -- 'bdl', 'espn', etc.
    original_name STRING NOT NULL,       -- Name as it appears in source
    normalized_lookup STRING NOT NULL,   -- Normalized version
    
    -- Context
    first_seen_date DATE NOT NULL,
    last_seen_date DATE NOT NULL,
    team_abbr STRING,                    -- Team context if available
    season STRING,                       -- Season context
    occurrences INT64 NOT NULL,          -- How many times seen
    example_games ARRAY<STRING>,         -- Sample game IDs
    
    -- Resolution workflow
    status STRING NOT NULL,              -- 'pending', 'resolved', 'invalid', 'ignored'
    resolution_type STRING,              -- 'create_alias', 'add_to_registry', 'typo'
    resolved_to_name STRING,             -- NBA canonical name if resolved
    notes STRING,                        -- Manual research notes
    
    -- Review tracking
    reviewed_by STRING,
    reviewed_date DATE,
    created_date DATE NOT NULL,
    updated_date DATE NOT NULL
)
PARTITION BY first_seen_date
CLUSTER BY status, source, normalized_lookup
OPTIONS (
  description = "Queue for manual review of unknown player names not used in production resolution"
);