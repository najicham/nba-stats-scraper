-- Migration: Add source hash fields for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency (Phase 3)
-- Table: nba_analytics.player_game_summary

-- Add hash field for each of the 6 Phase 2 dependencies
ALTER TABLE `nba_analytics.player_game_summary`
ADD COLUMN IF NOT EXISTS source_nbac_hash STRING,
ADD COLUMN IF NOT EXISTS source_bdl_hash STRING,
ADD COLUMN IF NOT EXISTS source_bbd_hash STRING,
ADD COLUMN IF NOT EXISTS source_nbac_pbp_hash STRING,
ADD COLUMN IF NOT EXISTS source_odds_hash STRING,
ADD COLUMN IF NOT EXISTS source_bp_hash STRING;
