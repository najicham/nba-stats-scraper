-- File: schemas/bigquery/nba_reference/player_aliases_table.sql
-- Description: Player aliases table for production name resolution mapping
-- Created: 2025-01-20
-- Purpose: Maps confirmed name variations to NBA.com canonical names for production resolution

-- =============================================================================
-- Table: Player Aliases - Production name resolution mapping
-- =============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.player_aliases` (
    -- Input → Output mapping (alias first for intuitive lookup)
    alias_lookup STRING NOT NULL,           -- Normalized alias (PRIMARY KEY)
    nba_canonical_lookup STRING NOT NULL,   -- Normalized NBA canonical name

    -- Display names for reference
    alias_display STRING NOT NULL,          -- Original alias name
    nba_canonical_display STRING NOT NULL,  -- Original NBA canonical name

    -- Classification
    alias_type STRING,                      -- 'suffix_difference', 'nickname', 'source_variation'
    alias_source STRING,                    -- 'bdl', 'espn', 'historical', etc.

    -- Status
    is_active BOOLEAN NOT NULL,

    -- Manual tracking
    notes STRING,
    created_by STRING NOT NULL,
    created_date DATE NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
CLUSTER BY alias_lookup, nba_canonical_lookup
OPTIONS (
  description = "Maps confirmed name variations to NBA.com canonical names for production resolution"
);