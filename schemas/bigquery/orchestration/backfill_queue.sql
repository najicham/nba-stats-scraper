-- ============================================================================
-- NBA Props Platform - Backfill Queue Table
-- Data Quality Self-Healing System
-- ============================================================================
-- Table: nba_orchestration.backfill_queue
-- Purpose: Queue for automated backfill tasks triggered by quality issues
-- Update: On-demand when quality issues detected
-- Retention: 90 days
--
-- Version: 1.0 (Initial implementation)
-- Date: January 2026
-- Status: Production-Ready
--
-- Related Documents:
-- - docs/08-projects/current/data-quality-self-healing/README.md
-- ============================================================================

-- ============================================================================
-- TABLE DEFINITION
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.backfill_queue` (
  -- ============================================================================
  -- IDENTIFIERS (2 fields)
  -- ============================================================================
  queue_id STRING NOT NULL,                         -- Unique queue entry ID (UUID)
                                                     -- Example: '550e8400-e29b-41d4-a716-446655440000'

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When entry was created

  -- ============================================================================
  -- TARGET (2 fields)
  -- ============================================================================
  table_name STRING NOT NULL,                       -- Table to backfill
                                                     -- Example: 'player_game_summary'

  game_date DATE NOT NULL,                          -- Date to backfill
                                                     -- Example: '2026-01-22'

  -- ============================================================================
  -- REASON (4 fields)
  -- ============================================================================
  reason STRING NOT NULL,                           -- Why backfill was triggered
                                                     -- Example: 'High zero-points rate: 46.8%'

  triggered_by STRING DEFAULT 'auto',               -- What triggered this
                                                     -- Values: 'auto', 'manual', 'incident', 'validation'

  quality_metric STRING,                            -- Metric that triggered this
                                                     -- Example: 'pct_zero_points'

  quality_value FLOAT64,                            -- Value that triggered this
                                                     -- Example: 46.8

  -- ============================================================================
  -- SCHEDULING (3 fields)
  -- ============================================================================
  priority INT64 DEFAULT 0,                         -- Higher = more urgent
                                                     -- 0 = normal, 1 = elevated, 2 = critical

  scheduled_for TIMESTAMP,                          -- Don't run before this time
                                                     -- Null = run immediately

  dependencies ARRAY<STRING>,                       -- Other queue_ids that must complete first
                                                     -- Example: ['queue-123', 'queue-456']

  -- ============================================================================
  -- EXECUTION (6 fields)
  -- ============================================================================
  status STRING DEFAULT 'PENDING',                  -- Current status
                                                     -- Values: 'PENDING', 'RUNNING', 'COMPLETED',
                                                     --         'FAILED', 'CANCELLED', 'SKIPPED'

  attempts INT64 DEFAULT 0,                         -- Number of attempts
                                                     -- Example: 2

  max_attempts INT64 DEFAULT 3,                     -- Max retry attempts

  last_attempt_at TIMESTAMP,                        -- When last attempted

  completed_at TIMESTAMP,                           -- When completed successfully

  error_message STRING,                             -- Error if failed
                                                     -- Example: 'Raw data not available'

  -- ============================================================================
  -- RESULTS (3 fields)
  -- ============================================================================
  records_processed INT64,                          -- Records affected
                                                     -- Example: 250

  duration_seconds INT64,                           -- How long it took
                                                     -- Example: 120

  post_backfill_metric FLOAT64,                     -- Metric value after backfill
                                                     -- Example: 8.5 (improved from 46.8)

  -- ============================================================================
  -- METADATA (2 fields)
  -- ============================================================================
  worker_id STRING,                                 -- Which worker processed this
                                                     -- Example: 'backfill-worker-001'

  quality_event_id STRING                           -- Link to data_quality_events.event_id
                                                     -- Example: '550e8400-e29b-41d4-a716-446655440000'
)
PARTITION BY DATE(created_at)
CLUSTER BY status, table_name
OPTIONS(
  description="Queue for automated backfill tasks. Workers poll this table and execute pending backfills.",
  partition_expiration_days=90
);

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Backfill queue status
SELECT
  status,
  table_name,
  COUNT(*) as count,
  MIN(created_at) as oldest,
  MAX(created_at) as newest,
  ROUND(AVG(attempts), 1) as avg_attempts
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY
  CASE status
    WHEN 'RUNNING' THEN 0
    WHEN 'PENDING' THEN 1
    WHEN 'FAILED' THEN 2
    ELSE 3
  END,
  table_name;

-- Query 2: Pending backfills ready to run
SELECT
  queue_id,
  table_name,
  game_date,
  reason,
  priority,
  attempts,
  created_at
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE status = 'PENDING'
  AND attempts < max_attempts
  AND (scheduled_for IS NULL OR scheduled_for <= CURRENT_TIMESTAMP())
ORDER BY priority DESC, created_at ASC
LIMIT 10;

-- Query 3: Failed backfills needing attention
SELECT
  queue_id,
  table_name,
  game_date,
  reason,
  attempts,
  last_attempt_at,
  error_message
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE status = 'FAILED'
   OR (status = 'PENDING' AND attempts >= max_attempts)
ORDER BY created_at DESC
LIMIT 20;

-- Query 4: Backfill success rate
SELECT
  DATE(created_at) as date,
  COUNT(*) as total,
  COUNTIF(status = 'COMPLETED') as completed,
  COUNTIF(status = 'FAILED') as failed,
  ROUND(100.0 * COUNTIF(status = 'COMPLETED') / COUNT(*), 1) as success_rate_pct,
  ROUND(AVG(CASE WHEN status = 'COMPLETED' THEN duration_seconds END), 0) as avg_duration_sec
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY 1 DESC;

-- Query 5: Quality improvement from backfills
SELECT
  table_name,
  quality_metric,
  AVG(quality_value) as avg_before,
  AVG(post_backfill_metric) as avg_after,
  AVG(quality_value - post_backfill_metric) as avg_improvement
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE status = 'COMPLETED'
  AND post_backfill_metric IS NOT NULL
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1, 2
ORDER BY avg_improvement DESC;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Active backfill queue
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_active_backfill_queue` AS
SELECT
  queue_id,
  table_name,
  game_date,
  reason,
  status,
  priority,
  attempts,
  created_at,
  last_attempt_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, MINUTE) as minutes_in_queue
FROM `nba-props-platform.nba_orchestration.backfill_queue`
WHERE status IN ('PENDING', 'RUNNING')
ORDER BY
  CASE status WHEN 'RUNNING' THEN 0 ELSE 1 END,
  priority DESC,
  created_at ASC;

-- ============================================================================
-- SAMPLE ROWS
-- ============================================================================

/*
-- Sample: Pending backfill
{
  "queue_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-01-30T08:00:05Z",
  "table_name": "player_game_summary",
  "game_date": "2026-01-22",
  "reason": "High zero-points rate: 46.8%",
  "triggered_by": "auto",
  "quality_metric": "pct_zero_points",
  "quality_value": 46.8,
  "priority": 1,
  "status": "PENDING",
  "attempts": 0,
  "max_attempts": 3
}

-- Sample: Completed backfill
{
  "queue_id": "550e8400-e29b-41d4-a716-446655440001",
  "created_at": "2026-01-30T07:00:00Z",
  "table_name": "player_game_summary",
  "game_date": "2026-01-21",
  "reason": "High zero-points rate: 35.2%",
  "triggered_by": "auto",
  "quality_metric": "pct_zero_points",
  "quality_value": 35.2,
  "priority": 0,
  "status": "COMPLETED",
  "attempts": 1,
  "last_attempt_at": "2026-01-30T07:05:00Z",
  "completed_at": "2026-01-30T07:07:30Z",
  "records_processed": 280,
  "duration_seconds": 150,
  "post_backfill_metric": 7.8,
  "worker_id": "backfill-worker-001"
}
*/

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
