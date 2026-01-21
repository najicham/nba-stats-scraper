-- File: schemas/bigquery/mlb_reference/unresolved_players_table.sql
-- Description: Unresolved MLB player tracking table for registry resolution
-- Created: 2026-01-20
-- Purpose: Track unresolved MLB players for systematic resolution and data quality monitoring

-- =============================================================================
-- Table: Unresolved MLB Players - Resolution Tracking
-- =============================================================================
-- This table tracks MLB players that couldn't be resolved by the player registry
-- reader during prediction processing. It enables:
-- - Data loss prevention (all unresolved players are persisted)
-- - Systematic resolution (track occurrence counts and patterns)
-- - Data quality monitoring (identify registry gaps)
-- - Trend analysis (which players/sources have resolution issues)
--
-- Resolution workflow:
-- 1. Player lookup fails in mlb_reference.mlb_player_registry
-- 2. UnresolvedPlayer object created with context
-- 3. Flushed to this table periodically for review
-- 4. Manual or automated resolution adds player to registry
-- 5. Future lookups succeed
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_reference.unresolved_players` (
    -- =============================================================================
    -- PLAYER IDENTIFICATION
    -- =============================================================================
    player_lookup STRING NOT NULL,       -- Normalized player name used for lookup
                                        -- Format: lowercase, no spaces (e.g., "loganwebb")

    player_type STRING NOT NULL,        -- Player type from source:
                                        --   'PITCHER' - pitcher stats/predictions
                                        --   'BATTER' - batter stats/predictions
                                        --   'UNKNOWN' - type not determined

    -- =============================================================================
    -- SOURCE & CONTEXT
    -- =============================================================================
    source STRING NOT NULL,             -- Source that encountered unresolved player
                                        -- Examples:
                                        --   'pitcher_strikeouts_predictor'
                                        --   'batter_hits_predictor'
                                        --   'mlb_game_processor'
                                        --   'bdl_pitcher_stats_processor'

    -- =============================================================================
    -- TRACKING METADATA
    -- =============================================================================
    first_seen TIMESTAMP NOT NULL,      -- When first encountered by this source
    occurrence_count INT64 NOT NULL,    -- Number of times seen in this flush
                                        -- NOTE: Represents count since last flush,
                                        -- not total historical count

    reported_at TIMESTAMP NOT NULL      -- When this record was inserted
                                        -- Multiple records may exist for same player
                                        -- from different flush cycles
)
PARTITION BY DATE(reported_at)
CLUSTER BY player_lookup, player_type, source
OPTIONS (
  description = "Tracks unresolved MLB players for registry gap analysis and systematic resolution. Records are inserted during periodic flushes from prediction processors.",
  partition_expiration_days = 90
);

-- =============================================================================
-- INDEXES & OPTIMIZATION
-- =============================================================================
-- Partitioning by reported_at (date) allows efficient date-range queries and auto-cleanup
-- Clustering by player_lookup, player_type, source optimizes:
--   1. Finding all occurrences of a specific player (WHERE player_lookup = 'playername')
--   2. Filtering by player type (WHERE player_type = 'PITCHER')
--   3. Analyzing by source (WHERE source = 'pitcher_strikeouts_predictor')
--
-- Partition expiration (90 days) automatically cleans up old unresolved records
-- after they've been reviewed and (hopefully) resolved.

-- =============================================================================
-- COMMON QUERIES
-- =============================================================================

-- Get unresolved players in last 7 days with total occurrences
-- SELECT
--   player_lookup,
--   player_type,
--   source,
--   COUNT(*) as reports,
--   SUM(occurrence_count) as total_occurrences,
--   MIN(first_seen) as earliest_seen,
--   MAX(reported_at) as latest_report
-- FROM `nba-props-platform.mlb_reference.unresolved_players`
-- WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY player_lookup, player_type, source
-- ORDER BY total_occurrences DESC
-- LIMIT 50;

-- Find high-frequency unresolved players (top 20)
-- SELECT
--   player_lookup,
--   player_type,
--   COUNT(DISTINCT source) as source_count,
--   SUM(occurrence_count) as total_occurrences,
--   ARRAY_AGG(DISTINCT source LIMIT 5) as sources
-- FROM `nba-props-platform.mlb_reference.unresolved_players`
-- WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
-- GROUP BY player_lookup, player_type
-- HAVING total_occurrences >= 10
-- ORDER BY total_occurrences DESC
-- LIMIT 20;

-- Analyze by source to identify problematic data sources
-- SELECT
--   source,
--   player_type,
--   COUNT(DISTINCT player_lookup) as unique_players,
--   SUM(occurrence_count) as total_occurrences
-- FROM `nba-props-platform.mlb_reference.unresolved_players`
-- WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY source, player_type
-- ORDER BY total_occurrences DESC;

-- Find players that need urgent resolution (multiple recent reports)
-- SELECT
--   player_lookup,
--   player_type,
--   COUNT(*) as report_count,
--   SUM(occurrence_count) as total_occurrences,
--   ARRAY_AGG(source LIMIT 5) as sources,
--   MAX(reported_at) as last_seen
-- FROM `nba-props-platform.mlb_reference.unresolved_players`
-- WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
-- GROUP BY player_lookup, player_type
-- HAVING report_count >= 3
-- ORDER BY total_occurrences DESC;

-- Check which players were resolved (no longer appearing)
-- WITH recent_unresolved AS (
--   SELECT DISTINCT player_lookup, player_type
--   FROM `nba-props-platform.mlb_reference.unresolved_players`
--   WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- ),
-- older_unresolved AS (
--   SELECT DISTINCT player_lookup, player_type
--   FROM `nba-props-platform.mlb_reference.unresolved_players`
--   WHERE reported_at BETWEEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
--                        AND TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- )
-- SELECT
--   o.player_lookup,
--   o.player_type,
--   'Resolved (no longer appearing)' as status
-- FROM older_unresolved o
-- LEFT JOIN recent_unresolved r USING (player_lookup, player_type)
-- WHERE r.player_lookup IS NULL
-- ORDER BY o.player_lookup;

-- Daily trend of unresolved players
-- SELECT
--   DATE(reported_at) as report_date,
--   COUNT(DISTINCT player_lookup) as unique_players,
--   SUM(occurrence_count) as total_occurrences,
--   COUNT(*) as total_reports
-- FROM `nba-props-platform.mlb_reference.unresolved_players`
-- WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
-- GROUP BY report_date
-- ORDER BY report_date DESC;

-- =============================================================================
-- RESOLUTION WORKFLOW
-- =============================================================================
-- 1. Run one of the queries above to identify unresolved players
-- 2. For each player:
--    a. Search mlb_reference.mlb_player_registry to confirm missing
--    b. Look up player on baseball-reference.com or MLB.com
--    c. Add to mlb_player_registry with correct universal_player_id
--    d. Optionally add aliases if name variations exist
-- 3. Monitor this table - resolved players should stop appearing in new reports
-- 4. Old records auto-expire after 90 days via partition expiration

-- =============================================================================
-- INTEGRATION NOTES
-- =============================================================================
-- This table is populated by:
--   - predictions/coordinator/shared/utils/mlb_player_registry/reader.py
--   - MLBRegistryReader.flush_unresolved_to_bigquery() method
--
-- Called during:
--   - End of prediction processing
--   - Periodic flushes during long-running processes
--   - Manual flush via CLI/admin tools
--
-- If inserts fail:
--   - Errors are logged but don't fail the prediction process
--   - Unresolved players are still logged to Cloud Logging as backup
--   - Check IAM permissions on the table if inserts consistently fail
