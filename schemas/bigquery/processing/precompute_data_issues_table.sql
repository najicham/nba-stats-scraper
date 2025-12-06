-- ============================================================================
-- PRECOMPUTE DATA ISSUES TABLE
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/processing/precompute_data_issues_table.sql
-- Purpose: Track data quality issues detected during Phase 4 precompute processing
-- Created: 2025-12-05 (Session 37: Schema Fixes)

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_data_issues` (
  issue_id STRING NOT NULL,
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  issue_type STRING NOT NULL,
  severity STRING NOT NULL,
  category STRING,
  identifier STRING NOT NULL,
  table_name STRING,
  field_name STRING,
  issue_description STRING NOT NULL,
  expected_value STRING,
  actual_value STRING,
  analysis_date DATE,
  game_date DATE,
  season_year INT64,
  team_abbr STRING,
  player_lookup STRING,
  resolved BOOLEAN DEFAULT FALSE,
  resolution_notes STRING,
  auto_resolved BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  resolved_at TIMESTAMP
)
PARTITION BY DATE(created_at)
CLUSTER BY processor_name, resolved, severity, created_at
OPTIONS (
  description = "Data quality issues tracked during Phase 4 precompute processing for debugging and improvement"
);
