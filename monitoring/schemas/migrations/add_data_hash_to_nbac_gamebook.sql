-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.nbac_gamebook_player_stats
--
-- Purpose: Add data_hash column to enable skip logic when gamebook stats unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - game_id
--   - player_lookup
--   - minutes
--   - field_goals_made
--   - field_goals_attempted
--   - points
--   - rebounds
--   - assists
--
-- Impact: Reduces cascade processing when gamebook scraped post-game

ALTER TABLE `nba_raw.nbac_gamebook_player_stats`
ADD COLUMN IF NOT EXISTS data_hash STRING;
