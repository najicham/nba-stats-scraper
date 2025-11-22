-- Migration: Add source hash fields for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency (Phase 3)
-- Table: nba_analytics.upcoming_player_game_context

-- Add hash field for each of the 4 Phase 2 dependencies
ALTER TABLE `nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS source_boxscore_hash STRING,
ADD COLUMN IF NOT EXISTS source_schedule_hash STRING,
ADD COLUMN IF NOT EXISTS source_props_hash STRING,
ADD COLUMN IF NOT EXISTS source_game_lines_hash STRING;
