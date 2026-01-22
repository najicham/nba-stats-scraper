-- File: schemas/bigquery/nba_orchestration/phase_execution_log.sql
-- ============================================================================
-- NBA Props Platform - Phase Execution Logging
-- ============================================================================
-- Purpose: Track orchestrator execution timing at phase boundaries
-- Update: Every phase transition (when orchestrators run)
-- Entities: Phase 2→3, 3→4, 4→5 orchestrators
-- Retention: 90 days (partition expiration)
--
-- Version: 1.0
-- Date: January 22, 2026
-- Status: Production-Ready
--
-- Use Case: Fill latency tracking blind spot between phases
--
-- Example Queries:
--   1. Phase 2→3 execution timing:
--      SELECT game_date, duration_seconds, games_processed, status
--      FROM `nba-props-platform.nba_orchestration.phase_execution_log`
--      WHERE phase_name = 'phase2_to_phase3'
--      AND game_date >= '2026-01-15'
--      ORDER BY execution_timestamp DESC;
--
--   2. Find slow executions (>5 seconds):
--      SELECT phase_name, game_date, duration_seconds, status, metadata
--      FROM `nba-props-platform.nba_orchestration.phase_execution_log`
--      WHERE duration_seconds > 5.0
--      ORDER BY duration_seconds DESC;
--
--   3. Deadline exceeded events:
--      SELECT game_date, execution_timestamp, duration_seconds,
--             JSON_VALUE(metadata, '$.missing_processors') as missing_processors,
--             JSON_VALUE(metadata, '$.elapsed_minutes') as elapsed_minutes
--      FROM `nba-props-platform.nba_orchestration.phase_execution_log`
--      WHERE status = 'deadline_exceeded'
--      ORDER BY execution_timestamp DESC;
--
-- Dependencies: None (foundational logging table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.phase_execution_log` (
  -- ==========================================================================
  -- EXECUTION TRACKING (4 fields)
  -- ==========================================================================

  execution_timestamp TIMESTAMP NOT NULL,
    -- When the orchestrator function was invoked (UTC)
    -- Format: ISO 8601 timestamp
    -- Example: "2026-01-22T07:30:15.123Z"
    -- Used for: Tracking execution timing, identifying gaps

  phase_name STRING NOT NULL,
    -- Name of the phase transition
    -- Format: "phase[X]_to_phase[Y]"
    -- Examples:
    --   - "phase2_to_phase3" (raw to analytics)
    --   - "phase3_to_phase4" (analytics to precompute)
    --   - "phase4_to_phase5" (precompute to predictions)
    -- Used for: Grouping by phase, identifying bottlenecks

  game_date DATE NOT NULL,
    -- Date being processed
    -- Format: YYYY-MM-DD
    -- Example: "2026-01-21"
    -- Used for: Partitioning, filtering by date

  correlation_id STRING,
    -- Links back to scraper_execution_log
    -- Format: 8-character hex UUID
    -- Example: "a1b2c3d4"
    -- Used for: End-to-end tracing from scraper to predictions

  -- ==========================================================================
  -- TIMING METRICS (2 fields)
  -- ==========================================================================

  start_time TIMESTAMP NOT NULL,
    -- When the phase work actually started (UTC)
    -- For monitoring orchestrators, this is when first processor completed
    -- For active orchestrators, this is when triggering logic began
    -- Used for: Calculating phase duration, gap analysis

  duration_seconds FLOAT64 NOT NULL,
    -- How long the orchestrator execution took (seconds)
    -- Calculated as: (execution_timestamp - start_time)
    -- Examples:
    --   - 0.234 (normal execution, <1 second)
    --   - 45.678 (slow execution, investigate)
    --   - 1800.0 (deadline exceeded, 30 minutes)
    -- Used for: Performance monitoring, alerting on slow executions

  -- ==========================================================================
  -- COMPLETION TRACKING (2 fields)
  -- ==========================================================================

  games_processed INT64,
    -- Number of games/processors completed
    -- Examples:
    --   - 6 (all Phase 2 processors complete)
    --   - 5 (all Phase 3 processors complete)
    --   - 4 (partial completion, deadline exceeded)
    -- Used for: Monitoring completion rates, partial execution tracking

  status STRING NOT NULL,
    -- Execution status
    -- Values:
    --   - "complete": All expected processors/games completed
    --   - "partial": Triggered with incomplete data
    --   - "deadline_exceeded": Timeout occurred, proceeding with partial
    -- Used for: Filtering by execution outcome, alerting

  -- ==========================================================================
  -- METADATA (1 field)
  -- ==========================================================================

  metadata JSON,
    -- Additional context about execution
    -- Structure (varies by phase and status):
    -- {
    --   "completed_processors": ["proc1", "proc2", ...],  // Which processors finished
    --   "missing_processors": ["proc3", ...],              // Which didn't (if partial)
    --   "trigger_reason": "all_complete",                  // Why triggered
    --   "orchestrator_mode": "monitoring_only",            // Orchestrator configuration
    --   "elapsed_minutes": 45.2,                           // For deadline_exceeded
    --   "deadline_minutes": 30                             // For deadline_exceeded
    -- }
    -- Used for: Debugging, detailed analysis, alerting context

  -- ==========================================================================
  -- AUDIT FIELDS (1 field)
  -- ==========================================================================

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- When this record was written to BigQuery
    -- Auto-populated by BigQuery
    -- Used for: Data freshness tracking, debugging late writes
)
PARTITION BY game_date
CLUSTER BY phase_name, status, execution_timestamp
OPTIONS(
  description="Phase execution timing log - tracks orchestrator execution at phase boundaries",
  labels=[("team", "data-engineering"), ("purpose", "orchestration-monitoring")],
  partition_expiration_days=90
);

-- ============================================================================
-- INDEXES (for query performance)
-- ============================================================================

-- Note: BigQuery doesn't have explicit indexes, but clustering provides similar benefits
-- Clustered by: phase_name, status, execution_timestamp
-- Common query patterns:
--   1. Filter by phase_name → uses clustering
--   2. Filter by status → uses clustering
--   3. Order by execution_timestamp → uses clustering
--   4. Partition by game_date → uses partitioning

-- ============================================================================
-- SAMPLE DATA (for development/testing)
-- ============================================================================

-- Example 1: Normal execution (all processors complete)
-- INSERT INTO `nba-props-platform.nba_orchestration.phase_execution_log`
-- (execution_timestamp, phase_name, game_date, correlation_id, start_time,
--  duration_seconds, games_processed, status, metadata)
-- VALUES (
--   TIMESTAMP('2026-01-22 07:30:15.123 UTC'),
--   'phase2_to_phase3',
--   '2026-01-21',
--   'abc123de',
--   TIMESTAMP('2026-01-22 07:30:14.890 UTC'),
--   0.233,
--   6,
--   'complete',
--   JSON '{"completed_processors": ["bdl_player_boxscores", "nbac_gamebook_player_stats",
--           "odds_api_game_lines", "nbac_schedule", "bigdataball_play_by_play", "br_rosters_current"],
--          "trigger_reason": "all_complete", "orchestrator_mode": "monitoring_only"}'
-- );

-- Example 2: Deadline exceeded (partial completion)
-- INSERT INTO `nba-props-platform.nba_orchestration.phase_execution_log`
-- (execution_timestamp, phase_name, game_date, correlation_id, start_time,
--  duration_seconds, games_processed, status, metadata)
-- VALUES (
--   TIMESTAMP('2026-01-22 08:00:45.678 UTC'),
--   'phase2_to_phase3',
--   '2026-01-21',
--   'def456gh',
--   TIMESTAMP('2026-01-22 07:30:45.678 UTC'),
--   1800.0,
--   4,
--   'deadline_exceeded',
--   JSON '{"completed_processors": ["bdl_player_boxscores", "nbac_gamebook_player_stats",
--           "odds_api_game_lines", "nbac_schedule"],
--          "missing_processors": ["bigdataball_play_by_play", "br_rosters_current"],
--          "elapsed_minutes": 30.0, "deadline_minutes": 30,
--          "trigger_reason": "deadline_exceeded"}'
-- );

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Query 1: Average execution time by phase (last 7 days)
-- SELECT
--   phase_name,
--   COUNT(*) as execution_count,
--   ROUND(AVG(duration_seconds), 3) as avg_duration_seconds,
--   ROUND(MAX(duration_seconds), 3) as max_duration_seconds,
--   ROUND(MIN(duration_seconds), 3) as min_duration_seconds,
--   COUNTIF(status = 'complete') as complete_count,
--   COUNTIF(status = 'deadline_exceeded') as timeout_count
-- FROM `nba-props-platform.nba_orchestration.phase_execution_log`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY phase_name
-- ORDER BY phase_name;

-- Query 2: Find gaps between phase executions
-- WITH phase_executions AS (
--   SELECT
--     phase_name,
--     game_date,
--     execution_timestamp,
--     LAG(execution_timestamp) OVER (PARTITION BY game_date ORDER BY execution_timestamp) as prev_execution,
--     status
--   FROM `nba-props-platform.nba_orchestration.phase_execution_log`
--   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- )
-- SELECT
--   game_date,
--   phase_name,
--   execution_timestamp,
--   prev_execution,
--   TIMESTAMP_DIFF(execution_timestamp, prev_execution, SECOND) as gap_seconds,
--   status
-- FROM phase_executions
-- WHERE prev_execution IS NOT NULL
--   AND TIMESTAMP_DIFF(execution_timestamp, prev_execution, SECOND) > 300  -- >5 minute gaps
-- ORDER BY gap_seconds DESC;

-- Query 3: Deadline exceeded analysis
-- SELECT
--   game_date,
--   execution_timestamp,
--   duration_seconds / 60 as duration_minutes,
--   games_processed,
--   JSON_VALUE(metadata, '$.missing_processors') as missing_processors,
--   JSON_VALUE(metadata, '$.elapsed_minutes') as elapsed_minutes,
--   JSON_VALUE(metadata, '$.deadline_minutes') as deadline_minutes
-- FROM `nba-props-platform.nba_orchestration.phase_execution_log`
-- WHERE status = 'deadline_exceeded'
-- ORDER BY execution_timestamp DESC;

-- ============================================================================
-- DEPLOYMENT NOTES
-- ============================================================================

-- To deploy this table:
--   bq mk --table \
--     --project_id=nba-props-platform \
--     --time_partitioning_field=game_date \
--     --time_partitioning_expiration=7776000 \
--     --clustering_fields=phase_name,status,execution_timestamp \
--     --description="Phase execution timing log - tracks orchestrator execution at phase boundaries" \
--     --label=team:data-engineering \
--     --label=purpose:orchestration-monitoring \
--     nba_orchestration.phase_execution_log \
--     schemas/bigquery/nba_orchestration/phase_execution_log.sql

-- Or use the schema file directly:
--   bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/phase_execution_log.sql

-- ============================================================================
-- CHANGELOG
-- ============================================================================

-- Version 1.0 (2026-01-22)
--   - Initial schema
--   - Supports Phase 2→3 execution logging
--   - Tracks timing, completion, and deadline exceeded events
--   - Partitioned by game_date, clustered by phase_name/status/execution_timestamp
