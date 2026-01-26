-- BigQuery Scheduled Query: Pipeline Quota Usage Tracking
-- Purpose: Monitor partition modifications and event logging patterns to prevent quota exceeded errors
-- Schedule: Run every hour
-- Destination: nba_orchestration.quota_usage_hourly
--
-- This query calculates key metrics to help predict and prevent BigQuery quota issues:
-- 1. Partition modifications per hour (BigQuery has limits on partition modifications)
-- 2. Events logged per hour (measures workload)
-- 3. Average batch size (efficiency metric - higher is better)
-- 4. Failed flush count (quality metric)
--
-- Setup Instructions:
-- 1. Create destination table (if not exists):
--    CREATE TABLE IF NOT EXISTS nba_orchestration.quota_usage_hourly (
--      hour_timestamp TIMESTAMP,
--      partition_modifications INT64,
--      events_logged INT64,
--      avg_batch_size FLOAT64,
--      failed_flushes INT64,
--      unique_processors INT64,
--      unique_game_dates INT64,
--      error_events INT64
--    )
--    PARTITION BY DATE(hour_timestamp)
--    OPTIONS(
--      description='Hourly quota usage tracking for pipeline event logging',
--      labels=[('purpose', 'monitoring'), ('component', 'pipeline_logger')]
--    );
--
-- 2. Create scheduled query in Cloud Console or via bq CLI:
--    bq mk --transfer_config \
--      --project_id=<YOUR_PROJECT_ID> \
--      --data_source=scheduled_query \
--      --schedule='every 1 hours' \
--      --display_name='Pipeline Quota Usage Tracking' \
--      --target_dataset=nba_orchestration \
--      --params='{
--        "query":"<THIS_QUERY>",
--        "destination_table_name_template":"quota_usage_hourly",
--        "write_disposition":"WRITE_APPEND",
--        "partitioning_type":"HOUR"
--      }'

WITH hourly_events AS (
  SELECT
    TIMESTAMP_TRUNC(timestamp, HOUR) AS hour_timestamp,
    event_id,
    event_type,
    phase,
    processor_name,
    game_date
  FROM `nba_orchestration.pipeline_event_log`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
),

-- Calculate partition modifications
-- Each batch flush = 1 partition modification (we write to daily partitions)
partition_mods AS (
  SELECT
    hour_timestamp,
    -- Estimate partition modifications based on batching
    -- Assumption: BATCH_SIZE=50 events per flush (configured default)
    -- So partition_mods ≈ total_events / batch_size
    CAST(CEIL(COUNT(*) / 50.0) AS INT64) AS estimated_partition_mods
  FROM hourly_events
  GROUP BY hour_timestamp
),

-- Calculate event patterns
event_stats AS (
  SELECT
    hour_timestamp,
    COUNT(*) AS events_logged,
    COUNT(DISTINCT processor_name) AS unique_processors,
    COUNT(DISTINCT game_date) AS unique_game_dates,
    COUNTIF(event_type = 'error') AS error_events
  FROM hourly_events
  GROUP BY hour_timestamp
)

SELECT
  es.hour_timestamp,
  pm.estimated_partition_mods AS partition_modifications,
  es.events_logged,
  -- Average batch size (how many events per partition modification)
  SAFE_DIVIDE(es.events_logged, pm.estimated_partition_mods) AS avg_batch_size,
  -- Failed flushes would need to be logged separately - placeholder for now
  0 AS failed_flushes,
  es.unique_processors,
  es.unique_game_dates,
  es.error_events
FROM event_stats es
JOIN partition_mods pm USING (hour_timestamp)
ORDER BY es.hour_timestamp DESC;

-- Usage Examples:
--
-- 1. Check current hour's quota usage:
--    SELECT * FROM nba_orchestration.quota_usage_hourly
--    WHERE hour_timestamp = TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), HOUR)
--    ORDER BY hour_timestamp DESC;
--
-- 2. Find hours approaching quota limits (assuming 100 partition mods/hour limit):
--    SELECT
--      hour_timestamp,
--      partition_modifications,
--      ROUND(partition_modifications / 100.0 * 100, 1) AS quota_usage_pct
--    FROM nba_orchestration.quota_usage_hourly
--    WHERE partition_modifications > 80  -- Alert at 80% threshold
--    ORDER BY hour_timestamp DESC
--    LIMIT 10;
--
-- 3. Trend analysis - detect increasing quota usage:
--    SELECT
--      DATE(hour_timestamp) AS date,
--      AVG(partition_modifications) AS avg_hourly_mods,
--      MAX(partition_modifications) AS peak_hourly_mods,
--      SUM(events_logged) AS total_daily_events
--    FROM nba_orchestration.quota_usage_hourly
--    WHERE hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
--    GROUP BY DATE(hour_timestamp)
--    ORDER BY date DESC;
--
-- 4. Alert query - find hours exceeding quota:
--    SELECT
--      hour_timestamp,
--      partition_modifications,
--      events_logged,
--      'CRITICAL: Quota exceeded' AS alert_level
--    FROM nba_orchestration.quota_usage_hourly
--    WHERE partition_modifications > 90  -- 90% of assumed 100 limit
--      AND hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
--    ORDER BY hour_timestamp DESC;
