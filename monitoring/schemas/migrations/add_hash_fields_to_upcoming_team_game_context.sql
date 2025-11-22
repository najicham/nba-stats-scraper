-- Migration: Add source hash fields for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency (Phase 3)
-- Table: nba_analytics.upcoming_team_game_context

-- Add hash field for each of the 3 Phase 2 dependencies
ALTER TABLE `nba_analytics.upcoming_team_game_context`
ADD COLUMN IF NOT EXISTS source_nbac_schedule_hash STRING,
ADD COLUMN IF NOT EXISTS source_odds_lines_hash STRING,
ADD COLUMN IF NOT EXISTS source_injury_report_hash STRING;
