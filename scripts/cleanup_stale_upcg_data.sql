-- ============================================================================
-- One-Time Cleanup: Stale upcoming_player_game_context Records
-- ============================================================================
--
-- Purpose: Remove historical records from "upcoming" tables that should only
--          contain future game data. This prevents partial/stale data from
--          blocking fallback logic during backfills.
--
-- Incident: Jan 6, 2026 - Partial UPCG data (1/187 players) blocked fallback
--           causing incomplete backfill that went undetected for 6 days.
--
-- Safety: Creates backup before deletion
-- Author: Claude (Session 30)
-- Date: 2026-01-13
-- ============================================================================

-- Step 1: Create backup table
-- Note: Replace YYYYMMDD with today's date (e.g., 20260113)
CREATE TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113` AS
SELECT *
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;

-- Verify backup was created
SELECT
  'Backup created' as status,
  COUNT(*) as total_records,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113`;

-- ============================================================================

-- Step 2: Identify stale records (for review before deletion)
-- "Stale" = game_date is more than 7 days in the past
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as player_count,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 100;

-- ============================================================================

-- Step 3: DELETE stale records
-- WARNING: This is destructive! Ensure backup was created first.
DELETE FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY;

-- ============================================================================

-- Step 4: Verify deletion
SELECT
  'After Cleanup' as period,
  COUNT(*) as total_records,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date,
  COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;

-- Compare with backup
SELECT
  'Backup (Before)' as period,
  COUNT(*) as total_records,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date,
  COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113`;

-- ============================================================================

-- Step 5: Verify no upcoming games were deleted
-- This should return 0 records (all remaining dates should be >= today - 7 days)
SELECT
  game_date,
  COUNT(*) as records
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY
GROUP BY game_date;

-- ============================================================================

-- Step 6: Calculate impact
SELECT
  COUNT(*) as records_deleted,
  ROUND(COUNT(*) * 100.0 / (
    SELECT COUNT(*)
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113`
  ), 2) as pct_deleted
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY;

-- ============================================================================
-- ROLLBACK (if needed)
-- ============================================================================
-- If something went wrong, restore from backup:
--
-- DELETE FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;
--
-- INSERT INTO `nba-props-platform.nba_analytics.upcoming_player_game_context`
-- SELECT * FROM `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113`;
-- ============================================================================

-- ============================================================================
-- CLEANUP BACKUP (after verifying success)
-- ============================================================================
-- After confirming cleanup worked correctly, you can drop the backup:
-- (Keep it for at least 30 days)
--
-- DROP TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260113`;
-- ============================================================================
