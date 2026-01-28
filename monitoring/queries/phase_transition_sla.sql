-- File: monitoring/queries/phase_transition_sla.sql
-- Description: Monitor phase transition timing and SLA compliance
-- Added: 2026-01-27 as part of data quality investigation fixes
--
-- Phase transition SLAs:
-- - Phase 3 to Phase 4: Should trigger within 15 minutes
-- - Phase 4 to Phase 5: Should complete within 30 minutes
--
-- Issues detected:
-- - Phase 4 not auto-triggering (trigger_source = 'manual' instead of 'orchestrator')
-- - Long delays between phase completions

-- Phase 3 to Phase 4 transition analysis
WITH phase_completions AS (
  SELECT
    data_date,
    phase,
    processor_name,
    trigger_source,
    started_at,
    completed_at,
    status,
    ROW_NUMBER() OVER (PARTITION BY data_date, phase ORDER BY completed_at DESC) as rn
  FROM `nba-props-platform.nba_orchestration.processor_run_history`
  WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
phase3_last AS (
  SELECT data_date, MAX(completed_at) as phase3_completed
  FROM phase_completions
  WHERE phase = 'phase_3_analytics' AND status = 'success'
  GROUP BY data_date
),
phase4_first AS (
  SELECT data_date, MIN(started_at) as phase4_started, ANY_VALUE(trigger_source) as trigger_source
  FROM phase_completions
  WHERE phase = 'phase_4_precompute'
  GROUP BY data_date
)
SELECT
  p3.data_date,
  p3.phase3_completed,
  p4.phase4_started,
  p4.trigger_source,
  TIMESTAMP_DIFF(p4.phase4_started, p3.phase3_completed, MINUTE) as transition_minutes,
  CASE
    WHEN p4.phase4_started IS NULL THEN 'PHASE_4_NOT_TRIGGERED'
    WHEN p4.trigger_source = 'manual' THEN 'MANUAL_TRIGGER (should be orchestrator)'
    WHEN TIMESTAMP_DIFF(p4.phase4_started, p3.phase3_completed, MINUTE) > 15 THEN 'SLA_BREACH (>15 min)'
    WHEN TIMESTAMP_DIFF(p4.phase4_started, p3.phase3_completed, MINUTE) > 5 THEN 'WARNING (>5 min)'
    ELSE 'OK'
  END as status
FROM phase3_last p3
LEFT JOIN phase4_first p4 ON p3.data_date = p4.data_date
ORDER BY p3.data_date DESC;

-- Trigger source distribution (should be mostly 'orchestrator')
SELECT
  data_date,
  trigger_source,
  COUNT(*) as run_count,
  ARRAY_AGG(DISTINCT processor_name) as processors
FROM `nba-props-platform.nba_orchestration.processor_run_history`
WHERE phase = 'phase_4_precompute'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY data_date, trigger_source
ORDER BY data_date DESC, trigger_source;

-- Overall phase completion timing by date
SELECT
  data_date,
  phase,
  MIN(started_at) as first_started,
  MAX(completed_at) as last_completed,
  TIMESTAMP_DIFF(MAX(completed_at), MIN(started_at), MINUTE) as phase_duration_minutes,
  COUNTIF(status = 'success') as successful_runs,
  COUNTIF(status = 'error') as failed_runs
FROM `nba-props-platform.nba_orchestration.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY data_date, phase
ORDER BY data_date DESC, phase;

-- SLA summary for alerting
SELECT
  'phase_transition_sla' as check_name,
  COUNTIF(
    p4.phase4_started IS NULL
    OR p4.trigger_source = 'manual'
    OR TIMESTAMP_DIFF(p4.phase4_started, p3.phase3_completed, MINUTE) > 15
  ) as violations,
  COUNT(*) as total_days,
  ROUND(COUNTIF(
    p4.phase4_started IS NOT NULL
    AND p4.trigger_source = 'orchestrator'
    AND TIMESTAMP_DIFF(p4.phase4_started, p3.phase3_completed, MINUTE) <= 15
  ) * 100.0 / COUNT(*), 2) as compliance_pct
FROM (
  SELECT data_date, MAX(completed_at) as phase3_completed
  FROM `nba-props-platform.nba_orchestration.processor_run_history`
  WHERE phase = 'phase_3_analytics' AND status = 'success'
    AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  GROUP BY data_date
) p3
LEFT JOIN (
  SELECT data_date, MIN(started_at) as phase4_started, ANY_VALUE(trigger_source) as trigger_source
  FROM `nba-props-platform.nba_orchestration.processor_run_history`
  WHERE phase = 'phase_4_precompute'
    AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  GROUP BY data_date
) p4 ON p3.data_date = p4.data_date;
