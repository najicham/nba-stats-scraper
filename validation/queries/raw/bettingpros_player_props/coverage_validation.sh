#!/bin/bash
# Simple BettingPros coverage validation without requiring schedule table

echo "============================================================================"
echo "BETTINGPROS DATA COVERAGE VALIDATION (SIMPLE)"
echo "============================================================================"
echo ""

echo "=== 1. Overall Date Range ==="
bq query --use_legacy_sql=false '
SELECT 
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as days_span,
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNT(*) as total_records,
  ROUND(AVG(records_per_date), 0) as avg_records_per_date
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
CROSS JOIN (
  SELECT COUNT(*) / COUNT(DISTINCT game_date) as records_per_date
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= "2021-10-01"
)
WHERE game_date >= "2021-10-01"
'

echo ""
echo "=== 2. Coverage by Season (Oct-Sep) ==="
bq query --use_legacy_sql=false '
SELECT 
  CASE 
    WHEN EXTRACT(MONTH FROM game_date) >= 10 THEN EXTRACT(YEAR FROM game_date)
    ELSE EXTRACT(YEAR FROM game_date) - 1
  END as season_start_year,
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNT(*) as total_records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  ROUND(AVG(records_per_date), 0) as avg_records_per_date
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
CROSS JOIN (
  SELECT 
    CASE 
      WHEN EXTRACT(MONTH FROM game_date) >= 10 THEN EXTRACT(YEAR FROM game_date)
      ELSE EXTRACT(YEAR FROM game_date) - 1
    END as season,
    game_date,
    COUNT(*) as records_per_date
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= "2021-10-01"
  GROUP BY season, game_date
) sub
WHERE CASE 
    WHEN EXTRACT(MONTH FROM game_date) >= 10 THEN EXTRACT(YEAR FROM game_date)
    ELSE EXTRACT(YEAR FROM game_date) - 1
  END = sub.season
  AND game_date = sub.game_date
  AND game_date >= "2021-10-01"
GROUP BY season_start_year
ORDER BY season_start_year
'

echo ""
echo "=== 3. Monthly Summary (Last 18 Months) ==="
bq query --use_legacy_sql=false '
SELECT 
  FORMAT_DATE("%Y-%m", game_date) as year_month,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT bookmaker) as unique_bookmakers,
  MIN(records_per_date) as min_records,
  MAX(records_per_date) as max_records,
  ROUND(AVG(records_per_date), 0) as avg_records
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
CROSS JOIN (
  SELECT game_date as d, COUNT(*) as records_per_date
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 18 MONTH)
  GROUP BY d
) sub
WHERE game_date = sub.d
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 18 MONTH)
GROUP BY year_month
ORDER BY year_month DESC
'

echo ""
echo "=== 4. Potential Date Gaps (Multi-Day Gaps) ==="
bq query --use_legacy_sql=false '
WITH dated_data AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= "2021-10-01"
  ORDER BY game_date
),
gaps AS (
  SELECT 
    game_date,
    LAG(game_date) OVER (ORDER BY game_date) as prev_date,
    DATE_DIFF(game_date, LAG(game_date) OVER (ORDER BY game_date), DAY) as days_since_prev
  FROM dated_data
)
SELECT 
  prev_date as last_date_before_gap,
  game_date as first_date_after_gap,
  days_since_prev as gap_days
FROM gaps
WHERE days_since_prev > 7  -- Gaps of more than 7 days (could be All-Star break, summer)
ORDER BY prev_date
'

echo ""
echo "=== 5. Data Quality by Date (Last 30 Days) ==="
bq query --use_legacy_sql=false '
SELECT 
  game_date,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(DISTINCT source_file_path) as scrape_files
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND game_date <= CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date DESC
'

echo ""
echo "=== 6. Low Data Quality Dates (< 500 records) ==="
bq query --use_legacy_sql=false '
SELECT 
  game_date,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT bookmaker) as bookmakers
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date >= "2021-10-01"
GROUP BY game_date
HAVING COUNT(*) < 500
ORDER BY game_date
'

echo ""
echo "=== 7. Bookmaker Coverage Over Time ==="
bq query --use_legacy_sql=false '
SELECT 
  FORMAT_DATE("%Y-%m", game_date) as year_month,
  COUNT(DISTINCT bookmaker) as unique_bookmakers,
  STRING_AGG(DISTINCT bookmaker ORDER BY bookmaker LIMIT 10) as sample_bookmakers
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date >= "2021-10-01"
GROUP BY year_month
ORDER BY year_month
'

echo ""
echo "============================================================================"
echo "INTERPRETATION"
echo "============================================================================"
echo ""
echo "Query 1: Should show Oct 2021 to present, ~3-4 years of data"
echo "Query 2: Each season should have 170-200 dates (regular + playoffs)"
echo "Query 3: Recent months should have 1,000-8,000 avg records per date"
echo "Query 4: Gaps > 7 days are normal (All-Star break, summer off-season)"
echo "Query 5: Recent dates validate current scraping is working"
echo "Query 6: Low data dates may be early season or data quality issues"
echo "Query 7: Bookmaker count should increase over time (more books added)"
echo ""
echo "⚠️  If Query 6 shows many dates: Historical data may be incomplete"
echo "✅ If Query 3 shows consistent 1,000+ records: Data quality is good"
echo ""
