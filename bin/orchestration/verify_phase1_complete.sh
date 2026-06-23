#!/bin/bash
# verify_phase1_complete.sh
# Comprehensive verification of Phase 1 orchestration system
# Path: bin/orchestration/verify_phase1_complete.sh

set -euo pipefail

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Phase 1 Orchestration - Complete System Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Date: $(date)"
echo ""

# ============================================================================
# 1. TABLE EXISTENCE CHECK
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Checking Table Existence"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for table in daily_expected_schedule workflow_decisions cleanup_operations scraper_execution_log workflow_executions; do
    if bq show nba-props-platform:nba_orchestration.$table &>/dev/null; then
        echo "✅ Table exists: nba_orchestration.$table"
    else
        echo "❌ Table missing: nba_orchestration.$table"
    fi
done

echo ""

# ============================================================================
# 2. DAILY SCHEDULE CHECK
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Daily Schedule Generation (5:00 AM ET)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

bq query --use_legacy_sql=false --format=pretty "
SELECT
  date,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S %Z', locked_at, 'America/New_York') as locked_at_et,
  COUNT(*) as workflows_scheduled
FROM \`nba-props-platform.nba_orchestration.daily_expected_schedule\`
WHERE date = CURRENT_DATE('America/New_York')
GROUP BY date, locked_at
ORDER BY locked_at DESC
LIMIT 1
"

echo ""

# ============================================================================
# 3. WORKFLOW DECISIONS CHECK
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Workflow Decisions (Hourly 6 AM-11 PM ET)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "📊 Decision Summary:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  action,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY action
ORDER BY count DESC
"

echo ""
echo "📈 Hourly Pattern:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  EXTRACT(HOUR FROM decision_time AT TIME ZONE 'America/New_York') as hour_et,
  COUNT(*) as total_evaluations,
  COUNTIF(action = 'RUN') as run_decisions,
  COUNTIF(action = 'SKIP') as skip_decisions,
  COUNTIF(action = 'ABORT') as abort_decisions
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY hour_et
ORDER BY hour_et
"

echo ""
echo "🚨 Alerts (if any):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  FORMAT_TIMESTAMP('%H:%M:%S %Z', decision_time, 'America/New_York') as time_et,
  workflow_name,
  alert_level,
  reason
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND alert_level IN ('WARNING', 'ERROR')
ORDER BY decision_time DESC
LIMIT 10
"

echo ""

# ============================================================================
# 4. WORKFLOW EXECUTIONS CHECK (NEW!)
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Workflow Executions (5 min after decisions)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "📊 Execution Summary:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  workflow_name,
  status,
  COUNT(*) as executions,
  ROUND(AVG(duration_seconds), 1) as avg_duration_sec,
  SUM(scrapers_triggered) as total_scrapers,
  SUM(scrapers_succeeded) as total_succeeded,
  SUM(scrapers_failed) as total_failed,
  ROUND(SUM(scrapers_succeeded) * 100.0 / NULLIF(SUM(scrapers_triggered), 0), 1) as success_rate_pct
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY workflow_name, status
ORDER BY workflow_name, status
"

echo ""
echo "⏱️  Recent Executions:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  FORMAT_TIMESTAMP('%H:%M:%S %Z', execution_time, 'America/New_York') as time_et,
  workflow_name,
  status,
  scrapers_triggered,
  scrapers_succeeded,
  scrapers_failed,
  ROUND(duration_seconds, 1) as duration_sec
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY execution_time DESC
LIMIT 10
"

echo ""

# ============================================================================
# 5. END-TO-END FLOW CHECK
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  End-to-End Flow: Decision → Execution → Scrapers"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "🔗 Decision-to-Execution Link:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  d.workflow_name,
  FORMAT_TIMESTAMP('%H:%M %Z', d.decision_time, 'America/New_York') as decision_time_et,
  d.action,
  FORMAT_TIMESTAMP('%H:%M %Z', e.execution_time, 'America/New_York') as execution_time_et,
  e.status as exec_status,
  e.scrapers_succeeded,
  e.scrapers_failed,
  TIMESTAMP_DIFF(e.execution_time, d.decision_time, SECOND) as delay_seconds
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
ORDER BY d.decision_time DESC
LIMIT 10
"

echo ""

# ============================================================================
# 6. SCRAPER EXECUTION LOG CHECK
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6️⃣  Scraper Execution Log (Individual Scraper Runs)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "📊 Scraper Summary (Controller-triggered only):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  scraper_name,
  COUNT(*) as total_runs,
  COUNTIF(status = 'SUCCESS') as successful,
  COUNTIF(status = 'FAILED') as failed,
  ROUND(COUNTIF(status = 'SUCCESS') * 100.0 / COUNT(*), 1) as success_rate_pct,
  ROUND(AVG(duration_seconds), 1) as avg_duration_sec
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND source = 'CONTROLLER'
GROUP BY scraper_name
ORDER BY total_runs DESC
LIMIT 20
"

echo ""

# ============================================================================
# 7. CLEANUP OPERATIONS CHECK
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "7️⃣  Cleanup Operations (Every 15 minutes)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as cleanup_runs,
  SUM(files_checked) as total_files_checked,
  SUM(missing_files_found) as total_missing,
  SUM(republished_count) as total_republished,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec,
  MAX(missing_files_found) as max_missing_in_run
FROM \`nba-props-platform.nba_orchestration.cleanup_operations\`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
"

echo ""
echo "⚠️  Recovery Events (if any):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  FORMAT_TIMESTAMP('%H:%M:%S %Z', cleanup_time, 'America/New_York') as time_et,
  files_checked,
  missing_files_found,
  republished_count
FROM \`nba-props-platform.nba_orchestration.cleanup_operations\`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND missing_files_found > 0
ORDER BY cleanup_time DESC
LIMIT 10
"

echo ""

# ============================================================================
# 8. CLOUD SCHEDULER STATUS
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "8️⃣  Cloud Scheduler Jobs Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
gcloud scheduler jobs list --location=us-west2 --format="table(
    name.basename(),
    schedule,
    state,
    lastAttemptTime.date('%Y-%m-%d %H:%M %Z'),
    httpTarget.uri.basename()
)"

echo ""

# ============================================================================
# 9. HEALTH SCORE
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "9️⃣  System Health Score"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""

# Check schedule generated today
SCHEDULE_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.daily_expected_schedule\`
WHERE date = CURRENT_DATE('America/New_York')
" | tail -n 1)

if [ "$SCHEDULE_COUNT" -gt 0 ]; then
    echo "✅ Schedule Generation: HEALTHY ($SCHEDULE_COUNT workflows scheduled)"
else
    echo "❌ Schedule Generation: FAILED (no schedule for today)"
fi

# Check recent decisions (last 2 hours)
RECENT_DECISIONS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
WHERE decision_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
" | tail -n 1)

if [ "$RECENT_DECISIONS" -gt 0 ]; then
    echo "✅ Master Controller: HEALTHY ($RECENT_DECISIONS decisions in last 2 hours)"
else
    echo "⚠️  Master Controller: NO RECENT ACTIVITY (check if it's game day)"
fi

# Check recent executions (last 2 hours)
RECENT_EXECUTIONS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE execution_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
" | tail -n 1)

if [ "$RECENT_EXECUTIONS" -gt 0 ]; then
    echo "✅ Workflow Executor: HEALTHY ($RECENT_EXECUTIONS executions in last 2 hours)"
else
    echo "⚠️  Workflow Executor: NO RECENT ACTIVITY (check if it's game day)"
fi

# Check cleanup running
RECENT_CLEANUP=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.cleanup_operations\`
WHERE cleanup_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
" | tail -n 1)

if [ "$RECENT_CLEANUP" -gt 0 ]; then
    echo "✅ Cleanup Processor: HEALTHY ($RECENT_CLEANUP runs in last 30 min)"
else
    echo "❌ Cleanup Processor: NOT RUNNING (no cleanup in last 30 min)"
fi

# Check execution success rate
EXEC_SUCCESS_RATE=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT ROUND(COUNTIF(status='completed') * 100.0 / COUNT(*), 1) as rate
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
" | tail -n 1)

if [ ! -z "$EXEC_SUCCESS_RATE" ] && [ "$EXEC_SUCCESS_RATE" != "" ]; then
    if (( $(echo "$EXEC_SUCCESS_RATE >= 80" | bc -l) )); then
        echo "✅ Execution Success Rate: HEALTHY ($EXEC_SUCCESS_RATE%)"
    else
        echo "⚠️  Execution Success Rate: DEGRADED ($EXEC_SUCCESS_RATE%)"
    fi
else
    echo "ℹ️  Execution Success Rate: NO DATA (no executions yet today)"
fi

echo ""

# ============================================================================
# 10. RECOMMENDATIONS
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Recommendations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""

# Check for missing executions (RUN decisions without executions)
MISSING_EXECUTIONS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
" | tail -n 1)

if [ "$MISSING_EXECUTIONS" -gt 0 ]; then
    echo "⚠️  Found $MISSING_EXECUTIONS RUN decision(s) without executions"
    echo "   → Check if execute-workflows scheduler job is running"
    echo "   → Check Cloud Run logs for errors"
else
    echo "✅ All RUN decisions have corresponding executions"
fi

# Check for high failure rate
FAILED_EXECUTIONS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND status = 'failed'
" | tail -n 1)

if [ "$FAILED_EXECUTIONS" -gt 2 ]; then
    echo "⚠️  High failure rate: $FAILED_EXECUTIONS failed execution(s)"
    echo "   → Investigate scraper issues"
    echo "   → Check parameter resolution"
else
    echo "✅ Low failure rate"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Verification Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "For detailed logs, run:"
echo "  gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers' --limit=50"
echo ""
