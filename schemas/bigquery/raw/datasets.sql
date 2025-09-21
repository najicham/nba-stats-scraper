-- Create datasets for NBA data processing
-- Run with: bq query --use_legacy_sql=false < schemas/bigquery/datasets.sql

-- Raw data from scrapers
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_raw`
OPTIONS(
  description="Raw data from NBA scrapers",
  location="us-west2"
);

-- Processing metadata and logs
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_processing`
OPTIONS(
  description="Processing metadata, logs, and data quality tracking",
  location="us-west2"
);

-- Processed/enriched data (future use)
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_enriched`
OPTIONS(
  description="Processed and enriched NBA data",
  location="us-west2"
);