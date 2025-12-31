-- Schema: Pipeline Latency Metrics Table
-- Table: nba_analytics.pipeline_latency_metrics
--
-- Tracks end-to-end pipeline latency from Phase 1 to Phase 6.
-- Used by monitoring/pipeline_latency_tracker.py to store metrics.
--
-- Created: 2025-12-30
-- Issue: P2-MON-1 End-to-end latency tracking

CREATE TABLE IF NOT EXISTS `nba_analytics.pipeline_latency_metrics` (
  -- Primary key: date of the pipeline run
  date DATE NOT NULL,

  -- Phase 1 start timestamp (when first scraper completed)
  phase1_start TIMESTAMP,

  -- Phase 6 completion timestamp (when export completed)
  phase6_complete TIMESTAMP,

  -- Total end-to-end latency in seconds (Phase 1 start to Phase 6 complete)
  total_latency_seconds INT64,

  -- Per-phase latency breakdown as JSON
  -- Example: {"phase1_to_phase2": 120, "phase2_to_phase3": 300, ...}
  phase_latencies JSON,

  -- When this record was written
  recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
PARTITION BY date
OPTIONS(
  description='Pipeline end-to-end latency metrics from Phase 1 to Phase 6',
  labels=[("component", "monitoring"), ("team", "data-engineering")]
);

-- Note: BigQuery doesn't support COMMENT ON COLUMN directly
-- Column descriptions:
-- * date: The game date for which the pipeline ran
-- * phase1_start: When Phase 1 (scrapers) started/completed
-- * phase6_complete: When Phase 6 (export) completed
-- * total_latency_seconds: Total pipeline duration in seconds
-- * phase_latencies: JSON object with per-phase latencies:
--   - phase1_to_phase2: Scraping to Phase 2 processors
--   - phase2_to_phase3: Phase 2 to Phase 3 analytics
--   - phase3_to_phase4: Phase 3 to Phase 4 precompute
--   - phase4_to_phase5: Phase 4 to Phase 5 predictions
--   - phase5_to_phase6: Phase 5 predictions to Phase 6 export
-- * recorded_at: Timestamp when this metric was recorded

-- Sample queries:

-- Average latency by day of week
/*
SELECT
  FORMAT_DATE('%A', date) as day_of_week,
  AVG(total_latency_seconds) as avg_latency_seconds,
  COUNT(*) as sample_count
FROM `nba_analytics.pipeline_latency_metrics`
WHERE date > DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY 2 DESC;
*/

-- Identify slow phase transitions
/*
SELECT
  date,
  JSON_EXTRACT_SCALAR(phase_latencies, '$.phase1_to_phase2') as phase1_to_2,
  JSON_EXTRACT_SCALAR(phase_latencies, '$.phase2_to_phase3') as phase2_to_3,
  JSON_EXTRACT_SCALAR(phase_latencies, '$.phase3_to_phase4') as phase3_to_4,
  JSON_EXTRACT_SCALAR(phase_latencies, '$.phase4_to_phase5') as phase4_to_5,
  JSON_EXTRACT_SCALAR(phase_latencies, '$.phase5_to_phase6') as phase5_to_6,
  total_latency_seconds
FROM `nba_analytics.pipeline_latency_metrics`
WHERE total_latency_seconds > 1800  -- More than 30 minutes
ORDER BY date DESC;
*/

-- Latency trend over time
/*
SELECT
  date,
  total_latency_seconds,
  AVG(total_latency_seconds) OVER (
    ORDER BY date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) as rolling_7day_avg
FROM `nba_analytics.pipeline_latency_metrics`
ORDER BY date DESC
LIMIT 30;
*/
