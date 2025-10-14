-- ============================================================================
-- File: validation/queries/raw/bdl_standings/find_missing_dates.sql
-- ============================================================================
-- BDL Standings Find Missing Dates
-- Purpose: Identify specific dates without standings during NBA season
-- Expected: Daily snapshots October-June, sparse July-September
-- Run: When gaps detected, for creating backfill lists
-- ============================================================================
--
-- INSTRUCTIONS:
-- 1. Update date range below for season being checked (lines 23-24)
-- 2. Run query to identify missing dates
-- 3. Export results to create scraper backfill list
--
-- ============================================================================

WITH date_range AS (
  -- Generate all dates in the season
  -- UPDATE THESE DATES FOR THE SEASON YOU'RE VALIDATING
  SELECT date_val as expected_date
  FROM UNNEST(GENERATE_DATE_ARRAY(
    '2024-10-22',  -- Season start (update for target season)
    '2025-06-20'   -- Season end (update for target season)
  )) as date_val
),

season_context AS (
  SELECT
    expected_date,
    FORMAT_DATE('%A', expected_date) as day_of_week,
    EXTRACT(MONTH FROM expected_date) as month,
    CASE
      WHEN EXTRACT(MONTH FROM expected_date) BETWEEN 10 AND 12 THEN 'Regular Season'
      WHEN EXTRACT(MONTH FROM expected_date) BETWEEN 1 AND 3 THEN 'Regular Season'
      WHEN EXTRACT(MONTH FROM expected_date) = 4 AND EXTRACT(DAY FROM expected_date) < 19 THEN 'Regular Season'
      WHEN EXTRACT(MONTH FROM expected_date) = 4 AND EXTRACT(DAY FROM expected_date) >= 19 THEN 'Playoffs'
      WHEN EXTRACT(MONTH FROM expected_date) IN (5, 6) THEN 'Playoffs'
      ELSE 'Offseason'
    END as season_phase,
    CASE
      WHEN EXTRACT(MONTH FROM expected_date) BETWEEN 10 AND 12 THEN TRUE
      WHEN EXTRACT(MONTH FROM expected_date) BETWEEN 1 AND 6 THEN TRUE
      ELSE FALSE
    END as is_nba_season
  FROM date_range
),

actual_dates AS (
  SELECT DISTINCT 
    date_recorded,
    COUNT(*) as team_count
  FROM `nba-props-platform.nba_raw.bdl_standings`
  WHERE date_recorded BETWEEN '2024-10-22' AND '2025-06-20'  -- Match date_range above
  GROUP BY date_recorded
),

missing_dates_list AS (
  SELECT
    s.expected_date as missing_date,
    s.day_of_week,
    s.season_phase,
    FORMAT_DATE('%Y-%m', s.expected_date) as year_month,
    CASE
      WHEN s.season_phase = 'Regular Season' THEN '🔴 CRITICAL: Missing regular season standings'
      WHEN s.season_phase = 'Playoffs' THEN '🔴 CRITICAL: Missing playoff standings'
      WHEN s.season_phase = 'Offseason' THEN '⚪ Normal: Offseason gap'
      ELSE '⚠️ Review needed'
    END as status,
    CASE
      WHEN s.is_nba_season THEN 'ACTION: Run scraper for this date'
      ELSE 'No action needed - offseason'
    END as recommendation
  FROM season_context s
  LEFT JOIN actual_dates a ON s.expected_date = a.date_recorded
  WHERE a.date_recorded IS NULL
),

monthly_summary AS (
  SELECT
    FORMAT_DATE('%Y-%m', s.expected_date) as year_month,
    FORMAT_DATE('%B %Y', s.expected_date) as month_name,
    s.season_phase,
    COUNT(*) as missing_dates,
    MIN(s.expected_date) as first_missing,
    MAX(s.expected_date) as last_missing,
    CASE
      WHEN s.season_phase IN ('Regular Season', 'Playoffs') AND COUNT(*) > 5
        THEN '🔴 CRITICAL: Many missing dates'
      WHEN s.season_phase IN ('Regular Season', 'Playoffs') AND COUNT(*) > 0
        THEN '⚠️ WARNING: Some missing dates'
      WHEN s.season_phase = 'Offseason'
        THEN '⚪ Offseason gaps (normal)'
      ELSE '✅ No missing dates'
    END as status
  FROM season_context s
  LEFT JOIN actual_dates a ON s.expected_date = a.date_recorded
  WHERE a.date_recorded IS NULL
  GROUP BY year_month, month_name, s.season_phase
),

coverage_stats AS (
  SELECT
    COUNT(DISTINCT dr.expected_date) as total_days_in_range,
    COUNT(DISTINCT a.date_recorded) as days_with_data,
    COUNT(DISTINCT dr.expected_date) - COUNT(DISTINCT a.date_recorded) as missing_days,
    ROUND(COUNT(DISTINCT a.date_recorded) / COUNT(DISTINCT dr.expected_date) * 100, 1) as coverage_pct,
    MIN(a.date_recorded) as first_data_date,
    MAX(a.date_recorded) as last_data_date
  FROM date_range dr
  LEFT JOIN actual_dates a ON dr.expected_date = a.date_recorded
),

consecutive_gaps AS (
  SELECT
    s.expected_date,
    ROW_NUMBER() OVER (ORDER BY s.expected_date) as rn,
    DATE_SUB(s.expected_date, INTERVAL ROW_NUMBER() OVER (ORDER BY s.expected_date) DAY) as gap_group
  FROM season_context s
  LEFT JOIN actual_dates a ON s.expected_date = a.date_recorded
  WHERE a.date_recorded IS NULL
    AND s.is_nba_season = TRUE
),

gap_ranges AS (
  SELECT
    MIN(expected_date) as gap_start,
    MAX(expected_date) as gap_end,
    COUNT(*) as consecutive_days_missing,
    CASE
      WHEN COUNT(*) = 1 THEN '⚠️ Single day'
      WHEN COUNT(*) BETWEEN 2 AND 3 THEN '⚠️ Short gap'
      WHEN COUNT(*) BETWEEN 4 AND 7 THEN '🔴 Week-long gap'
      ELSE '🔴 CRITICAL: Extended gap'
    END as severity
  FROM consecutive_gaps
  GROUP BY gap_group
)

-- Combine all results
(
SELECT
  'MISSING DATES' as section,
  CAST(missing_date AS STRING) as detail1,
  day_of_week as detail2,
  season_phase as detail3,
  year_month as detail4,
  status as detail5,
  recommendation as detail6,
  NULL as detail7,
  NULL as detail8
FROM missing_dates_list

UNION ALL

SELECT
  '📊 MISSING DATES SUMMARY' as section,
  year_month as detail1,
  month_name as detail2,
  season_phase as detail3,
  CAST(missing_dates AS STRING) as detail4,
  CAST(first_missing AS STRING) as detail5,
  CAST(last_missing AS STRING) as detail6,
  status as detail7,
  NULL as detail8
FROM monthly_summary

UNION ALL

SELECT
  '📈 COVERAGE STATISTICS' as section,
  CONCAT('Total days: ', CAST(total_days_in_range AS STRING)) as detail1,
  CONCAT('Days with data: ', CAST(days_with_data AS STRING)) as detail2,
  CONCAT('Missing days: ', CAST(missing_days AS STRING)) as detail3,
  CONCAT('Coverage: ', CAST(coverage_pct AS STRING), '%') as detail4,
  CONCAT('First data: ', CAST(first_data_date AS STRING)) as detail5,
  CONCAT('Last data: ', CAST(last_data_date AS STRING)) as detail6,
  NULL as detail7,
  NULL as detail8
FROM coverage_stats

UNION ALL

SELECT
  '🔍 CONSECUTIVE MISSING RANGES' as section,
  CAST(gap_start AS STRING) as detail1,
  CAST(gap_end AS STRING) as detail2,
  CAST(consecutive_days_missing AS STRING) as detail3,
  severity as detail4,
  NULL as detail5,
  NULL as detail6,
  NULL as detail7,
  NULL as detail8
FROM gap_ranges

ORDER BY 
  CASE section
    WHEN 'MISSING DATES' THEN 1
    WHEN '📊 MISSING DATES SUMMARY' THEN 2
    WHEN '📈 COVERAGE STATISTICS' THEN 3
    WHEN '🔍 CONSECUTIVE MISSING RANGES' THEN 4
  END,
  detail1
);
