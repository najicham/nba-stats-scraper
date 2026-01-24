#!/bin/bash
# File: bin/processor_validation/validate_nbac_gamebook.sh
# Validate NBA.com Gamebook data quality in BigQuery

set -euo pipefail

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}

echo "========================================"
echo "NBA.com Gamebook Data Validation"
echo "========================================"
echo ""

echo "1. Data Coverage by Season:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT 
  season_year,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT game_date) as days,
  COUNT(*) as total_records,
  COUNTIF(player_status = 'active') as active_players,
  COUNTIF(player_status = 'dnp') as dnp_players,
  COUNTIF(player_status = 'inactive') as inactive_players
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
GROUP BY season_year
ORDER BY season_year DESC;
SQL

echo ""
echo "2. Name Resolution Status:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT 
  name_resolution_status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE player_status = 'inactive'
GROUP BY name_resolution_status
ORDER BY count DESC;
SQL

echo ""
echo "3. Data Quality Issues:"
bq query --use_legacy_sql=false --format=pretty <<SQL
WITH quality_checks AS (
  SELECT 
    'Missing player names' as check_type,
    COUNT(*) as issue_count
  FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
  WHERE player_name IS NULL OR player_name = ''
  
  UNION ALL
  
  SELECT 
    'Active players without points',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
  WHERE player_status = 'active' AND points IS NULL
  
  UNION ALL
  
  SELECT 
    'Invalid minutes (negative or > 60)',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
  WHERE minutes_decimal < 0 OR minutes_decimal > 60
  
  UNION ALL
  
  SELECT 
    'Missing team abbreviations',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
  WHERE team_abbr IS NULL
)
SELECT * FROM quality_checks WHERE issue_count > 0;
SQL

echo ""
echo "4. Sample Inactive Players (Unresolved Names):"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT 
  game_date,
  team_abbr,
  player_name_original,
  dnp_reason
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE player_status = 'inactive' 
  AND name_resolution_status != 'resolved'
ORDER BY game_date DESC
LIMIT 10;
SQL

echo ""
echo "5. Recent Processing Activity:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT 
  DATE(processed_at) as process_date,
  COUNT(DISTINCT game_id) as games_processed,
  COUNT(*) as records_added,
  MAX(processed_at) as last_update
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY process_date
ORDER BY process_date DESC;
SQL

echo ""
echo "========================================"
echo "Validation Complete"
echo "========================================"