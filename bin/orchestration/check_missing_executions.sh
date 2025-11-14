#!/bin/bash
# Check for RUN decisions without executions

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Checking for Missing Executions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT 
  d.decision_id,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S %Z', d.decision_time, 'America/New_York') as decision_time_et,
  d.workflow_name,
  ARRAY_LENGTH(d.scrapers_triggered) as scrapers_requested,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), d.decision_time, MINUTE) as minutes_ago,
  CASE 
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), d.decision_time, MINUTE) < 10 
    THEN 'ℹ️  RECENT (may still execute)'
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), d.decision_time, MINUTE) < 30
    THEN '⚠️  DELAYED (should have executed)'
    ELSE '❌ MISSED (likely will not execute)'
  END as status
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
ORDER BY d.decision_time DESC
"

MISSING_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
" | tail -n 1)

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$MISSING_COUNT" -eq 0 ] 2>/dev/null; then
    echo "✅ All RUN decisions have been executed!"
else
    echo "⚠️  Found $MISSING_COUNT RUN decision(s) without executions"
    echo ""
    echo "Next steps:"
    echo "  • Wait if recent (<10 min ago)"
    echo "  • Check logs: gcloud logging read 'resource.labels.service_name=nba-scrapers' --limit=50"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
