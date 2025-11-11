-- File: schemas/bigquery/nba_orchestration/daily_expected_schedule.sql
-- ============================================================================
-- NBA Props Platform - Phase 1 Orchestration: Daily Expected Schedule
-- ============================================================================
-- Purpose: Daily expected workflow schedule locked at day start for monitoring
-- Update: Once daily at 5 AM ET (day start)
-- Entities: All workflows expected to run today
-- Retention: 90 days (partition expiration)
--
-- Version: 1.0
-- Date: November 10, 2025
-- Status: Production-Ready
--
-- Key Concept:
--   At 5 AM ET each day, the controller generates the expected schedule
--   for that day based on: games scheduled, workflow configs, and discovery
--   mode rules. This "locked" schedule is then used throughout the day to
--   compare expected vs actual executions in Grafana dashboards.
--
-- Use Cases:
--   - Grafana monitoring (expected vs actual comparison)
--   - Alert on missed critical workflows
--   - Performance tracking (on-time execution percentage)
--   - Schedule optimization analysis
--
-- Dependencies:
--   - nba_raw.nbac_schedule (to know games today)
--   - config/workflows.yaml (workflow definitions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.daily_expected_schedule` (
  -- ==========================================================================
  -- DATE IDENTIFIERS (2 fields)
  -- ==========================================================================
  
  date DATE NOT NULL,
    -- Schedule date in Eastern Time (YYYY-MM-DD)
    -- Partition key (daily partitions)
    -- Example: "2025-01-15"
    -- Used for: Grouping by date, partition filtering
    -- Always filter on this field for efficient queries
  
  locked_at TIMESTAMP NOT NULL,
    -- When this schedule was generated in UTC
    -- Typically 5 AM ET = 9-10 AM UTC (depending on DST)
    -- Example: "2025-01-15T10:00:00Z" (5 AM ET during EST)
    -- Used for: Audit trail, schedule version tracking
    -- Once locked, this schedule doesn't change for the day
  
  -- ==========================================================================
  -- WORKFLOW IDENTIFICATION (1 field)
  -- ==========================================================================
  
  workflow_name STRING NOT NULL,
    -- Workflow expected to run
    -- Examples:
    --   'betting_lines' (pre-game odds)
    --   'injury_discovery' (find injury report)
    --   'morning_operations' (daily foundation data)
    --   'post_game_window_1' (first post-game collection)
    -- Used for: Matching with actual executions
  
  -- ==========================================================================
  -- EXPECTED EXECUTION (2 fields)
  -- ==========================================================================
  
  expected_run_time TIMESTAMP NOT NULL,
    -- When workflow should execute in UTC
    -- Converted from ET to UTC for consistency
    -- Examples:
    --   "2025-01-15T11:00:00Z" (6 AM ET - morning operations)
    --   "2025-01-15T16:00:00Z" (11 AM ET - betting lines window start)
    --   "2025-01-16T02:30:00Z" (9:30 PM ET prev day - post-game window 1)
    -- Used for: Expected vs actual comparison, lateness detection
  
  reason STRING,
    -- Why this execution is expected
    -- Examples:
    --   'Daily foundation data collection'
    --   'Pre-game betting lines (5 games scheduled)'
    --   'Discovery attempt 1/12 (injury report)'
    --   'Post-game collection (8 games scheduled)'
    -- Helps understand the context in Grafana dashboards
    -- Used for: Dashboard labels, debugging schedule logic
  
  -- ==========================================================================
  -- WORKFLOW COMPOSITION (1 field)
  -- ==========================================================================
  
  scrapers ARRAY<STRING>,
    -- List of scrapers expected to run in this workflow execution
    -- Examples:
    --   ['nbac_schedule_api', 'nbac_player_list'] (morning_operations)
    --   ['nbac_injury_report'] (injury_discovery)
    --   ['oddsa_events', 'oddsa_player_props'] (betting_lines)
    -- Used for: Understanding workflow scope, debugging
  
  -- ==========================================================================
  -- GAME CONTEXT (1 field)
  -- ==========================================================================
  
  games_today INT64,
    -- Number of games scheduled for this date
    -- Range: 0-15 (typical NBA day)
    -- Special values:
    --   0 = Offseason or no games
    --   1-3 = Light day
    --   8-12 = Typical game day
    --   13-15 = Heavy game day
    -- NULL for: Workflows not dependent on game count
    -- Used for: Context in dashboards, understanding workflow triggers
  
  -- ==========================================================================
  -- PRIORITY (1 field)
  -- ==========================================================================
  
  priority STRING,
    -- Workflow priority level
    -- Values:
    --   'CRITICAL' = Must execute (foundation data, betting lines)
    --   'HIGH' = Important (injury reports, odds updates)
    --   'MEDIUM' = Normal operations (backfills, analytics)
    --   'LOW' = Nice to have (reference data)
    -- Used for: Alert severity, dashboard filtering
  
  -- ==========================================================================
  -- VERSION TRACKING (2 fields)
  -- ==========================================================================
  
  schedule_version STRING,
    -- Config version used to generate schedule
    -- Format: "v1.2.3" or config file hash
    -- Example: "v1.0.0", "abc123def"
    -- Used for: Tracking config changes over time
    -- Helps explain schedule variations after config updates
  
  generated_by STRING,
    -- Controller instance that generated schedule
    -- Examples:
    --   'nba-scrapers-prod' (production controller)
    --   'local-test' (development)
    -- Used for: Debugging, identifying test vs production schedules
  
  -- ==========================================================================
  -- ENVIRONMENT (1 field)
  -- ==========================================================================
  
  environment STRING,
    -- Environment where schedule was generated
    -- Values: 'prod', 'dev'
    -- Used for: Filtering production schedules only
  
  -- ==========================================================================
  -- METADATA (1 field)
  -- ==========================================================================
  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- Row creation timestamp (auto-populated by BigQuery)
    -- Used for: Audit trail, data freshness checks

)
PARTITION BY date
CLUSTER BY workflow_name, expected_run_time
OPTIONS(
  description = "Daily expected workflow schedule locked at 5 AM ET for monitoring. Used for expected vs actual comparison in Grafana dashboards. Generated once per day and never modified. Partition key: date. Cluster by: workflow_name, expected_run_time. CRITICAL TABLE for Phase 1 orchestration monitoring.",
  partition_expiration_days = 90
);

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 12
--   - Date identifiers: 2 (date, locked_at)
--   - Workflow: 1 (workflow_name)
--   - Expected execution: 2 (expected_run_time, reason)
--   - Composition: 1 (scrapers array)
--   - Game context: 1 (games_today)
--   - Priority: 1 (priority)
--   - Version tracking: 2 (schedule_version, generated_by)
--   - Environment: 1 (environment)
--   - Metadata: 1 (created_at)
-- ============================================================================

-- ============================================================================
-- SAMPLE ROW (Morning Operations - Game Day)
-- ============================================================================
/*
{
  "date": "2025-01-15",
  "locked_at": "2025-01-15T10:00:00Z",
  "workflow_name": "morning_operations",
  "expected_run_time": "2025-01-15T11:00:00Z",
  "reason": "Daily foundation data collection",
  "scrapers": ["nbac_schedule_api", "nbac_player_list"],
  "games_today": 8,
  "priority": "CRITICAL",
  "schedule_version": "v1.0.0",
  "generated_by": "nba-scrapers-prod",
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Betting Lines - Pre-Game Window)
-- ============================================================================
/*
{
  "date": "2025-01-15",
  "locked_at": "2025-01-15T10:00:00Z",
  "workflow_name": "betting_lines",
  "expected_run_time": "2025-01-15T16:00:00Z",
  "reason": "Pre-game betting lines (8 games, first tip: 19:30 ET)",
  "scrapers": ["oddsa_events", "oddsa_player_props"],
  "games_today": 8,
  "priority": "CRITICAL",
  "schedule_version": "v1.0.0",
  "generated_by": "nba-scrapers-prod",
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Injury Discovery - First Attempt)
-- ============================================================================
/*
{
  "date": "2025-01-15",
  "locked_at": "2025-01-15T10:00:00Z",
  "workflow_name": "injury_discovery",
  "expected_run_time": "2025-01-15T16:00:00Z",
  "reason": "Discovery attempt 1/12 (injury report typically published 11 AM - 3 PM ET)",
  "scrapers": ["nbac_injury_report"],
  "games_today": 8,
  "priority": "MEDIUM",
  "schedule_version": "v1.0.0",
  "generated_by": "nba-scrapers-prod",
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Post-Game Collection)
-- ============================================================================
/*
{
  "date": "2025-01-15",
  "locked_at": "2025-01-15T10:00:00Z",
  "workflow_name": "post_game_window_1",
  "expected_run_time": "2025-01-16T02:30:00Z",
  "reason": "Post-game collection window 1 (8 games scheduled, last game ends ~2 AM ET)",
  "scrapers": ["nbac_player_boxscore", "nbac_team_boxscore", "nbac_play_by_play"],
  "games_today": 8,
  "priority": "HIGH",
  "schedule_version": "v1.0.0",
  "generated_by": "nba-scrapers-prod",
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (Discovery Attempts - Multiple Expected)
-- ============================================================================
/*
-- Note: Discovery workflows generate multiple expected runs
-- Injury Discovery: Attempts at 11 AM, 12 PM, 1 PM, 2 PM, 3 PM ET (up to 12 total)

{
  "date": "2025-01-15",
  "locked_at": "2025-01-15T10:00:00Z",
  "workflow_name": "injury_discovery",
  "expected_run_time": "2025-01-15T17:00:00Z",
  "reason": "Discovery attempt 2/12",
  "scrapers": ["nbac_injury_report"],
  "games_today": 8,
  "priority": "MEDIUM",
  "schedule_version": "v1.0.0",
  "generated_by": "nba-scrapers-prod",
  "environment": "prod"
}
*/

-- ============================================================================
-- SAMPLE ROW (No Games Today - Minimal Schedule)
-- ============================================================================
/*
{
  "date": "2025-07-15",
  "locked_at": "2025-07-15T09:00:00Z",
  "workflow_name": "morning_operations",
  "expected_run_time": "2025-07-15T11:00:00Z",
  "reason": "Offseason foundation data update",
  "scrapers": ["nbac_schedule_api"],
  "games_today": 0,
  "priority": "MEDIUM",
  "schedule_version": "v1.0.0",
  "generated_by": "nba-scrapers-prod",
  "environment": "prod"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Today's expected schedule
-- Purpose: Quick view of what should happen today
-- Expected: All workflows listed with execution times
-- SELECT 
--   workflow_name,
--   FORMAT_TIMESTAMP('%H:%M', expected_run_time, 'America/New_York') as time_et,
--   reason,
--   priority,
--   ARRAY_LENGTH(scrapers) as scraper_count,
--   games_today
-- FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
-- WHERE date = CURRENT_DATE('America/New_York')
-- ORDER BY expected_run_time;

-- -- Query 2: Expected vs actual comparison
-- -- Purpose: Core monitoring query for Grafana
-- -- Expected: All expected workflows executed on time
-- WITH expected AS (
--   SELECT 
--     workflow_name,
--     expected_run_time,
--     reason as expected_reason,
--     priority
--   FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
--   WHERE date = CURRENT_DATE('America/New_York')
-- ),
-- actual AS (
--   SELECT 
--     workflow_name,
--     decision_time as actual_run_time,
--     action,
--     reason as actual_reason
--   FROM `nba-props-platform.nba_orchestration.workflow_decisions`
--   WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
--     AND action = 'RUN'
-- )
-- SELECT 
--   expected.workflow_name,
--   expected.priority,
--   FORMAT_TIMESTAMP('%H:%M', expected.expected_run_time, 'America/New_York') as expected_time_et,
--   FORMAT_TIMESTAMP('%H:%M', actual.actual_run_time, 'America/New_York') as actual_time_et,
--   CASE 
--     WHEN actual.workflow_name IS NULL THEN '🔴 MISSING'
--     WHEN TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE) > 30 THEN '🟡 LATE'
--     WHEN TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE) < -30 THEN '🟠 EARLY'
--     ELSE '✅ ON TIME'
--   END as status,
--   TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE) as minutes_diff,
--   expected.expected_reason,
--   actual.actual_reason
-- FROM expected
-- LEFT JOIN actual 
--   ON expected.workflow_name = actual.workflow_name
--   AND ABS(TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE)) < 120
-- ORDER BY expected.expected_run_time;

-- -- Query 3: Workflow execution rate (last 7 days)
-- -- Purpose: Track reliability of workflow execution
-- -- Expected: >95% on-time execution for CRITICAL workflows
-- WITH expected AS (
--   SELECT 
--     workflow_name,
--     priority,
--     date,
--     COUNT(*) as expected_count
--   FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
--   WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   GROUP BY workflow_name, priority, date
-- ),
-- actual AS (
--   SELECT 
--     workflow_name,
--     DATE(decision_time, 'America/New_York') as date,
--     COUNT(*) as actual_count
--   FROM `nba-props-platform.nba_orchestration.workflow_decisions`
--   WHERE DATE(decision_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--     AND action = 'RUN'
--   GROUP BY workflow_name, date
-- )
-- SELECT 
--   expected.workflow_name,
--   expected.priority,
--   SUM(expected.expected_count) as total_expected,
--   SUM(COALESCE(actual.actual_count, 0)) as total_actual,
--   ROUND(SUM(COALESCE(actual.actual_count, 0)) * 100.0 / SUM(expected.expected_count), 1) as execution_rate_pct
-- FROM expected
-- LEFT JOIN actual 
--   ON expected.workflow_name = actual.workflow_name
--   AND expected.date = actual.date
-- GROUP BY expected.workflow_name, expected.priority
-- ORDER BY expected.priority, execution_rate_pct ASC;

-- -- Query 4: Games per day schedule pattern
-- -- Purpose: Understand how schedule varies by game count
-- -- Expected: More workflows on heavy game days
-- SELECT 
--   date,
--   games_today,
--   COUNT(DISTINCT workflow_name) as workflows_scheduled,
--   COUNT(*) as total_expected_runs,
--   STRING_AGG(DISTINCT workflow_name ORDER BY workflow_name) as workflows
-- FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
-- WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
-- GROUP BY date, games_today
-- ORDER BY date DESC;

-- -- Query 5: Discovery mode expected attempts
-- -- Purpose: Verify discovery workflows have correct attempt count
-- -- Expected: Up to 12 attempts for injury_discovery
-- SELECT 
--   workflow_name,
--   date,
--   COUNT(*) as expected_attempts,
--   MIN(expected_run_time) as first_attempt,
--   MAX(expected_run_time) as last_attempt,
--   TIMESTAMP_DIFF(MAX(expected_run_time), MIN(expected_run_time), HOUR) as hour_span
-- FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
-- WHERE date = CURRENT_DATE('America/New_York')
--   AND workflow_name LIKE '%discovery%'
-- GROUP BY workflow_name, date;

-- -- Query 6: Config version tracking
-- -- Purpose: Track when schedule logic changes
-- -- Expected: Version changes correlate with behavior changes
-- SELECT 
--   schedule_version,
--   MIN(date) as first_used,
--   MAX(date) as last_used,
--   COUNT(DISTINCT date) as days_used,
--   COUNT(*) as total_schedule_entries
-- FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
-- WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY schedule_version
-- ORDER BY first_used DESC;

-- -- ============================================================================
-- -- MONITORING QUERIES
-- -- ============================================================================

-- -- Alert: Critical workflow missing from today's schedule
-- -- Threshold: CRITICAL workflows must be in schedule every day
-- SELECT 
--   'daily_expected_schedule' as alert_source,
--   'Missing critical workflows' as alert_type,
--   CURRENT_DATE() as date,
--   'No critical workflows scheduled' as details
-- WHERE NOT EXISTS (
--   SELECT 1
--   FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
--   WHERE date = CURRENT_DATE()
--     AND priority = 'CRITICAL'
-- );

-- -- Alert: Schedule not generated today
-- -- Threshold: Schedule should be generated by 6 AM ET
-- SELECT 
--   'daily_expected_schedule' as alert_source,
--   'Schedule not generated' as alert_type,
--   CURRENT_DATE() as date,
--   'Schedule should be locked by 6 AM ET' as details
-- WHERE NOT EXISTS (
--   SELECT 1
--   FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
--   WHERE date = CURRENT_DATE()
-- )
-- AND CURRENT_TIMESTAMP() > TIMESTAMP(CURRENT_DATE(), 'America/New_York') + INTERVAL 6 HOUR;

-- -- Alert: Execution rate below threshold
-- -- Threshold: <90% execution rate for HIGH/CRITICAL workflows
-- WITH rates AS (
--   SELECT 
--     e.workflow_name,
--     e.priority,
--     COUNT(DISTINCT e.date) as expected_days,
--     COUNT(DISTINCT a.date) as actual_days,
--     ROUND(COUNT(DISTINCT a.date) * 100.0 / COUNT(DISTINCT e.date), 1) as execution_rate_pct
--   FROM `nba-props-platform.nba_orchestration.daily_expected_schedule` e
--   LEFT JOIN (
--     SELECT 
--       workflow_name,
--       DATE(decision_time, 'America/New_York') as date
--     FROM `nba-props-platform.nba_orchestration.workflow_decisions`
--     WHERE action = 'RUN'
--   ) a ON e.workflow_name = a.workflow_name AND e.date = a.date
--   WHERE e.date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--     AND e.priority IN ('CRITICAL', 'HIGH')
--   GROUP BY e.workflow_name, e.priority
-- )
-- SELECT 
--   'daily_expected_schedule' as alert_source,
--   workflow_name,
--   priority,
--   execution_rate_pct,
--   expected_days,
--   actual_days
-- FROM rates
-- WHERE execution_rate_pct < 90.0;

-- -- ============================================================================
-- -- HELPER VIEWS
-- -- ============================================================================

-- -- View: Today's schedule with status
-- CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_todays_schedule_status` AS
-- WITH expected AS (
--   SELECT 
--     workflow_name,
--     expected_run_time,
--     reason,
--     priority,
--     scrapers,
--     games_today
--   FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
--   WHERE date = CURRENT_DATE('America/New_York')
-- ),
-- actual AS (
--   SELECT 
--     workflow_name,
--     decision_time as actual_run_time,
--     action
--   FROM `nba-props-platform.nba_orchestration.workflow_decisions`
--   WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
-- )
-- SELECT 
--   expected.workflow_name,
--   expected.priority,
--   expected.expected_run_time,
--   expected.reason,
--   expected.scrapers,
--   expected.games_today,
--   actual.actual_run_time,
--   actual.action,
--   CASE 
--     WHEN actual.workflow_name IS NULL AND expected.expected_run_time > CURRENT_TIMESTAMP() THEN 'PENDING'
--     WHEN actual.workflow_name IS NULL THEN 'MISSING'
--     WHEN actual.action = 'RUN' AND TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE) <= 30 THEN 'ON_TIME'
--     WHEN actual.action = 'RUN' THEN 'LATE'
--     WHEN actual.action = 'SKIP' THEN 'SKIPPED'
--     ELSE 'UNKNOWN'
--   END as status
-- FROM expected
-- LEFT JOIN actual ON expected.workflow_name = actual.workflow_name
-- ORDER BY expected.expected_run_time;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_orchestration dataset
-- [ ] Verify partitioning (daily on date)
-- [ ] Verify clustering (workflow_name, expected_run_time)
-- [ ] Implement schedule generation logic in controller
-- [ ] Test schedule generation with sample config
-- [ ] Verify schedule locks at 5 AM ET
-- [ ] Test expected vs actual query
-- [ ] Enable monitoring queries
-- [ ] Configure Grafana dashboards
-- [ ] Document schedule generation rules
-- ============================================================================
