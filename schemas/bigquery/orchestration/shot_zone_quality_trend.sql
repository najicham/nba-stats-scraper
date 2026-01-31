-- Shot Zone Quality Trend Table
-- Stores daily shot zone data quality metrics for trend analysis and alerting
-- Created: Session 54 (2026-01-31)
-- Purpose: Track shot zone completeness and rate distributions to detect regressions

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.shot_zone_quality_trend` (
    -- Primary key
    game_date DATE NOT NULL,

    -- Completeness metrics
    total_records INT64 NOT NULL,
    complete_records INT64 NOT NULL,
    pct_complete FLOAT64 NOT NULL,

    -- Rate distributions (for complete records only)
    avg_paint_rate FLOAT64,
    avg_three_rate FLOAT64,
    avg_mid_rate FLOAT64,

    -- Anomaly counts (data corruption indicators)
    low_paint_anomalies INT64,  -- Count of records with paint <25%
    high_three_anomalies INT64,  -- Count of records with three >55%

    -- Metadata
    checked_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_date
OPTIONS(
    description="Daily shot zone data quality metrics for monitoring and trend analysis"
);
