-- File: schemas/bigquery/nba_orchestration/scraper_cost_metrics.sql
-- ============================================================================
-- NBA Props Platform - Scraper Cost Tracking Metrics
-- ============================================================================
-- Purpose: Track per-scraper execution costs including compute, network, and API costs
-- Update: Every scraper run (real-time via ScraperBase integration)
-- Entities: All scrapers (26+ active scrapers)
-- Retention: 90 days (partition expiration)
--
-- Version: 1.0
-- Date: January 23, 2026
-- Status: Production-Ready
--
-- Cost Model:
--   - Compute: Cloud Run vCPU-seconds + memory GB-seconds + per-request cost
--   - Network: Egress cost for downloaded + exported bytes
--   - API: Per-provider costs (Odds API charges, etc.)
--
-- Dependencies:
--   - nba_orchestration dataset
--   - monitoring/scraper_cost_tracker.py
--   - Integration with ScraperBase
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.scraper_cost_metrics` (
  -- ==========================================================================
  -- IDENTIFIERS (2 fields)
  -- ==========================================================================

  scraper_name STRING NOT NULL,
    -- Scraper identifier in snake_case format
    -- Examples: 'nbac_injury_report', 'oddsa_events', 'bdl_boxscores'
    -- Naming convention: [source]_[data_type]
    -- Used for: Grouping by scraper, cost analysis by source

  run_id STRING NOT NULL,
    -- Unique execution identifier (UUID or run_id from scraper)
    -- Format: 8-character hex UUID
    -- Example: "a1b2c3d4"
    -- Used for: Correlation with scraper_execution_log, debugging specific runs

  -- ==========================================================================
  -- TIMING METRICS (5 fields)
  -- ==========================================================================

  start_time TIMESTAMP NOT NULL,
    -- Execution start time in UTC
    -- Partition key (daily partitions)
    -- Used for: Time-based queries, cost trending
    -- Always filter on this field for efficient queries

  end_time TIMESTAMP,
    -- Execution end time in UTC
    -- NULL if: Failed before completion, currently running
    -- Used for: Duration calculation, completion tracking

  execution_time_seconds FLOAT64,
    -- Total execution time in seconds
    -- Includes download, processing, and export time
    -- Range: 1-300 seconds (typical), up to 600 for large scrapes
    -- Used for: Compute cost calculation, performance monitoring

  download_time_seconds FLOAT64,
    -- Time spent downloading data from APIs
    -- Subset of execution_time_seconds
    -- Used for: API performance analysis

  export_time_seconds FLOAT64,
    -- Time spent exporting data to GCS
    -- Subset of execution_time_seconds
    -- Used for: Export optimization

  -- ==========================================================================
  -- REQUEST METRICS (2 fields)
  -- ==========================================================================

  request_count INT64,
    -- Number of HTTP requests made
    -- Includes initial request and all retries
    -- Range: 1-50 (most scrapers), up to 100 for batch scrapers
    -- Used for: API cost calculation, rate limiting analysis

  retry_count INT64,
    -- Number of retry attempts (excluding initial request)
    -- request_count = 1 + retry_count for single-endpoint scrapers
    -- Range: 0-10 typically
    -- Used for: Reliability analysis, retry cost impact

  -- ==========================================================================
  -- DATA VOLUME METRICS (3 fields)
  -- ==========================================================================

  bytes_downloaded INT64,
    -- Total bytes received from API responses
    -- Sum of all response body sizes
    -- Range: 1KB - 10MB typically
    -- Used for: Network cost calculation, data volume trending

  bytes_exported INT64,
    -- Total bytes written to GCS
    -- May differ from downloaded due to transformation/compression
    -- NULL if: Export failed or skipped
    -- Used for: Storage cost estimation

  record_count INT64,
    -- Number of data records processed
    -- Business-level count (games, players, props, etc.)
    -- NULL if: Parse failed
    -- Used for: Cost per record calculation

  -- ==========================================================================
  -- STATUS (3 fields)
  -- ==========================================================================

  success BOOLEAN NOT NULL,
    -- Whether the scraper run completed successfully
    -- true = exported data, false = error occurred
    -- Used for: Error rate calculation, cost efficiency analysis

  error_type STRING,
    -- Exception class name if success=false
    -- Examples: 'DownloadDataException', 'InvalidHttpStatusCodeException'
    -- NULL if: success=true
    -- Used for: Error categorization, cost of failures

  error_message STRING,
    -- Error details if success=false
    -- Truncated to 500 characters
    -- NULL if: success=true
    -- Used for: Debugging, root cause analysis

  -- ==========================================================================
  -- RESOURCE USAGE (2 fields)
  -- ==========================================================================

  vcpu_used FLOAT64,
    -- vCPU allocation for this run
    -- Default: 1.0 for standard Cloud Run instances
    -- Range: 0.5 - 4.0
    -- Used for: Compute cost calculation

  memory_gb_used FLOAT64,
    -- Memory allocation in GB
    -- Default: 0.5 GB for standard instances
    -- Range: 0.25 - 8.0
    -- Used for: Compute cost calculation

  -- ==========================================================================
  -- COST BREAKDOWN (4 fields)
  -- ==========================================================================

  compute_cost FLOAT64,
    -- Compute cost in USD
    -- Formula: (vcpu * seconds * $0.000024) + (memory_gb * seconds * $0.0000025)
    --          + (requests * $0.0000004)
    -- Range: $0.000001 - $0.01 per run
    -- Used for: Cloud Run cost attribution

  network_cost FLOAT64,
    -- Network egress cost in USD
    -- Formula: (bytes_downloaded + bytes_exported) / 1GB * $0.12
    -- Range: $0.0000001 - $0.001 per run
    -- Used for: Network cost attribution

  api_cost FLOAT64,
    -- Third-party API cost in USD
    -- Variable by provider:
    --   - Odds API: ~$0.001/request
    --   - BettingPros: ~$0.0005/request
    --   - NBA.com, ESPN, BDL: $0 (free)
    -- Range: $0 - $0.01 per run
    -- Used for: API cost tracking, provider comparison

  total_cost FLOAT64,
    -- Total cost in USD
    -- Formula: compute_cost + network_cost + api_cost
    -- Range: $0.000001 - $0.02 per run
    -- Used for: Overall cost analysis, budget tracking

  -- ==========================================================================
  -- CONTEXT (4 fields)
  -- ==========================================================================

  source STRING,
    -- Execution trigger source
    -- Values: 'CONTROLLER', 'MANUAL', 'LOCAL', 'CLOUD_RUN', 'SCHEDULER', 'RECOVERY'
    -- Used for: Cost by trigger source

  environment STRING,
    -- Execution environment
    -- Values: 'prod', 'dev', 'local'
    -- Used for: Separating test from production costs

  workflow STRING,
    -- Parent workflow name
    -- Examples: 'injury_discovery', 'morning_operations', 'betting_lines'
    -- NULL for: Direct execution
    -- Used for: Cost by workflow

  game_date DATE,
    -- Game date for which data was collected
    -- Format: DATE (YYYY-MM-DD)
    -- NULL for: Non-date-based scrapers
    -- Used for: Cost by game date, seasonal analysis

  -- ==========================================================================
  -- METADATA (1 field)
  -- ==========================================================================

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- Row creation timestamp (auto-populated)
    -- Used for: Audit trail, data freshness

)
PARTITION BY DATE(start_time)
CLUSTER BY scraper_name, source, success
OPTIONS(
  description = "Per-scraper execution cost metrics including compute, network, and API costs. Supports cost analysis by scraper, workflow, and time period. Partition key: start_time (daily). Cluster by: scraper_name, source, success.",
  partition_expiration_days = 90
);

-- ============================================================================
-- INDEXES / VIEWS
-- ============================================================================

-- View: Daily cost summary by scraper
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_daily_costs` AS
SELECT
  DATE(start_time) as date,
  scraper_name,
  COUNT(*) as run_count,
  COUNTIF(success = true) as success_count,
  ROUND(COUNTIF(success = true) * 100.0 / COUNT(*), 1) as success_rate_pct,
  SUM(request_count) as total_requests,
  SUM(bytes_downloaded) as total_bytes,
  ROUND(SUM(bytes_downloaded) / (1024 * 1024), 2) as total_mb,
  SUM(record_count) as total_records,
  ROUND(SUM(compute_cost), 6) as compute_cost,
  ROUND(SUM(network_cost), 6) as network_cost,
  ROUND(SUM(api_cost), 6) as api_cost,
  ROUND(SUM(total_cost), 6) as total_cost
FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date, scraper_name
ORDER BY date DESC, total_cost DESC;

-- View: Scraper cost leaderboard (top spenders)
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_cost_leaderboard` AS
SELECT
  scraper_name,
  COUNT(*) as total_runs,
  ROUND(COUNTIF(success = true) * 100.0 / COUNT(*), 1) as success_rate_pct,
  ROUND(AVG(execution_time_seconds), 2) as avg_duration_seconds,
  SUM(request_count) as total_requests,
  ROUND(SUM(bytes_downloaded) / (1024 * 1024 * 1024), 4) as total_gb_downloaded,
  SUM(record_count) as total_records,
  ROUND(SUM(total_cost), 4) as total_cost_usd,
  ROUND(AVG(total_cost), 6) as avg_cost_per_run_usd,
  ROUND(SUM(total_cost) / NULLIF(SUM(record_count), 0) * 1000, 6) as cost_per_1k_records_usd
FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY scraper_name
HAVING COUNT(*) >= 5  -- At least 5 runs for meaningful stats
ORDER BY total_cost_usd DESC;

-- View: Error cost analysis (cost of failures)
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_error_costs` AS
SELECT
  scraper_name,
  error_type,
  COUNT(*) as error_count,
  ROUND(SUM(total_cost), 6) as wasted_cost,
  ROUND(AVG(execution_time_seconds), 2) as avg_time_before_error,
  MIN(start_time) as first_error,
  MAX(start_time) as last_error
FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND success = false
  AND error_type IS NOT NULL
GROUP BY scraper_name, error_type
ORDER BY wasted_cost DESC;

-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

-- Query 1: Total costs for today
-- SELECT
--   ROUND(SUM(total_cost), 4) as total_cost_today,
--   COUNT(*) as runs_today,
--   ROUND(AVG(total_cost), 6) as avg_cost_per_run
-- FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
-- WHERE DATE(start_time) = CURRENT_DATE();

-- Query 2: Most expensive scrapers this week
-- SELECT
--   scraper_name,
--   COUNT(*) as runs,
--   ROUND(SUM(total_cost), 4) as total_cost,
--   ROUND(AVG(total_cost), 6) as avg_cost
-- FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
-- WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY scraper_name
-- ORDER BY total_cost DESC
-- LIMIT 10;

-- Query 3: Cost breakdown by category
-- SELECT
--   ROUND(SUM(compute_cost), 4) as compute,
--   ROUND(SUM(network_cost), 4) as network,
--   ROUND(SUM(api_cost), 4) as api,
--   ROUND(SUM(total_cost), 4) as total
-- FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
-- WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);

-- Query 4: Wasted cost from failures
-- SELECT
--   scraper_name,
--   error_type,
--   COUNT(*) as failures,
--   ROUND(SUM(total_cost), 6) as wasted_cost
-- FROM `nba-props-platform.nba_orchestration.scraper_cost_metrics`
-- WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
--   AND success = false
-- GROUP BY scraper_name, error_type
-- ORDER BY wasted_cost DESC;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_orchestration dataset
-- [ ] Verify partitioning (daily on start_time)
-- [ ] Verify clustering (scraper_name, source, success)
-- [ ] Create views (v_scraper_daily_costs, v_scraper_cost_leaderboard, v_scraper_error_costs)
-- [ ] Test with sample insert
-- [ ] Integrate with ScraperBase (scraper_base.py)
-- [ ] Add admin dashboard endpoint
-- [ ] Configure monitoring/alerting for cost spikes
-- ============================================================================
