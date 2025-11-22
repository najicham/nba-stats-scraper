-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.bdl_injuries
--
-- Purpose: Add data_hash column to enable skip logic when injury status unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - player_lookup
--   - team_abbr
--   - injury_status_normalized
--   - return_date
--   - reason_category
--
-- Impact: Reduces cascade processing when injuries scraped multiple times per day
-- with no status changes (50-75% write reduction expected)

ALTER TABLE `nba_raw.bdl_injuries`
ADD COLUMN IF NOT EXISTS data_hash STRING;
