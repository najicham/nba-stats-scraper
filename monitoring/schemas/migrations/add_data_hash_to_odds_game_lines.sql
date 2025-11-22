-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.odds_api_game_lines
--
-- Purpose: Add data_hash column to enable skip logic when game lines unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - game_id
--   - game_date
--   - bookmaker_key
--   - market_key
--   - outcome_name
--   - outcome_point
--   - snapshot_timestamp
--
-- Impact: Reduces cascade processing when game lines scraped hourly with no changes
-- (60-80% write reduction expected during stable periods)

ALTER TABLE `nba_raw.odds_api_game_lines`
ADD COLUMN IF NOT EXISTS data_hash STRING;
