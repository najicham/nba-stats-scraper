SELECT 
  execution_id,
  workflow_name,
  status,
  scrapers_requested,
  scrapers_triggered,
  scrapers_succeeded,
  scrapers_failed,
  TIMESTAMP(execution_time) as execution_time
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE workflow_name = 'morning_operations'
  AND DATE(execution_time) = CURRENT_DATE()
ORDER BY execution_time DESC
LIMIT 5;
