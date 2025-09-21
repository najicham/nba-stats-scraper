-- File: schemas/bigquery/nba_reference/datasets.sql
-- Description: Create the nba_reference dataset for NBA Player Name Resolution System
-- Created: 2025-01-20
-- Purpose: Foundational dataset for consistent player identification across all NBA data sources

-- Create the nba_reference dataset if it doesn't exist
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_reference`
OPTIONS (
  description = "NBA reference data for consistent player identification across data sources",
  location = "US"
);