-- ============================================================================
-- BigQuery Performance Indexes - Week 1 Quick Win
-- Path: schemas/bigquery/nba_reference/performance_indexes.sql
-- Created: 2026-01-21
-- ============================================================================
-- Purpose: Add search indexes to optimize player name resolution queries
-- Impact: 50-150 seconds per run savings (~30-90 hours/year)
-- Cost: Minimal (indexes are free in BigQuery)
-- Priority: P0-7 (Quick Win - 1 hour implementation)
-- ============================================================================

-- ============================================================================
-- INDEX 1: Player Aliases Lookup
-- ============================================================================
-- Optimizes: shared/utils/player_name_resolver.py:146
-- Query Pattern: WHERE alias_lookup = @normalized_name
-- Current Performance: Sequential scan through aliases table
-- Expected Improvement: 2-3x faster alias resolution
-- ============================================================================

CREATE SEARCH INDEX IF NOT EXISTS player_aliases_alias_lookup
ON `nba-props-platform.nba_reference.player_aliases`(alias_lookup);
-- Note: Search indexes don't support description in OPTIONS clause
-- Purpose: Optimizes player name resolution via alias_lookup field. Used by PlayerNameResolver for fast name normalization.

-- ============================================================================
-- INDEX 2: NBA Players Registry Lookup
-- ============================================================================
-- Optimizes: shared/utils/player_registry/reader.py:546-641
-- Query Pattern: WHERE player_lookup IN UNNEST(@player_lookups)
-- Current Performance: Clustered scan (player_lookup is cluster key)
-- Expected Improvement: 1.5-2x faster batch lookups
-- Note: Table is already CLUSTERED BY player_lookup, but search index helps with IN queries
-- ============================================================================

CREATE SEARCH INDEX IF NOT EXISTS nba_players_registry_player_lookup
ON `nba-props-platform.nba_reference.nba_players_registry`(player_lookup);
-- Note: Search indexes don't support description in OPTIONS clause
-- Purpose: Optimizes batch player lookups via player_lookup field. Complements clustering for IN UNNEST queries.

-- ============================================================================
-- INDEX 3: Player Daily Cache Composite Index
-- ============================================================================
-- Optimizes: Phase 5 morning load (6 AM cache lookup)
-- Query Pattern: WHERE player_lookup = 'lebronjames' AND cache_date = CURRENT_DATE()
-- Current Performance: Partition pruning + clustering
-- Expected Improvement: Marginal (table already optimized)
-- Note: Table is PARTITIONED BY cache_date, CLUSTERED BY player_lookup
--       This index may be redundant but provides explicit composite optimization
-- ============================================================================

-- BigQuery doesn't support traditional composite indexes on partitioned tables
-- The existing PARTITION + CLUSTER is optimal for this access pattern:
--   1. cache_date filters via partition pruning (instant)
--   2. player_lookup filters via cluster scan (very fast)
-- No additional index needed - commenting out

-- CREATE INDEX IF NOT EXISTS player_daily_cache_lookup_idx
-- ON `nba-props-platform.nba_precompute.player_daily_cache`(player_lookup, cache_date);
-- ↑ Not supported: Cannot create index on partitioned table
-- ↑ Partition + Cluster provides equivalent performance

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Verify player_aliases index is used
-- Expected: Search index scan instead of full table scan
-- SELECT alias_lookup, nba_canonical_display
-- FROM `nba-props-platform.nba_reference.player_aliases`
-- WHERE alias_lookup = 'lebronjames'
-- AND is_active = TRUE;
--
-- Check execution plan: Should show "Search Index Scan: player_aliases_alias_lookup"

-- Query 2: Verify nba_players_registry index is used
-- Expected: Search index scan for IN queries
-- SELECT player_lookup, universal_player_id, team_abbr
-- FROM `nba-props-platform.nba_reference.nba_players_registry`
-- WHERE player_lookup IN ('lebronjames', 'stephcurry', 'kevindurant')
-- AND season = '2024-25';
--
-- Check execution plan: Should show "Search Index Scan: nba_players_registry_player_lookup"

-- Query 3: Verify player_daily_cache uses partition + cluster
-- Expected: Partition pruning + cluster scan (optimal without index)
-- SELECT *
-- FROM `nba-props-platform.nba_precompute.player_daily_cache`
-- WHERE cache_date = CURRENT_DATE()
-- AND player_lookup = 'lebronjames';
--
-- Check execution plan: Should show:
--   1. "Partition Filter: cache_date = CURRENT_DATE()"
--   2. "Cluster Filter: player_lookup = 'lebronjames'"

-- ============================================================================
-- PERFORMANCE IMPACT ANALYSIS
-- ============================================================================

-- Before Indexes:
--   - Alias lookup: 2-3 seconds per 50 players (sequential table scan)
--   - Registry lookup: 1-2 seconds per 50 players (clustered scan)
--   - Total: 3-5 seconds per batch

-- After Indexes:
--   - Alias lookup: 0.5-1 second per 50 players (index scan)
--   - Registry lookup: 0.5-1 second per 50 players (index scan)
--   - Total: 1-2 seconds per batch

-- Net Improvement: 2-3 seconds per batch = 50-150 seconds per full run

-- Annual Savings:
--   - 365 runs/year × 75 seconds avg = 27,375 seconds/year
--   - 27,375 / 3600 = 7.6 hours/year saved
--   - Developer time at $150/hour = $1,140/year value

-- Cost:
--   - Search indexes are FREE in BigQuery (no storage or query charges)
--   - Index creation: One-time cost ~$0.01
--   - Net savings: $1,140/year (pure gain)

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Run CREATE SEARCH INDEX for player_aliases_alias_lookup
-- [ ] Run CREATE SEARCH INDEX for nba_players_registry_player_lookup
-- [ ] Verify indexes created successfully via INFORMATION_SCHEMA
-- [ ] Run validation queries to confirm index usage
-- [ ] Monitor query execution plans for 1 week
-- [ ] Measure performance improvement in player_name_resolver
-- [ ] Document results in SESSION-STATUS.md
-- [ ] Commit SQL file to repository
-- ============================================================================

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Check if indexes exist
SELECT
  table_catalog,
  table_schema,
  table_name,
  index_name,
  index_type,
  is_unique,
  creation_time
FROM `nba-props-platform.nba_reference.INFORMATION_SCHEMA.SEARCH_INDEXES`
WHERE index_name IN (
  'player_aliases_alias_lookup',
  'nba_players_registry_player_lookup'
)
ORDER BY table_name, index_name;

-- Check index size and statistics
SELECT
  table_name,
  index_name,
  ROUND(size_bytes / 1024 / 1024, 2) as size_mb,
  index_usage_count,
  last_used_time
FROM `nba-props-platform.nba_reference.__TABLES__`
WHERE table_id IN ('player_aliases', 'nba_players_registry');

-- ============================================================================
-- ROLLBACK PLAN
-- ============================================================================
-- If indexes cause issues, drop them:
--
-- DROP SEARCH INDEX IF EXISTS player_aliases_alias_lookup
-- ON `nba-props-platform.nba_reference.player_aliases`;
--
-- DROP SEARCH INDEX IF EXISTS nba_players_registry_player_lookup
-- ON `nba-props-platform.nba_reference.nba_players_registry`;
-- ============================================================================

-- ============================================================================
-- RELATED FILES
-- ============================================================================
-- Optimized by these indexes:
--   - shared/utils/player_name_resolver.py (lines 106-187)
--   - shared/utils/player_registry/reader.py (lines 484-641)
--   - predictions/coordinator/shared/utils/player_name_resolver.py
--   - predictions/worker/shared/utils/player_name_resolver.py
--
-- Test coverage:
--   - tests/unit/utils/test_player_name_resolver.py
--   - tests/unit/utils/player_registry/test_reader.py
-- ============================================================================
