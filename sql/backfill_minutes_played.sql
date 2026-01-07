--
-- Backfill minutes_played in player_game_summary
--
-- Problem: 99.5% of records have NULL minutes_played
-- Root Cause: Analytics table never backfilled from raw data
-- Solution: Update from nbac_gamebook (primary) and bdl (fallback)
--
-- Expected Impact: 0.5% → 99%+ coverage
-- Time Required: 5-10 minutes
--

-- ============================================================================
-- STEP 1: Update from nbac_gamebook (primary source, 100% coverage)
-- ============================================================================

-- This updates ~86,000 records from NBA.com gamebook data
-- Handles "MM:SS" format (e.g., "44:07" → 44)

UPDATE `nba-props-platform.nba_analytics.player_game_summary` AS pgs
SET minutes_played = SAFE_CAST(
    SPLIT(nbac.minutes, ':')[SAFE_OFFSET(0)] AS INT64
)
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` AS nbac
WHERE pgs.game_id = nbac.game_id
  AND pgs.player_lookup = nbac.player_lookup
  AND pgs.game_date = nbac.game_date
  AND nbac.minutes IS NOT NULL
  AND nbac.minutes != ''
  AND pgs.minutes_played IS NULL
  AND pgs.game_date >= '2021-10-19'
  AND pgs.game_date < '2024-05-01';

-- Expected: ~86,000 rows updated

-- ============================================================================
-- STEP 2: Fill remaining from BDL (fallback source)
-- ============================================================================

-- This fills games NOT in nbac_gamebook
-- BDL uses integer format (e.g., "44" → 44)

UPDATE `nba-props-platform.nba_analytics.player_game_summary` AS pgs
SET minutes_played = SAFE_CAST(bdl.minutes AS INT64)
FROM `nba-props-platform.nba_raw.bdl_player_boxscores` AS bdl
WHERE pgs.game_id = bdl.game_id
  AND pgs.player_lookup = bdl.player_lookup
  AND pgs.game_date = bdl.game_date
  AND bdl.minutes IS NOT NULL
  AND bdl.minutes != ''
  AND bdl.minutes != '0'
  AND pgs.minutes_played IS NULL
  AND pgs.game_date >= '2021-10-19'
  AND pgs.game_date < '2024-05-01';

-- Expected: ~30,000-40,000 additional rows updated

-- ============================================================================
-- STEP 3: Validation Queries
-- ============================================================================

-- Run these AFTER the updates to verify success

-- 3a. Check overall coverage
SELECT
  COUNT(*) as total_records,
  COUNTIF(minutes_played IS NOT NULL) as with_minutes,
  ROUND(COUNTIF(minutes_played IS NOT NULL) / COUNT(*) * 100, 1) as pct_coverage,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19' AND game_date < '2024-05-01';

-- Expected:
-- total_records: 83,534
-- with_minutes: 82,000-83,000 (99%+)
-- pct_coverage: 98-99%

-- 3b. Check distribution by minutes
SELECT
  CASE
    WHEN minutes_played IS NULL THEN 'NULL'
    WHEN minutes_played = 0 THEN '0 minutes'
    WHEN minutes_played < 10 THEN '1-9 minutes'
    WHEN minutes_played < 20 THEN '10-19 minutes'
    WHEN minutes_played < 30 THEN '20-29 minutes'
    WHEN minutes_played < 40 THEN '30-39 minutes'
    ELSE '40+ minutes'
  END as minutes_bucket,
  COUNT(*) as count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19' AND game_date < '2024-05-01'
GROUP BY minutes_bucket
ORDER BY
  CASE minutes_bucket
    WHEN 'NULL' THEN 0
    WHEN '0 minutes' THEN 1
    WHEN '1-9 minutes' THEN 2
    WHEN '10-19 minutes' THEN 3
    WHEN '20-29 minutes' THEN 4
    WHEN '30-39 minutes' THEN 5
    ELSE 6
  END;

-- Expected distribution (rough):
-- NULL: <1% (500-1000 records)
-- 0 minutes: 5-10% (DNPs)
-- 1-9 minutes: 5-10% (garbage time)
-- 10-19 minutes: 15-20% (bench players)
-- 20-29 minutes: 25-30% (rotation players)
-- 30-39 minutes: 30-35% (starters)
-- 40+ minutes: 5-10% (heavy minutes)

-- 3c. Spot check specific players (optional)
SELECT
  game_date,
  player_lookup,
  team_abbr,
  points,
  minutes_played,
  CASE
    WHEN minutes_played IS NULL THEN '❌ MISSING'
    WHEN minutes_played BETWEEN 25 AND 40 THEN '✅ NORMAL'
    WHEN minutes_played < 10 THEN '⚠️ LIMITED'
    WHEN minutes_played > 45 THEN '⚠️ HEAVY'
    ELSE '✅ OK'
  END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2024-04-14'
  AND points > 25
ORDER BY points DESC
LIMIT 20;

-- Should see mostly '✅ NORMAL' or '✅ OK'
-- Very few '❌ MISSING'

-- ============================================================================
-- Notes
-- ============================================================================

-- Why two separate UPDATE statements?
-- 1. Different data formats (MM:SS vs integer)
-- 2. Clear priority (nbac first, then BDL fallback)
-- 3. Easier to debug if one fails

-- Why SAFE_CAST?
-- - Handles edge cases gracefully (returns NULL instead of error)
-- - Empty strings → NULL
-- - Invalid formats → NULL
-- - Better than failing entire update

-- Why the filters?
-- - game_date range: Only backfill historical data we care about
-- - IS NULL check: Don't overwrite existing valid data
-- - Empty string checks: Skip placeholder values

-- Estimated run time:
-- - Step 1: 2-4 minutes (~86,000 rows)
-- - Step 2: 1-2 minutes (~35,000 rows)
-- - Total: 5-10 minutes

-- Cost:
-- - Minimal (UPDATE is cheap, no table scans)
-- - Estimated: $1-2 total

-- ============================================================================
-- Troubleshooting
-- ============================================================================

-- If updates fail with "partition" error:
-- - Add explicit partition filter to both statements
-- - Example: AND nbac.game_date BETWEEN '2021-10-19' AND '2024-04-30'

-- If coverage still low after updates:
-- - Check raw tables have data: SELECT COUNT(*) FROM nbac_gamebook...
-- - Check game_id matching: Ensure format consistent
-- - Check player_lookup matching: Ensure normalization consistent

-- If some records have wrong values:
-- - Spot check: Compare analytics vs raw for specific game
-- - Check parsing: SPLIT logic might need adjustment
-- - Run full processor backfill instead

-- ============================================================================
