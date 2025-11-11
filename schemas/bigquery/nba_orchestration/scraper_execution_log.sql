-- File: schemas/bigquery/nba_orchestration/scraper_execution_log.sql
-- ============================================================================
-- NBA Props Platform - Phase 1 Orchestration: Scraper Execution Log
-- ============================================================================
-- Purpose: Complete log of all scraper executions with 3-status tracking
-- Update: Every scraper run (real-time)
-- Entities: All scrapers (26+ active scrapers)
-- Retention: 90 days (partition expiration)
--
-- Version: 1.0
-- Date: November 10, 2025
-- Status: Production-Ready
--
-- Three-Status System:
--   - 'success': Got data (record_count > 0)
--   - 'no_data': Tried but empty (record_count = 0) 
--   - 'failed': Error occurred
--
-- Discovery Mode Support:
--   Controller stops trying when status='success' AND record_count > 0
--   Controller keeps trying when status='no_data'
--   Controller retries immediately when status='failed'
--
-- Source Tracking Values:
--   - CONTROLLER: Called by master workflow controller
--   - MANUAL: Direct API call via curl/Postman
--   - LOCAL: Running on dev laptop
--   - CLOUD_RUN: Direct endpoint call to Cloud Run service
--   - SCHEDULER: Triggered by Cloud Scheduler job
--   - RECOVERY: Republished by cleanup processor
--
-- Dependencies: None (foundational logging table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.scraper_execution_log` (
  -- ==========================================================================
  -- IDENTIFIERS (2 fields)
  -- ==========================================================================
  
  execution_id STRING NOT NULL,
    -- Unique execution identifier (UUID or run_id from scraper)
    -- Format: 8-character hex UUID
    -- Example: "a1b2c3d4"
    -- Used for: Correlation across logs, debugging specific runs
  
  scraper_name STRING NOT NULL,
    -- Scraper identifier in snake_case format
    -- Examples: 'nbac_injury_report', 'oddsa_events', 'bdl_boxscores'
    -- Naming convention: [source]_[data_type]
    --   - nbac_ = NBA.com
    --   - oddsa_ = The Odds API
    --   - bdl_ = Ball Don't Lie API
    -- Used for: Grouping by scraper, success rate analysis
  
  -- ==========================================================================
  -- WORKFLOW CONTEXT (1 field)
  -- ==========================================================================
  
  workflow STRING,
    -- Parent workflow name that triggered this scraper
    -- Examples: 'injury_discovery', 'morning_operations', 'betting_lines'
    -- Special value: 'MANUAL' for direct execution
    -- NULL for: Legacy runs before workflow system
    -- Used for: Workflow success tracking, orchestration debugging
  
  -- ==========================================================================
  -- EXECUTION STATUS (1 field)
  -- ==========================================================================
  
  status STRING NOT NULL,
    -- Execution result (three-status system)
    -- Values:
    --   'success' = Got data (record_count > 0)
    --   'no_data' = Tried but empty (record_count = 0)
    --   'failed' = Error occurred
    -- Discovery mode logic:
    --   - Stop trying after 'success' with records
    --   - Keep trying after 'no_data' (up to max attempts)
    --   - Retry immediately after 'failed' (up to max retries)
  
  -- ==========================================================================
  -- TIMING (3 fields)
  -- ==========================================================================
  
  triggered_at TIMESTAMP NOT NULL,
    -- Execution start time in UTC
    -- Partition key (daily partitions)
    -- Used for: Time-based queries, discovery mode timing
    -- Always filter on this field for efficient queries
  
  completed_at TIMESTAMP,
    -- Execution end time in UTC
    -- NULL if: Failed before completion, currently running
    -- Used for: Duration calculation, success verification
  
  duration_seconds FLOAT64,
    -- Total execution time in seconds
    -- Calculated: completed_at - triggered_at
    -- Range: 1-300 seconds (typical), up to 600 for large scrapes
    -- NULL if: Execution failed before completion
    -- Used for: Performance monitoring, timeout detection
  
  -- ==========================================================================
  -- SOURCE TRACKING (3 fields)
  -- ==========================================================================
  
  source STRING NOT NULL,
    -- Execution trigger source
    -- Values:
    --   'CONTROLLER' = Master workflow controller (automated)
    --   'MANUAL' = Direct API call (testing)
    --   'LOCAL' = Dev machine (development)
    --   'CLOUD_RUN' = Direct endpoint call
    --   'SCHEDULER' = Cloud Scheduler job
    --   'RECOVERY' = Cleanup processor (self-healing)
    -- Used for: Cost analysis, debugging, automation metrics
  
  environment STRING,
    -- Execution environment
    -- Values: 'prod', 'dev', 'local'
    -- NULL for: Very old runs
    -- Used for: Separating test from production data
  
  triggered_by STRING,
    -- User or system that triggered execution
    -- Examples:
    --   'naji@local' (local development)
    --   'cloud-scheduler' (automated)
    --   'master-controller' (workflow system)
    --   'cleanup-processor' (recovery)
    -- Used for: Attribution, debugging, access auditing
  
  -- ==========================================================================
  -- OUTPUT (1 field)
  -- ==========================================================================
  
  gcs_path STRING,
    -- Output GCS file path where data was exported
    -- Format: gs://bucket-name/path/to/file.json
    -- Example: "gs://nba-props-scrapers/nbac_injury_report/2025/01/15/08AM_run.json"
    -- NULL if: Scraper failed before export, no data to export
    -- Used for: Data lineage, recovery, reprocessing
  
  -- ==========================================================================
  -- DATA SUMMARY (1 field - JSON)
  -- ==========================================================================
  
  data_summary JSON,
    -- Summary of data collected
    -- Structure: {
    --   "record_count": int,           // Number of records scraped
    --   "scraper_stats": {...},        // Scraper-specific metrics
    --   "is_empty_report": bool,       // True if intentionally empty
    --   "games_processed": int,        // For game-based scrapers
    --   "players_found": int           // For player-based scrapers
    -- }
    -- Example: {"record_count": 15, "is_empty_report": false, "games_processed": 8}
    -- Used for: Discovery mode decisions, data quality checks
  
  -- ==========================================================================
  -- ERROR TRACKING (2 fields)
  -- ==========================================================================
  
  error_type STRING,
    -- Exception class name if status='failed'
    -- Examples:
    --   'DownloadDataException' (network failure)
    --   'InvalidHttpStatusCodeException' (API error)
    --   'ParseException' (data format issue)
    --   'ValidationException' (data quality issue)
    -- NULL if: status != 'failed'
    -- Used for: Error categorization, alerting rules
  
  error_message STRING,
    -- Full error details if status='failed'
    -- Includes: Stack trace, error context, debug info
    -- NULL if: status != 'failed'
    -- Used for: Debugging, root cause analysis
  
  -- ==========================================================================
  -- RETRY TRACKING (1 field)
  -- ==========================================================================
  
  retry_count INT64,
    -- Number of retries attempted before final status
    -- Range: 0 (first attempt) to 3 (max retries)
    -- NULL if: No retries configured for this scraper
    -- Used for: Reliability analysis, retry policy tuning
  
  -- ==========================================================================
  -- RECOVERY TRACKING (1 field)
  -- ==========================================================================
  
  recovery BOOLEAN,
    -- True if this was a recovery/cleanup run
    -- Set when: Cleanup processor republishes missed Pub/Sub message
    -- NULL for: Normal executions (not recovery)
    -- Used for: Measuring self-healing effectiveness
  
  -- ==========================================================================
  -- CORRELATION (1 field)
  -- ==========================================================================
  
  run_id STRING,
    -- Scraper run correlation ID (8-char UUID)
    -- Format: First 8 chars of UUID
    -- Example: "a1b2c3d4"
    -- Used for: Tracking across logs, linking related operations
    -- Note: May match execution_id or be separate
  
  -- ==========================================================================
  -- CONFIGURATION (1 field - JSON)
  -- ==========================================================================
  
  opts JSON,
    -- Scraper options used for this execution
    -- Secrets redacted before logging
    -- Common fields:
    --   gamedate: "20250115"
    --   sport: "basketball"
    --   hour: 8
    --   period: "AM"
    --   workflow: "injury_discovery"
    -- Example: {"gamedate": "20250115", "hour": 8, "period": "AM"}
    -- Used for: Reproducing runs, debugging configuration issues
  
  -- ==========================================================================
  -- METADATA (1 field)
  -- ==========================================================================
  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- Row creation timestamp (auto-populated by BigQuery)
    -- Used for: Audit trail, data freshness checks

) 
PARTITION BY DATE(triggered_at)
CLUSTER BY scraper_name, workflow, status, source
OPTIONS(
  description = "Complete log of all scraper executions with 3-status tracking (success/no_data/failed). Supports discovery mode workflows and comprehensive source tracking. Partition key: triggered_at (daily). Cluster by: scraper_name, workflow, status, source. CRITICAL TABLE for Phase 1 orchestration.",
  partition_expiration_days = 90
);

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 18
--   - Identifiers: 2 (execution_id, scraper_name)
--   - Workflow context: 1 (workflow)
--   - Status: 1 (status)
--   - Timing: 3 (triggered_at, completed_at, duration_seconds)
--   - Source tracking: 3 (source, environment, triggered_by)
--   - Output: 1 (gcs_path)
--   - Data summary: 1 (data_summary JSON)
--   - Error tracking: 2 (error_type, error_message)
--   - Retry tracking: 1 (retry_count)
--   - Recovery: 1 (recovery)
--   - Correlation: 1 (run_id)
--   - Configuration: 1 (opts JSON)
--   - Metadata: 1 (created_at)
-- ============================================================================

-- ============================================================================
-- SAMPLE ROW (Successful Discovery - Found Data)
-- ============================================================================
/*
{
  "execution_id": "a1b2c3d4",
  "scraper_name": "nbac_injury_report",
  "workflow": "injury_discovery",
  "status": "success",
  "triggered_at": "2025-01-15T13:00:00Z",
  "completed_at": "2025-01-15T13:00:05Z",
  "duration_seconds": 5.2,
  "source": "CONTROLLER",
  "environment": "prod",
  "triggered_by": "master-controller",
  "gcs_path": "gs://nba-props-scrapers/nbac_injury_report/2025/01/15/08AM_run.json",
  "data_summary": {
    "record_count": 12,
    "is_empty_report": false,
    "games_today": 8,
    "players_affected": 12
  },
  "error_type": null,
  "error_message": null,
  "retry_count": 0,
  "recovery": null,
  "run_id": "a1b2c3d4",
  "opts": {
    "gamedate": "20250115",
    "hour": 8,
    "period": "AM",
    "workflow": "injury_discovery"
  },
  "insert_time": "2025-01-15T13:00:06Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Discovery Mode - No Data Yet)
-- ============================================================================
/*
{
  "execution_id": "e5f6g7h8",
  "scraper_name": "nbac_injury_report",
  "workflow": "injury_discovery",
  "status": "no_data",
  "triggered_at": "2025-01-15T11:00:00Z",
  "completed_at": "2025-01-15T11:00:03Z",
  "duration_seconds": 3.1,
  "source": "CONTROLLER",
  "environment": "prod",
  "triggered_by": "master-controller",
  "gcs_path": "gs://nba-props-scrapers/nbac_injury_report/2025/01/15/06AM_run.json",
  "data_summary": {
    "record_count": 0,
    "is_empty_report": true,
    "message": "Injury report not yet published"
  },
  "error_type": null,
  "error_message": null,
  "retry_count": 0,
  "recovery": null,
  "run_id": "e5f6g7h8",
  "opts": {
    "gamedate": "20250115",
    "hour": 6,
    "period": "AM",
    "workflow": "injury_discovery"
  },
  "insert_time": "2025-01-15T11:00:04Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Failed Execution)
-- ============================================================================
/*
{
  "execution_id": "i9j0k1l2",
  "scraper_name": "oddsa_events",
  "workflow": "betting_lines",
  "status": "failed",
  "triggered_at": "2025-01-15T14:30:00Z",
  "completed_at": null,
  "duration_seconds": null,
  "source": "CONTROLLER",
  "environment": "prod",
  "triggered_by": "master-controller",
  "gcs_path": null,
  "data_summary": null,
  "error_type": "DownloadDataException",
  "error_message": "HTTP 503 Service Unavailable: API rate limit exceeded",
  "retry_count": 2,
  "recovery": null,
  "run_id": "i9j0k1l2",
  "opts": {
    "sport": "basketball",
    "workflow": "betting_lines"
  },
  "insert_time": "2025-01-15T14:30:15Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Local Development)
-- ============================================================================
/*
{
  "execution_id": "m3n4o5p6",
  "scraper_name": "nbac_schedule_api",
  "workflow": "MANUAL",
  "status": "success",
  "triggered_at": "2025-01-15T18:45:00Z",
  "completed_at": "2025-01-15T18:45:02Z",
  "duration_seconds": 2.3,
  "source": "LOCAL",
  "environment": "local",
  "triggered_by": "naji@local",
  "gcs_path": null,
  "data_summary": {
    "record_count": 82,
    "games_found": 82,
    "season": "2024-25"
  },
  "error_type": null,
  "error_message": null,
  "retry_count": 0,
  "recovery": null,
  "run_id": "m3n4o5p6",
  "opts": {
    "season": "2024-25"
  },
  "insert_time": "2025-01-15T18:45:03Z"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Discovery mode status check
-- Purpose: Check if injury report found data today
-- Expected: Latest run shows 'success' with record_count > 0
-- SELECT 
--   status,
--   JSON_VALUE(data_summary, '$.record_count') as records,
--   triggered_at,
--   workflow
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE scraper_name = 'nbac_injury_report'
--   AND DATE(triggered_at) = CURRENT_DATE()
-- ORDER BY triggered_at DESC
-- LIMIT 1;

-- Query 2: Count discovery attempts today
-- Purpose: Track how many times we've tried to get injury data
-- Expected: Increases until we find data, then stops
-- SELECT 
--   COUNT(*) as attempts_today,
--   COUNTIF(status = 'success' AND CAST(JSON_VALUE(data_summary, '$.record_count') AS INT64) > 0) as found_data,
--   COUNTIF(status = 'no_data') as no_data_yet,
--   COUNTIF(status = 'failed') as failures
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE scraper_name = 'nbac_injury_report'
--   AND DATE(triggered_at) = CURRENT_DATE();

-- Query 3: Success rates by scraper (last 7 days)
-- Purpose: Identify scrapers with reliability issues
-- Expected: Most scrapers >95% success rate
-- SELECT 
--   scraper_name,
--   COUNT(*) as total_runs,
--   COUNTIF(status = 'success') as success_count,
--   COUNTIF(status = 'no_data') as no_data_count,
--   COUNTIF(status = 'failed') as failed_count,
--   ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 1) as success_rate_pct
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY scraper_name
-- ORDER BY success_rate_pct ASC;

-- Query 4: Source breakdown (where executions come from)
-- Purpose: Understand automation vs manual usage
-- Expected: CONTROLLER dominates in production
-- SELECT 
--   source,
--   environment,
--   COUNT(*) as executions,
--   COUNTIF(status = 'success') as successful,
--   ROUND(AVG(duration_seconds), 2) as avg_duration_sec
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE DATE(triggered_at) = CURRENT_DATE()
-- GROUP BY source, environment
-- ORDER BY executions DESC;

-- Query 5: Recent failures for investigation
-- Purpose: Quick debugging of failed scrapers
-- Expected: Empty or minimal failures
-- SELECT 
--   scraper_name,
--   workflow,
--   triggered_at,
--   error_type,
--   error_message,
--   retry_count
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE status = 'failed'
--   AND DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
-- ORDER BY triggered_at DESC
-- LIMIT 20;

-- Query 6: Average duration by scraper
-- Purpose: Identify slow scrapers, detect timeout issues
-- Expected: Most scrapers <10 seconds
-- SELECT 
--   scraper_name,
--   COUNT(*) as runs,
--   ROUND(AVG(duration_seconds), 2) as avg_duration,
--   ROUND(MIN(duration_seconds), 2) as min_duration,
--   ROUND(MAX(duration_seconds), 2) as max_duration,
--   ROUND(STDDEV(duration_seconds), 2) as stddev_duration
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND status = 'success'
-- GROUP BY scraper_name
-- ORDER BY avg_duration DESC;

-- -- ============================================================================
-- -- MONITORING QUERIES
-- -- ============================================================================

-- -- Alert: No successful runs in last hour for critical scrapers
-- -- Threshold: 0 successes for scrapers that should run hourly
-- SELECT 
--   'scraper_execution_log' as alert_source,
--   scraper_name,
--   COUNT(*) as total_attempts,
--   COUNTIF(status = 'success') as successes,
--   MAX(triggered_at) as last_attempt
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE scraper_name IN ('nbac_injury_report', 'oddsa_events', 'nbac_schedule_api')
--   AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
-- GROUP BY scraper_name
-- HAVING COUNTIF(status = 'success') = 0;

-- -- Alert: High failure rate (>20% failed)
-- -- Threshold: 20% failure rate indicates systemic issues
-- SELECT 
--   'scraper_execution_log' as alert_source,
--   scraper_name,
--   COUNT(*) as total_runs,
--   COUNTIF(status = 'failed') as failures,
--   ROUND(COUNTIF(status = 'failed') * 100.0 / COUNT(*), 1) as failure_rate_pct
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
-- WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
-- GROUP BY scraper_name
-- HAVING ROUND(COUNTIF(status = 'failed') * 100.0 / COUNT(*), 1) > 20.0;

-- -- Alert: Unusually slow executions (>3x normal)
-- -- Threshold: Duration >3x average indicates performance issue
-- WITH avg_durations AS (
--   SELECT 
--     scraper_name,
--     AVG(duration_seconds) as avg_duration
--   FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
--   WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--     AND status = 'success'
--   GROUP BY scraper_name
-- )
-- SELECT 
--   'scraper_execution_log' as alert_source,
--   e.scraper_name,
--   e.execution_id,
--   e.triggered_at,
--   e.duration_seconds,
--   a.avg_duration,
--   ROUND(e.duration_seconds / a.avg_duration, 1) as duration_multiplier
-- FROM `nba-props-platform.nba_orchestration.scraper_execution_log` e
-- JOIN avg_durations a ON e.scraper_name = a.scraper_name
-- WHERE DATE(e.triggered_at) = CURRENT_DATE()
--   AND e.duration_seconds > (a.avg_duration * 3)
-- ORDER BY e.duration_seconds DESC;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_orchestration dataset
-- [ ] Verify partitioning (daily on triggered_at)
-- [ ] Verify clustering (scraper_name, workflow, status, source)
-- [ ] Test with sample insert
-- [ ] Validate JSON fields (data_summary, opts)
-- [ ] Test discovery mode queries
-- [ ] Enable monitoring queries
-- [ ] Configure alerts in Grafana
-- [ ] Document alert thresholds
-- [ ] Add to scraper_base.py logging
-- ============================================================================
