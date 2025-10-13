-- ============================================================================
-- File: validation/queries/raw/bdl_injuries/data_quality_check.sql
-- Purpose: Comprehensive data quality validation for BDL injuries
-- Usage: Run weekly or when investigating data anomalies
-- ============================================================================
-- Expected Results:
--   - 29-30 teams should appear in dataset over time
--   - Reasonable distribution of injury statuses
--   - High return date parsing success
--   - Minimal data quality flags
-- ============================================================================

WITH
-- Overall statistics (last 30 days)
overall_stats AS (
  SELECT
    COUNT(*) as total_records,
    COUNT(DISTINCT scrape_date) as days_with_data,
    COUNT(DISTINCT bdl_player_id) as unique_players_all_time,
    COUNT(DISTINCT team_abbr) as unique_teams_all_time,
    AVG(parsing_confidence) as avg_confidence,
    MIN(parsing_confidence) as min_confidence,
    -- Return date parsing
    COUNT(CASE WHEN return_date_parsed = TRUE THEN 1 END) as return_dates_parsed,
    COUNT(CASE WHEN return_date_parsed = FALSE THEN 1 END) as return_dates_unparsed,
    -- Injury status breakdown
    COUNT(CASE WHEN injury_status_normalized = 'out' THEN 1 END) as status_out,
    COUNT(CASE WHEN injury_status_normalized = 'questionable' THEN 1 END) as status_questionable,
    COUNT(CASE WHEN injury_status_normalized = 'doubtful' THEN 1 END) as status_doubtful,
    COUNT(CASE WHEN injury_status_normalized = 'probable' THEN 1 END) as status_probable,
    COUNT(CASE WHEN injury_status_normalized IS NULL THEN 1 END) as status_unknown,
    -- Reason categories
    COUNT(CASE WHEN reason_category = 'injury' THEN 1 END) as reason_injury,
    COUNT(CASE WHEN reason_category = 'g_league' THEN 1 END) as reason_g_league,
    COUNT(CASE WHEN reason_category = 'rest' THEN 1 END) as reason_rest,
    COUNT(CASE WHEN reason_category = 'personal' THEN 1 END) as reason_personal,
    COUNT(CASE WHEN reason_category = 'suspension' THEN 1 END) as reason_suspension,
    -- Data quality
    COUNT(CASE WHEN data_quality_flags IS NOT NULL AND data_quality_flags != '' THEN 1 END) as records_with_flags
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- Team coverage analysis
team_coverage AS (
  SELECT
    team_abbr,
    COUNT(DISTINCT scrape_date) as days_appeared,
    COUNT(DISTINCT bdl_player_id) as unique_players,
    COUNT(*) as total_injuries,
    AVG(parsing_confidence) as avg_confidence
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY team_abbr
),

-- Most recent data quality
latest_date_quality AS (
  SELECT
    MAX(scrape_date) as latest_date,
    COUNT(*) as latest_injury_count,
    COUNT(DISTINCT team_abbr) as latest_teams,
    AVG(parsing_confidence) as latest_confidence
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date = (SELECT MAX(scrape_date) FROM `nba-props-platform.nba_raw.bdl_injuries`)
)

-- Output overall stats
SELECT 
  'OVERALL_STATS' as section,
  'Last 30 Days' as metric,
  CAST(total_records AS STRING) as value1,
  CONCAT(days_with_data, ' days with data') as value2,
  CONCAT(unique_players_all_time, ' players, ', unique_teams_all_time, ' teams') as value3
FROM overall_stats

UNION ALL

SELECT
  'OVERALL_STATS' as section,
  'Confidence Scores' as metric,
  CONCAT('Avg: ', CAST(ROUND(avg_confidence, 3) AS STRING)) as value1,
  CONCAT('Min: ', CAST(ROUND(min_confidence, 3) AS STRING)) as value2,
  CASE 
    WHEN avg_confidence >= 0.95 THEN '✅ Excellent'
    WHEN avg_confidence >= 0.8 THEN '⚠️  Acceptable'
    ELSE '🔴 Poor'
  END as value3
FROM overall_stats

UNION ALL

SELECT
  'OVERALL_STATS' as section,
  'Return Date Parsing' as metric,
  CAST(return_dates_parsed AS STRING) as value1,
  CAST(return_dates_unparsed AS STRING) as value2,
  CONCAT(CAST(ROUND(100.0 * return_dates_parsed / (return_dates_parsed + return_dates_unparsed), 1) AS STRING), '% parsed') as value3
FROM overall_stats

UNION ALL

SELECT
  'INJURY_STATUS' as section,
  'Status Distribution' as metric,
  CONCAT('Out: ', CAST(status_out AS STRING)) as value1,
  CONCAT('Q: ', CAST(status_questionable AS STRING), ', D: ', CAST(status_doubtful AS STRING)) as value2,
  CONCAT('Probable: ', CAST(status_probable AS STRING), ', Unknown: ', CAST(status_unknown AS STRING)) as value3
FROM overall_stats

UNION ALL

SELECT
  'REASON_CATEGORY' as section,
  'Reason Distribution' as metric,
  CONCAT('Injury: ', CAST(reason_injury AS STRING)) as value1,
  CONCAT('G-League: ', CAST(reason_g_league AS STRING), ', Rest: ', CAST(reason_rest AS STRING)) as value2,
  CONCAT('Personal: ', CAST(reason_personal AS STRING), ', Suspension: ', CAST(reason_suspension AS STRING)) as value3
FROM overall_stats

UNION ALL

SELECT
  'DATA_QUALITY' as section,
  'Quality Flags' as metric,
  CAST(records_with_flags AS STRING) as value1,
  CONCAT(CAST(ROUND(100.0 * records_with_flags / total_records, 1) AS STRING), '% flagged') as value2,
  CASE 
    WHEN records_with_flags * 100.0 / total_records < 5 THEN '✅ Good'
    WHEN records_with_flags * 100.0 / total_records < 15 THEN '⚠️  Review'
    ELSE '🔴 High flag rate'
  END as value3
FROM overall_stats

UNION ALL

SELECT
  'LATEST_DATA' as section,
  'Most Recent Scrape' as metric,
  CAST(latest_date AS STRING) as value1,
  CONCAT(CAST(latest_injury_count AS STRING), ' injuries, ', CAST(latest_teams AS STRING), ' teams') as value2,
  CONCAT('Confidence: ', CAST(ROUND(latest_confidence, 3) AS STRING)) as value3
FROM latest_date_quality

UNION ALL

SELECT
  'TEAM_COVERAGE' as section,
  'Teams Missing Data' as metric,
  CAST(30 - COUNT(*) AS STRING) as value1,
  CONCAT('Covered: ', CAST(COUNT(*) AS STRING), '/30 teams') as value2,
  CASE 
    WHEN COUNT(*) >= 25 THEN '✅ Good coverage'
    WHEN COUNT(*) >= 20 THEN '⚠️  Moderate coverage'
    ELSE '🔴 Low coverage'
  END as value3
FROM team_coverage

ORDER BY 
  CASE section
    WHEN 'OVERALL_STATS' THEN 1
    WHEN 'INJURY_STATUS' THEN 2
    WHEN 'REASON_CATEGORY' THEN 3
    WHEN 'DATA_QUALITY' THEN 4
    WHEN 'LATEST_DATA' THEN 5
    WHEN 'TEAM_COVERAGE' THEN 6
  END,
  metric;
