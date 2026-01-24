#!/bin/bash
# Check for workflow failure patterns
# Run daily to detect systematic workflow issues

set -euo pipefail

echo "=== Workflow Health Check ==="
echo "Time: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Checking last 48 hours..."
echo ""

# Query for workflows with >=5 failures in last 48h
RESULTS=$(bq query --use_legacy_sql=false --format=csv --max_rows=20 "
WITH recent_failures AS (
  SELECT
    workflow_name,
    DATE(execution_time) as date,
    COUNTIF(status = 'failed') as failures,
    COUNTIF(status = 'completed') as successes,
    COUNT(*) as attempts
  FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
  WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
  GROUP BY workflow_name, date
)
SELECT
  workflow_name,
  SUM(failures) as total_failures,
  SUM(successes) as total_successes,
  ROUND(100.0 * SUM(failures) / SUM(attempts), 1) as failure_rate_pct
FROM recent_failures
GROUP BY workflow_name
HAVING SUM(failures) >= 5
ORDER BY total_failures DESC
" 2>/dev/null)

if echo "$RESULTS" | grep -q "workflow_name"; then
  echo "🚨 ALERT: Workflows with >=5 failures in 48h:"
  echo ""
  echo "$RESULTS"
  echo ""
  echo "⚠️  Action required: Investigate workflow failures"
  echo "Common causes:"
  echo "  - API authentication failures"
  echo "  - Rate limiting"
  echo "  - Transient network issues"
  echo ""
  exit 1
else
  echo "✅ No workflow failure patterns detected"
  echo "(Threshold: >=5 failures in 48h)"
  exit 0
fi
