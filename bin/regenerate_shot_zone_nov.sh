#!/bin/bash
# Regenerate player_shot_zone_analysis for November 4-18, 2025
# Session 113+ dynamic threshold fix

set -e

DATES=(
  "2025-11-06"
  "2025-11-07"
  "2025-11-08"
  "2025-11-09"
  "2025-11-10"
  "2025-11-11"
  "2025-11-12"
  "2025-11-13"
  "2025-11-14"
  "2025-11-15"
  "2025-11-16"
  "2025-11-17"
  "2025-11-18"
)

echo "========================================"
echo "Shot Zone Regeneration - Nov 6-18, 2025"
echo "========================================"
echo ""

for date in "${DATES[@]}"; do
  echo "-----------------------------------"
  echo "Processing: $date"
  echo "-----------------------------------"

  PYTHONPATH=. python -m data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor "$date" 2>&1 | grep -E "(Season.*start|Early season|Completed|Successfully saved)"

  echo ""
  echo "Verifying records for $date..."
  bq query --use_legacy_sql=false "
  SELECT
    '$date' as date,
    COUNT(*) as records,
    COUNTIF(early_season_flag = TRUE) as early_season,
    MIN(games_in_sample_10) as min_games,
    MAX(games_in_sample_10) as max_games
  FROM nba_precompute.player_shot_zone_analysis
  WHERE analysis_date = '$date'
  " --format=csv

  echo ""
  sleep 2
done

echo "========================================"
echo "Regeneration Complete!"
echo "========================================"
