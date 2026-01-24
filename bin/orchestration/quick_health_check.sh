#!/bin/bash
set -euo pipefail
# quick_health_check.sh
# Fast health check for Phase 1 orchestration (30 seconds)
# Path: bin/orchestration/quick_health_check.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚡ Quick Health Check - Phase 1 Orchestration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# All-in-one query for speed
bq query --use_legacy_sql=false --format=pretty "
WITH 
schedule_check AS (
  SELECT COUNT(*) as scheduled_workflows
  FROM \`nba-props-platform.nba_orchestration.daily_expected_schedule\`
  WHERE date = CURRENT_DATE('America/New_York')
),
decisions_check AS (
  SELECT 
    COUNT(*) as total_decisions,
    COUNTIF(action = 'RUN') as run_decisions,
    COUNTIF(action = 'SKIP') as skip_decisions,
    COUNTIF(action = 'ABORT') as abort_decisions,
    MAX(decision_time) as last_decision
  FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
executions_check AS (
  SELECT 
    COUNT(*) as total_executions,
    COUNTIF(status = 'completed') as completed,
    COUNTIF(status = 'failed') as failed,
    SUM(scrapers_succeeded) as scrapers_succeeded,
    SUM(scrapers_failed) as scrapers_failed,
    MAX(execution_time) as last_execution
  FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
  WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
cleanup_check AS (
  SELECT 
    COUNT(*) as cleanup_runs,
    SUM(missing_files_found) as total_missing,
    MAX(cleanup_time) as last_cleanup
  FROM \`nba-props-platform.nba_orchestration.cleanup_operations\`
  WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
missing_executions AS (
  SELECT COUNT(*) as missing_count
  FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d
  LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e
    ON d.decision_id = e.decision_id
  WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND d.action = 'RUN'
    AND e.execution_id IS NULL
)

SELECT 
  -- Schedule
  s.scheduled_workflows,
  
  -- Decisions
  d.total_decisions,
  d.run_decisions,
  d.skip_decisions,
  d.abort_decisions,
  FORMAT_TIMESTAMP('%H:%M %Z', d.last_decision, 'America/New_York') as last_decision_et,
  
  -- Executions
  e.total_executions,
  e.completed as executions_completed,
  e.failed as executions_failed,
  ROUND(e.completed * 100.0 / NULLIF(e.total_executions, 0), 1) as execution_success_pct,
  e.scrapers_succeeded,
  e.scrapers_failed,
  ROUND(e.scrapers_succeeded * 100.0 / NULLIF(e.scrapers_succeeded + e.scrapers_failed, 0), 1) as scraper_success_pct,
  FORMAT_TIMESTAMP('%H:%M %Z', e.last_execution, 'America/New_York') as last_execution_et,
  
  -- Cleanup
  c.cleanup_runs,
  c.total_missing as missing_files_recovered,
  FORMAT_TIMESTAMP('%H:%M %Z', c.last_cleanup, 'America/New_York') as last_cleanup_et,
  
  -- Missing executions
  m.missing_count as run_decisions_not_executed,
  
  -- Health indicator
  CASE 
    WHEN s.scheduled_workflows > 0 
     AND e.total_executions > 0
     AND m.missing_count = 0
     AND (e.completed * 100.0 / NULLIF(e.total_executions, 0)) >= 80
    THEN '✅ HEALTHY'
    WHEN s.scheduled_workflows > 0 
     AND e.total_executions > 0
     AND (e.completed * 100.0 / NULLIF(e.total_executions, 0)) >= 50
    THEN '⚠️  DEGRADED'
    WHEN s.scheduled_workflows = 0 AND d.total_decisions = 0
    THEN 'ℹ️  NO GAMES TODAY'
    ELSE '❌ UNHEALTHY'
  END as health_status

FROM schedule_check s
CROSS JOIN decisions_check d
CROSS JOIN executions_check e
CROSS JOIN cleanup_check c
CROSS JOIN missing_executions m
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "For detailed verification, run:"
echo "  ./bin/orchestration/verify_phase1_complete.sh"
echo ""
