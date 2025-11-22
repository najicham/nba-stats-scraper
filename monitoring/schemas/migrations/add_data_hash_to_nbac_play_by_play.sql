-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.nbac_play_by_play
--
-- Purpose: Add data_hash column to enable skip logic when play-by-play events unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - game_id
--   - event_id
--   - period
--   - game_clock
--   - event_type
--   - event_description
--   - score_home
--   - score_away
--
-- Impact: Reduces cascade processing when play-by-play scraped multiple times post-game

ALTER TABLE `nba_raw.nbac_play_by_play`
ADD COLUMN IF NOT EXISTS data_hash STRING;
