-- ============================================================================
-- Migration: Add data_hash to team_defense_game_summary
-- Purpose: Enable Smart Reprocessing Pattern #3 for Phase 4 processors
-- Date: 2025-12-05
-- ============================================================================
-- This adds a data_hash field to track when meaningful analytics outputs change.
-- Phase 4 processors can compare hashes to skip reprocessing when upstream data
-- hasn't changed, reducing processing time by 20-40%.
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS data_hash STRING
OPTIONS(description='SHA256 hash (16 chars) of meaningful analytics output fields. Used for Smart Reprocessing Pattern #3.');
