#!/bin/bash
# Quick pipeline health check - run anytime to see status

echo "🏀 NBA Pipeline Health Check"
echo "============================"
echo "Time: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# 1. Check for recent errors
echo "📋 Recent Errors (last hour):"
ERROR_COUNT=$(gcloud logging read 'resource.type="cloud_run_revision" AND (severity>=ERROR)' --limit=50 --freshness=1h --format="value(textPayload)" 2>/dev/null | wc -l)
echo "   Error count: $ERROR_COUNT"

# 2. Check today's data counts
echo ""
echo "📊 Today's Data:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'BDL Boxscores' as source, COUNT(DISTINCT game_id) as games, COUNT(*) as row_count
FROM nba_raw.bdl_player_boxscores WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'BettingPros Props', 0, COUNT(*) FROM nba_raw.bettingpros_player_points_props WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'Gamebooks', COUNT(DISTINCT game_id), COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = CURRENT_DATE()
" 2>/dev/null

# 3. Check service health
echo ""
echo "🔧 Service Health:"
for svc in nba-phase1-scrapers nba-phase2-raw-processors; do
    STATUS=$(curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" 2>/dev/null | jq -r '.status // "unknown"')
    echo "   $svc: $STATUS"
done

# 4. Check for stale data
echo ""
echo "⏰ Data Freshness:"
PYTHONPATH=/home/naji/code/nba-stats-scraper /home/naji/code/nba-stats-scraper/.venv/bin/python /home/naji/code/nba-stats-scraper/scripts/check_data_freshness.py --json 2>/dev/null | jq -r '.results[] | "   \(.description): \(.status) (\(.message))"'

echo ""
echo "✅ Check complete"
