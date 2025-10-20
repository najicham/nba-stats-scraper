-- ============================================================================
-- Infrastructure: Processing Monitoring Dataset
-- ============================================================================
-- Creates the nba_processing dataset for pipeline monitoring
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/processing/datasets.sql

CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_processing`
OPTIONS (
  description = "Pipeline execution logs, data quality tracking, and monitoring. Used for debugging and operations.",
  location = "US"
);
