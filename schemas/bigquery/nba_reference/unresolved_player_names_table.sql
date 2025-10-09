-- File: schemas/bigquery/nba_reference/unresolved_player_names_table.sql
-- Description: Unresolved player names table for manual review queue
-- Created: 2025-01-20
-- Updated: 2025-10-07 - Added snooze_until for CLI tool support
-- Purpose: Queue for manual review of unknown player names not used in production resolution

-- =============================================================================
-- Table: Unresolved Player Names - Manual review queue
-- =============================================================================
-- This table maintains a queue of player names that couldn't be automatically
-- resolved by the registry processors. These names require human review to
-- determine if they represent:
-- - A new player (create registry entry)
-- - An alias for an existing player (create alias mapping)
-- - A data quality issue (mark as invalid)
-- - A minor variation not worth tracking (mark as ignored)
--
-- Status workflow:
--   pending -> resolved | invalid | ignored | under_review | snoozed
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.unresolved_player_names` (
    -- =============================================================================
    -- SOURCE INFORMATION
    -- =============================================================================
    source STRING NOT NULL,              -- Data source: 'espn', 'br', 'basketball_reference', 'nba_com'
    original_name STRING NOT NULL,       -- Name as it appears in source (display format)
    normalized_lookup STRING NOT NULL,   -- Normalized version for matching (lowercase, no spaces)

    -- =============================================================================
    -- CONTEXT & TRACKING
    -- =============================================================================
    first_seen_date DATE NOT NULL,       -- When first encountered
    last_seen_date DATE NOT NULL,        -- Most recent occurrence
    team_abbr STRING,                    -- Team context if available
    season STRING,                       -- Season context (e.g., "2024-25")
    occurrences INT64 NOT NULL,          -- How many times seen across all sources
    example_games ARRAY<STRING>,         -- Sample game IDs where this name appeared

    -- =============================================================================
    -- RESOLUTION WORKFLOW
    -- =============================================================================
    status STRING NOT NULL,              -- Current status:
                                         --   'pending' - awaiting review
                                         --   'resolved' - mapped to canonical name
                                         --   'invalid' - typo or data error
                                         --   'ignored' - too minor to track
                                         --   'under_review' - needs more research
                                         --   'snoozed' - delayed for later review
    
    resolution_type STRING,              -- Type of resolution:
                                         --   'create_alias' - alias mapping created
                                         --   'add_to_registry' - new player added
                                         --   'typo' - marked as invalid
                                         --   NULL for pending/ignored/snoozed
    
    resolved_to_name STRING,             -- NBA canonical name if resolved (for reference)
    notes STRING,                        -- Manual research notes, reasons, context
    
    -- =============================================================================
    -- SNOOZE FUNCTIONALITY (Added 2025-10-07)
    -- =============================================================================
    snooze_until DATE,                   -- If snoozed, when to show again
                                         -- NULL for non-snoozed records
                                         -- When DATE >= snooze_until, record appears in pending list

    -- =============================================================================
    -- REVIEW TRACKING
    -- =============================================================================
    reviewed_by STRING,                  -- Username of person who reviewed
    reviewed_at TIMESTAMP,               -- When review occurred
    
    -- =============================================================================
    -- METADATA
    -- =============================================================================
    created_at TIMESTAMP NOT NULL,       -- When record first created
    processed_at TIMESTAMP NOT NULL      -- When record last updated
)
PARTITION BY first_seen_date
CLUSTER BY status, source, normalized_lookup
OPTIONS (
  description = "Queue for manual review of unknown player names. Supports snooze functionality for delayed review. Status values: pending, resolved, invalid, ignored, under_review, snoozed."
);

-- =============================================================================
-- INDEXES & OPTIMIZATION
-- =============================================================================
-- Partitioning by first_seen_date allows efficient date-range queries
-- Clustering by status, source, normalized_lookup optimizes common query patterns:
--   1. Finding pending names (WHERE status = 'pending')
--   2. Filtering by source (WHERE source = 'espn')
--   3. Looking up specific names (WHERE normalized_lookup = 'playername')

-- =============================================================================
-- COMMON QUERIES
-- =============================================================================

-- Get all pending names (excluding snoozed until their date)
-- SELECT *
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- WHERE status = 'pending' 
--    OR (status = 'snoozed' AND (snooze_until IS NULL OR snooze_until <= CURRENT_DATE()))
-- ORDER BY occurrences DESC, last_seen_date DESC;

-- Get names needing review by source
-- SELECT source, COUNT(*) as pending_count
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- WHERE status = 'pending'
-- GROUP BY source
-- ORDER BY pending_count DESC;

-- Find high-occurrence unresolved names
-- SELECT 
--   original_name,
--   normalized_lookup,
--   source,
--   team_abbr,
--   season,
--   occurrences,
--   status
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- WHERE status = 'pending'
--   AND occurrences >= 5
-- ORDER BY occurrences DESC;

-- Check snoozed names due for review
-- SELECT 
--   original_name,
--   team_abbr,
--   season,
--   snooze_until,
--   notes
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- WHERE status = 'snoozed'
--   AND snooze_until <= CURRENT_DATE()
-- ORDER BY snooze_until;

-- Resolution statistics
-- SELECT 
--   status,
--   COUNT(*) as count,
--   COUNT(DISTINCT source) as sources,
--   AVG(occurrences) as avg_occurrences
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- GROUP BY status
-- ORDER BY count DESC;

-- Recent resolutions by reviewer
-- SELECT 
--   reviewed_by,
--   resolution_type,
--   COUNT(*) as resolutions
-- FROM `nba-props-platform.nba_reference.unresolved_player_names`
-- WHERE status = 'resolved'
--   AND reviewed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
-- GROUP BY reviewed_by, resolution_type
-- ORDER BY reviewed_by, resolutions DESC;