-- ============================================================================
-- File: validation/queries/raw/odds_api_props/verify_may_2023_coverage.sql
-- Purpose: Verify coverage from May 2023 (data collection start date)
-- Shows: 1) Date range summary, 2) Monthly coverage, 3) Specific gap dates
-- ============================================================================
-- FIXED: Corrected aggregation in gap_dates CTE
-- FIXED: Moved ORDER BY and LIMIT to end (after UNION ALL)
-- ============================================================================

WITH monthly_data AS (
  SELECT
    FORMAT_DATE('%Y-%m', month_date) as month,
    scheduled,
    with_props,
    missing,
    coverage_pct
  FROM (
    SELECT
      DATE_TRUNC(s.game_date, MONTH) as month_date,
      COUNT(DISTINCT s.game_id) as scheduled,
      COUNT(DISTINCT p.game_id) as with_props,
      COUNT(DISTINCT s.game_id) - COUNT(DISTINCT p.game_id) as missing,
      ROUND(COUNT(DISTINCT p.game_id) * 100.0 / NULLIF(COUNT(DISTINCT s.game_id), 0), 1) as coverage_pct
    FROM `nba-props-platform.nba_raw.nbac_schedule` s
    LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
      ON s.game_date = p.game_date
      AND s.home_team_tricode = p.home_team_abbr
      AND s.away_team_tricode = p.away_team_abbr
    WHERE s.game_date >= '2023-05-01'
      AND s.game_date <= CURRENT_DATE()
    GROUP BY DATE_TRUNC(s.game_date, MONTH)
  )
),

gap_dates AS (
  SELECT
    game_date,
    scheduled_games,
    scheduled_games - games_with_props as missing_games
  FROM (
    SELECT
      s.game_date,
      COUNT(DISTINCT s.game_id) as scheduled_games,
      COUNT(DISTINCT p.game_id) as games_with_props
    FROM `nba-props-platform.nba_raw.nbac_schedule` s
    LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
      ON s.game_date = p.game_date
      AND s.home_team_tricode = p.home_team_abbr
      AND s.away_team_tricode = p.away_team_abbr
    WHERE s.game_date >= '2023-05-01'
      AND s.game_date <= CURRENT_DATE()
    GROUP BY s.game_date
  )
  WHERE scheduled_games > games_with_props
)

-- Output with proper column names
SELECT 
  '1_SUMMARY' as section,
  CAST(MIN(game_date) AS STRING) as col1,
  CAST(MAX(game_date) AS STRING) as col2,
  CAST(COUNT(DISTINCT game_date) AS STRING) as col3,
  CAST(COUNT(DISTINCT game_id) AS STRING) as col4,
  CAST(COUNT(DISTINCT player_lookup) AS STRING) as col5
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2023-05-01'

UNION ALL

SELECT
  '2_MONTHLY' as section,
  month as col1,
  CAST(scheduled AS STRING) as col2,
  CAST(with_props AS STRING) as col3,
  CAST(missing AS STRING) as col4,
  CONCAT(CAST(coverage_pct AS STRING), '% ',
    CASE 
      WHEN coverage_pct >= 100 THEN '✅'
      WHEN coverage_pct >= 90 THEN '🟢'
      WHEN coverage_pct >= 70 THEN '🟡'
      WHEN coverage_pct >= 50 THEN '🟠'
      WHEN coverage_pct > 0 THEN '🔴'
      ELSE '❌'
    END
  ) as col5
FROM monthly_data

UNION ALL

SELECT
  '3_GAPS' as section,
  CAST(game_date AS STRING) as col1,
  CAST(scheduled_games AS STRING) as col2,
  CAST(missing_games AS STRING) as col3,
  CASE 
    WHEN LAG(game_date) OVER (ORDER BY game_date) IS NULL THEN 'First'
    WHEN DATE_DIFF(game_date, LAG(game_date) OVER (ORDER BY game_date), DAY) = 1 THEN 'Consecutive'
    ELSE CONCAT(CAST(DATE_DIFF(game_date, LAG(game_date) OVER (ORDER BY game_date), DAY) AS STRING), ' day gap')
  END as col4,
  '' as col5
FROM gap_dates

-- ORDER BY and LIMIT must come AFTER all UNION ALL statements
ORDER BY section, col1
LIMIT 50;