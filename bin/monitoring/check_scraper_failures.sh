#!/bin/bash
# Alert on sustained scraper failures
# Run daily to catch scraper issues within 24h

set -e

echo "=== Scraper Failure Detection ==="
echo "Time: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Checking last 24 hours..."
echo ""

# Query for scrapers with >= 10 failures in last 24h
FAILURES=$(bq query --use_legacy_sql=false --format=csv --max_rows=20 "
SELECT
  scraper_name,
  COUNT(*) as failures,
  MIN(triggered_at) as first_failure,
  MAX(triggered_at) as last_failure
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE status = 'failed'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
HAVING COUNT(*) >= 10
ORDER BY failures DESC
" 2>/dev/null)

if echo "$FAILURES" | grep -q "scraper_name"; then
  echo "🚨 ALERT: Scrapers with >=10 failures detected:"
  echo ""
  echo "$FAILURES"
  echo ""
  echo "⚠️  Action required: Investigate failing scrapers"
  exit 1
else
  echo "✅ No scraper failure spikes detected"
  echo "(Threshold: >=10 failures in 24h)"
  exit 0
fi
