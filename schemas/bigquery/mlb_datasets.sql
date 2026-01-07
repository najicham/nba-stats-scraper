-- ============================================================================
-- MLB Props Platform - Master Dataset Creation
-- ============================================================================
-- Creates all BigQuery datasets for MLB Pitcher Strikeout Predictions
-- Run this first before creating any tables
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/mlb_datasets.sql
--
-- Note: Uses same project (nba-props-platform) but separate datasets prefixed with mlb_
-- ============================================================================

-- ============================================================================
-- PHASE 2: Raw Data
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.mlb_raw`
OPTIONS (
  description = "Phase 2: Scraped MLB data from Ball Don't Lie API. Minimally processed, close to original format. Contains pitcher stats, games, injuries.",
  location = "US"
);

-- ============================================================================
-- PHASE 3: Analytics Enrichment
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.mlb_analytics`
OPTIONS (
  description = "Phase 3: MLB pitcher performance analytics with calculated metrics. Rolling averages, home/away splits, historical trends.",
  location = "US"
);

-- ============================================================================
-- PHASE 4: Precompute Cache
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.mlb_precompute`
OPTIONS (
  description = "Phase 4: Pre-computed MLB aggregations and feature engineering. Pitcher K/9 trends, matchup data, ML feature vectors.",
  location = "US"
);

-- ============================================================================
-- PHASE 5: Predictions
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.mlb_predictions`
OPTIONS (
  description = "Phase 5: ML model predictions for pitcher strikeout props. Ensemble predictions, accuracy tracking, betting recommendations.",
  location = "US"
);

-- ============================================================================
-- INFRASTRUCTURE: Reference Data
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.mlb_reference`
OPTIONS (
  description = "MLB reference data: Player registry, team mappings, ballpark factors. Continuously updated.",
  location = "US"
);

-- ============================================================================
-- INFRASTRUCTURE: Orchestration & Monitoring
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.mlb_orchestration`
OPTIONS (
  description = "MLB pipeline orchestration: Execution logs, scraper tracking, data quality monitoring.",
  location = "US"
);

-- ============================================================================
-- Deployment Complete
-- ============================================================================
-- Next steps:
-- 1. Deploy mlb_raw/ schemas (pitcher stats, games, injuries)
-- 2. Deploy mlb_analytics/ schemas (pitcher game summary)
-- 3. Deploy mlb_precompute/ schemas (feature engineering)
-- 4. Deploy mlb_predictions/ schemas (strikeout predictions)
-- 5. Deploy mlb_reference/ schemas (player registry)
-- 6. Deploy mlb_orchestration/ schemas (monitoring)
