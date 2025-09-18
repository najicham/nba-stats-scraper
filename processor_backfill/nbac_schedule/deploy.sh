#!/bin/bash
# FILE: processor_backfill/nbac_schedule/deploy.sh

# Deploy NBA.com Schedule Processor Backfill Job

set -e

echo "Deploying NBA.com Schedule Processor Backfill Job..."

# Use standardized processor backfill deployment script
./bin/processors/deploy/deploy_processor_backfill_job.sh nbac_schedule

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run (2 seasons test):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--dry-run,--limit=2 --region=us-west2"
echo ""
echo "  # Single season test (current season):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2024-25 --region=us-west2"
echo ""
echo "  # Recent seasons test (last 2 seasons):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--limit=2 --region=us-west2"
echo ""
echo "  # Full historical backfill (all 5 seasons):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --region=us-west2"
echo ""
echo "  # Specific season processing:"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2023-24 --region=us-west2"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2022-23 --region=us-west2"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2021-22 --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  # Get recent execution"
echo "  gcloud run jobs executions list --job=nbac-schedule-processor-backfill --region=us-west2 --limit=1"
echo ""
echo "  # Follow specific execution logs"
echo "  gcloud run jobs executions logs [execution-id] --region=us-west2 --follow"
echo ""
echo "Validate results:"
echo "  # Check enhanced schedule data coverage"
echo "  bq query --use_legacy_sql=false \"SELECT season_nba_format, COUNT(*) as games, COUNT(CASE WHEN is_primetime THEN 1 END) as primetime_games, ROUND(COUNT(CASE WHEN is_primetime THEN 1 END) * 100.0 / COUNT(*), 1) as primetime_pct FROM \\\`nba_raw.nbac_schedule\\\` GROUP BY season_nba_format ORDER BY season_nba_format DESC\""
echo ""
echo "  # Check data quality and filtering"
echo "  bq query --use_legacy_sql=false \"SELECT is_regular_season, is_playoffs, is_all_star, COUNT(*) as game_count FROM \\\`nba_raw.nbac_schedule\\\` WHERE game_date >= '2021-01-01' GROUP BY 1,2,3 ORDER BY game_count DESC\""
echo ""
echo "  # Verify enhanced fields are populated"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_games, COUNT(CASE WHEN primary_network IS NOT NULL THEN 1 END) as games_with_network, COUNT(CASE WHEN day_of_week IS NOT NULL THEN 1 END) as games_with_day FROM \\\`nba_raw.nbac_schedule\\\` WHERE game_date >= '2021-01-01'\""
echo ""
echo "  # Network distribution analysis"
echo "  bq query --use_legacy_sql=false \"SELECT primary_network, COUNT(*) as games FROM \\\`nba_raw.nbac_schedule\\\` WHERE is_primetime = TRUE AND season_nba_format = '2024-25' GROUP BY primary_network ORDER BY games DESC\""
echo ""
echo "Use analytics views:"
echo "  # Season analytics summary"
echo "  bq query --use_legacy_sql=false \"SELECT * FROM \\\`nba_raw.nbac_schedule_analytics\\\`\""
echo ""
echo "  # Recent primetime games"
echo "  bq query --use_legacy_sql=false \"SELECT game_date, home_team_tricode, away_team_tricode, primary_network FROM \\\`nba_raw.nbac_schedule_primetime\\\` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) ORDER BY game_date DESC LIMIT 10\""
