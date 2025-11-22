-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.espn_scoreboard
--
-- Purpose: Add data_hash column to enable skip logic when scoreboard data unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - game_id
--   - game_status
--   - home_score
--   - away_score
--   - home_team_abbr
--   - away_team_abbr
--
-- Impact: Reduces cascade processing when scoreboard scraped throughout game day

ALTER TABLE `nba_raw.espn_scoreboard`
ADD COLUMN IF NOT EXISTS data_hash STRING;
