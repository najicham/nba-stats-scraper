-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency
-- Table: nba_raw.nbac_injury_report
--
-- Purpose: Add data_hash column to enable skip logic when injury status unchanged
--
-- Hash Fields (defined in processor HASH_FIELDS):
--   - player_lookup
--   - team
--   - game_date
--   - game_id
--   - injury_status
--   - reason
--   - reason_category
--
-- Impact: Reduces cascade processing when injuries scraped multiple times per day
-- with no status changes (50-75% write reduction expected)

ALTER TABLE `nba_raw.nbac_injury_report`
ADD COLUMN IF NOT EXISTS data_hash STRING;

-- Add column comment for documentation
-- Note: BigQuery doesn't support COMMENT ON COLUMN for existing tables via ALTER
-- Documentation in CREATE TABLE SQL and this migration header
