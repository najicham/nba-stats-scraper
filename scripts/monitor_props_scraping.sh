#!/bin/bash
set -euo pipefail
# Props Scraping Monitor
# Run at 10:00 AM PST (1:00 PM ET) to verify betting_lines workflow

echo "=== PROPS SCRAPING MONITOR ==="
echo "Time: $(date)"
echo ""

# Check if betting_lines workflow ran
echo "1. Checking betting_lines workflow decision..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  FORMAT_TIMESTAMP("%H:%M:%S", decision_time, "America/New_York") as time_et,
  action,
  reason,
  context
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE workflow_name = "betting_lines"
  AND DATE(decision_time, "America/New_York") = "2026-01-20"
ORDER BY decision_time DESC
LIMIT 5
'

echo ""
echo "2. Checking if props data arrived..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  COUNT(*) as total_props,
  COUNT(DISTINCT player_lookup) as unique_players,
  MIN(created_at) as first_scrape,
  MAX(created_at) as last_scrape
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date = "2026-01-20"
'

echo ""
echo "3. Checking scraper execution log..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  FORMAT_TIMESTAMP("%H:%M:%S", triggered_at, "America/New_York") as time_et,
  scraper_name,
  status,
  workflow
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at, "America/New_York") = "2026-01-20"
  AND workflow = "betting_lines"
ORDER BY triggered_at DESC
LIMIT 10
'

echo ""
echo "=== EXPECTED RESULTS ==="
echo "- Action: RUN (not SKIP)"
echo "- Props count: ~1000-1500"
echo "- Unique players: ~150"
echo "- Scraper status: success"
echo ""
echo "If all checks pass, props scraping succeeded! ✅"
