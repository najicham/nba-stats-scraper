-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.espn_boxscores
--
-- Purpose: Add data_hash column to enable skip logic when player stats unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - game_id
--   - player_lookup
--   - points
--   - rebounds
--   - assists
--   - field_goals_made
--   - field_goals_attempted
--
-- Impact: Reduces cascade processing when ESPN boxscores scraped post-game

ALTER TABLE `nba_raw.espn_boxscores`
ADD COLUMN IF NOT EXISTS data_hash STRING;
