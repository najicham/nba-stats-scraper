-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.nbac_scoreboard_v2

ALTER TABLE `nba_raw.nbac_scoreboard_v2`
ADD COLUMN IF NOT EXISTS data_hash STRING;
