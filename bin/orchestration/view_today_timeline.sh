#!/bin/bash
# view_today_timeline.sh
# Shows complete timeline of today's orchestration activities
# Path: bin/orchestration/view_today_timeline.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📅 Today's Orchestration Timeline"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

bq query --use_legacy_sql=false --format=pretty "
WITH timeline AS (
  -- Schedule generation (5 AM)
  SELECT 
    locked_at as event_time,
    'SCHEDULE' as event_type,
    CAST(COUNT(*) AS STRING) || ' workflows scheduled' as description,
    NULL as workflow_name,
    NULL as status
  FROM \`nba-props-platform.nba_orchestration.daily_expected_schedule\`
  WHERE date = CURRENT_DATE('America/New_York')
  GROUP BY locked_at
  
  UNION ALL
  
  -- Workflow decisions (hourly)
  SELECT 
    decision_time as event_time,
    'DECISION' as event_type,
    workflow_name || ': ' || action as description,
    workflow_name,
    action as status
  FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  
  UNION ALL
  
  -- Workflow executions (5 min after decisions)
  SELECT 
    execution_time as event_time,
    'EXECUTION' as event_type,
    workflow_name || ': ' || status || ' (' || 
    CAST(scrapers_succeeded AS STRING) || '/' || 
    CAST(scrapers_triggered AS STRING) || ' scrapers)' as description,
    workflow_name,
    status
  FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
  WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
)

SELECT 
  FORMAT_TIMESTAMP('%H:%M:%S %Z', event_time, 'America/New_York') as time_et,
  event_type,
  workflow_name,
  description,
  status
FROM timeline
ORDER BY event_time DESC
LIMIT 100
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Hourly Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

bq query --use_legacy_sql=false --format=pretty "
WITH hourly_activity AS (
  SELECT 
    EXTRACT(HOUR FROM decision_time AT TIME ZONE 'America/New_York') as hour_et,
    'decision' as activity_type,
    COUNT(*) as count
  FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  GROUP BY hour_et
  
  UNION ALL
  
  SELECT 
    EXTRACT(HOUR FROM execution_time AT TIME ZONE 'America/New_York') as hour_et,
    'execution' as activity_type,
    COUNT(*) as count
  FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
  WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  GROUP BY hour_et
)

SELECT 
  hour_et,
  COUNTIF(activity_type = 'decision') as decisions,
  COUNTIF(activity_type = 'execution') as executions,
  CASE 
    WHEN COUNTIF(activity_type = 'decision') > 0 
     AND COUNTIF(activity_type = 'execution') = 0 
    THEN '⚠️  Missing executions'
    WHEN COUNTIF(activity_type = 'decision') > 0 
     AND COUNTIF(activity_type = 'execution') > 0
    THEN '✅ Complete'
    WHEN COUNTIF(activity_type = 'decision') = 0
    THEN 'ℹ️  No activity'
    ELSE '❓ Check status'
  END as status
FROM hourly_activity
GROUP BY hour_et
ORDER BY hour_et DESC
"

echo ""
