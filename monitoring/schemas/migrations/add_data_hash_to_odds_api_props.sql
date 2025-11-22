-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.odds_api_player_points_props
--
-- Purpose: Add data_hash column to enable skip logic when prop lines unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - player_lookup
--   - game_date
--   - game_id
--   - bookmaker
--   - points_line
--   - snapshot_timestamp
--
-- Impact: Reduces cascade processing when props scraped hourly with no line changes
-- (60-80% write reduction expected during stable periods)

ALTER TABLE `nba_raw.odds_api_player_points_props`
ADD COLUMN IF NOT EXISTS data_hash STRING;
