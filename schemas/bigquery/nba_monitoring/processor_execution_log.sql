-- ============================================================================
-- NBA Monitoring - Processor Execution Log
-- Path: schemas/bigquery/nba_monitoring/processor_execution_log.sql
-- Created: 2026-01-21
-- ============================================================================
-- Purpose: Track processor execution for debugging and monitoring
-- Impact: Enables 30-min debugging time reduction per issue (100+ hours/year)
-- Priority: P0-4 (CRITICAL - currently no processor execution logging)
-- ============================================================================

-- ============================================================================
-- TABLE: processor_execution_log
-- ============================================================================
-- This table provides execution-level observability for all data processors.
-- It enables:
--   1. Debugging failures with execution context
--   2. Performance monitoring across processors
--   3. Correlation of errors across pipeline phases
--   4. Historical execution analysis
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_monitoring.processor_execution_log` (
  -- ============================================================================
  -- EXECUTION IDENTIFICATION (4 fields)
  -- ============================================================================
  execution_id STRING NOT NULL,                 -- Unique execution ID (UUID)
  processor_name STRING NOT NULL,               -- Processor identifier (e.g., "player_game_summary")
  phase INT64 NOT NULL,                         -- Pipeline phase (1-6)
  correlation_id STRING,                        -- Links related executions across phases

  -- ============================================================================
  -- EXECUTION SCOPE (3 fields)
  -- ============================================================================
  game_date DATE,                               -- Game date being processed (if applicable)
  season STRING,                                -- Season identifier (e.g., "2024-25")
  scope STRING,                                 -- Execution scope: "game_date", "season", "backfill"

  -- ============================================================================
  -- TIMING (3 fields)
  -- ============================================================================
  started_at TIMESTAMP NOT NULL,                -- When execution started
  completed_at TIMESTAMP,                       -- When execution completed (NULL if still running/failed)
  duration_seconds FLOAT64,                     -- Execution duration (computed: completed_at - started_at)

  -- ============================================================================
  -- EXECUTION RESULTS (4 fields)
  -- ============================================================================
  status STRING NOT NULL,                       -- Status: "success", "failure", "partial", "running"
  record_count INT64,                           -- Number of records processed
  rows_inserted INT64,                          -- Rows inserted/updated in target table
  rows_failed INT64,                            -- Rows that failed processing

  -- ============================================================================
  -- ERROR TRACKING (3 fields)
  -- ============================================================================
  error_message STRING,                         -- High-level error message
  error_type STRING,                            -- Error classification: "transient", "permanent", "unknown"
  stack_trace STRING,                           -- Full stack trace for debugging (truncated to 10KB)

  -- ============================================================================
  -- METADATA (5 fields)
  -- ============================================================================
  metadata JSON,                                -- Flexible metadata for processor-specific context
                                                 -- Examples: {"source_tables": [...], "filters": {...}, "config": {...}}
  hostname STRING,                              -- Host that ran the processor
  container_id STRING,                          -- Container ID (for Cloud Run)
  triggered_by STRING,                          -- Trigger source: "pubsub", "scheduler", "manual", "backfill"
  parent_execution_id STRING,                   -- Parent execution ID (for retry/reprocessing chains)

  -- ============================================================================
  -- RECORD METADATA (2 fields)
  -- ============================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP                          -- Updated when execution status changes
)
PARTITION BY DATE(started_at)
CLUSTER BY processor_name, game_date
OPTIONS(
  description="Execution log for all data processors. Provides debugging context, performance monitoring, and error tracking across pipeline phases.",
  partition_expiration_days=90                  -- Keep 90 days of execution history
);

-- ============================================================================
-- INDEXES
-- ============================================================================
-- Partition key: started_at (DATE)
--   - Enables efficient time-based queries
--   - Automatic partition expiration after 90 days
--   - Typical query: WHERE DATE(started_at) >= CURRENT_DATE() - 7
--
-- Cluster keys: processor_name, game_date
--   - Co-locates records for same processor
--   - Optimizes debugging queries by processor and date
--   - Typical query: WHERE processor_name = 'player_game_summary' AND game_date = '2026-01-21'
-- ============================================================================

-- ============================================================================
-- EXAMPLE ROWS
-- ============================================================================

-- Example 1: Successful Execution
/*
{
  "execution_id": "exec-20260121-player-game-summary-123456",
  "processor_name": "player_game_summary",
  "phase": 3,
  "correlation_id": "corr-20260121-123456",
  "game_date": "2026-01-21",
  "season": "2024-25",
  "scope": "game_date",
  "started_at": "2026-01-21T02:15:00Z",
  "completed_at": "2026-01-21T02:18:45Z",
  "duration_seconds": 225.0,
  "status": "success",
  "record_count": 450,
  "rows_inserted": 450,
  "rows_failed": 0,
  "error_message": null,
  "error_type": null,
  "stack_trace": null,
  "metadata": {
    "source_tables": ["nba_raw.nbac_player_boxscore"],
    "filters": {"game_date": "2026-01-21"},
    "config": {"lookback_days": 10}
  },
  "hostname": "player-game-summary-abc123",
  "container_id": "cloud-run-xyz789",
  "triggered_by": "pubsub",
  "parent_execution_id": null,
  "created_at": "2026-01-21T02:15:00Z",
  "updated_at": "2026-01-21T02:18:45Z"
}
*/

-- Example 2: Failed Execution with Error
/*
{
  "execution_id": "exec-20260121-team-defense-summary-789012",
  "processor_name": "team_defense_summary",
  "phase": 3,
  "correlation_id": "corr-20260121-123456",
  "game_date": "2026-01-21",
  "season": "2024-25",
  "scope": "game_date",
  "started_at": "2026-01-21T02:20:00Z",
  "completed_at": "2026-01-21T02:20:15Z",
  "duration_seconds": 15.0,
  "status": "failure",
  "record_count": 0,
  "rows_inserted": 0,
  "rows_failed": 0,
  "error_message": "NotFound: Table nba_raw.nbac_team_boxscore not found",
  "error_type": "permanent",
  "stack_trace": "Traceback (most recent call last):\\n  File \"/app/processors/team_defense_summary.py\", line 145...",
  "metadata": {
    "source_tables": ["nba_raw.nbac_team_boxscore"],
    "filters": {"game_date": "2026-01-21"}
  },
  "hostname": "team-defense-summary-def456",
  "container_id": "cloud-run-uvw123",
  "triggered_by": "pubsub",
  "parent_execution_id": null,
  "created_at": "2026-01-21T02:20:00Z",
  "updated_at": "2026-01-21T02:20:15Z"
}
*/

-- Example 3: Partial Success (Some Records Failed)
/*
{
  "execution_id": "exec-20260121-player-name-resolver-345678",
  "processor_name": "player_name_resolver",
  "phase": 2,
  "correlation_id": "corr-20260121-123456",
  "game_date": "2026-01-21",
  "season": "2024-25",
  "scope": "game_date",
  "started_at": "2026-01-21T02:10:00Z",
  "completed_at": "2026-01-21T02:11:30Z",
  "duration_seconds": 90.0,
  "status": "partial",
  "record_count": 500,
  "rows_inserted": 485,
  "rows_failed": 15,
  "error_message": "15 players could not be resolved to NBA canonical names",
  "error_type": "unknown",
  "stack_trace": null,
  "metadata": {
    "unresolved_players": ["Player A", "Player B", "..."],
    "source_tables": ["nba_raw.espn_boxscore"],
    "resolution_rate": 0.97
  },
  "hostname": "player-name-resolver-ghi789",
  "container_id": "cloud-run-rst456",
  "triggered_by": "pubsub",
  "parent_execution_id": null,
  "created_at": "2026-01-21T02:10:00Z",
  "updated_at": "2026-01-21T02:11:30Z"
}
*/

-- ============================================================================
-- USAGE PATTERNS
-- ============================================================================

-- Pattern 1: Log Execution Start
-- INSERT INTO `nba-props-platform.nba_monitoring.processor_execution_log`
-- (execution_id, processor_name, phase, game_date, started_at, status, correlation_id, triggered_by)
-- VALUES
-- ('exec-20260121-player-game-summary-123456', 'player_game_summary', 3, '2026-01-21',
--  CURRENT_TIMESTAMP(), 'running', 'corr-20260121-123456', 'pubsub');

-- Pattern 2: Update Execution on Success
-- UPDATE `nba-props-platform.nba_monitoring.processor_execution_log`
-- SET
--   completed_at = CURRENT_TIMESTAMP(),
--   duration_seconds = TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, SECOND),
--   status = 'success',
--   record_count = 450,
--   rows_inserted = 450,
--   updated_at = CURRENT_TIMESTAMP()
-- WHERE execution_id = 'exec-20260121-player-game-summary-123456';

-- Pattern 3: Update Execution on Failure
-- UPDATE `nba-props-platform.nba_monitoring.processor_execution_log`
-- SET
--   completed_at = CURRENT_TIMESTAMP(),
--   duration_seconds = TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, SECOND),
--   status = 'failure',
--   error_message = 'Table not found',
--   error_type = 'permanent',
--   stack_trace = '...',
--   updated_at = CURRENT_TIMESTAMP()
-- WHERE execution_id = 'exec-20260121-player-game-summary-123456';

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Query 1: Recent Failures (Last 24 Hours)
SELECT
  execution_id,
  processor_name,
  game_date,
  started_at,
  error_message,
  error_type,
  duration_seconds
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE DATE(started_at) >= CURRENT_DATE() - 1
  AND status = 'failure'
ORDER BY started_at DESC
LIMIT 50;

-- Query 2: Processor Performance Summary (Last 7 Days)
SELECT
  processor_name,
  phase,
  COUNT(*) as execution_count,
  COUNTIF(status = 'success') as success_count,
  COUNTIF(status = 'failure') as failure_count,
  COUNTIF(status = 'partial') as partial_count,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec,
  ROUND(MAX(duration_seconds), 2) as max_duration_sec,
  SUM(rows_inserted) as total_rows_inserted
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE DATE(started_at) >= CURRENT_DATE() - 7
GROUP BY processor_name, phase
ORDER BY phase, processor_name;

-- Query 3: Error Analysis by Type
SELECT
  error_type,
  COUNT(*) as error_count,
  ARRAY_AGG(DISTINCT processor_name LIMIT 10) as affected_processors,
  ARRAY_AGG(DISTINCT error_message LIMIT 5) as sample_errors
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE DATE(started_at) >= CURRENT_DATE() - 7
  AND status = 'failure'
GROUP BY error_type
ORDER BY error_count DESC;

-- Query 4: Game Date Processing Timeline
SELECT
  processor_name,
  phase,
  started_at,
  completed_at,
  status,
  duration_seconds,
  record_count
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE game_date = '2026-01-21'
  AND correlation_id = 'corr-20260121-123456'
ORDER BY phase, started_at;

-- Query 5: Long-Running Executions (>5 minutes)
SELECT
  execution_id,
  processor_name,
  game_date,
  started_at,
  duration_seconds,
  status,
  record_count
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE DATE(started_at) >= CURRENT_DATE() - 1
  AND duration_seconds > 300
ORDER BY duration_seconds DESC
LIMIT 20;

-- Query 6: Currently Running Executions
SELECT
  execution_id,
  processor_name,
  game_date,
  started_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as runtime_minutes,
  triggered_by
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE status = 'running'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY started_at;

-- ============================================================================
-- ALERT QUERIES
-- ============================================================================

-- Alert 1: Processor Failures (Last Hour)
-- Trigger: 5+ failures in 1 hour for same processor
SELECT
  processor_name,
  COUNT(*) as failure_count,
  ARRAY_AGG(error_message LIMIT 3) as sample_errors
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND status = 'failure'
GROUP BY processor_name
HAVING COUNT(*) >= 5;

-- Alert 2: Slow Executions (>10 min)
-- Trigger: Execution takes >10 minutes
SELECT
  execution_id,
  processor_name,
  game_date,
  duration_seconds,
  record_count
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND duration_seconds > 600;

-- Alert 3: Stuck Executions (>30 min still running)
-- Trigger: Execution still running after 30 minutes
SELECT
  execution_id,
  processor_name,
  game_date,
  started_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as runtime_minutes
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE status = 'running'
  AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE);

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View 1: Latest Execution Status Per Processor
CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.v_latest_processor_status` AS
SELECT
  processor_name,
  MAX(started_at) as last_execution,
  ARRAY_AGG(status ORDER BY started_at DESC LIMIT 1)[OFFSET(0)] as last_status,
  ARRAY_AGG(duration_seconds ORDER BY started_at DESC LIMIT 1)[OFFSET(0)] as last_duration_sec,
  ARRAY_AGG(error_message ORDER BY started_at DESC LIMIT 1)[OFFSET(0)] as last_error
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE DATE(started_at) >= CURRENT_DATE() - 1
GROUP BY processor_name
ORDER BY last_execution DESC;

-- View 2: Daily Execution Summary
CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.v_daily_execution_summary` AS
SELECT
  DATE(started_at) as execution_date,
  processor_name,
  phase,
  COUNT(*) as total_executions,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failure') as failures,
  COUNTIF(status = 'partial') as partials,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec,
  SUM(rows_inserted) as total_rows_inserted
FROM `nba-props-platform.nba_monitoring.processor_execution_log`
WHERE DATE(started_at) >= CURRENT_DATE() - 30
GROUP BY execution_date, processor_name, phase
ORDER BY execution_date DESC, phase, processor_name;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create nba_monitoring dataset if not exists
-- [ ] Run CREATE TABLE for processor_execution_log
-- [ ] Verify schema matches expectations (23 fields total)
-- [ ] Set partition expiration (90 days)
-- [ ] Configure clustering (processor_name, game_date)
-- [ ] Create helper views (v_latest_processor_status, v_daily_execution_summary)
-- [ ] Test INSERT and UPDATE patterns
-- [ ] Configure alerts for failures and slow executions
-- [ ] Update processor code to log execution starts and completions
-- [ ] Document integration in processor base classes
-- [ ] Set up dashboard for execution monitoring
-- ============================================================================

-- ============================================================================
-- INTEGRATION NOTES
-- ============================================================================
-- Processors should:
--   1. Generate execution_id (UUID) at start
--   2. INSERT row with status='running' before processing
--   3. UPDATE row with results on completion/failure
--   4. Include correlation_id to link related executions
--   5. Populate metadata with processor-specific context
--   6. Truncate stack_trace to 10KB max (avoid storage bloat)
-- ============================================================================
