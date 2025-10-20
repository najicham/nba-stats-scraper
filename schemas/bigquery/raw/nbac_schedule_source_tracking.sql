-- File: schemas/bigquery/raw/nbac_schedule_source_tracking.sql
-- Description: Source tracking history table and views for NBA.com schedule data
--
-- PURPOSE: Track each daily processing run to monitor system health
--
-- This table answers questions like:
-- - "Which scraper ran today?" (API or CDN)
-- - "How often do we fall back to CDN?"
-- - "How long does processing take?"
-- - "Did any errors occur?"
--
-- Example use case:
--   If props are missing, check this table to see if the scraper failed
--   or if we fell back to CDN which might be missing some data.

-- ============================================================================
-- NEW TABLE: Processing history
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_schedule_source_history` (
  -- Tracking identifiers
  processing_id STRING NOT NULL,
  season STRING NOT NULL,
  season_nba_format STRING NOT NULL,
  processing_date DATE NOT NULL,
  
  -- Source information
  data_source STRING NOT NULL,              -- "api_stats" or "cdn_static"
  is_fallback BOOLEAN DEFAULT FALSE,        -- Was this a fallback run?
  primary_source_failed BOOLEAN DEFAULT FALSE,  -- Did primary source fail?
  
  -- Processing stats
  games_processed INT64,
  games_inserted INT64,
  games_updated INT64,
  games_skipped INT64,
  
  -- Timing
  processing_duration_seconds INT64,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP NOT NULL,
  
  -- File information
  source_file_path STRING,
  file_size_bytes INT64,
  
  -- Error tracking
  had_errors BOOLEAN DEFAULT FALSE,
  error_message STRING,
  
  -- Metadata
  processor_version STRING,
  notes STRING
)
PARTITION BY processing_date
CLUSTER BY processing_date, data_source, season_nba_format
OPTIONS (
  description = "Historical record of schedule processing runs, tracking which data source was used and whether fallback was triggered.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS: Source tracking analytics
-- ============================================================================

-- View: Current source usage by season
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_source_usage` AS
SELECT 
  season_nba_format,
  data_source,
  COUNT(*) as game_count,
  COUNT(CASE WHEN is_primetime THEN 1 END) as primetime_count,
  COUNT(CASE WHEN has_national_tv THEN 1 END) as national_tv_count,
  MAX(source_updated_at) as last_updated,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM `nba_raw.nbac_schedule`
WHERE data_source IS NOT NULL
  AND game_date >= "2020-01-01"
GROUP BY season_nba_format, data_source
ORDER BY season_nba_format DESC, data_source;

-- View: Daily source health check
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_source_daily` AS
SELECT 
  game_date,
  data_source,
  COUNT(*) as games,
  COUNT(CASE WHEN is_primetime THEN 1 END) as primetime_games,
  MAX(source_updated_at) as last_update
FROM `nba_raw.nbac_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND data_source IS NOT NULL
GROUP BY game_date, data_source
ORDER BY game_date DESC, data_source;

-- View: Fallback frequency tracking
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_fallback_stats` AS
SELECT 
  DATE_TRUNC(processing_date, MONTH) as month,
  COUNT(*) as total_runs,
  COUNT(CASE WHEN is_fallback THEN 1 END) as fallback_runs,
  COUNT(CASE WHEN data_source = 'api_stats' THEN 1 END) as api_runs,
  COUNT(CASE WHEN data_source = 'cdn_static' THEN 1 END) as cdn_runs,
  ROUND(COUNT(CASE WHEN is_fallback THEN 1 END) * 100.0 / COUNT(*), 2) as fallback_percentage,
  AVG(processing_duration_seconds) as avg_processing_seconds
FROM `nba_raw.nbac_schedule_source_history`
GROUP BY month
ORDER BY month DESC;

-- View: Data quality by source
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_source_quality` AS
SELECT 
  data_source,
  season_nba_format,
  COUNT(*) as total_games,
  COUNT(CASE WHEN primary_network IS NOT NULL THEN 1 END) as games_with_network,
  COUNT(CASE WHEN is_primetime THEN 1 END) as primetime_games,
  ROUND(COUNT(CASE WHEN primary_network IS NOT NULL THEN 1 END) * 100.0 / COUNT(*), 2) as network_coverage_pct,
  ROUND(COUNT(CASE WHEN is_primetime THEN 1 END) * 100.0 / COUNT(*), 2) as primetime_pct
FROM `nba_raw.nbac_schedule`
WHERE data_source IS NOT NULL
  AND game_date >= "2020-01-01"
GROUP BY data_source, season_nba_format
ORDER BY season_nba_format DESC, data_source;

-- View: Games that switched sources
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_source_changes` AS
WITH source_changes AS (
  SELECT 
    game_id,
    game_date,
    home_team_tricode,
    away_team_tricode,
    data_source,
    source_updated_at,
    created_at,
    -- Flag if source_updated_at is different from created_at (indicates update)
    TIMESTAMP_DIFF(source_updated_at, created_at, SECOND) as seconds_since_creation
  FROM `nba_raw.nbac_schedule`
  WHERE source_updated_at IS NOT NULL
    AND created_at IS NOT NULL
)
SELECT *
FROM source_changes
WHERE seconds_since_creation > 60  -- Updated more than 1 minute after creation
ORDER BY source_updated_at DESC;

-- View: Which source are we using today?
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_today_source` AS
SELECT 
  data_source,
  COUNT(*) as games_today,
  MAX(source_updated_at) as last_update,
  STRING_AGG(DISTINCT primary_network ORDER BY primary_network) as networks
FROM `nba_raw.nbac_schedule`
WHERE game_date = CURRENT_DATE()
  AND data_source IS NOT NULL
GROUP BY data_source;

-- View: Source reliability over last 30 days
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_source_reliability` AS
SELECT 
  processing_date,
  data_source,
  is_fallback,
  games_processed,
  processing_duration_seconds,
  had_errors
FROM `nba_raw.nbac_schedule_source_history`
WHERE processing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY processing_date DESC, data_source;

-- ============================================================================
-- USEFUL MONITORING QUERIES (as comments for documentation)
-- ============================================================================

-- Check if we're using API or CDN for current season
/*
SELECT 
  data_source,
  COUNT(*) as games,
  COUNT(CASE WHEN game_date >= CURRENT_DATE() THEN 1 END) as upcoming_games,
  MAX(source_updated_at) as last_update
FROM `nba_raw.nbac_schedule`
WHERE season_nba_format = '2025-26'
  AND data_source IS NOT NULL
  AND game_date >= "2025-10-01"
GROUP BY data_source;
*/

-- Find games where we fell back to CDN
/*
SELECT 
  game_date,
  home_team_tricode,
  away_team_tricode,
  data_source,
  source_updated_at
FROM `nba_raw.nbac_schedule`
WHERE data_source = 'cdn_static'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;
*/

-- Check fallback frequency this month
/*
SELECT 
  COUNT(*) as total_runs,
  COUNT(CASE WHEN is_fallback THEN 1 END) as fallback_runs,
  ROUND(COUNT(CASE WHEN is_fallback THEN 1 END) * 100.0 / COUNT(*), 1) as fallback_pct
FROM `nba_raw.nbac_schedule_source_history`
WHERE processing_date >= DATE_TRUNC(CURRENT_DATE(), MONTH)
  AND processing_date <= CURRENT_DATE();
*/

-- Compare data quality between sources
/*
SELECT 
  data_source,
  COUNT(*) as games,
  COUNT(CASE WHEN primary_network IS NOT NULL THEN 1 END) as with_network,
  ROUND(AVG(CASE WHEN is_primetime THEN 1 ELSE 0 END) * 100, 1) as primetime_pct,
  ROUND(AVG(CASE WHEN primary_network IS NOT NULL THEN 1 ELSE 0 END) * 100, 1) as network_coverage
FROM `nba_raw.nbac_schedule`
WHERE season_nba_format = '2025-26'
  AND data_source IS NOT NULL
  AND game_date >= "2025-10-01"
GROUP BY data_source;
*/

-- Alert: High fallback rate
/*
SELECT 
  'ALERT: High fallback rate' as alert_type,
  COUNT(CASE WHEN is_fallback THEN 1 END) as fallback_count,
  COUNT(*) as total_runs,
  ROUND(COUNT(CASE WHEN is_fallback THEN 1 END) * 100.0 / COUNT(*), 1) as fallback_pct
FROM `nba_raw.nbac_schedule_source_history`
WHERE processing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND processing_date <= CURRENT_DATE()
HAVING fallback_pct > 10;  -- Alert if >10% fallback rate
*/

-- Today's processing run
/*
SELECT 
  processing_id,
  data_source,
  is_fallback,
  games_processed,
  processing_duration_seconds,
  started_at,
  completed_at,
  had_errors,
  error_message
FROM `nba_raw.nbac_schedule_source_history`
WHERE processing_date = CURRENT_DATE()
ORDER BY started_at DESC
LIMIT 1;
*/