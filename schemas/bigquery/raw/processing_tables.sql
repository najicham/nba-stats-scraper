-- Processing metadata and quality tracking tables

-- Processor run log (matches scraper ingestion pattern)
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.processor_runs` (
  run_id STRING NOT NULL,              -- 8-char UUID like scrapers
  processor_name STRING NOT NULL,      -- e.g., "BasketballRefRosterProcessor"
  
  -- Timing
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  
  -- Status
  status STRING NOT NULL,              -- 'running', 'success', 'failed'
  error_message STRING,
  
  -- Metrics
  rows_processed INT64,
  rows_inserted INT64,
  rows_updated INT64,
  rows_failed INT64,
  
  -- Performance
  load_time_seconds FLOAT64,
  transform_time_seconds FLOAT64,
  save_time_seconds FLOAT64,
  total_runtime_seconds FLOAT64,
  
  -- Context
  opts JSON,                           -- Processing options
  file_path STRING,                    -- Source file processed
  
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(started_at)
CLUSTER BY processor_name, status;

-- Data quality issues
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.quality_issues` (
  issue_id STRING DEFAULT GENERATE_UUID(),
  detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  
  -- Context
  processor_name STRING NOT NULL,
  source_table STRING,
  record_key STRING,                   -- Identifier of problematic record
  
  -- Issue details
  issue_type STRING NOT NULL,          -- 'missing_field', 'invalid_value', 'duplicate'
  issue_severity STRING NOT NULL,      -- 'info', 'warning', 'error', 'critical'
  issue_description STRING,
  issue_details JSON,                  -- Flexible additional details
  
  -- Resolution
  resolved BOOLEAN DEFAULT FALSE,
  resolved_at TIMESTAMP,
  resolution_notes STRING,
  
  PRIMARY KEY (issue_id) NOT ENFORCED
)
PARTITION BY DATE(detected_at)
CLUSTER BY processor_name, issue_severity;

-- Name resolution tracking (for fuzzy matching)
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.name_resolutions` (
  detected_date DATE NOT NULL,
  processor_name STRING NOT NULL,
  
  -- Name matching
  searched_name STRING NOT NULL,       -- What we looked for
  matched_name STRING,                 -- What we found
  similarity_score FLOAT64,            -- Match confidence (0-1)
  
  -- Context
  team_abbrev STRING,
  season_year INT64,
  
  -- Resolution
  resolution_type STRING,              -- 'auto_matched', 'manual_review', 'not_found'
  
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY detected_date
CLUSTER BY processor_name, resolution_type;