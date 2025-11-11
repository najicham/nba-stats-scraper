-- File: schemas/bigquery/nba_orchestration/cleanup_operations.sql
-- ============================================================================
-- NBA Props Platform - Phase 1 Orchestration: Cleanup Operations
-- ============================================================================
-- Purpose: Self-healing cleanup processor operations log
-- Update: Every cleanup run (typically every 30 minutes)
-- Entities: GCS files missing from processing pipeline
-- Retention: 90 days (partition expiration)
--
-- Version: 1.0
-- Date: November 10, 2025
-- Status: Production-Ready
--
-- Self-Healing Concept:
--   The cleanup processor runs every 30 minutes and checks for GCS files
--   that were created by scrapers but never processed by Phase 2 (missing
--   Pub/Sub messages). When found, it republishes the Pub/Sub message to
--   trigger processing, creating a self-healing system.
--
-- Week 1 Behavior:
--   Pub/Sub integration deferred to Week 2, so cleanup processor will:
--   - Check for missing files (detection works)
--   - Log findings (this table)
--   - NOT republish (pubsub_enabled=false)
--   - Act as monitoring only until Pub/Sub setup complete
--
-- Use Cases:
--   - Monitoring self-healing effectiveness
--   - Detecting processing pipeline issues
--   - Cost analysis (recovery vs normal operation)
--   - Alert on high missing file counts
--
-- Dependencies:
--   - GCS bucket access (to list files)
--   - Phase 2 processor logs (to check processing status)
--   - Pub/Sub topic (Week 2 onwards)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.cleanup_operations` (
  -- ==========================================================================
  -- OPERATION IDENTIFIERS (2 fields)
  -- ==========================================================================
  
  cleanup_id STRING NOT NULL,
    -- Unique cleanup operation identifier (UUID)
    -- Format: Full UUID
    -- Example: "550e8400-e29b-41d4-a716-446655440000"
    -- Used for: Correlation, debugging specific cleanup runs
  
  cleanup_time TIMESTAMP NOT NULL,
    -- When cleanup processor ran in UTC
    -- Partition key (daily partitions)
    -- Used for: Time-based queries, frequency analysis
    -- Always filter on this field for efficient queries
  
  -- ==========================================================================
  -- SCAN RESULTS (3 fields)
  -- ==========================================================================
  
  files_checked INT64 NOT NULL,
    -- Number of GCS files checked for processing status
    -- Range: 0-10000 (typical), higher during backfills
    -- Includes: All JSON files in scraper output directories
    -- Used for: Understanding scan scope, performance monitoring
  
  missing_files_found INT64 NOT NULL,
    -- Count of files in GCS but not yet processed by Phase 2
    -- Range: 0-100 (typical), 0 is ideal
    -- High values indicate: Pub/Sub delivery issues, Phase 2 downtime
    -- Used for: Alert triggers, self-healing effectiveness
  
  republished_count INT64 NOT NULL,
    -- Number of Pub/Sub messages republished for recovery
    -- Range: 0-100 (typical)
    -- Should match missing_files_found when Pub/Sub enabled
    -- 0 in Week 1: Pub/Sub not yet configured
    -- Used for: Measuring self-healing actions taken
  
  -- ==========================================================================
  -- MISSING FILE DETAILS (1 field - REPEATED RECORD)
  -- ==========================================================================
  
  missing_files ARRAY<STRUCT<
    scraper_name STRING,
      -- Scraper that created the file
      -- Examples: 'nbac_injury_report', 'oddsa_events'
      -- Used for: Identifying which scrapers have processing issues
    
    gcs_path STRING,
      -- Full GCS path to the file
      -- Format: gs://bucket-name/path/to/file.json
      -- Example: "gs://nba-props-scrapers/nbac_injury_report/2025/01/15/08AM_run.json"
      -- Used for: Recovery operations, debugging
    
    triggered_at TIMESTAMP,
      -- When the scraper originally ran
      -- Extracted from file metadata or filename
      -- Used for: Age calculation, priority determination
    
    age_minutes INT64,
      -- How long the file has been waiting for processing
      -- Calculated: cleanup_time - triggered_at
      -- Range: 30-1440 (30 min to 24 hours typical)
      -- High values indicate: Persistent processing issues
      -- Used for: Alert escalation, priority recovery
    
    republished BOOLEAN
      -- Whether Pub/Sub message was successfully republished
      -- true: Recovery initiated
      -- false: Republish failed or skipped (Week 1)
      -- Used for: Tracking recovery success rate
  >>,
    -- Array of missing files found in this cleanup run
    -- Empty array if: No missing files (ideal state)
    -- Used for: Detailed investigation, recovery tracking
  
  -- ==========================================================================
  -- ERROR TRACKING (1 field)
  -- ==========================================================================
  
  errors ARRAY<STRING>,
    -- List of errors encountered during cleanup operation
    -- Examples:
    --   'Unable to access GCS bucket: Permission denied'
    --   'Pub/Sub publish failed: Quota exceeded'
    --   'BigQuery query timeout checking processed files'
    -- Empty array if: Cleanup completed successfully
    -- Used for: Debugging cleanup processor issues
  
  -- ==========================================================================
  -- PERFORMANCE (1 field)
  -- ==========================================================================
  
  duration_seconds FLOAT64,
    -- Total cleanup operation duration in seconds
    -- Range: 5-300 seconds (typical)
    -- Includes: GCS scan, BigQuery checks, Pub/Sub republish
    -- High values indicate: Performance issues, large backlogs
    -- Used for: Performance monitoring, timeout tuning
  
  -- ==========================================================================
  -- WEEK 1 CONFIGURATION (1 field)
  -- ==========================================================================
  
  pubsub_enabled BOOLEAN,
    -- Whether Pub/Sub was enabled during this cleanup run
    -- false: Week 1 (monitoring only, no republishing)
    -- true: Week 2+ (full self-healing enabled)
    -- Used for: Understanding system capabilities at time of run
    -- Note: When false, republished_count should be 0
  
  -- ==========================================================================
  -- ENVIRONMENT (1 field)
  -- ==========================================================================
  
  environment STRING,
    -- Execution environment
    -- Values: 'prod', 'dev'
    -- Used for: Filtering production cleanup operations
  
  -- ==========================================================================
  -- METADATA (1 field)
  -- ==========================================================================
  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- Row creation timestamp (auto-populated by BigQuery)
    -- Used for: Audit trail, data freshness checks

)
PARTITION BY DATE(cleanup_time)
CLUSTER BY missing_files_found, republished_count
OPTIONS(
  description = "Self-healing cleanup processor operations log. Tracks GCS files that were created but not processed (missing Pub/Sub messages). Week 1: monitoring only. Week 2+: full self-healing with Pub/Sub republishing. Partition key: cleanup_time (daily). Cluster by: missing_files_found, republished_count. CRITICAL TABLE for self-healing monitoring.",
  partition_expiration_days = 90
);

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 11 (+ 5 nested in missing_files struct)
--   - Operation identifiers: 2 (cleanup_id, cleanup_time)
--   - Scan results: 3 (files_checked, missing_files_found, republished_count)
--   - Missing file details: 1 (missing_files array of structs with 5 fields)
--   - Error tracking: 1 (errors array)
--   - Performance: 1 (duration_seconds)
--   - Configuration: 1 (pubsub_enabled)
--   - Environment: 1 (environment)
--   - Metadata: 1 (created_at)
-- ============================================================================

-- ============================================================================
-- SAMPLE ROW (Perfect State - No Missing Files)
-- ============================================================================
/*
{
  "cleanup_id": "550e8400-e29b-41d4-a716-446655440000",
  "cleanup_time": "2025-01-15T14:30:00Z",
  "files_checked": 156,
  "missing_files_found": 0,
  "republished_count": 0,
  "missing_files": [],
  "errors": [],
  "duration_seconds": 8.3,
  "pubsub_enabled": true,
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Week 1 - Monitoring Only)
-- ============================================================================
/*
{
  "cleanup_id": "660e8400-e29b-41d4-a716-446655440001",
  "cleanup_time": "2025-01-15T15:00:00Z",
  "files_checked": 142,
  "missing_files_found": 3,
  "republished_count": 0,
  "missing_files": [
    {
      "scraper_name": "nbac_injury_report",
      "gcs_path": "gs://nba-props-scrapers/nbac_injury_report/2025/01/15/08AM_run.json",
      "triggered_at": "2025-01-15T13:00:00Z",
      "age_minutes": 120,
      "republished": false
    },
    {
      "scraper_name": "oddsa_events",
      "gcs_path": "gs://nba-props-scrapers/oddsa_events/2025/01/15/09AM_run.json",
      "triggered_at": "2025-01-15T14:00:00Z",
      "age_minutes": 60,
      "republished": false
    },
    {
      "scraper_name": "nbac_schedule_api",
      "gcs_path": "gs://nba-props-scrapers/nbac_schedule_api/2025/01/15/06AM_run.json",
      "triggered_at": "2025-01-15T11:00:00Z",
      "age_minutes": 240,
      "republished": false
    }
  ],
  "errors": [],
  "duration_seconds": 12.7,
  "pubsub_enabled": false,
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Week 2+ - Self-Healing Active)
-- ============================================================================
/*
{
  "cleanup_id": "770e8400-e29b-41d4-a716-446655440002",
  "cleanup_time": "2025-02-01T10:00:00Z",
  "files_checked": 168,
  "missing_files_found": 2,
  "republished_count": 2,
  "missing_files": [
    {
      "scraper_name": "nbac_player_boxscore",
      "gcs_path": "gs://nba-props-scrapers/nbac_player_boxscore/2025/02/01/02AM_run.json",
      "triggered_at": "2025-02-01T07:00:00Z",
      "age_minutes": 180,
      "republished": true
    },
    {
      "scraper_name": "bdl_boxscores",
      "gcs_path": "gs://nba-props-scrapers/bdl_boxscores/2025/02/01/03AM_run.json",
      "triggered_at": "2025-02-01T08:00:00Z",
      "age_minutes": 120,
      "republished": true
    }
  ],
  "errors": [],
  "duration_seconds": 15.2,
  "pubsub_enabled": true,
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Error During Cleanup)
-- ============================================================================
/*
{
  "cleanup_id": "880e8400-e29b-41d4-a716-446655440003",
  "cleanup_time": "2025-01-15T16:00:00Z",
  "files_checked": 95,
  "missing_files_found": 0,
  "republished_count": 0,
  "missing_files": [],
  "errors": [
    "Unable to query nba_raw.processing_log: Table not found",
    "Partial scan completed - some scrapers skipped"
  ],
  "duration_seconds": 5.8,
  "pubsub_enabled": true,
  "environment": "prod"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Recent cleanup activity
-- Purpose: Quick view of self-healing system health
-- Expected: Regular runs (every 30 min), low/zero missing files
-- SELECT 
--   cleanup_time,
--   files_checked,
--   missing_files_found,
--   republished_count,
--   ROUND(duration_seconds, 2) as duration_sec,
--   pubsub_enabled,
--   ARRAY_LENGTH(errors) as error_count
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations`
-- WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ORDER BY cleanup_time DESC
-- LIMIT 20;

-- -- Query 2: Self-healing effectiveness
-- -- Purpose: Measure how well cleanup processor recovers missing files
-- -- Expected: 100% recovery rate when Pub/Sub enabled
-- SELECT 
--   DATE(cleanup_time) as date,
--   COUNT(*) as cleanup_runs,
--   SUM(missing_files_found) as total_missing,
--   SUM(republished_count) as total_republished,
--   ROUND(SUM(republished_count) * 100.0 / NULLIF(SUM(missing_files_found), 0), 1) as recovery_rate_pct,
--   ROUND(AVG(duration_seconds), 1) as avg_duration_sec
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations`
-- WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND pubsub_enabled = true
-- GROUP BY date
-- ORDER BY date DESC;

-- -- Query 3: Missing files by scraper
-- -- Purpose: Identify scrapers with persistent processing issues
-- -- Expected: No patterns (random Pub/Sub delivery failures)
-- SELECT 
--   mf.scraper_name,
--   COUNT(*) as times_missing,
--   AVG(mf.age_minutes) as avg_age_minutes,
--   COUNTIF(mf.republished) as times_recovered,
--   ROUND(COUNTIF(mf.republished) * 100.0 / COUNT(*), 1) as recovery_rate_pct
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations` co,
-- UNNEST(co.missing_files) as mf
-- WHERE DATE(co.cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY mf.scraper_name
-- ORDER BY times_missing DESC;

-- -- Query 4: Cleanup errors analysis
-- -- Purpose: Detect systemic issues with cleanup processor
-- -- Expected: Very few errors (<1%)
-- SELECT 
--   DATE(cleanup_time) as date,
--   COUNT(*) as total_runs,
--   COUNTIF(ARRAY_LENGTH(errors) > 0) as runs_with_errors,
--   ROUND(COUNTIF(ARRAY_LENGTH(errors) > 0) * 100.0 / COUNT(*), 1) as error_rate_pct,
--   STRING_AGG(DISTINCT error ORDER BY error LIMIT 5) as common_errors
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations`,
-- UNNEST(errors) as error
-- WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY date
-- ORDER BY date DESC;

-- -- Query 5: Currently missing files (needs recovery)
-- -- Purpose: Show files that need attention right now
-- -- Expected: Empty result (all files processed quickly)
-- WITH latest_cleanup AS (
--   SELECT 
--     cleanup_time,
--     missing_files
--   FROM `nba-props-platform.nba_orchestration.cleanup_operations`
--   ORDER BY cleanup_time DESC
--   LIMIT 1
-- )
-- SELECT 
--   mf.scraper_name,
--   mf.gcs_path,
--   mf.triggered_at,
--   mf.age_minutes,
--   mf.republished,
--   CASE 
--     WHEN mf.age_minutes > 240 THEN '🔴 CRITICAL (>4h)'
--     WHEN mf.age_minutes > 120 THEN '🟡 WARNING (>2h)'
--     ELSE '🟠 RECENT (<2h)'
--   END as urgency
-- FROM latest_cleanup,
-- UNNEST(missing_files) as mf
-- ORDER BY mf.age_minutes DESC;

-- -- Query 6: Performance trends
-- -- Purpose: Monitor cleanup processor performance over time
-- -- Expected: Consistent performance, <30 seconds typical
-- SELECT 
--   DATE(cleanup_time) as date,
--   COUNT(*) as runs,
--   ROUND(AVG(duration_seconds), 1) as avg_duration,
--   ROUND(MIN(duration_seconds), 1) as min_duration,
--   ROUND(MAX(duration_seconds), 1) as max_duration,
--   ROUND(AVG(files_checked), 0) as avg_files_checked
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations`
-- WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY date
-- ORDER BY date DESC;

-- -- ============================================================================
-- -- MONITORING QUERIES
-- -- ============================================================================

-- -- Alert: High missing file count
-- -- Threshold: >10 missing files indicates systemic issue
-- SELECT 
--   'cleanup_operations' as alert_source,
--   cleanup_time,
--   files_checked,
--   missing_files_found,
--   republished_count
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations`
-- WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
--   AND missing_files_found > 10
-- ORDER BY cleanup_time DESC;

-- -- Alert: Low recovery rate
-- -- Threshold: <90% recovery rate when Pub/Sub enabled
-- WITH recent_stats AS (
--   SELECT 
--     SUM(missing_files_found) as total_missing,
--     SUM(republished_count) as total_republished
--   FROM `nba-props-platform.nba_orchestration.cleanup_operations`
--   WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
--     AND pubsub_enabled = true
-- )
-- SELECT 
--   'cleanup_operations' as alert_source,
--   total_missing,
--   total_republished,
--   ROUND(total_republished * 100.0 / NULLIF(total_missing, 0), 1) as recovery_rate_pct
-- FROM recent_stats
-- WHERE ROUND(total_republished * 100.0 / NULLIF(total_missing, 0), 1) < 90.0;

-- -- Alert: Cleanup processor not running
-- -- Threshold: No cleanup runs in last 2 hours
-- SELECT 
--   'cleanup_operations' as alert_source,
--   'Cleanup processor not running' as alert_type,
--   MAX(cleanup_time) as last_run,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(cleanup_time), MINUTE) as minutes_since_last_run
-- FROM `nba-props-platform.nba_orchestration.cleanup_operations`
-- HAVING TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(cleanup_time), MINUTE) > 120;

-- -- Alert: High error rate
-- -- Threshold: >10% of runs have errors
-- WITH error_stats AS (
--   SELECT 
--     COUNT(*) as total_runs,
--     COUNTIF(ARRAY_LENGTH(errors) > 0) as runs_with_errors
--   FROM `nba-props-platform.nba_orchestration.cleanup_operations`
--   WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
-- )
-- SELECT 
--   'cleanup_operations' as alert_source,
--   total_runs,
--   runs_with_errors,
--   ROUND(runs_with_errors * 100.0 / total_runs, 1) as error_rate_pct
-- FROM error_stats
-- WHERE ROUND(runs_with_errors * 100.0 / total_runs, 1) > 10.0;

-- -- ============================================================================
-- -- HELPER VIEWS
-- -- ============================================================================

-- -- View: Latest cleanup status
-- CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_latest_cleanup_status` AS
-- WITH latest AS (
--   SELECT *
--   FROM `nba-props-platform.nba_orchestration.cleanup_operations`
--   ORDER BY cleanup_time DESC
--   LIMIT 1
-- )
-- SELECT 
--   cleanup_time,
--   files_checked,
--   missing_files_found,
--   republished_count,
--   ROUND(duration_seconds, 2) as duration_seconds,
--   pubsub_enabled,
--   ARRAY_LENGTH(errors) as error_count,
--   CASE 
--     WHEN missing_files_found = 0 THEN '✅ HEALTHY'
--     WHEN missing_files_found <= 5 THEN '🟡 WARNING'
--     ELSE '🔴 CRITICAL'
--   END as health_status
-- FROM latest;

-- -- View: Missing files by age
-- CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_missing_files_by_age` AS
-- WITH latest_cleanup AS (
--   SELECT 
--     cleanup_time,
--     missing_files
--   FROM `nba-props-platform.nba_orchestration.cleanup_operations`
--   ORDER BY cleanup_time DESC
--   LIMIT 1
-- )
-- SELECT 
--   mf.scraper_name,
--   mf.gcs_path,
--   mf.triggered_at,
--   mf.age_minutes,
--   mf.republished,
--   CASE 
--     WHEN mf.age_minutes < 60 THEN '0-1h'
--     WHEN mf.age_minutes < 120 THEN '1-2h'
--     WHEN mf.age_minutes < 240 THEN '2-4h'
--     WHEN mf.age_minutes < 480 THEN '4-8h'
--     ELSE '>8h'
--   END as age_bucket,
--   CASE 
--     WHEN mf.age_minutes > 240 THEN 'CRITICAL'
--     WHEN mf.age_minutes > 120 THEN 'WARNING'
--     ELSE 'RECENT'
--   END as urgency
-- FROM latest_cleanup,
-- UNNEST(missing_files) as mf
-- ORDER BY mf.age_minutes DESC;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_orchestration dataset
-- [ ] Verify partitioning (daily on cleanup_time)
-- [ ] Verify clustering (missing_files_found, republished_count)
-- [ ] Test with sample data (Week 1: pubsub_enabled=false)
-- [ ] Validate ARRAY<STRUCT> field structure
-- [ ] Implement cleanup processor
-- [ ] Test GCS file scanning
-- [ ] Test missing file detection
-- [ ] Enable monitoring queries
-- [ ] Configure alerts in Grafana
-- [ ] Week 2: Enable Pub/Sub republishing
-- [ ] Week 2: Verify self-healing works
-- ============================================================================
