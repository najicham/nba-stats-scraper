-- ============================================================================
-- PROCESSING TABLES (Monitoring & Data Quality Tracking)
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/processing/processing_tables.sql
-- Purpose: Analytics processor execution logs, performance tracking, and data quality monitoring

-- Analytics processor execution logs and performance tracking
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.analytics_processor_runs` (
  -- Execution identifiers
  processor_name STRING NOT NULL,                   -- Name of the analytics processor
  run_id STRING NOT NULL,                           -- Unique run identifier
  run_date TIMESTAMP NOT NULL,                      -- When the processor was executed
  
  -- Execution results
  success BOOLEAN,                                  -- TRUE if processor completed successfully (NULLABLE for autodetect compatibility)
  duration_seconds FLOAT64,                         -- Total execution time
  
  -- Data processing scope
  date_range_start DATE,                            -- Start date of data processed
  date_range_end DATE,                              -- End date of data processed
  records_processed INT64,                          -- Number of records processed
  records_inserted INT64,                           -- Number of new records inserted
  records_updated INT64,                            -- Number of existing records updated
  records_skipped INT64,                            -- Number of records skipped (duplicates, etc.)
  
  -- Error tracking
  errors_json STRING,                               -- JSON array of error messages
  warning_count INT64,                              -- Number of non-fatal warnings
  
  -- Resource usage
  bytes_processed INT64,                            -- Bytes of source data processed
  slot_ms INT64,                                    -- BigQuery slot milliseconds used
  
  -- Source data information
  source_files_count INT64,                         -- Number of source files processed
  source_data_freshness_hours FLOAT64,              -- Hours between data creation and processing
  
  -- Processing metadata
  processor_version STRING,                         -- Version of processor code
  config_hash STRING,                               -- Hash of processor configuration

  -- Pattern support (Pattern #1: Smart Skip, Pattern #3: Early Exit)
  skip_reason STRING,                               -- Why processing was skipped (e.g., 'no_games', 'irrelevant_source', 'offseason', 'historical')

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- When record was created
)
PARTITION BY DATE(run_date)
CLUSTER BY processor_name, success, run_date
OPTIONS (
  description = "Analytics processor execution logs and performance tracking for monitoring and optimization"
  -- partition_expiration_days = 365  -- 1 year retention for processing logs
);

-- Data quality issues tracked during analytics processing
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.analytics_data_issues` (
  -- Issue identification
  issue_id STRING NOT NULL,                         -- Unique issue identifier
  processor_name STRING NOT NULL,                   -- Processor that detected the issue
  run_id STRING,                                    -- Associated processor run
  
  -- Issue classification
  issue_type STRING NOT NULL,                       -- Type of issue (missing_data, data_quality, validation_error, etc.)
  severity STRING NOT NULL,                         -- CRITICAL, HIGH, MEDIUM, LOW
  category STRING,                                  -- PERFORMANCE, ACCURACY, COMPLETENESS, CONSISTENCY
  
  -- Issue details
  identifier STRING,                                -- Game ID, player ID, or other identifier related to issue
  table_name STRING,                                -- Table where issue was detected
  field_name STRING,                                -- Specific field with issue
  issue_description STRING,                         -- Human-readable description
  expected_value STRING,                            -- What was expected
  actual_value STRING,                              -- What was found
  
  -- Context information
  game_date DATE,                                   -- Game date if applicable
  season_year INT64,                                -- Season year if applicable
  team_abbr STRING,                                 -- Team if applicable
  player_lookup STRING,                             -- Player if applicable
  
  -- Resolution tracking
  resolved BOOLEAN DEFAULT FALSE,                   -- TRUE when issue is resolved
  resolution_notes STRING,                          -- How the issue was resolved
  auto_resolved BOOLEAN DEFAULT FALSE,              -- TRUE if automatically resolved
  
  -- Timestamps
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When issue was detected
  resolved_at TIMESTAMP                             -- When issue was resolved
)
PARTITION BY DATE(created_at)
CLUSTER BY processor_name, resolved, severity, created_at
OPTIONS (
  description = "Data quality issues tracked during analytics processing for debugging and improvement",
  partition_expiration_days = 730  -- 2 years retention for issue tracking
);

-- Precompute processor execution logs and performance tracking (Phase 4)
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_processor_runs` (
  -- Execution identifiers
  processor_name STRING NOT NULL,                   -- Name of the precompute processor
  run_id STRING NOT NULL,                           -- Unique run identifier
  run_date TIMESTAMP NOT NULL,                      -- When the processor was executed

  -- Execution results
  success BOOLEAN,                                  -- TRUE if processor completed successfully (NULLABLE - fixed in Session 37)
  duration_seconds FLOAT64,                         -- Total execution time

  -- Data processing scope (Phase 4 uses single analysis_date)
  analysis_date DATE,                               -- Date being analyzed
  records_processed INT64,                          -- Number of records processed
  records_inserted INT64,                           -- Number of new records inserted
  records_updated INT64,                            -- Number of existing records updated
  records_skipped INT64,                            -- Number of records skipped (duplicates, etc.)

  -- Dependency tracking (Phase 4 specific)
  dependency_check_passed BOOLEAN,                  -- TRUE if all dependencies met
  data_completeness_pct FLOAT64,                    -- Percentage of expected upstream data present (0-100)
  upstream_data_age_hours FLOAT64,                  -- Hours since upstream data was last updated

  -- Error tracking
  errors_json STRING,                               -- JSON array of error messages
  warning_count INT64,                              -- Number of non-fatal warnings

  -- Resource usage
  bytes_processed INT64,                            -- Bytes of source data processed
  slot_ms INT64,                                    -- BigQuery slot milliseconds used

  -- Processing metadata
  processor_version STRING,                         -- Version of processor code
  config_hash STRING,                               -- Hash of processor configuration

  -- Pattern support (Pattern #1: Smart Skip, Pattern #3: Early Exit)
  skip_reason STRING,                               -- Why processing was skipped (e.g., 'no_games', 'irrelevant_source', 'offseason', 'historical')

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- When record was created
)
PARTITION BY DATE(run_date)
CLUSTER BY processor_name, success, run_date
OPTIONS (
  description = "Precompute processor execution logs and performance tracking (Phase 4)",
  partition_expiration_days = 365  -- 1 year retention for processing logs
);

-- Track individual entity failures during Phase 4 precompute processing
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_failures` (
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  analysis_date DATE NOT NULL,
  entity_id STRING NOT NULL,
  failure_category STRING NOT NULL,
  failure_reason STRING NOT NULL,
  can_retry BOOLEAN NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY processor_name, failure_category, can_retry
OPTIONS (
  description = "Track individual entity failures during Phase 4 precompute processing for debugging and retry logic"
);

-- Data quality issues tracked during Phase 4 precompute processing
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_data_issues` (
  issue_id STRING NOT NULL,
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  issue_type STRING NOT NULL,
  severity STRING NOT NULL,
  category STRING,
  identifier STRING NOT NULL,
  table_name STRING,
  field_name STRING,
  issue_description STRING NOT NULL,
  expected_value STRING,
  actual_value STRING,
  analysis_date DATE,
  game_date DATE,
  season_year INT64,
  team_abbr STRING,
  player_lookup STRING,
  resolved BOOLEAN DEFAULT FALSE,
  resolution_notes STRING,
  auto_resolved BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  resolved_at TIMESTAMP
)
PARTITION BY DATE(created_at)
CLUSTER BY processor_name, resolved, severity, created_at
OPTIONS (
  description = "Data quality issues tracked during Phase 4 precompute processing for debugging and improvement"
);

-- Analytics data source freshness tracking
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.analytics_source_freshness` (
  -- Source identification
  source_name STRING NOT NULL,                      -- Name of data source (bdl_boxscores, odds_api, etc.)
  source_type STRING NOT NULL,                      -- API, SCRAPER, FILE
  table_name STRING,                                -- Target analytics table
  
  -- Freshness metrics
  data_date DATE NOT NULL,                          -- Date of the data
  expected_arrival_time TIMESTAMP,                  -- When data was expected
  actual_arrival_time TIMESTAMP,                    -- When data actually arrived
  processing_time TIMESTAMP,                        -- When data was processed into analytics
  
  -- Data quality indicators
  record_count INT64,                               -- Number of records processed
  completeness_score FLOAT64,                       -- 0.0 to 1.0 score of data completeness
  quality_score FLOAT64,                            -- 0.0 to 1.0 overall quality score
  
  -- Delay tracking
  arrival_delay_minutes INT64,                      -- Minutes late from expected arrival
  processing_delay_minutes INT64,                   -- Minutes from arrival to processing
  
  -- Status tracking
  status STRING NOT NULL,                           -- PENDING, ARRIVED, PROCESSED, FAILED
  issues_detected INT64,                            -- Number of data quality issues found
  
  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record was created
  updated_at TIMESTAMP                              -- When record was last updated
)
PARTITION BY data_date
CLUSTER BY source_name, status, data_date
OPTIONS (
  description = "Data source freshness and quality tracking for analytics pipeline monitoring",
  partition_expiration_days = 180  -- 6 months retention
);

-- ============================================================================
-- VIEWS FOR MONITORING DASHBOARDS
-- ============================================================================

-- Recent processor performance summary
CREATE VIEW `nba-props-platform.nba_processing.processor_performance_summary` AS
SELECT 
  processor_name,
  DATE(run_date) as run_date,
  COUNT(*) as total_runs,
  COUNTIF(success) as successful_runs,
  COUNTIF(NOT success) as failed_runs,
  AVG(duration_seconds) as avg_duration_seconds,
  MAX(duration_seconds) as max_duration_seconds,
  SUM(records_processed) as total_records_processed,
  AVG(IFNULL(slot_ms, 0)) as avg_slot_ms
FROM `nba-props-platform.nba_processing.analytics_processor_runs`
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY processor_name, DATE(run_date)
ORDER BY run_date DESC, processor_name;

-- Active data quality issues requiring attention
CREATE VIEW `nba-props-platform.nba_processing.active_data_issues` AS
SELECT 
  issue_type,
  severity,
  category,
  COUNT(*) as issue_count,
  MIN(created_at) as oldest_issue,
  MAX(created_at) as newest_issue
FROM `nba-props-platform.nba_processing.analytics_data_issues`
WHERE resolved = FALSE
GROUP BY issue_type, severity, category
ORDER BY severity DESC, issue_count DESC;

-- Data freshness status for recent dates
CREATE VIEW `nba-props-platform.nba_processing.source_freshness_status` AS
SELECT 
  source_name,
  data_date,
  status,
  arrival_delay_minutes,
  processing_delay_minutes,
  completeness_score,
  quality_score,
  issues_detected
FROM `nba-props-platform.nba_processing.analytics_source_freshness`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY data_date DESC, source_name;