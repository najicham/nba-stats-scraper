-- ============================================================================
-- File: validation/queries/raw/bdl_injuries/weekly_check_last_7_days.sql
-- Purpose: Weekly trend monitoring for BDL injury data
-- Usage: Run weekly or when investigating data quality issues
-- ============================================================================
-- Expected Results (During Season):
--   - Each day should have 20-60 injuries
--   - Consistent team coverage (15-25 teams)
--   - Stable confidence scores (1.0)
--   - Flags for any anomalies or missing days
-- ============================================================================

WITH
daily_summary AS (
  SELECT
    scrape_date,
    COUNT(*) as injury_count,
    COUNT(DISTINCT bdl_player_id) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams,
    AVG(parsing_confidence) as avg_confidence,
    MIN(parsing_confidence) as min_confidence,
    COUNT(CASE WHEN return_date_parsed = TRUE THEN 1 END) as return_dates_parsed,
    COUNT(CASE WHEN return_date_parsed = FALSE THEN 1 END) as return_dates_unparsed,
    COUNT(CASE WHEN injury_status_normalized = 'out' THEN 1 END) as status_out,
    COUNT(CASE WHEN injury_status_normalized = 'questionable' THEN 1 END) as status_questionable,
    COUNT(CASE WHEN injury_status_normalized = 'doubtful' THEN 1 END) as status_doubtful,
    COUNT(CASE WHEN data_quality_flags IS NOT NULL AND data_quality_flags != '' THEN 1 END) as records_with_flags
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY scrape_date
),

-- Generate all dates in last 7 days
date_range AS (
  SELECT date_value as check_date
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY),
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  )) as date_value
),

-- Combine to find missing dates
complete_week AS (
  SELECT
    d.check_date as scrape_date,
    COALESCE(s.injury_count, 0) as injury_count,
    COALESCE(s.unique_players, 0) as unique_players,
    COALESCE(s.unique_teams, 0) as unique_teams,
    s.avg_confidence,
    s.min_confidence,
    COALESCE(s.return_dates_parsed, 0) as return_dates_parsed,
    COALESCE(s.return_dates_unparsed, 0) as return_dates_unparsed,
    COALESCE(s.status_out, 0) as status_out,
    COALESCE(s.status_questionable, 0) as status_questionable,
    COALESCE(s.status_doubtful, 0) as status_doubtful,
    COALESCE(s.records_with_flags, 0) as records_with_flags,
    -- Season context
    CASE 
      WHEN EXTRACT(MONTH FROM d.check_date) IN (7, 8, 9) THEN FALSE
      ELSE TRUE
    END as is_season_active
  FROM date_range d
  LEFT JOIN daily_summary s ON d.check_date = s.scrape_date
)

SELECT
  scrape_date,
  FORMAT_DATE('%A', scrape_date) as day_of_week,
  is_season_active,
  injury_count,
  unique_players,
  unique_teams,
  ROUND(avg_confidence, 3) as avg_confidence,
  ROUND(min_confidence, 3) as min_confidence,
  return_dates_parsed,
  return_dates_unparsed,
  CONCAT(status_out, '/', status_questionable, '/', status_doubtful) as out_q_d,
  records_with_flags,
  CASE
    -- Off-season
    WHEN NOT is_season_active AND injury_count = 0 THEN '⚪ Off-season'
    
    -- Season active - issues
    WHEN is_season_active AND injury_count = 0 THEN '🔴 CRITICAL: No data'
    WHEN is_season_active AND injury_count < 10 THEN '🔴 CRITICAL: Very low'
    WHEN is_season_active AND unique_teams < 10 THEN '⚠️  WARNING: Low teams'
    WHEN is_season_active AND avg_confidence < 0.9 THEN '⚠️  WARNING: Low confidence'
    
    -- Season active - success
    WHEN is_season_active AND injury_count >= 10 THEN '✅ Complete'
    
    ELSE '📊 Review'
  END as status
FROM complete_week
ORDER BY scrape_date DESC;
