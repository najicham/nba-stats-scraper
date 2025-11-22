-- Migration: Add source hash fields for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency (Phase 3)
-- Table: nba_analytics.team_offense_game_summary

-- Add hash field for each of the 2 Phase 2 dependencies
ALTER TABLE `nba_analytics.team_offense_game_summary`
ADD COLUMN IF NOT EXISTS source_nbac_boxscore_hash STRING,
ADD COLUMN IF NOT EXISTS source_play_by_play_hash STRING;
