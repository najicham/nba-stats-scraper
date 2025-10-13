-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/discovery/discovery_query_4_date_gaps.sql
-- ============================================================================
-- BigDataBall Play-by-Play Discovery Query 4: Date Continuity Gaps
-- Purpose: Find large gaps in date coverage
-- ============================================================================
-- Normal gaps:
--   - All-Star Weekend (Feb): 6-7 days
--   - Off-season (Jun-Oct): 120-130 days
-- Abnormal gaps:
--   - >7 days during season = Data quality issue
-- ============================================================================

WITH date_series AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date >= '2021-10-01'  -- UPDATE based on Discovery Q1
  ORDER BY game_date
),
with_next_date AS (
  SELECT 
    game_date,
    LEAD(game_date) OVER (ORDER BY game_date) as next_date,
    DATE_DIFF(LEAD(game_date) OVER (ORDER BY game_date), game_date, DAY) as days_gap
  FROM date_series
)
SELECT 
  game_date,
  next_date,
  days_gap,
  CASE
    WHEN days_gap > 90 THEN '🔴 OFF-SEASON GAP (normal)'
    WHEN days_gap > 7 THEN '⚠️ LARGE GAP (investigate)'
    WHEN days_gap > 3 THEN '⚪ MEDIUM GAP (likely All-Star or off day)'
    ELSE '✅ Normal'
  END as status
FROM with_next_date
WHERE days_gap > 1
ORDER BY game_date;

-- Interpretation:
-- 🔴 90+ day gaps: Off-season (June-October) = NORMAL
-- ⚠️ 8-30 day gaps during season: Data quality issue
-- ⚪ 4-7 day gaps: All-Star break or extended off days = EXPECTED
