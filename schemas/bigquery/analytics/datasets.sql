-- ============================================================================
-- Phase 3: Analytics Dataset
-- ============================================================================
-- Creates the nba_analytics dataset for historical performance and context
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/analytics/datasets.sql

CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_analytics`
OPTIONS (
  description = "Phase 3: Historical player and team performance with calculated metrics. Enriched data ready for predictions.",
  location = "US"
);
