-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.bdl_standings

ALTER TABLE `nba_raw.bdl_standings`
ADD COLUMN IF NOT EXISTS data_hash STRING;
