-- ============================================================================
-- NBA Props Platform - Static Reference Data Dataset
-- File: schemas/bigquery/static/datasets.sql
-- Purpose: Create nba_static dataset for slowly-changing reference data
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_static`
OPTIONS (
  description = "Static reference data for NBA teams and league patterns. Updated manually or seasonally, not part of daily processing pipeline.",
  location = "US"
);
