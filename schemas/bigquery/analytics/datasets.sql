-- ============================================================================
-- NBA ANALYTICS DATASETS
-- ============================================================================
-- Creates BigQuery datasets for NBA analytics pipeline
-- Location: nba-stats-scraper/schemas/bigquery/analytics/datasets.sql

-- Analytics dataset for computed NBA metrics and player performance data
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_analytics`
OPTIONS (
  description = "Analytics tables with computed NBA metrics for prop betting analysis. Contains player game summaries, team offense/defense logs, and derived performance metrics."
);

-- Processing dataset for pipeline monitoring and data quality tracking
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_processing`
OPTIONS (
  description = "Processing logs, data quality tracking, and analytics pipeline monitoring. Used for debugging and performance optimization."
);

-- ============================================================================
-- DATASET PERMISSIONS (Optional - adjust based on your access patterns)
-- ============================================================================

-- Grant analytics dataset access to compute service accounts
-- GRANT `roles/bigquery.dataViewer` ON SCHEMA `nba-props-platform.nba_analytics` 
-- TO "serviceAccount:analytics-processor@nba-props-platform.iam.gserviceaccount.com";

-- Grant processing dataset access for monitoring
-- GRANT `roles/bigquery.dataEditor` ON SCHEMA `nba-props-platform.nba_processing` 
-- TO "serviceAccount:analytics-processor@nba-props-platform.iam.gserviceaccount.com";