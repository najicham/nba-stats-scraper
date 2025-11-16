#!/bin/bash
# check_missing_executions.sh
# Identifies RUN decisions that haven't been executed
# Path: bin/orchestration/check_missing_executions.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Checking for Missing Executions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check for RUN decisions without executions
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
    ELSE '❌ MISSED (likely won''t execute)'
  END as status
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
ORDER BY d.decision_time DESC
"

echo ""

# Count summary
MISSING_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
" | tail -n 1)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$MISSING_COUNT" -eq 0 ]; then
    echo "✅ All RUN decisions have been executed!"
    echo ""
    echo "System is working correctly. The 5-minute delay between"
    echo "decision and execution is functioning as designed."
else
    echo "⚠️  Found $MISSING_COUNT RUN decision(s) without executions"
    echo ""
    echo "Possible causes:"
    echo "  1. execute-workflows scheduler job not running"
    echo "  2. Workflow executor endpoint returning errors"
    echo "  3. SERVICE_URL environment variable not set"
    echo "  4. Recent decision (< 10 min ago) that will execute soon"
    echo ""
    echo "Next steps:"
    echo "  • Check scheduler: gcloud scheduler jobs describe execute-workflows --location=us-west2"
    echo "  • Check Cloud Run logs: gcloud logging read 'resource.labels.service_name=nba-scrapers' --limit=50"
    echo "  • Verify env var: gcloud run services describe nba-scrapers --region=us-west2 --format='yaml(spec.template.spec.containers[0].env)'"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check execute-workflows job status
echo "📋 Checking execute-workflows scheduler job..."
gcloud scheduler jobs describe execute-workflows --location=us-west2 --format="table(
    state,
    schedule,
    lastAttemptTime.date('%Y-%m-%d %H:%M %Z'),
    status.code,
    status.message
)" 2>/dev/null || echo "❌ Job 'execute-workflows' not found!"

echo ""

# Check recent executions to see if job is running
echo "⏱️  Recent workflow executions (last 2 hours):"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  FORMAT_TIMESTAMP('%H:%M:%S %Z', execution_time, 'America/New_York') as time_et,
  workflow_name,
  status,
  scrapers_succeeded,
  scrapers_failed
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE execution_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
ORDER BY execution_time DESC
LIMIT 10
"

echo ""
