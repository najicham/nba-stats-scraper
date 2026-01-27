-- Quality Metadata Schema Migration
-- ===================================
--
-- Adds quality tracking columns to analytics and precompute tables
-- to track data completeness and processing context.
--
-- Purpose: Enable detection of contaminated rolling averages and ML features
--          caused by late-arriving backfill data.
--
-- Created: 2026-01-26
-- Related: docs/08-projects/current/data-lineage-integrity/

-- =============================================================================
-- PHASE 3: Analytics Tables
-- =============================================================================

-- Player Game Summary
-- -------------------
-- Tracks quality of individual game data
ALTER TABLE `nba_analytics.player_game_summary`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING DEFAULT 'complete'
  OPTIONS(description='Quality flag: complete | partial | incomplete | corrected'),
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0
  OPTIONS(description='Quality score 0-1, based on completeness and data source'),
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily'
  OPTIONS(description='Context: daily | backfill | manual | cascade');

-- Team Offense Game Summary
ALTER TABLE `nba_analytics.team_offense_game_summary`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING DEFAULT 'complete',
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- Team Defense Game Summary
ALTER TABLE `nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING DEFAULT 'complete',
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- Upcoming Player Game Context
ALTER TABLE `nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING DEFAULT 'complete',
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- Upcoming Team Game Context
ALTER TABLE `nba_analytics.upcoming_team_game_context`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING DEFAULT 'complete',
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- =============================================================================
-- PHASE 4: Precompute Tables
-- =============================================================================

-- Player Composite Factors
-- ------------------------
-- Tracks quality of composite calculations with detailed window completeness
ALTER TABLE `nba_precompute.player_composite_factors`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0
  OPTIONS(description='Overall quality score 0-1'),
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 DEFAULT 1.0
  OPTIONS(description='Primary window completeness ratio'),
ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 DEFAULT 1.0
  OPTIONS(description='Minimum quality from upstream sources (weakest link)'),
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily'
  OPTIONS(description='Context: daily | backfill | manual | cascade');

-- Player Daily Cache
-- ------------------
-- Tracks completeness of rolling windows in cached statistics
ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0
  OPTIONS(description='Overall quality score 0-1'),
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 DEFAULT 1.0
  OPTIONS(description='Average completeness across all windows'),

-- Window-specific completeness flags for L5, L10, L7d, L14d
ADD COLUMN IF NOT EXISTS points_l5_complete BOOL DEFAULT true
  OPTIONS(description='Last 5 games window is complete'),
ADD COLUMN IF NOT EXISTS points_l10_complete BOOL DEFAULT true
  OPTIONS(description='Last 10 games window is complete'),
ADD COLUMN IF NOT EXISTS points_l7d_complete BOOL DEFAULT true
  OPTIONS(description='Last 7 days window is complete'),
ADD COLUMN IF NOT EXISTS points_l14d_complete BOOL DEFAULT true
  OPTIONS(description='Last 14 days window is complete'),

ADD COLUMN IF NOT EXISTS rebounds_l5_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS rebounds_l10_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS rebounds_l7d_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS rebounds_l14d_complete BOOL DEFAULT true,

ADD COLUMN IF NOT EXISTS assists_l5_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS assists_l10_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS assists_l7d_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS assists_l14d_complete BOOL DEFAULT true,

ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 DEFAULT 1.0
  OPTIONS(description='Minimum quality from upstream sources'),
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- ML Feature Store V2
-- -------------------
-- Tracks quality of features used in model training/prediction
ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0
  OPTIONS(description='Overall quality score 0-1'),
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 DEFAULT 1.0
  OPTIONS(description='Average completeness of rolling features'),

-- Feature group completeness flags
ADD COLUMN IF NOT EXISTS rolling_features_complete BOOL DEFAULT true
  OPTIONS(description='All rolling window features are complete'),
ADD COLUMN IF NOT EXISTS contextual_features_complete BOOL DEFAULT true
  OPTIONS(description='All contextual features are complete'),
ADD COLUMN IF NOT EXISTS opponent_features_complete BOOL DEFAULT true
  OPTIONS(description='All opponent features are complete'),

ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 DEFAULT 1.0
  OPTIONS(description='Minimum quality from upstream sources (weakest link)'),
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- Player Shot Zone Analysis
ALTER TABLE `nba_precompute.player_shot_zone_analysis`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- Team Defense Zone Analysis
ALTER TABLE `nba_precompute.team_defense_zone_analysis`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- =============================================================================
-- INDEXES FOR QUALITY QUERIES
-- =============================================================================

-- Add indexes to support quality validation queries
-- Note: BigQuery uses clustering and partitioning instead of traditional indexes

-- Example clustering recommendation (apply when creating new tables):
-- CLUSTER BY game_date, quality_score, processing_context

-- =============================================================================
-- VALIDATION QUERIES
-- =============================================================================

-- Check distribution of quality scores by date
/*
SELECT
  game_date,
  processing_context,
  COUNT(*) as record_count,
  AVG(quality_score) as avg_quality,
  SUM(CASE WHEN quality_score < 0.7 THEN 1 ELSE 0 END) as low_quality_count,
  SUM(CASE WHEN quality_score >= 1.0 THEN 1 ELSE 0 END) as perfect_quality_count
FROM `nba_precompute.player_daily_cache`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date, processing_context
ORDER BY game_date DESC;
*/

-- Find records with incomplete windows
/*
SELECT
  player_lookup,
  game_date,
  quality_score,
  window_completeness,
  CONCAT(
    IF(NOT points_l5_complete, 'L5,', ''),
    IF(NOT points_l10_complete, 'L10,', ''),
    IF(NOT points_l7d_complete, 'L7d,', ''),
    IF(NOT points_l14d_complete, 'L14d,', '')
  ) as incomplete_windows
FROM `nba_precompute.player_daily_cache`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND (
    NOT points_l5_complete
    OR NOT points_l10_complete
    OR NOT points_l7d_complete
    OR NOT points_l14d_complete
  )
ORDER BY game_date DESC, quality_score ASC
LIMIT 100;
*/

-- Compare processing contexts
/*
SELECT
  processing_context,
  COUNT(*) as record_count,
  AVG(quality_score) as avg_quality,
  COUNT(DISTINCT game_date) as date_count
FROM `nba_precompute.player_daily_cache`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY processing_context
ORDER BY processing_context;
*/
