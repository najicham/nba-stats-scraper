#!/bin/bash
set -euo pipefail
# Scraper Failure Investigation Script
# Analyzes recent scraper failures and provides actionable insights

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Scraper Failure Analysis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Overall health
echo "📊 Overall Health (Last 24 Hours)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  COUNT(*) as total_runs,
  COUNTIF(status = 'SUCCESS') as succeeded,
  COUNTIF(status = 'FAILED') as failed,
  ROUND(COUNTIF(status = 'SUCCESS') / COUNT(*) * 100, 1) as success_pct
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
"
echo ""

# 2. Failing scrapers
echo "❌ Top Failing Scrapers (Last 24 Hours)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  scraper_name,
  COUNT(*) as total_runs,
  COUNTIF(status = 'FAILED') as failures,
  ROUND(COUNTIF(status = 'FAILED') / COUNT(*) * 100, 1) as failure_pct,
  MAX(triggered_at) as last_run
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
HAVING COUNTIF(status = 'FAILED') > 0
ORDER BY failures DESC
LIMIT 10
"
echo ""

# 3. Common error patterns
echo "🔎 Common Error Patterns"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  CASE 
    WHEN error_message LIKE '%timeout%' THEN 'Timeout'
    WHEN error_message LIKE '%429%' OR error_message LIKE '%rate limit%' THEN 'Rate Limit'
    WHEN error_message LIKE '%401%' OR error_message LIKE '%403%' OR error_message LIKE '%Unauthorized%' THEN 'Auth Error'
    WHEN error_message LIKE '%404%' OR error_message LIKE '%Not Found%' THEN 'Not Found'
    WHEN error_message LIKE '%500%' OR error_message LIKE '%502%' OR error_message LIKE '%503%' THEN 'Server Error'
    WHEN error_message LIKE '%No data%' OR error_message LIKE '%empty%' THEN 'No Data (Expected)'
    WHEN error_message LIKE '%connection%' THEN 'Connection Error'
    ELSE 'Other'
  END as error_type,
  COUNT(*) as occurrences,
  ROUND(COUNT(*) / (SELECT COUNT(*) FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\` 
                      WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) 
                        AND status = 'FAILED') * 100, 1) as pct_of_failures
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND status = 'FAILED'
  AND error_message IS NOT NULL
GROUP BY error_type
ORDER BY occurrences DESC
"
echo ""

# 4. Sample error messages by scraper
echo "📋 Sample Error Messages (Top 5 Failing Scrapers)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
WITH failing_scrapers AS (
  SELECT scraper_name
  FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
  WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND status = 'FAILED'
  GROUP BY scraper_name
  ORDER BY COUNT(*) DESC
  LIMIT 5
)
SELECT 
  l.scraper_name,
  l.triggered_at,
  SUBSTR(l.error_message, 1, 100) as error_sample
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\` l
INNER JOIN failing_scrapers f ON l.scraper_name = f.scraper_name
WHERE l.triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND l.status = 'FAILED'
  AND l.error_message IS NOT NULL
ORDER BY l.scraper_name, l.triggered_at DESC
LIMIT 20
"
echo ""

# 5. Time-based failure analysis
echo "⏰ Failure Distribution by Hour (Last 24 Hours)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  EXTRACT(HOUR FROM triggered_at AT TIME ZONE 'America/New_York') as hour_et,
  COUNT(*) as total_runs,
  COUNTIF(status = 'FAILED') as failures,
  ROUND(COUNTIF(status = 'FAILED') / COUNT(*) * 100, 1) as failure_pct
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY hour_et
HAVING COUNTIF(status = 'FAILED') > 0
ORDER BY hour_et DESC
"
echo ""

# 6. Check for Pub/Sub publishing errors
echo "📨 Pub/Sub Publishing Errors (Last Hour)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
PUB_ERRORS=$(gcloud logging read \
  "resource.labels.service_name=nba-scrapers
   AND (textPayload:\"Pub/Sub publish failed\" OR textPayload:\"Error publishing\")
   AND timestamp>=\`date -u -d '1 hour ago' --iso-8601=seconds\`" \
  --limit=10 \
  --format=json 2>/dev/null | jq -s 'length')

if [ "$PUB_ERRORS" -eq 0 ]; then
  echo "   ✅ No Pub/Sub publishing errors"
else
  echo "   ⚠️  $PUB_ERRORS publishing errors found:"
  gcloud logging read \
    "resource.labels.service_name=nba-scrapers
     AND (textPayload:\"Pub/Sub publish failed\" OR textPayload:\"Error publishing\")
     AND timestamp>=\`date -u -d '1 hour ago' --iso-8601=seconds\`" \
    --limit=5 \
    --format="table(timestamp,textPayload)"
fi
echo ""

# 7. Recommendations
echo "💡 Recommendations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Based on the analysis above:"
echo ""
echo "1. If you see 'No Data (Expected)' errors:"
echo "   → This is normal when there are no games or data isn't available yet"
echo "   → No action needed"
echo ""
echo "2. If you see 'Rate Limit' errors:"
echo "   → Check API quotas in external services"
echo "   → Consider reducing scraper frequency"
echo "   → Review workflows.yaml timing"
echo ""
echo "3. If you see 'Timeout' errors:"
echo "   → External API may be slow"
echo "   → Consider increasing scraper timeout"
echo "   → Check if specific scrapers need optimization"
echo ""
echo "4. If you see 'Auth Error' errors:"
echo "   → Check API keys in Secret Manager"
echo "   → Verify keys haven't expired"
echo "   → Check service account permissions"
echo ""
echo "5. If you see 'Server Error' errors:"
echo "   → External API may be having issues"
echo "   → Check API status pages"
echo "   → Errors should be transient"
echo ""
echo "6. To investigate a specific scraper:"
echo "   bq query \"SELECT * FROM nba_orchestration.scraper_execution_log"
echo "   WHERE scraper_name = 'YOUR_SCRAPER_NAME'"
echo "   AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
echo "   ORDER BY triggered_at DESC LIMIT 10\""
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Analysis complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
