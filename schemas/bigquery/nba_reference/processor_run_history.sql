-- File: schemas/bigquery/nba_reference/processor_run_history.sql
-- Description: Tracks all processor runs for temporal ordering and gap detection
-- Created: 2025-10-04
-- Updated: 2025-10-04 - Added validation tracking fields for staleness detection
-- Purpose: Prevent duplicate processing, detect gaps, provide audit trail

-- =============================================================================
-- Table: Processor Run History - Temporal ordering and monitoring
-- =============================================================================
-- This table records every registry processor execution to enable:
-- 1. Temporal ordering protection (prevent processing out of sequence)
-- 2. Gap detection (identify missing dates)
-- 3. Staleness monitoring (alert when processors haven't run)
-- 4. Audit trail (complete history of all processing runs)
-- 5. Data quality tracking (validation and freshness monitoring)
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.processor_run_history` (
    -- =============================================================================
    -- IDENTIFICATION: Which processor ran for what data
    -- =============================================================================
    
    processor_name STRING NOT NULL,
    -- Which processor executed
    -- Values: 'gamebook', 'roster'
    -- Used for: Filtering queries by processor type
    
    run_id STRING NOT NULL,
    -- Unique identifier for this specific execution
    -- Format: '{processor}_{YYYYMMDD}_{HHMMSS}_{uuid}'
    -- Example: 'gamebook_20241004_083045_a3f2b7c1'
    -- Used for: Idempotency, tracking individual runs
    
    season_year INT64,
    -- NBA season starting year
    -- Example: 2024 represents the 2024-25 season
    -- Used for: Filtering by season, gap detection per season
    
    -- =============================================================================
    -- EXECUTION STATUS: How did the run perform
    -- =============================================================================
    
    status STRING NOT NULL,
    -- Current execution status
    -- Values: 'running', 'success', 'failed', 'partial', 'skipped'
    -- Lifecycle: 'running' → ('success' | 'failed' | 'partial')
    -- Used for: Gap detection (only 'success' counts as processed)
    
    duration_seconds FLOAT64,
    -- How long processing took in seconds
    -- NULL while status='running', populated on completion
    -- Example: 45.3 (45.3 seconds)
    -- Used for: Performance monitoring, detecting slow runs
    
    -- =============================================================================
    -- RECORD COUNTS: What was processed
    -- =============================================================================
    
    records_processed INT64 DEFAULT 0,
    -- Total records handled during this run
    -- Includes: created + updated + skipped
    -- Used for: Validating data volume, detecting anomalies
    
    records_created INT64 DEFAULT 0,
    -- New registry records inserted
    -- Used for: Tracking new player discoveries
    
    records_updated INT64 DEFAULT 0,
    -- Existing registry records modified
    -- Used for: Understanding data churn
    
    records_skipped INT64 DEFAULT 0,
    -- Records not processed (e.g., due to staleness checks)
    -- Used for: Detecting data quality issues
    
    -- =============================================================================
    -- SOURCE DATA: Where did the data come from
    -- =============================================================================
    
    data_source_primary STRING,
    -- Primary data source for this run
    -- Values: 'nba_gamebook', 'espn_roster', 'nbacom_roster', 'br_roster'
    -- Example: Gamebook processor uses 'nba_gamebook'
    -- Used for: Understanding data lineage
    
    data_source_enhancement STRING,
    -- Secondary/enhancement data source
    -- Values: 'br_roster', 'espn_roster', 'none'
    -- Example: Gamebook uses BR for jersey numbers
    -- Used for: Tracking data enrichment
    
    data_records_queried INT64,
    -- How many source records were queried
    -- Used for: Data volume analysis, detecting source issues
    
    -- =============================================================================
    -- DATA QUALITY TRACKING: Validation and freshness
    -- =============================================================================
    
    validation_mode STRING,
    -- How validation was performed
    -- Values: 'full', 'partial', 'none'
    -- 'full' = validated against NBA.com canonical set
    -- 'partial' = validated against some sources only
    -- 'none' = no validation (ESPN-only processing or fallback mode)
    -- Used for: Understanding data quality and validation coverage
    
    validation_skipped_reason STRING,
    -- Why validation was skipped (if applicable)
    -- Values: 'nbacom_stale', 'nbacom_unavailable', 'backfill_mode', NULL
    -- NULL when validation_mode='full'
    -- Used for: Diagnosing validation issues and staleness
    
    source_data_freshness_days INT64,
    -- How stale was primary source data (in days)
    -- 0 = same day, 1 = 1 day old, etc.
    -- NULL if freshness check not applicable (e.g., gamebook processor)
    -- Used for: Detecting stale data issues, alerting on data delays
    -- Example: Roster processor checks NBA.com data age
    
    -- =============================================================================
    -- FILTERS: What scope was processed
    -- =============================================================================
    
    season_filter STRING,
    -- Season filter applied during processing
    -- Format: "2024-25"
    -- NULL if no filter (processes all seasons)
    -- Used for: Understanding run scope
    
    team_filter STRING,
    -- Team filter applied during processing
    -- Format: "LAL"
    -- NULL if no filter (processes all teams)
    -- Used for: Tracking partial runs
    
    date_range_filter_start DATE,
    -- Start date of filter range (if date range filter was used)
    -- NULL for single-date processing (typical case)
    -- Reserved for future multi-date batch processing
    
    date_range_filter_end DATE,
    -- End date of filter range (if date range filter was used)
    -- NULL for single-date processing (typical case)
    -- Reserved for future multi-date batch processing
    
    -- =============================================================================
    -- FLAGS: How was the processor invoked
    -- =============================================================================
    
    backfill_mode BOOLEAN DEFAULT FALSE,
    -- TRUE if --allow-backfill flag was used
    -- Indicates: Historical processing, insert-only mode
    -- Used for: Distinguishing backfills from normal runs
    
    force_reprocess BOOLEAN DEFAULT FALSE,
    -- TRUE if --force-reprocess flag was used
    -- Indicates: Intentional reprocessing of already-processed date
    -- Used for: Understanding why duplicate processing occurred
    
    test_mode BOOLEAN DEFAULT FALSE,
    -- TRUE if processor was run in test mode
    -- Indicates: Using test tables, not production
    -- Used for: Filtering test runs from monitoring
    
    -- =============================================================================
    -- ENVIRONMENT: Where and how was it triggered
    -- =============================================================================
    
    execution_host STRING,
    -- Where the processor ran
    -- Values: 'cloud-run', 'local', 'backfill-job', 'workflow'
    -- Used for: Debugging, understanding execution context
    
    triggered_by STRING,
    -- What triggered this execution
    -- Values: 'scheduler', 'manual', 'workflow', 'api', 'retry'
    -- Used for: Understanding automation vs manual runs
    
    -- =============================================================================
    -- RESULTS: Errors and warnings
    -- =============================================================================
    
    errors JSON,
    -- Array of error objects if processing failed
    -- Format: [{"error_type": "BigQueryError", "error_message": "...", "timestamp": "..."}]
    -- NULL if no errors
    -- Used for: Debugging failures, alerting on error patterns
    
    warnings JSON,
    -- Array of warning objects (non-fatal issues)
    -- Format: [{"warning_type": "DataStaleness", "message": "...", "timestamp": "..."}]
    -- NULL if no warnings
    -- Used for: Identifying data quality issues
    
    summary JSON,
    -- Complete result summary from processor
    -- Contains: Full details from processing run
    -- Used for: Detailed analysis, debugging
    
    -- =============================================================================
    -- DATES: When and what (at end per convention)
    -- =============================================================================
    
    data_date DATE NOT NULL,
    -- The date this data represents (PRIMARY KEY COMPONENT)
    -- Gamebook: Date of games processed (e.g., Oct 3 games)
    -- Roster: Date of roster snapshot (e.g., Oct 3 roster)
    -- NOT the date the processor ran (use started_at for that)
    -- Used for: Temporal ordering, gap detection, partitioning
    
    started_at TIMESTAMP NOT NULL,
    -- When processor execution started
    -- Set at: Beginning of run (before any processing)
    -- Used for: Calculating duration, ordering runs
    
    processed_at TIMESTAMP,
    -- When processing completed
    -- NULL while status='running'
    -- Set at: End of run (success or failure)
    -- Used for: Calculating duration, completion tracking
    
    -- =============================================================================
    -- CONSTRAINTS AND KEYS
    -- =============================================================================
    
    PRIMARY KEY (processor_name, data_date, run_id) NOT ENFORCED
    -- Composite key ensures:
    -- - One processor can run multiple times for same date (with different run_ids)
    -- - Idempotent reprocessing supported (unique run_id each time)
    -- - Efficient queries by (processor_name, data_date)
)
PARTITION BY data_date
-- Partitioned by data_date for:
-- - Efficient date range queries (gap detection)
-- - Automatic data lifecycle management
-- - Query cost optimization (requires partition filter)

CLUSTER BY processor_name, status, season_year
-- Clustered for optimal query performance on:
-- - Processor-specific queries (most common access pattern)
-- - Status filtering (success vs failed)
-- - Season-based analysis

OPTIONS (
  description = "Audit log of all processor runs for temporal ordering, gap detection, and monitoring. Includes validation tracking for data quality monitoring.",
  partition_expiration_days = 1095  -- 3 years retention (matches registry table)
);

-- =============================================================================
-- USAGE EXAMPLES
-- =============================================================================

-- Example 1: Check if date already processed (temporal ordering)
-- SELECT run_id, status, started_at
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'gamebook'
--   AND data_date = '2024-10-03'
--   AND status = 'success'
-- LIMIT 1;

-- Example 2: Find gaps (missing dates in last 30 days)
-- WITH date_series AS (
--   SELECT date 
--   FROM UNNEST(GENERATE_DATE_ARRAY(
--     DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY), 
--     CURRENT_DATE()
--   )) AS date
-- )
-- SELECT d.date as missing_date
-- FROM date_series d
-- LEFT JOIN `nba-props-platform.nba_reference.processor_run_history` p 
--   ON p.data_date = d.date 
--   AND p.processor_name = 'gamebook'
--   AND p.status = 'success'
-- WHERE p.run_id IS NULL
-- ORDER BY d.date;

-- Example 3: Check data freshness and validation issues
-- SELECT 
--   processor_name,
--   data_date,
--   validation_mode,
--   validation_skipped_reason,
--   source_data_freshness_days,
--   status
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'roster'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND (validation_mode = 'none' OR source_data_freshness_days > 1)
-- ORDER BY data_date DESC;

-- Example 4: Recent failures with errors
-- SELECT 
--   processor_name,
--   data_date,
--   started_at,
--   JSON_EXTRACT_SCALAR(errors, '$[0].error_message') as error
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE status = 'failed'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ORDER BY started_at DESC;

-- Example 5: Validation quality summary
-- SELECT 
--   data_date,
--   validation_mode,
--   COUNT(*) as run_count,
--   AVG(source_data_freshness_days) as avg_freshness_days,
--   COUNTIF(validation_skipped_reason IS NOT NULL) as skipped_count
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'roster'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY data_date, validation_mode
-- ORDER BY data_date DESC;

-- =============================================================================
-- MONITORING QUERIES
-- =============================================================================

-- Alert: Processor hasn't run in 2+ days
-- SELECT processor_name
-- FROM (
--   SELECT 
--     processor_name,
--     DATE_DIFF(CURRENT_DATE(), MAX(data_date), DAY) as days_stale
--   FROM `nba-props-platform.nba_reference.processor_run_history`
--   WHERE status = 'success'
--   GROUP BY processor_name
-- )
-- WHERE days_stale > 2;

-- Alert: Stale source data detected
-- SELECT 
--   processor_name,
--   data_date,
--   source_data_freshness_days,
--   validation_skipped_reason
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE source_data_freshness_days > 1
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ORDER BY data_date DESC;

-- Alert: Multiple consecutive failures
-- SELECT 
--   processor_name,
--   COUNT(*) as failure_count,
--   MIN(data_date) as first_failure,
--   MAX(data_date) as last_failure
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE status = 'failed'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY processor_name
-- HAVING COUNT(*) >= 3;

-- =============================================================================
-- NOTES
-- =============================================================================
-- 1. Always filter by data_date when querying (partition requirement)
-- 2. Only status='success' means date was successfully processed
-- 3. Multiple runs for same date are allowed (backfills, retries)
-- 4. run_id ensures uniqueness even for same date/processor
-- 5. This table grows ~2 rows per day per processor (gamebook + roster)
-- 6. Expected size: ~730 rows/year (365 days × 2 processors)
-- 7. With 3-year retention: ~2,190 rows total (very manageable)
-- 8. Validation fields enable data quality monitoring for roster processor
-- 9. source_data_freshness_days tracks NBA.com data staleness