-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.bigdataball_play_by_play

ALTER TABLE `nba_raw.bigdataball_play_by_play`
ADD COLUMN IF NOT EXISTS data_hash STRING;
