#!/bin/bash
# =============================================================================
# NBA Injury Report Data Validation - BQ Commands
# =============================================================================
# These queries validate injury report coverage for regular season + playoffs
# Excludes All-Star exhibition games (which don't have injury reports)
# =============================================================================

# -----------------------------------------------------------------------------
# Query 1: Check Missing Game Days (Should return 0)
# -----------------------------------------------------------------------------
echo "Checking for missing game days..."
bq query --use_legacy_sql=false "
WITH all_scheduled_game_dates AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
    AND is_all_star = FALSE  -- Exclude All-Star exhibitions
),
injury_report_dates AS (
  SELECT DISTINCT report_date
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
)
SELECT COUNT(*) as total_missing_game_days
FROM all_scheduled_game_dates asg
LEFT JOIN injury_report_dates ird ON asg.game_date = ird.report_date
WHERE ird.report_date IS NULL;
"

# -----------------------------------------------------------------------------
# Query 2: List Any Missing Dates (Should be empty)
# -----------------------------------------------------------------------------
echo ""
echo "Listing any missing dates..."
bq query --use_legacy_sql=false "
WITH all_scheduled_game_dates AS (
  SELECT DISTINCT game_date, COUNT(*) as game_count
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
    AND is_all_star = FALSE
  GROUP BY game_date
),
injury_report_dates AS (
  SELECT DISTINCT report_date
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
)
SELECT 
  asg.game_date,
  asg.game_count as games_scheduled
FROM all_scheduled_game_dates asg
LEFT JOIN injury_report_dates ird ON asg.game_date = ird.report_date
WHERE ird.report_date IS NULL
ORDER BY asg.game_date;
"

# -----------------------------------------------------------------------------
# Query 3: Coverage Summary by Season
# -----------------------------------------------------------------------------
echo ""
echo "Coverage summary by season..."
bq query --use_legacy_sql=false "
WITH scheduled_days AS (
  SELECT 
    season_year,
    COUNT(DISTINCT game_date) as total_game_days
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
    AND is_all_star = FALSE
  GROUP BY season_year
),
covered_days AS (
  SELECT 
    CASE 
      WHEN EXTRACT(MONTH FROM report_date) >= 10 
        THEN EXTRACT(YEAR FROM report_date)
      ELSE EXTRACT(YEAR FROM report_date) - 1
    END as season_year,
    COUNT(DISTINCT report_date) as covered_days
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
  WHERE report_date BETWEEN '2021-10-01' AND '2025-06-30'
  GROUP BY season_year
)
SELECT 
  s.season_year,
  s.total_game_days,
  COALESCE(c.covered_days, 0) as covered_days,
  s.total_game_days - COALESCE(c.covered_days, 0) as missing_days,
  ROUND(COALESCE(c.covered_days, 0) / s.total_game_days * 100, 1) as coverage_pct
FROM scheduled_days s
LEFT JOIN covered_days c ON s.season_year = c.season_year
ORDER BY s.season_year;
"

# -----------------------------------------------------------------------------
# Query 4: Total Records Summary
# -----------------------------------------------------------------------------
echo ""
echo "Total records summary..."
bq query --use_legacy_sql=false "
SELECT 
  COUNT(*) as total_records,
  COUNT(DISTINCT report_date) as unique_dates,
  MIN(report_date) as earliest_date,
  MAX(report_date) as latest_date,
  COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
WHERE report_date BETWEEN '2021-10-01' AND '2025-06-30';
"

# -----------------------------------------------------------------------------
# Query 5: Regular Season vs Playoffs Breakdown
# -----------------------------------------------------------------------------
echo ""
echo "Regular season vs playoffs breakdown..."
bq query --use_legacy_sql=false "
WITH schedule_with_type AS (
  SELECT 
    game_date,
    CASE 
      WHEN is_playoffs THEN 'Playoffs'
      ELSE 'Regular Season'
    END as season_type
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
    AND is_all_star = FALSE
),
injury_by_type AS (
  SELECT 
    ir.report_date,
    s.season_type,
    COUNT(*) as injury_count
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\` ir
  LEFT JOIN schedule_with_type s ON ir.report_date = s.game_date
  WHERE ir.report_date BETWEEN '2021-10-01' AND '2025-06-30'
  GROUP BY ir.report_date, s.season_type
)
SELECT 
  season_type,
  COUNT(DISTINCT report_date) as game_days,
  SUM(injury_count) as total_injury_records,
  ROUND(AVG(injury_count), 1) as avg_injuries_per_day
FROM injury_by_type
GROUP BY season_type
ORDER BY season_type;
"

# -----------------------------------------------------------------------------
# Query 6: Verify All-Star Games Are Excluded
# -----------------------------------------------------------------------------
echo ""
echo "Confirming All-Star games are excluded from validation..."
bq query --use_legacy_sql=false "
SELECT 
  game_date,
  COUNT(*) as allstar_games,
  STRING_AGG(CONCAT(away_team_tricode, '@', home_team_tricode), ', ') as matchups
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
  AND is_all_star = TRUE
GROUP BY game_date
ORDER BY game_date;
"

# -----------------------------------------------------------------------------
# Query 7: Check for Dates with Low Injury Counts (Potential Issues)
# -----------------------------------------------------------------------------
echo ""
echo "Checking for dates with suspiciously low injury counts..."
bq query --use_legacy_sql=false "
WITH game_days AS (
  SELECT DISTINCT game_date, COUNT(*) as scheduled_games
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
    AND is_all_star = FALSE
  GROUP BY game_date
),
injury_counts AS (
  SELECT 
    report_date,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(*) as total_records
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
  WHERE report_date BETWEEN '2021-10-01' AND '2025-06-30'
  GROUP BY report_date
)
SELECT 
  g.game_date,
  g.scheduled_games,
  COALESCE(i.unique_players, 0) as players_on_report,
  COALESCE(i.total_records, 0) as total_records
FROM game_days g
LEFT JOIN injury_counts i ON g.game_date = i.report_date
WHERE COALESCE(i.unique_players, 0) = 0  -- Dates with zero injuries
ORDER BY g.game_date
LIMIT 20;
"

echo ""
echo "=========================================="
echo "Validation Complete"
echo "=========================================="
