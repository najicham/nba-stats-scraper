-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.bettingpros_player_points_props
--
-- Purpose: Add data_hash column to enable skip logic when prop lines unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - player_lookup
--   - game_date
--   - market_type
--   - bookmaker
--   - bet_side
--   - points_line
--   - is_best_line
--
-- Impact: Reduces cascade processing when props scraped multiple times daily
-- with no line changes (60-80% write reduction expected during stable periods)

ALTER TABLE `nba_raw.bettingpros_player_points_props`
ADD COLUMN IF NOT EXISTS data_hash STRING;
