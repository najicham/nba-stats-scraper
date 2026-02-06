#!/bin/bash
# Check feature quality for a specific date
# Usage: ./bin/queries/check_feature_quality.sh [YYYY-MM-DD]

DATE="${1:-$(date +%Y-%m-%d)}"

echo "=== Feature Quality Check for $DATE ==="
echo ""

bq query --use_legacy_sql=false --format=pretty "
-- Overall quality summary
SELECT
  'Overall' as category,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(quality_alert_level = 'red') as red_count,
  COUNTIF(quality_alert_level = 'yellow') as yellow_count,
  COUNTIF(quality_alert_level = 'green') as green_count,
  COUNT(*) as total_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

-- Category breakdown
SELECT
  'Matchup' as category,
  ROUND(AVG(matchup_quality_pct), 1) as avg_quality,
  COUNTIF(matchup_quality_pct < 50) as red_count,
  COUNTIF(matchup_quality_pct BETWEEN 50 AND 80) as yellow_count,
  COUNTIF(matchup_quality_pct > 80) as green_count,
  COUNT(*) as total_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Player History' as category,
  ROUND(AVG(player_history_quality_pct), 1),
  COUNTIF(player_history_quality_pct < 50),
  COUNTIF(player_history_quality_pct BETWEEN 50 AND 80),
  COUNTIF(player_history_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Game Context' as category,
  ROUND(AVG(game_context_quality_pct), 1),
  COUNTIF(game_context_quality_pct < 50),
  COUNTIF(game_context_quality_pct BETWEEN 50 AND 80),
  COUNTIF(game_context_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Team Context' as category,
  ROUND(AVG(team_context_quality_pct), 1),
  COUNTIF(team_context_quality_pct < 50),
  COUNTIF(team_context_quality_pct BETWEEN 50 AND 80),
  COUNTIF(team_context_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

SELECT
  'Vegas' as category,
  ROUND(AVG(vegas_quality_pct), 1),
  COUNTIF(vegas_quality_pct < 50),
  COUNTIF(vegas_quality_pct BETWEEN 50 AND 80),
  COUNTIF(vegas_quality_pct > 80),
  COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

ORDER BY category;
"
