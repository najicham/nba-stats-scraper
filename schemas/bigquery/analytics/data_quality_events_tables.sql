-- ============================================================================
-- NBA Props Platform - Data Quality Events Analytics Table
-- Centralized tracking of data quality issues across all tables for monitoring and debugging
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.data_quality_events` (
  -- Core identifiers (4 fields)
  event_id STRING NOT NULL,                         -- Unique event identifier
  table_name STRING NOT NULL,                       -- Affected table name
  record_key STRING NOT NULL,                       -- Key of affected record
  event_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When event occurred
  
  -- Event details (4 fields)
  event_type STRING NOT NULL,                       -- "missing_data", "source_conflict", "stale_data", "calculation_error"
  severity STRING NOT NULL,                         -- "low", "medium", "high", "critical"
  description STRING,                               -- Human-readable description
  affected_fields ARRAY<STRING>,                    -- List of fields affected
  
  -- Source and resolution (3 fields)
  source_info JSON,                                 -- Details about processors/sources involved
  resolution_status STRING DEFAULT 'open',          -- "open", "resolved", "ignored", "escalated"
  impact_on_predictions STRING,                     -- "none", "reduced_confidence", "excluded", "critical"
  
  -- Processing context (2 fields)
  processor_name STRING,                            -- Which processor detected the issue
  processing_batch_id STRING,                       -- Batch identifier for grouping related issues
  
  -- Processing metadata (1 field)
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY table_name, severity, event_type
OPTIONS(
  description="Centralized tracking of data quality issues across all tables for monitoring and debugging"
);