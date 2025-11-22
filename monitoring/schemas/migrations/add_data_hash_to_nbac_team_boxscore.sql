-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.nbac_team_boxscore
--
-- Purpose: Add data_hash column to enable skip logic when team stats unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - game_id
--   - team_abbr
--   - field_goals_made
--   - field_goals_attempted
--   - points
--   - rebounds
--   - assists
--
-- Impact: Reduces cascade processing when team boxscores scraped post-game

ALTER TABLE `nba_raw.nbac_team_boxscore`
ADD COLUMN IF NOT EXISTS data_hash STRING;
