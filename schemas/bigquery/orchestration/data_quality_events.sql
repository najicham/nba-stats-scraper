-- ============================================================================
-- NBA Props Platform - Data Quality Events (Audit Log)
-- Data Quality Self-Healing System
-- ============================================================================
-- Table: nba_orchestration.data_quality_events
-- Purpose: Audit log for data quality issues, detection, and remediation
-- Update: Real-time as quality events occur
-- Retention: 365 days
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

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.data_quality_events` (
  -- ============================================================================
  -- IDENTIFIERS (3 fields)
  -- ============================================================================
  event_id STRING NOT NULL,                         -- Unique event ID (UUID)
                                                     -- Example: '550e8400-e29b-41d4-a716-446655440000'

  event_timestamp TIMESTAMP NOT NULL,               -- When event occurred
                                                     -- Example: '2026-01-30T08:00:00Z'

  event_type STRING NOT NULL,                       -- Type of event
                                                     -- Values: 'QUALITY_ISSUE_DETECTED',
                                                     --         'BACKFILL_QUEUED',
                                                     --         'BACKFILL_STARTED',
                                                     --         'BACKFILL_COMPLETED',
                                                     --         'BACKFILL_FAILED',
                                                     --         'SELF_HEALED',
                                                     --         'VALIDATION_BLOCKED',
                                                     --         'ALERT_SENT',
                                                     --         'MANUAL_FIX_APPLIED'

  -- ============================================================================
  -- CONTEXT (5 fields)
  -- ============================================================================
  table_name STRING,                                -- Affected table
                                                     -- Example: 'player_game_summary'

  game_date DATE,                                   -- Affected date (if applicable)
                                                     -- Example: '2026-01-22'

  metric_name STRING,                               -- Quality metric that triggered event
                                                     -- Example: 'pct_zero_points', 'pct_dnp_marked'

  metric_value FLOAT64,                             -- Value that triggered the event
                                                     -- Example: 45.0 (45% zero points)

  threshold_breached STRING,                        -- Which threshold was breached
                                                     -- Values: 'warning', 'critical', null
                                                     -- Example: 'critical'

  -- ============================================================================
  -- DETAILS (4 fields)
  -- ============================================================================
  severity STRING NOT NULL,                         -- Event severity
                                                     -- Values: 'INFO', 'WARNING', 'CRITICAL'
                                                     -- Example: 'CRITICAL'

  description STRING NOT NULL,                      -- Human-readable description
                                                     -- Example: 'High zero-points rate detected: 45%'

  details_json STRING,                              -- Additional details as JSON
                                                     -- Example: '{"records_affected": 150, "expected": 8}'

  resolution_status STRING,                         -- Resolution status
                                                     -- Values: 'PENDING', 'IN_PROGRESS', 'RESOLVED',
                                                     --         'FAILED', 'MANUAL_REQUIRED', null
                                                     -- Example: 'RESOLVED'

  -- ============================================================================
  -- REMEDIATION TRACKING (4 fields)
  -- ============================================================================
  backfill_queue_id STRING,                         -- Reference to backfill_queue.queue_id
                                                     -- Null if not a backfill event
                                                     -- Example: '550e8400-e29b-41d4-a716-446655440001'

  triggered_by STRING,                              -- What triggered this event
                                                     -- Values: 'daily_check', 'validation_failure',
                                                     --         'manual', 'cascade', 'alert'
                                                     -- Example: 'daily_check'

  related_event_id STRING,                          -- Parent event ID (for event chains)
                                                     -- Example: links BACKFILL_COMPLETED to QUALITY_ISSUE_DETECTED

  duration_seconds INT64,                           -- Duration for completion events
                                                     -- Example: 120 (2 minutes for backfill)

  -- ============================================================================
  -- METADATA (3 fields)
  -- ============================================================================
  processor_name STRING,                            -- Processor that detected/fixed issue
                                                     -- Example: 'player_game_summary_processor'

  session_id STRING,                                -- Processing session ID
                                                     -- Example: 'session_20260130_080000'

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() -- Row creation timestamp
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY event_type, table_name, game_date
OPTIONS(
  description="Audit log for data quality events including detection, alerting, and remediation. Provides visibility into when data quality was low and when it self-healed.",
  partition_expiration_days=365
);

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Recent quality issues
-- Shows all quality issues detected in the last 7 days
SELECT
  event_timestamp,
  table_name,
  game_date,
  metric_name,
  metric_value,
  severity,
  description,
  resolution_status
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_type = 'QUALITY_ISSUE_DETECTED'
  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY event_timestamp DESC;

-- Query 2: Self-healing success rate
-- Shows how often issues are automatically resolved
SELECT
  DATE(event_timestamp) as date,
  COUNT(CASE WHEN event_type = 'QUALITY_ISSUE_DETECTED' THEN 1 END) as issues_detected,
  COUNT(CASE WHEN event_type = 'SELF_HEALED' THEN 1 END) as self_healed,
  COUNT(CASE WHEN event_type = 'BACKFILL_FAILED' THEN 1 END) as backfill_failed,
  ROUND(
    100.0 * COUNT(CASE WHEN event_type = 'SELF_HEALED' THEN 1 END) /
    NULLIF(COUNT(CASE WHEN event_type = 'QUALITY_ISSUE_DETECTED' THEN 1 END), 0),
    1
  ) as self_heal_rate_pct
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY 1 DESC;

-- Query 3: Event chain for a specific issue
-- Trace the full lifecycle of a quality issue
SELECT
  event_timestamp,
  event_type,
  severity,
  description,
  resolution_status,
  duration_seconds
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_id = @event_id
   OR related_event_id = @event_id
ORDER BY event_timestamp ASC;

-- Query 4: Unresolved issues needing attention
-- Shows issues that haven't been resolved
SELECT
  event_id,
  event_timestamp,
  table_name,
  game_date,
  metric_name,
  metric_value,
  severity,
  description,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR) as hours_unresolved
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_type = 'QUALITY_ISSUE_DETECTED'
  AND resolution_status IN ('PENDING', 'FAILED', 'MANUAL_REQUIRED')
  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY severity DESC, event_timestamp ASC;

-- Query 5: Quality issue trends by table
-- Shows which tables have the most issues
SELECT
  table_name,
  metric_name,
  COUNT(*) as issue_count,
  AVG(metric_value) as avg_metric_value,
  COUNTIF(resolution_status = 'RESOLVED') as resolved_count,
  COUNTIF(resolution_status IN ('PENDING', 'FAILED')) as unresolved_count
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_type = 'QUALITY_ISSUE_DETECTED'
  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY table_name, metric_name
ORDER BY issue_count DESC;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Data quality timeline for dashboard
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_data_quality_timeline` AS
SELECT
  DATE(event_timestamp) as event_date,
  table_name,
  event_type,
  COUNT(*) as event_count,
  COUNTIF(severity = 'CRITICAL') as critical_count,
  COUNTIF(severity = 'WARNING') as warning_count,
  COUNTIF(resolution_status = 'RESOLVED') as resolved_count
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;

-- View: Current unresolved issues
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_unresolved_quality_issues` AS
SELECT
  event_id,
  event_timestamp,
  table_name,
  game_date,
  metric_name,
  metric_value,
  severity,
  description,
  triggered_by,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR) as hours_unresolved,
  CASE
    WHEN severity = 'CRITICAL' AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR) > 24
    THEN 'ESCALATE'
    WHEN severity = 'WARNING' AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR) > 48
    THEN 'ESCALATE'
    ELSE 'MONITOR'
  END as recommended_action
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_type = 'QUALITY_ISSUE_DETECTED'
  AND (resolution_status IS NULL OR resolution_status IN ('PENDING', 'FAILED', 'MANUAL_REQUIRED'))
  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
ORDER BY
  CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
  event_timestamp ASC;

-- ============================================================================
-- SAMPLE ROWS
-- ============================================================================

/*
-- Sample: Quality Issue Detected
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_timestamp": "2026-01-30T08:00:00Z",
  "event_type": "QUALITY_ISSUE_DETECTED",
  "table_name": "player_game_summary",
  "game_date": "2026-01-22",
  "metric_name": "pct_zero_points",
  "metric_value": 46.8,
  "threshold_breached": "critical",
  "severity": "CRITICAL",
  "description": "High zero-points rate detected: 46.8% (threshold: 30%)",
  "details_json": "{\"total_records\": 250, \"zero_records\": 117, \"dnp_marked\": 0}",
  "resolution_status": "PENDING",
  "triggered_by": "daily_check",
  "processor_name": "data_quality_monitor"
}

-- Sample: Backfill Queued (linked to above)
{
  "event_id": "550e8400-e29b-41d4-a716-446655440001",
  "event_timestamp": "2026-01-30T08:00:05Z",
  "event_type": "BACKFILL_QUEUED",
  "table_name": "player_game_summary",
  "game_date": "2026-01-22",
  "severity": "INFO",
  "description": "Auto-backfill queued for player_game_summary 2026-01-22",
  "backfill_queue_id": "queue-12345",
  "related_event_id": "550e8400-e29b-41d4-a716-446655440000",
  "triggered_by": "daily_check"
}

-- Sample: Self-Healed (linked to original issue)
{
  "event_id": "550e8400-e29b-41d4-a716-446655440003",
  "event_timestamp": "2026-01-30T08:05:00Z",
  "event_type": "SELF_HEALED",
  "table_name": "player_game_summary",
  "game_date": "2026-01-22",
  "metric_name": "pct_zero_points",
  "metric_value": 8.5,
  "severity": "INFO",
  "description": "Data quality restored: pct_zero_points improved from 46.8% to 8.5%",
  "resolution_status": "RESOLVED",
  "related_event_id": "550e8400-e29b-41d4-a716-446655440000",
  "duration_seconds": 300,
  "triggered_by": "backfill"
}
*/

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
