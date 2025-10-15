-- File: schemas/bigquery/processor_run_history_schema.sql
-- Processor Run History Tracking Table
-- 
-- Tracks execution history for processors that log their runs
-- Used by processor_execution_monitoring system

CREATE TABLE IF NOT EXISTS `nba_reference.processor_run_history` (
    -- Identification
    processor_name STRING NOT NULL,        -- 'gamebook', 'roster', etc.
    run_id STRING NOT NULL,                -- Unique: 'gamebook_20241004_083045_a3f2'
    processing_date DATE NOT NULL,         -- Date being processed (PRIMARY KEY)
    run_timestamp TIMESTAMP NOT NULL,      -- When execution started (UTC)
    
    -- Status
    status STRING NOT NULL,                -- 'success', 'failed', 'partial', 'skipped', 'running'
    duration_seconds FLOAT64,              -- How long execution took
    
    -- Counts
    records_processed INT64,               -- Total records handled
    records_created INT64,                 -- New records inserted
    records_updated INT64,                 -- Existing records updated
    records_skipped INT64,                 -- Records skipped
    records_deleted INT64,                 -- Records deleted (if applicable)
    
    -- Source data metadata
    season_year INT64,                     -- 2024 for 2024-25 season
    data_date_range_start DATE,            -- Actual source data dates processed
    data_date_range_end DATE,
    
    -- Processing modes
    backfill_mode BOOLEAN,                 -- Was --allow-backfill used?
    force_reprocess BOOLEAN,               -- Was --force used?
    dry_run BOOLEAN,                       -- Was this a dry run?
    
    -- Issues and warnings
    errors JSON,                           -- Array of error objects
    warnings JSON,                         -- Array of warning objects
    
    -- Execution context
    triggered_by STRING,                   -- 'scheduler', 'manual', 'retry', 'api'
    trigger_source STRING,                 -- User email, service account, etc.
    execution_environment STRING,          -- 'cloud_run', 'local', 'cloud_function'
    
    -- Completion tracking
    completed_at TIMESTAMP,                -- When execution finished (NULL if running)
    error_message STRING,                  -- Brief error summary if failed
    
    -- Metadata
    processor_version STRING,              -- Code version/git commit
    config_hash STRING,                    -- Hash of processor config
    
    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY processing_date
CLUSTER BY processor_name, status, run_timestamp
OPTIONS(
    description = "Tracks processor execution history for monitoring and debugging",
    labels = [("system", "monitoring"), ("type", "execution_history")]
);

-- Create index for staleness queries
CREATE INDEX IF NOT EXISTS idx_processor_status_date
ON `nba_reference.processor_run_history`(processor_name, status, processing_date DESC);

-- Create view for latest successful runs per processor
CREATE OR REPLACE VIEW `nba_reference.processor_run_history_latest` AS
SELECT 
    processor_name,
    MAX(processing_date) as last_processing_date,
    MAX(run_timestamp) as last_run_timestamp,
    DATE_DIFF(CURRENT_DATE(), MAX(processing_date), DAY) as days_since_last_run
FROM `nba_reference.processor_run_history`
WHERE status = 'success'
GROUP BY processor_name;

-- Create view for recent failures
CREATE OR REPLACE VIEW `nba_reference.processor_run_history_failures` AS
SELECT 
    processor_name,
    processing_date,
    run_timestamp,
    duration_seconds,
    error_message,
    JSON_EXTRACT_SCALAR(errors, '$[0].error_type') as first_error_type,
    JSON_EXTRACT_SCALAR(errors, '$[0].error_message') as first_error_message
FROM `nba_reference.processor_run_history`
WHERE status = 'failed'
    AND processing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY run_timestamp DESC;

-- Create view for monitoring dashboard
CREATE OR REPLACE VIEW `nba_reference.processor_run_history_summary` AS
SELECT 
    processor_name,
    COUNT(*) as total_runs,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful_runs,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_runs,
    ROUND(COUNT(CASE WHEN status = 'success' THEN 1 END) * 100.0 / COUNT(*), 2) as success_rate,
    AVG(duration_seconds) as avg_duration_seconds,
    MIN(processing_date) as first_run,
    MAX(processing_date) as last_run
FROM `nba_reference.processor_run_history`
WHERE processing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY processor_name;