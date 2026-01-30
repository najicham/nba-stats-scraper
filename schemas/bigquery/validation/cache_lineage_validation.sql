-- File: schemas/bigquery/validation/cache_lineage_validation.sql
-- Description: Validation queries for cache lineage - ensures cached rolling averages match source data
-- Dataset: validation
-- Created: 2026-01-29 (Session 26)
--
-- PURPOSE:
-- These queries validate that player_daily_cache rolling averages (L5, L10) are correctly
-- calculated from player_game_summary source data.
--
-- CRITICAL: Validation queries MUST exactly match processor logic in:
--   data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py
--
-- The processor uses these filters:
--   - game_date < cache_date  (strictly BEFORE, not <=)
--   - season_year = current_season
--   - is_active = TRUE
--   - minutes_played > 0 OR points > 0  (excludes DNPs)
--
-- Common Validation Mistakes (DO NOT MAKE):
--   - Using game_date <= cache_date (includes game that hasn't happened yet)
--   - Forgetting season_year filter (includes prior season games)
--   - Forgetting is_active filter
--   - Forgetting DNP filter

-- ============================================================================
-- Query 1: L5 Points Average Validation
-- Usage: Validate points_avg_last_5 for a specific cache_date
-- ============================================================================

-- Replace @cache_date and @season_year with actual values
-- Example: @cache_date = '2025-01-15', @season_year = 2024

/*
DECLARE cache_date DATE DEFAULT '2025-01-15';
DECLARE season_year INT64 DEFAULT 2024;

WITH sample_cache AS (
  SELECT player_lookup, cache_date, points_avg_last_5 as cached_l5
  FROM `nba_precompute.player_daily_cache`
  WHERE cache_date = cache_date
    AND points_avg_last_5 IS NOT NULL
  LIMIT 50
),
games_ranked AS (
  SELECT
    g.player_lookup,
    s.cache_date,
    g.points,
    ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as rn
  FROM sample_cache s
  JOIN `nba_analytics.player_game_summary` g
    ON g.player_lookup = s.player_lookup
    AND g.game_date < s.cache_date  -- CRITICAL: strictly BEFORE
    AND g.season_year = season_year
    AND g.is_active = TRUE
    AND (g.minutes_played > 0 OR g.points > 0)
),
recalc AS (
  SELECT player_lookup, ROUND(AVG(points), 4) as calc_l5
  FROM games_ranked WHERE rn <= 5
  GROUP BY player_lookup
)
SELECT
  s.player_lookup,
  s.cached_l5,
  r.calc_l5,
  ABS(s.cached_l5 - r.calc_l5) as diff,
  CASE WHEN ABS(s.cached_l5 - r.calc_l5) < 0.01 THEN 'MATCH' ELSE 'DIFF' END as status
FROM sample_cache s
JOIN recalc r ON s.player_lookup = r.player_lookup
ORDER BY diff DESC;
*/

-- ============================================================================
-- Query 2: Batch Validation Summary
-- Usage: Validate a random sample and return pass/fail counts
-- ============================================================================

/*
DECLARE cache_date DATE DEFAULT '2025-01-15';
DECLARE season_year INT64 DEFAULT 2024;

WITH sample_cache AS (
  SELECT player_lookup, cache_date, points_avg_last_5 as cached_l5, points_avg_last_10 as cached_l10
  FROM `nba_precompute.player_daily_cache`
  WHERE cache_date = cache_date
    AND points_avg_last_5 IS NOT NULL
  ORDER BY RAND()
  LIMIT 100
),
games_ranked AS (
  SELECT
    g.player_lookup,
    s.cache_date,
    g.points,
    ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as rn
  FROM sample_cache s
  JOIN `nba_analytics.player_game_summary` g
    ON g.player_lookup = s.player_lookup
    AND g.game_date < s.cache_date
    AND g.season_year = season_year
    AND g.is_active = TRUE
    AND (g.minutes_played > 0 OR g.points > 0)
),
recalc AS (
  SELECT
    player_lookup,
    ROUND(AVG(CASE WHEN rn <= 5 THEN points END), 4) as calc_l5,
    ROUND(AVG(CASE WHEN rn <= 10 THEN points END), 4) as calc_l10
  FROM games_ranked
  GROUP BY player_lookup
),
comparison AS (
  SELECT
    s.player_lookup,
    s.cached_l5, r.calc_l5,
    s.cached_l10, r.calc_l10
  FROM sample_cache s
  JOIN recalc r ON s.player_lookup = r.player_lookup
)
SELECT
  'L5 Accuracy' as metric,
  COUNT(*) as total,
  COUNTIF(ABS(cached_l5 - calc_l5) < 0.01) as exact_match,
  COUNTIF(ABS(cached_l5 - calc_l5) >= 0.01) as mismatch,
  ROUND(100.0 * COUNTIF(ABS(cached_l5 - calc_l5) < 0.01) / COUNT(*), 1) as match_pct
FROM comparison
UNION ALL
SELECT
  'L10 Accuracy' as metric,
  COUNT(*) as total,
  COUNTIF(ABS(cached_l10 - calc_l10) < 0.01) as exact_match,
  COUNTIF(ABS(cached_l10 - calc_l10) >= 0.01) as mismatch,
  ROUND(100.0 * COUNTIF(ABS(cached_l10 - calc_l10) < 0.01) / COUNT(*), 1) as match_pct
FROM comparison
WHERE cached_l10 IS NOT NULL AND calc_l10 IS NOT NULL;
*/

-- ============================================================================
-- Query 3: Debug a Specific Discrepancy
-- Usage: When a DIFF is found, see which games are included in each calculation
-- ============================================================================

/*
DECLARE cache_date DATE DEFAULT '2025-01-12';
DECLARE player STRING DEFAULT 'markwilliams';
DECLARE season_year INT64 DEFAULT 2024;

-- Show what games the processor would include
SELECT
  'Processor Logic (< cache_date)' as logic,
  game_date,
  points,
  minutes_played,
  is_active,
  season_year,
  ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_rank
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = player
  AND game_date < cache_date  -- Processor uses strict <
  AND season_year = season_year
  AND is_active = TRUE
  AND (minutes_played > 0 OR points > 0)
ORDER BY game_date DESC
LIMIT 10;

-- Compare with what a flawed query would include
SELECT
  'Flawed Query (<= cache_date)' as logic,
  game_date,
  points,
  minutes_played,
  is_active,
  season_year
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = player
  AND game_date <= cache_date  -- WRONG: includes game on cache_date
  AND season_year = season_year
ORDER BY game_date DESC
LIMIT 10;
*/

-- ============================================================================
-- Query 4: Cross-Date Validation
-- Usage: Validate multiple cache dates at once
-- ============================================================================

/*
DECLARE season_year INT64 DEFAULT 2024;

WITH cache_dates AS (
  SELECT cache_date
  FROM UNNEST(GENERATE_DATE_ARRAY('2024-12-01', '2025-02-01', INTERVAL 7 DAY)) as cache_date
),
sample_per_date AS (
  SELECT c.player_lookup, c.cache_date, c.points_avg_last_5 as cached_l5
  FROM `nba_precompute.player_daily_cache` c
  WHERE c.cache_date IN (SELECT cache_date FROM cache_dates)
    AND c.points_avg_last_5 IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY c.cache_date ORDER BY RAND()) <= 20
),
games_ranked AS (
  SELECT
    g.player_lookup,
    s.cache_date,
    g.points,
    ROW_NUMBER() OVER (PARTITION BY g.player_lookup, s.cache_date ORDER BY g.game_date DESC) as rn
  FROM sample_per_date s
  JOIN `nba_analytics.player_game_summary` g
    ON g.player_lookup = s.player_lookup
    AND g.game_date < s.cache_date
    AND g.season_year = season_year
    AND g.is_active = TRUE
    AND (g.minutes_played > 0 OR g.points > 0)
),
recalc AS (
  SELECT player_lookup, cache_date, ROUND(AVG(points), 4) as calc_l5
  FROM games_ranked WHERE rn <= 5
  GROUP BY player_lookup, cache_date
)
SELECT
  s.cache_date,
  COUNT(*) as samples,
  COUNTIF(ABS(s.cached_l5 - r.calc_l5) < 0.01) as matches,
  ROUND(100.0 * COUNTIF(ABS(s.cached_l5 - r.calc_l5) < 0.01) / COUNT(*), 1) as match_pct
FROM sample_per_date s
JOIN recalc r ON s.player_lookup = r.player_lookup AND s.cache_date = r.cache_date
GROUP BY s.cache_date
ORDER BY s.cache_date;
*/

-- ============================================================================
-- Expected Results
-- ============================================================================
--
-- When queries are correct (matching processor logic):
--   - L5 match rate: 100% (within 0.01 tolerance for rounding)
--   - L10 match rate: 100% (within 0.01 tolerance for rounding)
--
-- If you see mismatches:
--   1. Check your query uses < not <= for date comparison
--   2. Check season_year filter is present
--   3. Check is_active filter is present
--   4. Check DNP filter is present
--   5. Use Query 3 to debug specific cases
