-- Quality Metadata Schema Migration (BigQuery Compatible)
-- ===================================
--
-- Adds quality tracking columns to analytics and precompute tables
-- Split into separate ADD and SET DEFAULT statements per BigQuery requirements
--
-- Created: 2026-01-27 (v2 - BigQuery compatible)

-- =============================================================================
-- PHASE 3: Analytics Tables
-- =============================================================================

-- Player Game Summary
ALTER TABLE `nba_analytics.player_game_summary`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING OPTIONS(description='Quality flag: complete | partial | incomplete | corrected');

ALTER TABLE `nba_analytics.player_game_summary`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 OPTIONS(description='Quality score 0-1, based on completeness and data source');

ALTER TABLE `nba_analytics.player_game_summary`
ADD COLUMN IF NOT EXISTS processing_context STRING OPTIONS(description='Context: daily | backfill | manual | cascade');

-- Team Offense Game Summary
ALTER TABLE `nba_analytics.team_offense_game_summary`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING;

ALTER TABLE `nba_analytics.team_offense_game_summary`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64;

ALTER TABLE `nba_analytics.team_offense_game_summary`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- Team Defense Game Summary
ALTER TABLE `nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING;

ALTER TABLE `nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64;

ALTER TABLE `nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- Upcoming Player Game Context
ALTER TABLE `nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING;

ALTER TABLE `nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64;

ALTER TABLE `nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- Upcoming Team Game Context
ALTER TABLE `nba_analytics.upcoming_team_game_context`
ADD COLUMN IF NOT EXISTS data_quality_flag STRING;

ALTER TABLE `nba_analytics.upcoming_team_game_context`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64;

ALTER TABLE `nba_analytics.upcoming_team_game_context`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- =============================================================================
-- PHASE 4: Precompute Tables
-- =============================================================================

-- Player Composite Factors
ALTER TABLE `nba_precompute.player_composite_factors`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 OPTIONS(description='Overall quality score 0-1');

ALTER TABLE `nba_precompute.player_composite_factors`
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 OPTIONS(description='Primary window completeness ratio');

ALTER TABLE `nba_precompute.player_composite_factors`
ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 OPTIONS(description='Minimum quality from upstream sources (weakest link)');

ALTER TABLE `nba_precompute.player_composite_factors`
ADD COLUMN IF NOT EXISTS processing_context STRING OPTIONS(description='Context: daily | backfill | manual | cascade');

-- Player Daily Cache
ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 OPTIONS(description='Overall quality score 0-1');

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 OPTIONS(description='Average completeness across all windows');

-- Window-specific completeness flags
ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS points_l5_complete BOOL OPTIONS(description='Last 5 games window is complete');

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS points_l10_complete BOOL OPTIONS(description='Last 10 games window is complete');

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS points_l7d_complete BOOL OPTIONS(description='Last 7 days window is complete');

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS points_l14d_complete BOOL OPTIONS(description='Last 14 days window is complete');

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS rebounds_l5_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS rebounds_l10_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS rebounds_l7d_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS rebounds_l14d_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS assists_l5_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS assists_l10_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS assists_l7d_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS assists_l14d_complete BOOL;

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 OPTIONS(description='Minimum quality from upstream sources');

ALTER TABLE `nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- ML Feature Store V2
ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 OPTIONS(description='Overall quality score 0-1');

ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 OPTIONS(description='Average completeness of rolling features');

ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS rolling_features_complete BOOL OPTIONS(description='All rolling window features are complete');

ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS contextual_features_complete BOOL OPTIONS(description='All contextual features are complete');

ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS opponent_features_complete BOOL OPTIONS(description='All opponent features are complete');

ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 OPTIONS(description='Minimum quality from upstream sources (weakest link)');

ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- Player Shot Zone Analysis
ALTER TABLE `nba_precompute.player_shot_zone_analysis`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64;

ALTER TABLE `nba_precompute.player_shot_zone_analysis`
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64;

ALTER TABLE `nba_precompute.player_shot_zone_analysis`
ADD COLUMN IF NOT EXISTS processing_context STRING;

-- Team Defense Zone Analysis
ALTER TABLE `nba_precompute.team_defense_zone_analysis`
ADD COLUMN IF NOT EXISTS quality_score FLOAT64;

ALTER TABLE `nba_precompute.team_defense_zone_analysis`
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64;

ALTER TABLE `nba_precompute.team_defense_zone_analysis`
ADD COLUMN IF NOT EXISTS processing_context STRING;
