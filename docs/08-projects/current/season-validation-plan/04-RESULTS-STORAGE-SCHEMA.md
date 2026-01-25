# Results Storage Schema

## Overview

This document defines the BigQuery schema for storing validation results, enabling easy querying to identify what needs backfilling.

## Primary Tables

### 1. `nba_validation.season_validation_results`

Main table storing per-date, per-phase validation results.

```sql
CREATE TABLE IF NOT EXISTS `nba_validation.season_validation_results` (
  -- Identification
  validation_run_id STRING NOT NULL,       -- Unique ID for this validation run
  validation_timestamp TIMESTAMP NOT NULL,  -- When validation was run
  season_year INT64 NOT NULL,               -- NBA season year (e.g., 2024 for 2024-25)

  -- Date being validated
  game_date DATE NOT NULL,                  -- The date being validated
  has_games BOOL NOT NULL,                  -- Were there scheduled games?
  games_scheduled INT64,                    -- Number of games scheduled
  games_completed INT64,                    -- Number of games with Final status

  -- Phase-level status
  phase STRING NOT NULL,                    -- 'phase1', 'phase2', ..., 'phase6'
  phase_status STRING NOT NULL,             -- 'PASS', 'WARN', 'FAIL', 'SKIP', 'BOOTSTRAP'

  -- Table-level details (repeated for each table in phase)
  table_name STRING,                        -- e.g., 'nbac_gamebook_player_stats'
  record_count INT64,                       -- Actual records found
  expected_min INT64,                       -- Minimum expected records
  expected_max INT64,                       -- Maximum expected records

  -- Quality metrics (nullable, depends on table)
  production_ready_count INT64,
  production_ready_pct FLOAT64,
  avg_completeness_pct FLOAT64,
  gold_tier_count INT64,
  silver_tier_count INT64,
  bronze_tier_count INT64,
  quality_tier_distribution STRING,         -- JSON: {"gold": 50, "silver": 30, "bronze": 20}

  -- Cascade tracking
  is_cascade_affected BOOL DEFAULT FALSE,
  upstream_gap_dates ARRAY<DATE>,
  cascade_severity STRING,                  -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', NULL
  needs_rerun_after_upstream BOOL DEFAULT FALSE,
  days_since_upstream_gap INT64,            -- Days since nearest upstream gap

  -- Issue details
  issues_found ARRAY<STRING>,               -- List of specific issues
  remediation_commands ARRAY<STRING>,       -- Commands to fix issues

  -- Metadata
  validator_version STRING,                 -- Version of validator used
  execution_duration_seconds FLOAT64,       -- How long validation took
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY season_year, phase, phase_status;
```

### 2. `nba_validation.season_validation_summary`

Aggregated summary view for quick dashboarding.

```sql
CREATE OR REPLACE VIEW `nba_validation.season_validation_summary` AS
WITH latest_run AS (
  SELECT MAX(validation_run_id) as latest_run_id
  FROM `nba_validation.season_validation_results`
  WHERE season_year = 2024
)
SELECT
  r.season_year,
  r.phase,
  COUNT(DISTINCT r.game_date) as total_dates,
  COUNTIF(r.phase_status = 'PASS') as pass_count,
  COUNTIF(r.phase_status = 'WARN') as warn_count,
  COUNTIF(r.phase_status = 'FAIL') as fail_count,
  COUNTIF(r.phase_status = 'SKIP') as skip_count,
  COUNTIF(r.phase_status = 'BOOTSTRAP') as bootstrap_count,
  ROUND(COUNTIF(r.phase_status = 'PASS') / COUNT(*) * 100, 1) as pass_rate_pct,
  COUNTIF(r.is_cascade_affected) as cascade_affected_count,
  COUNTIF(r.needs_rerun_after_upstream) as needs_rerun_count
FROM `nba_validation.season_validation_results` r
JOIN latest_run l ON r.validation_run_id = l.latest_run_id
GROUP BY r.season_year, r.phase
ORDER BY r.phase;
```

### 3. `nba_validation.backfill_queue`

Priority-ordered queue of dates needing backfill.

```sql
CREATE TABLE IF NOT EXISTS `nba_validation.backfill_queue` (
  -- Identification
  queue_id STRING NOT NULL,                 -- Unique ID
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  validation_run_id STRING NOT NULL,        -- Source validation run

  -- Date info
  game_date DATE NOT NULL,
  season_year INT64 NOT NULL,

  -- What needs fixing
  phase_to_fix STRING NOT NULL,             -- Earliest phase needing fix
  all_phases_to_rerun ARRAY<STRING>,        -- All phases needing rerun

  -- Priority calculation
  priority_score FLOAT64 NOT NULL,          -- 0-1, higher = more urgent
  priority_tier STRING NOT NULL,            -- 'P0', 'P1', 'P2', 'P3'

  -- Priority factors
  recency_days INT64,                       -- Days from today
  is_direct_gap BOOL,                       -- vs cascade-affected
  cascade_impact_count INT64,               -- How many downstream dates affected
  cascade_severity STRING,                  -- Severity if gap not fixed

  -- Execution tracking
  backfill_status STRING DEFAULT 'PENDING', -- 'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'
  backfill_started_at TIMESTAMP,
  backfill_completed_at TIMESTAMP,
  backfill_error STRING,

  -- Remediation
  remediation_commands ARRAY<STRING>
)
PARTITION BY game_date
CLUSTER BY priority_tier, backfill_status;
```

### 4. `nba_validation.cascade_impact_map`

Tracks which dates are affected by which upstream gaps.

```sql
CREATE TABLE IF NOT EXISTS `nba_validation.cascade_impact_map` (
  -- Identification
  validation_run_id STRING NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

  -- The gap
  gap_date DATE NOT NULL,
  gap_phase STRING NOT NULL,

  -- Affected downstream
  affected_date DATE NOT NULL,
  affected_phase STRING NOT NULL,
  days_downstream INT64,                    -- Days between gap and affected
  games_downstream INT64,                   -- Games between gap and affected

  -- Impact details
  impact_window STRING,                     -- 'L5', 'L10', 'L14d', 'L20'
  impact_severity STRING,                   -- 'HIGH', 'MEDIUM', 'LOW'

  -- Resolution tracking
  is_resolved BOOL DEFAULT FALSE,
  resolved_at TIMESTAMP,
  resolved_by_backfill_id STRING
)
PARTITION BY gap_date
CLUSTER BY gap_phase, affected_date;
```

## Derived Views

### View: Dates Needing Backfill

```sql
CREATE OR REPLACE VIEW `nba_validation.v_dates_needing_backfill` AS
SELECT
  game_date,
  ARRAY_AGG(DISTINCT phase ORDER BY phase) as failing_phases,
  MAX(CASE
    WHEN phase = 'phase2' THEN 1
    WHEN phase = 'phase3' THEN 2
    WHEN phase = 'phase4' THEN 3
    WHEN phase = 'phase5' THEN 4
    WHEN phase = 'phase6' THEN 5
    ELSE 6
  END) as earliest_failing_phase_num,
  ARRAY_AGG(DISTINCT i ORDER BY i) as all_issues,
  BOOL_OR(is_cascade_affected) as has_cascade_impact
FROM `nba_validation.season_validation_results`,
UNNEST(issues_found) as i
WHERE phase_status IN ('FAIL', 'WARN')
  AND validation_run_id = (
    SELECT MAX(validation_run_id)
    FROM `nba_validation.season_validation_results`
  )
GROUP BY game_date
ORDER BY game_date;
```

### View: Cascade Contamination Summary

```sql
CREATE OR REPLACE VIEW `nba_validation.v_cascade_contamination` AS
SELECT
  affected_date,
  COUNT(DISTINCT gap_date) as upstream_gaps_count,
  ARRAY_AGG(DISTINCT gap_date ORDER BY gap_date) as upstream_gap_dates,
  ARRAY_AGG(DISTINCT gap_phase ORDER BY gap_phase) as upstream_gap_phases,
  MAX(impact_severity) as max_severity,
  CASE
    WHEN COUNT(DISTINCT gap_date) >= 3 THEN 'CRITICAL'
    WHEN COUNT(DISTINCT gap_date) >= 2 THEN 'HIGH'
    WHEN MAX(impact_severity) = 'HIGH' THEN 'HIGH'
    ELSE 'MEDIUM'
  END as contamination_level
FROM `nba_validation.cascade_impact_map`
WHERE is_resolved = FALSE
GROUP BY affected_date
ORDER BY affected_date;
```

### View: Backfill Progress Dashboard

```sql
CREATE OR REPLACE VIEW `nba_validation.v_backfill_progress` AS
SELECT
  priority_tier,
  backfill_status,
  COUNT(*) as date_count,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  ARRAY_AGG(DISTINCT phase_to_fix ORDER BY phase_to_fix) as phases
FROM `nba_validation.backfill_queue`
WHERE queue_id = (
  SELECT MAX(queue_id) FROM `nba_validation.backfill_queue`
)
GROUP BY priority_tier, backfill_status
ORDER BY priority_tier, backfill_status;
```

## Query Examples

### 1. Find All Dates That Need Backfill

```sql
SELECT
  game_date,
  failing_phases,
  all_issues,
  has_cascade_impact
FROM `nba_validation.v_dates_needing_backfill`
ORDER BY game_date;
```

### 2. Get Backfill Commands for a Date

```sql
SELECT
  game_date,
  phase_to_fix,
  remediation_commands
FROM `nba_validation.backfill_queue`
WHERE game_date = '2025-01-15'
  AND backfill_status = 'PENDING';
```

### 3. Check Season Health Summary

```sql
SELECT * FROM `nba_validation.season_validation_summary`;
```

### 4. Find Cascade-Affected Dates for a Gap

```sql
SELECT
  affected_date,
  affected_phase,
  days_downstream,
  impact_severity
FROM `nba_validation.cascade_impact_map`
WHERE gap_date = '2025-01-15'
  AND is_resolved = FALSE
ORDER BY affected_date, affected_phase;
```

### 5. Get Priority Backfill Queue

```sql
SELECT
  game_date,
  phase_to_fix,
  priority_tier,
  priority_score,
  cascade_impact_count,
  remediation_commands[SAFE_OFFSET(0)] as first_command
FROM `nba_validation.backfill_queue`
WHERE backfill_status = 'PENDING'
ORDER BY priority_score DESC
LIMIT 20;
```

### 6. Track Backfill Progress

```sql
SELECT
  DATE(backfill_started_at) as backfill_date,
  backfill_status,
  COUNT(*) as dates_processed,
  COUNTIF(backfill_status = 'COMPLETED') as successful,
  COUNTIF(backfill_status = 'FAILED') as failed
FROM `nba_validation.backfill_queue`
WHERE backfill_started_at IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC;
```

## Populating the Tables

### Initial Population Query

```sql
-- Populate season_validation_results for Phase 2
INSERT INTO `nba_validation.season_validation_results`
WITH schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_scheduled,
    COUNTIF(game_status = 'Final') as games_completed
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
  GROUP BY game_date
),
phase2_counts AS (
  SELECT
    game_date,
    'nbac_gamebook_player_stats' as table_name,
    COUNT(*) as record_count
  FROM `nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
  GROUP BY game_date
)
SELECT
  GENERATE_UUID() as validation_run_id,
  CURRENT_TIMESTAMP() as validation_timestamp,
  2024 as season_year,
  s.game_date,
  s.games_scheduled > 0 as has_games,
  s.games_scheduled,
  s.games_completed,
  'phase2' as phase,
  CASE
    WHEN COALESCE(p.record_count, 0) = 0 THEN 'FAIL'
    WHEN COALESCE(p.record_count, 0) < s.games_scheduled * 20 THEN 'WARN'
    ELSE 'PASS'
  END as phase_status,
  p.table_name,
  COALESCE(p.record_count, 0) as record_count,
  s.games_scheduled * 20 as expected_min,
  s.games_scheduled * 30 as expected_max,
  -- Quality metrics (null for phase 2)
  NULL as production_ready_count,
  NULL as production_ready_pct,
  NULL as avg_completeness_pct,
  NULL as gold_tier_count,
  NULL as silver_tier_count,
  NULL as bronze_tier_count,
  NULL as quality_tier_distribution,
  -- Cascade (to be calculated separately)
  FALSE as is_cascade_affected,
  [] as upstream_gap_dates,
  NULL as cascade_severity,
  FALSE as needs_rerun_after_upstream,
  NULL as days_since_upstream_gap,
  -- Issues
  CASE
    WHEN COALESCE(p.record_count, 0) = 0 THEN ['MISSING_DATA']
    WHEN COALESCE(p.record_count, 0) < s.games_scheduled * 20 THEN ['LOW_RECORD_COUNT']
    ELSE []
  END as issues_found,
  CASE
    WHEN COALESCE(p.record_count, 0) = 0 THEN [
      CONCAT('python bin/backfill/bdl_boxscores.py --date ', CAST(s.game_date AS STRING))
    ]
    ELSE []
  END as remediation_commands,
  'v1.0' as validator_version,
  0.0 as execution_duration_seconds
FROM schedule s
LEFT JOIN phase2_counts p USING (game_date)
WHERE s.game_date BETWEEN '2024-10-22' AND CURRENT_DATE();
```

## Table Maintenance

### Retention Policy

```sql
-- Keep only last 5 validation runs per season
DELETE FROM `nba_validation.season_validation_results`
WHERE validation_run_id NOT IN (
  SELECT validation_run_id
  FROM (
    SELECT
      validation_run_id,
      ROW_NUMBER() OVER (PARTITION BY season_year ORDER BY validation_timestamp DESC) as rn
    FROM `nba_validation.season_validation_results`
  )
  WHERE rn <= 5
);
```

### Update Backfill Status

```sql
-- Mark dates as completed after backfill
UPDATE `nba_validation.backfill_queue`
SET
  backfill_status = 'COMPLETED',
  backfill_completed_at = CURRENT_TIMESTAMP()
WHERE game_date = @completed_date
  AND backfill_status = 'IN_PROGRESS';
```

## Dashboard Integration

These tables support dashboard queries for:

1. **Season Health Overview** - Overall pass/fail rates by phase
2. **Gap Timeline** - Visual timeline of gaps and cascade impact
3. **Backfill Progress** - Tracking resolution of identified issues
4. **Quality Trends** - How quality metrics change over time
5. **Priority Queue** - What to fix next
