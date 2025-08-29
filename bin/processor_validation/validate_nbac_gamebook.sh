#!/bin/bash
# File: bin/processor_validation/validate_nbac_gamebook.sh
# Validate NBA.com gamebook data quality in BigQuery after processing

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
TABLE_NAME="nba_raw.nbac_gamebook_player_stats"

echo "Validating NBA.com Gamebook Data"
echo "================================="
echo ""

# 1. Check data coverage
echo "📊 Data Coverage:"
echo "-----------------"
bq query --use_legacy_sql=false <<SQL
WITH coverage AS (
  SELECT 
    season_year,
    MIN(game_date) as season_start,
    MAX(game_date) as season_end,
    COUNT(DISTINCT game_id) as games,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(*) as total_records
  FROM \`${PROJECT_ID}.${TABLE_NAME}\`
  GROUP BY season_year
)
SELECT * FROM coverage
ORDER BY season_year DESC;
SQL

# 2. Check for data completeness issues
echo ""
echo "🔍 Data Completeness Checks:"
echo "-----------------------------"
bq query --use_legacy_sql=false <<SQL
SELECT 
  'Games without any players' as check_type,
  COUNT(DISTINCT game_id) as issue_count
FROM (
  SELECT game_id, COUNT(*) as player_count
  FROM \`${PROJECT_ID}.${TABLE_NAME}\`
  GROUP BY game_id
  HAVING player_count = 0
)
UNION ALL
SELECT 
  'Active players with NULL points',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE player_status = 'active' AND points IS NULL
UNION ALL
SELECT 
  'Active players with NULL minutes',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE player_status = 'active' AND minutes IS NULL
UNION ALL
SELECT 
  'Missing player names',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE player_name IS NULL OR player_name = ''
UNION ALL
SELECT 
  'Invalid team abbreviations',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE team_abbr NOT IN (
  'ATL','BKN','BOS','CHA','CHI','CLE','DAL','DEN','DET','GSW',
  'HOU','IND','LAC','LAL','MEM','MIA','MIL','MIN','NOP','NYK',
  'OKC','ORL','PHI','PHX','POR','SAC','SAS','TOR','UTA','WAS'
);
SQL

# 3. Check name resolution success rate
echo ""
echo "📛 Name Resolution Stats:"
echo "-------------------------"
bq query --use_legacy_sql=false <<SQL
SELECT 
  player_status,
  name_resolution_status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY player_status), 2) as pct
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE player_status = 'inactive'
GROUP BY player_status, name_resolution_status
ORDER BY count DESC;
SQL

# 4. Check for duplicate records
echo ""
echo "🔄 Duplicate Check:"
echo "-------------------"
bq query --use_legacy_sql=false <<SQL
WITH duplicates AS (
  SELECT 
    game_id, 
    player_lookup,
    player_status,
    COUNT(*) as duplicate_count
  FROM \`${PROJECT_ID}.${TABLE_NAME}\`
  GROUP BY game_id, player_lookup, player_status
  HAVING duplicate_count > 1
)
SELECT 
  CASE 
    WHEN COUNT(*) = 0 THEN '✓ No duplicate records found'
    ELSE CONCAT('⚠️  Found ', CAST(COUNT(*) AS STRING), ' duplicate player-game combinations')
  END as duplicate_check
FROM duplicates;
SQL

# 5. Sample unresolved names
echo ""
echo "❓ Sample Unresolved Inactive Players:"
echo "---------------------------------------"
bq query --use_legacy_sql=false <<SQL
SELECT 
  game_date,
  team_abbr,
  player_name_original as last_name,
  dnp_reason,
  name_resolution_status,
  COUNT(*) OVER (PARTITION BY player_name_original) as total_occurrences
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE player_status = 'inactive'
  AND name_resolution_status IN ('not_found', 'multiple_matches')
ORDER BY total_occurrences DESC, game_date DESC
LIMIT 10;
SQL

# 6. Check for reasonable stat values
echo ""
echo "📈 Statistical Sanity Checks:"
echo "-----------------------------"
bq query --use_legacy_sql=false <<SQL
SELECT 
  'Players with 60+ minutes' as anomaly,
  COUNT(*) as count
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE minutes_decimal > 60
UNION ALL
SELECT 
  'Players with 70+ points',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE points > 70
UNION ALL
SELECT 
  'Players with 30+ rebounds',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE total_rebounds > 30
UNION ALL
SELECT 
  'Players with 20+ assists',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE assists > 20
UNION ALL
SELECT 
  'Players with negative stats',
  COUNT(*)
FROM \`${PROJECT_ID}.${TABLE_NAME}\`
WHERE points < 0 OR total_rebounds < 0 OR assists < 0;
SQL

# 7. Compare with Odds API data (if available)
echo ""
echo "🎲 Cross-Reference with Odds API:"
echo "----------------------------------"
bq query --use_legacy_sql=false <<SQL
WITH comparison AS (
  SELECT 
    g.game_date,
    COUNT(DISTINCT g.player_lookup) as gamebook_players,
    COUNT(DISTINCT o.player_lookup) as odds_players,
    COUNT(DISTINCT CASE WHEN g.player_lookup IS NOT NULL AND o.player_lookup IS NOT NULL THEN g.player_lookup END) as matched_players
  FROM \`${PROJECT_ID}.${TABLE_NAME}\` g
  FULL OUTER JOIN \`${PROJECT_ID}.nba_raw.odds_api_player_points_props\` o
    ON g.game_id = o.game_id AND g.player_lookup = o.player_lookup
  WHERE g.game_date >= '2023-05-01'  -- Odds API data starts here
  GROUP BY g.game_date
)
SELECT 
  MIN(game_date) as earliest_overlap,
  MAX(game_date) as latest_overlap,
  COUNT(*) as days_with_data,
  ROUND(AVG(matched_players * 100.0 / NULLIF(odds_players, 0)), 2) as avg_match_rate
FROM comparison
WHERE gamebook_players > 0 AND odds_players > 0;
SQL

echo ""
echo "✅ Validation Complete!"
echo ""
echo "Next Steps:"
echo "1. Review any data quality issues identified above"
echo "2. Check unresolved player names and update Basketball Reference rosters if needed"
echo "3. Run queries to validate prop outcomes against actual stats"
echo ""