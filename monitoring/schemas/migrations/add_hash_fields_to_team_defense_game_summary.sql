-- Migration: Add source hash fields for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency (Phase 3)
-- Table: nba_analytics.team_defense_game_summary

-- Add hash field for each of the 3 Phase 2 dependencies
ALTER TABLE `nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS source_team_boxscore_hash STRING,
ADD COLUMN IF NOT EXISTS source_gamebook_players_hash STRING,
ADD COLUMN IF NOT EXISTS source_bdl_players_hash STRING;
