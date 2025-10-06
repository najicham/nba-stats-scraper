-- File: schemas/bigquery/nba_reference/processor_run_history.sql
-- Description: Tracks all registry processor runs for temporal ordering and gap detection
-- Created: 2025-10-04
-- Updated: 2025-10-05 - Added source date tracking fields for strict date matching
-- Purpose: Prevent duplicate processing, detect gaps, provide audit trail

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.processor_run_history` (
    -- =============================================================================
    -- IDENTIFICATION: Which processor ran for what data
    -- =============================================================================
    
    processor_name STRING NOT NULL, -- Which processor executed ('gamebook' or 'roster')
    run_id STRING NOT NULL, -- Unique identifier for this specific execution
    season_year INT64, -- NBA season starting year (e.g., 2024 for 2024-25 season)
    
    -- =============================================================================
    -- EXECUTION STATUS: How did the run perform
    -- =============================================================================
    
    status STRING NOT NULL, -- Execution status ('running', 'success', 'failed', 'partial', 'skipped')
    duration_seconds FLOAT64, -- How long processing took in seconds
    
    -- =============================================================================
    -- RECORD COUNTS: What was processed
    -- =============================================================================
    
    records_processed INT64 DEFAULT 0, -- Total records handled (created + updated + skipped)
    records_created INT64 DEFAULT 0, -- New registry records inserted
    records_updated INT64 DEFAULT 0, -- Existing registry records modified
    records_skipped INT64 DEFAULT 0, -- Records not processed due to staleness/protection checks
    
    -- =============================================================================
    -- SOURCE DATA: Where did the data come from
    -- =============================================================================
    
    data_source_primary STRING, -- Primary data source ('nba_gamebook', 'espn_roster', etc.)
    data_source_enhancement STRING, -- Secondary/enhancement data source ('br_roster', 'espn_roster', 'none')
    data_records_queried INT64, -- How many source records were queried
    
    -- =============================================================================
    -- DATA QUALITY TRACKING: Validation and freshness
    -- =============================================================================
    
    validation_mode STRING, -- Validation method used ('full', 'partial', 'none')
    validation_skipped_reason STRING, -- Why validation was skipped ('nbacom_stale', 'nbacom_unavailable', etc.)
    source_data_freshness_days INT64, -- How stale primary source data was in days (0=same day)
    
    -- =============================================================================
    -- SOURCE DATE TRACKING: What actual source dates were used
    -- =============================================================================
    
    espn_roster_date DATE, -- Actual roster_date from ESPN data used in this run
    nbacom_source_date DATE, -- Actual source_file_date from NBA.com data used in this run
    br_scrape_date DATE, -- Actual last_scraped_date from Basketball Reference data used
    gamebook_pdf_date DATE, -- Actual PDF date from gamebook data used (NULL for roster processor)
    
    espn_matched_requested_date BOOLEAN, -- TRUE if espn_roster_date matched data_date exactly
    nbacom_matched_requested_date BOOLEAN, -- TRUE if nbacom_source_date matched data_date exactly
    br_matched_requested_date BOOLEAN, -- TRUE if br_scrape_date matched data_date exactly
    gamebook_matched_requested_date BOOLEAN, -- TRUE if gamebook_pdf_date matched data_date exactly
    
    used_source_fallback BOOLEAN DEFAULT FALSE, -- TRUE if any source used fallback (latest available vs exact date)
    
    -- =============================================================================
    -- FILTERS: What scope was processed
    -- =============================================================================
    
    season_filter STRING, -- Season filter applied (e.g., "2024-25") or NULL for all seasons
    team_filter STRING, -- Team filter applied (e.g., "LAL") or NULL for all teams
    date_range_filter_start DATE, -- Start date of filter range (NULL for single-date processing)
    date_range_filter_end DATE, -- End date of filter range (NULL for single-date processing)
    
    -- =============================================================================
    -- FLAGS: How was the processor invoked
    -- =============================================================================
    
    backfill_mode BOOLEAN DEFAULT FALSE, -- TRUE if --allow-backfill flag was used
    force_reprocess BOOLEAN DEFAULT FALSE, -- TRUE if --force-reprocess flag was used
    test_mode BOOLEAN DEFAULT FALSE, -- TRUE if processor was run in test mode
    
    -- =============================================================================
    -- ENVIRONMENT: Where and how was it triggered
    -- =============================================================================
    
    execution_host STRING, -- Where processor ran ('cloud-run', 'local', 'backfill-job', 'workflow')
    triggered_by STRING, -- What triggered execution ('scheduler', 'manual', 'workflow', 'api', 'retry')
    
    -- =============================================================================
    -- RESULTS: Errors and warnings
    -- =============================================================================
    
    errors JSON, -- Array of error objects if processing failed
    warnings JSON, -- Array of warning objects (non-fatal issues)
    summary JSON, -- Complete result summary from processor
    
    -- =============================================================================
    -- DATES: When and what (at end per convention)
    -- =============================================================================
    
    data_date DATE NOT NULL, -- The date this data represents (partition key)
    started_at TIMESTAMP NOT NULL, -- When processor execution started
    processed_at TIMESTAMP, -- When processing completed (NULL while status='running')
    
    PRIMARY KEY (processor_name, data_date, run_id) NOT ENFORCED
)
PARTITION BY data_date
CLUSTER BY processor_name, status, season_year
OPTIONS (
  description = "Audit log of all registry processor runs with source date tracking for strict date matching validation"
);

-- =============================================================================
-- NEW QUERY EXAMPLES: Source Date Tracking
-- =============================================================================

-- Example 1: Find runs where sources didn't match requested date
-- SELECT 
--   data_date,
--   espn_roster_date,
--   nbacom_source_date,
--   br_scrape_date,
--   used_source_fallback
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'roster'
--   AND used_source_fallback = TRUE
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ORDER BY data_date DESC;

-- Example 2: Check average staleness by source
-- SELECT 
--   AVG(DATE_DIFF(data_date, espn_roster_date, DAY)) as espn_avg_staleness,
--   AVG(DATE_DIFF(data_date, nbacom_source_date, DAY)) as nbacom_avg_staleness,
--   AVG(DATE_DIFF(data_date, br_scrape_date, DAY)) as br_avg_staleness,
--   COUNT(*) as total_runs
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'roster'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
--   AND status = 'success';

-- Example 3: Identify which sources are most frequently missing
-- SELECT 
--   COUNTIF(espn_roster_date IS NULL) as espn_missing_count,
--   COUNTIF(nbacom_source_date IS NULL) as nbacom_missing_count,
--   COUNTIF(br_scrape_date IS NULL) as br_missing_count,
--   COUNT(*) as total_runs
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'roster'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Example 4: Alert on runs with missing sources
-- SELECT 
--   data_date,
--   CASE 
--     WHEN espn_roster_date IS NULL THEN 'ESPN missing'
--     WHEN nbacom_source_date IS NULL THEN 'NBA.com missing'
--     WHEN br_scrape_date IS NULL THEN 'BR missing'
--   END as missing_source,
--   status
-- FROM `nba-props-platform.nba_reference.processor_run_history`
-- WHERE processor_name = 'roster'
--   AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND (espn_roster_date IS NULL 
--        OR nbacom_source_date IS NULL 
--        OR br_scrape_date IS NULL)
-- ORDER BY data_date DESC;