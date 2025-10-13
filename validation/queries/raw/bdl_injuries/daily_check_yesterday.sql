-- ============================================================================
-- File: validation/queries/raw/bdl_injuries/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's BDL injury scrape
-- Usage: Run every morning at ~9 AM (after scraper completes)
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM during NBA season
--   2. Set up alerts for status != "✅ Complete" or "⚪ Off-season"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results (During Season):
--   - status = "✅ Complete" with 20-60 injuries
--   - 15-25 teams represented
--   - 1.0 confidence score
--   - status = "🔴 CRITICAL" requires immediate investigation
-- ============================================================================

WITH
-- Check yesterday's injury data
yesterday_injuries AS (
  SELECT
    COUNT(*) as injury_count,
    COUNT(DISTINCT bdl_player_id) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams,
    AVG(parsing_confidence) as avg_confidence,
    MIN(parsing_confidence) as min_confidence,
    COUNT(CASE WHEN return_date_parsed = TRUE THEN 1 END) as return_dates_parsed,
    COUNT(CASE WHEN return_date_parsed = FALSE THEN 1 END) as return_dates_unparsed,
    COUNT(CASE WHEN data_quality_flags IS NOT NULL AND data_quality_flags != '' THEN 1 END) as records_with_flags,
    STRING_AGG(DISTINCT injury_status_normalized ORDER BY injury_status_normalized) as statuses_present
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Check if NBA season is active (Oct-Jun)
season_context AS (
  SELECT
    EXTRACT(MONTH FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as check_month,
    CASE 
      WHEN EXTRACT(MONTH FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) IN (7, 8, 9) THEN FALSE
      ELSE TRUE
    END as is_season_active
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  FORMAT_DATE('%A', DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as day_of_week,
  s.is_season_active,
  COALESCE(i.injury_count, 0) as injury_count,
  COALESCE(i.unique_players, 0) as unique_players,
  COALESCE(i.unique_teams, 0) as unique_teams,
  ROUND(i.avg_confidence, 3) as avg_confidence,
  ROUND(i.min_confidence, 3) as min_confidence,
  COALESCE(i.return_dates_parsed, 0) as return_dates_parsed,
  COALESCE(i.return_dates_unparsed, 0) as return_dates_unparsed,
  COALESCE(i.records_with_flags, 0) as records_with_flags,
  i.statuses_present,
  CASE
    -- Off-season scenarios (July-September)
    WHEN NOT s.is_season_active AND COALESCE(i.injury_count, 0) = 0
      THEN '⚪ Expected: Off-season - no scraper run'
    WHEN NOT s.is_season_active AND i.injury_count > 0
      THEN '✅ Complete: Off-season with data'

    -- Active season scenarios - CRITICAL issues
    WHEN s.is_season_active AND COALESCE(i.injury_count, 0) = 0
      THEN '🔴 CRITICAL: Season active - NO injury data'
    WHEN s.is_season_active AND i.injury_count < 10
      THEN '🔴 CRITICAL: Season active - very low count'

    -- Active season scenarios - WARNING issues
    WHEN s.is_season_active AND i.unique_teams < 10
      THEN '⚠️  WARNING: Low team coverage (< 10 teams)'
    WHEN s.is_season_active AND i.avg_confidence < 0.9
      THEN '⚠️  WARNING: Low confidence score'
    WHEN s.is_season_active AND i.return_dates_unparsed > i.return_dates_parsed
      THEN '⚠️  WARNING: Most return dates unparsed'

    -- Active season scenarios - SUCCESS
    WHEN s.is_season_active AND i.injury_count >= 10
      THEN '✅ Complete: Good coverage'

    ELSE '📊 Review: Unusual pattern'
  END as status
FROM season_context s
CROSS JOIN yesterday_injuries i;
