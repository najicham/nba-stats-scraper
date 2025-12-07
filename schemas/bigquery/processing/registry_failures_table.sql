-- ============================================================================
-- REGISTRY FAILURES TABLE
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/processing/registry_failures_table.sql
-- Purpose: Track player name resolution failures for reprocessing workflow
-- Created: 2025-12-06 (Session 56: Failure Tracking Design v3.0)

-- This table tracks players who couldn't be found in the registry during
-- Phase 3 processing. It supports a full lifecycle:
--   1. PENDING: Failure recorded, waiting for alias to be created
--   2. RESOLVED: Alias created, ready to reprocess
--   3. REPROCESSED: Dates have been reprocessed, complete

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.registry_failures` (
  -- Identity (composite key: player_lookup + game_date + processor_name)
  player_lookup STRING NOT NULL,        -- Raw name that failed lookup (e.g., "marcusmorris")
  game_date DATE NOT NULL,              -- When the player played
  processor_name STRING NOT NULL,       -- Which processor encountered it

  -- Context (for debugging and reporting)
  team_abbr STRING,                     -- Team context (e.g., "LAL")
  season STRING,                        -- Season (e.g., "2021-22")
  game_id STRING,                       -- Specific game ID

  -- Lifecycle timestamps
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),  -- When failure was first recorded
  resolved_at TIMESTAMP,                             -- When alias was created
  reprocessed_at TIMESTAMP,                          -- When date was reprocessed

  -- Metadata
  occurrence_count INT64 DEFAULT 1,     -- How many times seen (for re-runs)
  run_id STRING                         -- Processing run that created/updated this
)
PARTITION BY game_date
CLUSTER BY player_lookup, processor_name
OPTIONS (
  description = "Track player name resolution failures for reprocessing workflow. Lifecycle: PENDING -> RESOLVED -> REPROCESSED"
);

-- Example queries:
--
-- Get status breakdown:
-- SELECT
--   CASE
--     WHEN reprocessed_at IS NOT NULL THEN 'reprocessed'
--     WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
--     ELSE 'pending_resolution'
--   END as status,
--   COUNT(DISTINCT player_lookup) as players
-- FROM `nba_processing.registry_failures`
-- GROUP BY status
--
-- Find players ready to reprocess:
-- SELECT player_lookup, COUNT(*) as dates
-- FROM `nba_processing.registry_failures`
-- WHERE resolved_at IS NOT NULL AND reprocessed_at IS NULL
-- GROUP BY player_lookup
