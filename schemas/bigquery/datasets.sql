-- ============================================================================
-- NBA Props Platform - Master Dataset Creation
-- ============================================================================
-- Creates all BigQuery datasets for the NBA Props Platform
-- Run this first before creating any tables
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/datasets.sql

-- ============================================================================
-- PHASE 2: Raw Data
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_raw`
OPTIONS (
  description = "Phase 2: Scraped and normalized data from external sources (APIs, websites). Minimally processed, close to original format.",
  location = "US"
);

-- ============================================================================
-- PHASE 3: Analytics Enrichment
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_analytics`
OPTIONS (
  description = "Phase 3: Historical player and team performance with calculated metrics. Enriched data ready for predictions.",
  location = "US"
);

-- ============================================================================
-- PHASE 4: Precompute Cache
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_precompute`
OPTIONS (
  description = "Phase 4: Pre-computed aggregations and cached calculations shared across player reports. Disposable performance optimization layer.",
  location = "US"
);

-- ============================================================================
-- PHASE 5: Predictions
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_predictions`
OPTIONS (
  description = "Phase 5: ML model predictions and accuracy tracking. The core product output.",
  location = "US"
);

-- ============================================================================
-- INFRASTRUCTURE: Player Identity
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_reference`
OPTIONS (
  description = "Player identity registry with universal player IDs. Continuously updated as players are added/traded.",
  location = "US"
);

-- ============================================================================
-- INFRASTRUCTURE: Static Reference Data
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_static`
OPTIONS (
  description = "Team locations, travel distances, and league patterns. Rarely updated (seasonal or when teams relocate).",
  location = "US"
);

-- ============================================================================
-- INFRASTRUCTURE: Processing Monitoring
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_processing`
OPTIONS (
  description = "Pipeline execution logs, data quality tracking, and monitoring. Used for debugging and operations.",
  location = "US"
);

-- ============================================================================
-- Deployment Complete
-- ============================================================================
-- Next steps:
-- 1. Deploy raw/ schemas
-- 2. Deploy analytics/ schemas (Phase 3)
-- 3. Deploy precompute/ schemas (Phase 4)
-- 4. Deploy predictions/ schemas (Phase 5)
-- 5. Deploy reference/ and static/ schemas
-- 6. Deploy processing/ schemas
