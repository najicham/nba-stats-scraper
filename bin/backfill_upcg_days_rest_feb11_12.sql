-- Backfill days_rest for Feb 11-12 UPCG records
-- Session 236: Fix for UPCG days_rest calculation broken by commit 922b8c16
--
-- ROOT CAUSE: UPCG processor stopped calculating days_rest after BDL→nbac migration
-- TEMPORARY FIX: Manually calculate and UPDATE days_rest from player_game_summary
-- PERMANENT FIX: Fix UPCG processor to properly extract historical_boxscores
--
-- Usage: bq query --nouse_legacy_sql < bin/backfill_upcg_days_rest_feb11_12.sql

-- Create temp table with calculated days_rest
CREATE TEMP TABLE days_rest_calc AS
WITH historical_games AS (
  SELECT
    player_lookup,
    game_date,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date < '2026-02-13'  -- Before target dates
    AND game_date >= '2026-01-12'  -- 30+ days lookback
),
most_recent AS (
  SELECT
    player_lookup,
    game_date as last_game_date
  FROM historical_games
  WHERE rn = 1
),
upcg_target AS (
  SELECT
    player_lookup,
    game_date,
    game_id
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date IN ('2026-02-11', '2026-02-12')
)
SELECT
  upcg.player_lookup,
  upcg.game_date,
  upcg.game_id,
  COALESCE(DATE_DIFF(upcg.game_date, mr.last_game_date, DAY), NULL) as calculated_days_rest
FROM upcg_target upcg
LEFT JOIN most_recent mr ON upcg.player_lookup = mr.player_lookup;

-- Show summary before update
SELECT
  'BEFORE UPDATE' as status,
  game_date,
  COUNT(*) as total_players,
  COUNTIF(days_rest IS NOT NULL) as has_days_rest_before,
  COUNTIF(days_rest IS NULL) as null_days_rest_before
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date IN ('2026-02-11', '2026-02-12')
GROUP BY game_date
ORDER BY game_date;

-- Update days_rest values
UPDATE `nba-props-platform.nba_analytics.upcoming_player_game_context` upcg
SET days_rest = calc.calculated_days_rest
FROM days_rest_calc calc
WHERE upcg.player_lookup = calc.player_lookup
  AND upcg.game_date = calc.game_date
  AND upcg.game_id = calc.game_id;

-- Show summary after update
SELECT
  'AFTER UPDATE' as status,
  game_date,
  COUNT(*) as total_players,
  COUNTIF(days_rest IS NOT NULL) as has_days_rest_after,
  COUNTIF(days_rest IS NULL) as null_days_rest_after,
  ROUND(100.0 * COUNTIF(days_rest IS NOT NULL) / COUNT(*), 1) as pct_coverage
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date IN ('2026-02-11', '2026-02-12')
GROUP BY game_date
ORDER BY game_date;
