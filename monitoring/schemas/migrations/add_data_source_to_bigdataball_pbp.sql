-- Migration: Add data_source column for fallback tracking
-- Date: 2026-01-28
-- Description: Tracks whether PBP data came from BigDataBall (primary) or NBA.com (fallback)
-- Table: nba_raw.bigdataball_play_by_play

ALTER TABLE `nba_raw.bigdataball_play_by_play`
ADD COLUMN IF NOT EXISTS data_source STRING;

-- Add comment describing the column values
-- data_source values:
--   'bigdataball' - Primary source with full lineup data
--   'nbacom_fallback' - Fallback source when BDB unavailable (no lineup data)
--   NULL - Legacy data before this migration

-- Optional: Backfill existing rows as 'bigdataball' since they all came from BDB
-- UPDATE `nba_raw.bigdataball_play_by_play`
-- SET data_source = 'bigdataball'
-- WHERE data_source IS NULL;
