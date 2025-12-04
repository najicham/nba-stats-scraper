-- File: schemas/bigquery/nba_reference/unresolved_resolution_log_table.sql
-- Description: Audit log for unresolved player name resolutions
-- Created: 2025-10-07
-- Purpose: Track all resolution actions for compliance and analytics

-- =============================================================================
-- Table: Unresolved Resolution Log - Action audit trail
-- =============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.unresolved_resolution_log` (
    -- Timestamp
    timestamp TIMESTAMP NOT NULL,
    
    -- Action details
    action STRING NOT NULL,                -- 'ALIAS_CREATED', 'MARKED_INVALID', 'NEW_PLAYER_CREATED', etc.
    normalized_lookup STRING NOT NULL,      -- Player lookup being resolved
    original_name STRING NOT NULL,          -- Original display name
    
    -- Resolution details (JSON)
    resolution_details STRING,              -- JSON with action-specific details
    
    -- Context
    team_abbr STRING,
    season STRING,
    
    -- User tracking
    reviewed_by STRING NOT NULL,            -- Who performed the action
    notes STRING                            -- Additional notes
)
PARTITION BY DATE(timestamp)
CLUSTER BY reviewed_by, action
OPTIONS (
  description = "Audit log of all unresolved player name resolution actions"
);

-- =============================================================================
-- Example queries
-- =============================================================================

-- Recent actions by reviewer
-- SELECT 
--   DATE(timestamp) as date,
--   action,
--   COUNT(*) as count
-- FROM `nba-props-platform.nba_reference.unresolved_resolution_log`
-- WHERE reviewed_by = 'your_username'
--   AND DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY date, action
-- ORDER BY date DESC, action;

-- Most active reviewers this week
-- SELECT 
--   reviewed_by,
--   COUNT(*) as actions_taken,
--   COUNT(DISTINCT DATE(timestamp)) as days_active
-- FROM `nba-props-platform.nba_reference.unresolved_resolution_log`
-- WHERE DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY reviewed_by
-- ORDER BY actions_taken DESC;

-- Action type breakdown
-- SELECT 
--   action,
--   COUNT(*) as count,
--   COUNT(DISTINCT reviewed_by) as unique_reviewers
-- FROM `nba-props-platform.nba_reference.unresolved_resolution_log`
-- WHERE DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY action
-- ORDER BY count DESC;