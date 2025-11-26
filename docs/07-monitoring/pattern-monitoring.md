# Pattern Efficiency Monitoring - Smart Idempotency & Reprocessing

**File:** `docs/monitoring/08-pattern-efficiency-monitoring.md`
**Created:** 2025-11-21
**Purpose:** Monitor the 4 processing optimization patterns (skip rates, cost savings, data quality)
**Status:** Production Ready
**For:** Grafana dashboards with BigQuery data source

---

## Overview

Monitor the efficiency of our 4 processing patterns:
1. **Smart Idempotency** (Phase 2) - Skip BigQuery writes when data unchanged
2. **Dependency Tracking** (Phase 3) - Validate upstream data availability
3. **Smart Reprocessing** (Phase 3) - Skip processing when Phase 2 unchanged
4. **Backfill Detection** (Phase 3) - Find historical data gaps

**Expected Impact:**
- Phase 2: ~50% write reduction
- Phase 3: ~30-50% processing reduction
- Total: 30-50% cost savings across pipeline

---

## Quick Dashboard Overview

**Recommended Grafana Dashboard Panels:**

| Panel | Metric | Query | Alert Threshold |
|-------|--------|-------|-----------------|
| Phase 2 Skip Rate | % writes skipped | `pattern_1_phase2_skip_rate` | < 30% (low efficiency) |
| Phase 3 Skip Rate | % processing skipped | `pattern_3_phase3_skip_rate` | < 20% (low efficiency) |
| Dependency Failures | Count of missing deps | `pattern_2_dependency_failures` | > 0 (critical) |
| Backfill Candidates | Games needing processing | `pattern_4_backfill_candidates` | > 100 (investigate) |
| Cost Savings | % compute reduction | `cost_savings_estimate` | Track trend |
| Hash Stability | % hashes unchanged | `hash_stability_rate` | Track trend |

---

## Pattern 1: Smart Idempotency (Phase 2)

### Panel 1.1: Skip Rate by Processor (Last 7 Days)

**Purpose:** Track which Phase 2 processors are effectively skipping writes

**Query:**
```sql
-- Phase 2: Smart Idempotency Skip Rate
-- Shows % of runs that skipped write due to unchanged hash
WITH processor_runs AS (
  SELECT
    REGEXP_EXTRACT(table_id, r'nba_raw\.(.+)') as processor_name,
    DATE(processed_at) as run_date,
    game_id,
    ARRAY_AGG(data_hash ORDER BY processed_at) as hashes,
    COUNT(*) as run_count
  FROM `nba-props-platform.region-us.INFORMATION_SCHEMA.TABLES`
  WHERE table_schema = 'nba_raw'
    AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY processor_name, run_date, game_id
  HAVING run_count > 1
),
skip_analysis AS (
  SELECT
    processor_name,
    run_date,
    COUNT(*) as total_reruns,
    COUNTIF(hashes[OFFSET(0)] = hashes[OFFSET(1)]) as skipped_writes,
    SAFE_DIVIDE(
      COUNTIF(hashes[OFFSET(0)] = hashes[OFFSET(1)]),
      COUNT(*)
    ) * 100 as skip_rate_pct
  FROM processor_runs
  GROUP BY processor_name, run_date
)
SELECT
  processor_name,
  run_date,
  total_reruns,
  skipped_writes,
  ROUND(skip_rate_pct, 2) as skip_rate_pct
FROM skip_analysis
ORDER BY run_date DESC, skip_rate_pct DESC;
```

**Expected Results:**
- **Good**: 40-60% skip rate (data stable, idempotency working)
- **Warning**: 0-20% skip rate (data constantly changing, investigate)
- **Critical**: >80% skip rate (possible duplicate processing, investigate)

**Grafana Panel Config:**
- **Type:** Time series (line chart)
- **Y-Axis:** Skip Rate %
- **Group By:** processor_name
- **Alert:** < 30% for 3 consecutive days

---

### Panel 1.2: Hash Stability by Table

**Purpose:** Track how often data_hash values remain unchanged across runs

**Query:**
```sql
-- Hash Stability Analysis
-- Shows which tables have stable vs volatile data
SELECT
  table_name,
  DATE(processed_at) as date,
  COUNT(DISTINCT data_hash) as unique_hashes,
  COUNT(*) as total_records,
  ROUND(SAFE_DIVIDE(
    COUNT(DISTINCT data_hash),
    COUNT(*)
  ) * 100, 2) as hash_diversity_pct,
  -- Lower diversity = more stable data
  100 - ROUND(SAFE_DIVIDE(
    COUNT(DISTINCT data_hash),
    COUNT(*)
  ) * 100, 2) as stability_pct
FROM (
  SELECT 'nbac_player_boxscore' as table_name, processed_at, data_hash
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)

  UNION ALL

  SELECT 'nbac_injury_report' as table_name, processed_at, data_hash
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)

  -- Add more tables as needed
)
GROUP BY table_name, date
ORDER BY date DESC, stability_pct DESC;
```

**Expected Results:**
- **High Stability (>70%)**: Boxscores, schedules (data rarely changes after initial write)
- **Medium Stability (30-70%)**: Odds, props (data updates frequently)
- **Low Stability (<30%)**: Injuries, rosters (data changes often)

---

### Panel 1.3: Write Operations Saved (Cost Impact)

**Purpose:** Estimate BigQuery write operations saved by smart idempotency

**Query:**
```sql
-- Estimated Write Operations Saved
-- Compares actual writes to potential writes without idempotency
WITH daily_stats AS (
  SELECT
    DATE(processed_at) as date,
    table_name,
    COUNT(*) as actual_writes,
    -- Estimate: without idempotency, would write on every processor run
    -- Assuming average 2 runs per game
    COUNT(*) * 2 as potential_writes_without_idempotency
  FROM (
    SELECT 'nbac_player_boxscore' as table_name, processed_at
    FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
    WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)

    UNION ALL

    SELECT 'nbac_team_boxscore' as table_name, processed_at
    FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
    WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  )
  GROUP BY date, table_name
)
SELECT
  date,
  table_name,
  actual_writes,
  potential_writes_without_idempotency,
  potential_writes_without_idempotency - actual_writes as writes_saved,
  ROUND(SAFE_DIVIDE(
    potential_writes_without_idempotency - actual_writes,
    potential_writes_without_idempotency
  ) * 100, 2) as savings_pct
FROM daily_stats
ORDER BY date DESC, savings_pct DESC;
```

**Grafana Panel Config:**
- **Type:** Bar chart (stacked)
- **Y-Axis:** Write operations
- **Series:** actual_writes (blue), writes_saved (green)

---

## Pattern 2: Dependency Tracking (Phase 3)

### Panel 2.1: Dependency Check Failures

**Purpose:** Track when Phase 3 processors fail dependency checks

**Query:**
```sql
-- Dependency Check Failures
-- Phase 3 processors that couldn't run due to missing Phase 2 data
SELECT
  DATE(processed_at) as date,
  processor_name,
  missing_dependency,
  COUNT(*) as failure_count,
  MAX(error_message) as latest_error
FROM (
  -- Player game summary dependencies
  SELECT
    processed_at,
    'player_game_summary' as processor_name,
    'nbac_gamebook_player_stats' as missing_dependency,
    'Missing critical dependency' as error_message
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE source_nbac_rows_found IS NULL
    OR source_nbac_rows_found = 0
    AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)

  UNION ALL

  -- Team offense dependencies
  SELECT
    processed_at,
    'team_offense_game_summary' as processor_name,
    'nbac_team_boxscore' as missing_dependency,
    'Missing critical dependency' as error_message
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE source_nbac_boxscore_rows_found IS NULL
    OR source_nbac_boxscore_rows_found = 0
    AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
GROUP BY date, processor_name, missing_dependency
ORDER BY date DESC, failure_count DESC;
```

**Alert Configuration:**
- **Critical:** > 0 failures in last 6 hours
- **Action:** Check Phase 2 scrapers/processors for the missing table

---

### Panel 2.2: Source Data Freshness

**Purpose:** Monitor age of Phase 2 data used by Phase 3 processors

**Query:**
```sql
-- Phase 2 Source Data Age Analysis
-- Shows how fresh the Phase 2 data is when Phase 3 uses it
SELECT
  DATE(processed_at) as processing_date,
  'player_game_summary' as processor,
  AVG(TIMESTAMP_DIFF(processed_at, source_nbac_last_updated, HOUR)) as avg_source_age_hours,
  MAX(TIMESTAMP_DIFF(processed_at, source_nbac_last_updated, HOUR)) as max_source_age_hours,
  MIN(TIMESTAMP_DIFF(processed_at, source_nbac_last_updated, HOUR)) as min_source_age_hours
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND source_nbac_last_updated IS NOT NULL
GROUP BY processing_date
ORDER BY processing_date DESC;
```

**Expected Results:**
- **Good**: <6 hours average age
- **Warning**: 6-24 hours (data getting stale)
- **Critical**: >24 hours (stale data, investigate Phase 2)

---

### Panel 2.3: Source Completeness Tracking

**Purpose:** Monitor data completeness from Phase 2 sources

**Query:**
```sql
-- Source Completeness Heatmap
-- Shows which Phase 2 sources are providing complete data
SELECT
  game_date,
  ROUND(AVG(source_nbac_completeness_pct), 2) as nbac_completeness,
  ROUND(AVG(source_bdl_completeness_pct), 2) as bdl_completeness,
  ROUND(AVG(source_bbd_completeness_pct), 2) as bbd_completeness,
  ROUND(AVG(source_odds_completeness_pct), 2) as odds_completeness,
  -- Overall score
  ROUND(AVG(
    COALESCE(source_nbac_completeness_pct, 0) +
    COALESCE(source_bdl_completeness_pct, 0) +
    COALESCE(source_bbd_completeness_pct, 0) +
    COALESCE(source_odds_completeness_pct, 0)
  ) / 4, 2) as overall_completeness
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

**Grafana Panel Config:**
- **Type:** Heatmap or stacked bar chart
- **Y-Axis:** Completeness %
- **Alert:** overall_completeness < 80%

---

## Pattern 3: Smart Reprocessing (Phase 3)

### Panel 3.1: Phase 3 Processing Skip Rate

**Purpose:** Track how often Phase 3 skips processing due to unchanged Phase 2 hashes

**Query:**
```sql
-- Phase 3 Smart Reprocessing Skip Rate
-- Compares current Phase 2 hash to previous run's hash
WITH hash_changes AS (
  SELECT
    game_date,
    game_id,
    processed_at,
    source_nbac_hash,
    LAG(source_nbac_hash) OVER (
      PARTITION BY game_date, game_id
      ORDER BY processed_at
    ) as previous_hash,
    source_nbac_hash = LAG(source_nbac_hash) OVER (
      PARTITION BY game_date, game_id
      ORDER BY processed_at
    ) as hash_unchanged
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
SELECT
  DATE(processed_at) as date,
  COUNT(*) as total_processing_runs,
  COUNTIF(hash_unchanged) as skipped_processing,
  COUNTIF(NOT hash_unchanged OR previous_hash IS NULL) as actual_processing,
  ROUND(SAFE_DIVIDE(
    COUNTIF(hash_unchanged),
    COUNT(*)
  ) * 100, 2) as skip_rate_pct
FROM hash_changes
WHERE previous_hash IS NOT NULL  -- Exclude first run
GROUP BY date
ORDER BY date DESC;
```

**Expected Results:**
- **Good**: 30-50% skip rate (Phase 2 stable, reprocessing working)
- **Low**: 0-20% skip rate (Phase 2 constantly changing)
- **High**: >70% skip rate (possibly stale Phase 2 data)

---

### Panel 3.2: Hash Change Frequency by Source

**Purpose:** Identify which Phase 2 sources change most frequently

**Query:**
```sql
-- Phase 2 Source Change Frequency
-- Shows which upstream sources are volatile vs stable
WITH source_changes AS (
  SELECT
    game_date,
    game_id,
    processed_at,
    -- Check each source individually
    source_nbac_hash != LAG(source_nbac_hash) OVER w as nbac_changed,
    source_bdl_hash != LAG(source_bdl_hash) OVER w as bdl_changed,
    source_odds_hash != LAG(source_odds_hash) OVER w as odds_changed
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  WINDOW w AS (PARTITION BY game_date, game_id ORDER BY processed_at)
)
SELECT
  DATE(processed_at) as date,
  COUNTIF(nbac_changed) as nbac_changes,
  COUNTIF(bdl_changed) as bdl_changes,
  COUNTIF(odds_changed) as odds_changes,
  COUNT(*) as total_runs,
  -- Change rates
  ROUND(SAFE_DIVIDE(COUNTIF(nbac_changed), COUNT(*)) * 100, 2) as nbac_change_rate_pct,
  ROUND(SAFE_DIVIDE(COUNTIF(bdl_changed), COUNT(*)) * 100, 2) as bdl_change_rate_pct,
  ROUND(SAFE_DIVIDE(COUNTIF(odds_changed), COUNT(*)) * 100, 2) as odds_change_rate_pct
FROM source_changes
GROUP BY date
ORDER BY date DESC;
```

**Insights:**
- High change rate → More volatile data (expected for odds/props)
- Low change rate → Stable data (expected for boxscores after game final)

---

### Panel 3.3: Cascade Prevention Impact

**Purpose:** Estimate how many Phase 4/5 triggers were prevented by smart reprocessing

**Query:**
```sql
-- Cascade Prevention Estimate
-- Phase 3 skips → Phase 4/5 not triggered → cost savings
WITH skip_analysis AS (
  SELECT
    DATE(processed_at) as date,
    COUNT(*) as phase3_runs,
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id
        ORDER BY processed_at
      )
    ) as phase3_skips,
    -- Estimate: each Phase 3 skip prevents 1 Phase 4 run and 5 Phase 5 prediction runs
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id
        ORDER BY processed_at
      )
    ) * 1 as phase4_triggers_prevented,
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id
        ORDER BY processed_at
      )
    ) * 5 as phase5_triggers_prevented
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  date,
  phase3_runs,
  phase3_skips,
  phase4_triggers_prevented,
  phase5_triggers_prevented,
  phase3_skips + phase4_triggers_prevented + phase5_triggers_prevented as total_operations_saved,
  ROUND(SAFE_DIVIDE(
    phase3_skips + phase4_triggers_prevented + phase5_triggers_prevented,
    phase3_runs * 7  -- Estimate total operations if no skipping (1 P3 + 1 P4 + 5 P5)
  ) * 100, 2) as cascade_prevention_pct
FROM skip_analysis
ORDER BY date DESC;
```

**Expected Impact:**
- 30-50% of total pipeline operations prevented
- Significant cost savings on Cloud Run executions

---

## Pattern 4: Backfill Detection

### Panel 4.1: Current Backfill Candidates

**Purpose:** Show games with Phase 2 data but missing Phase 3 analytics

**Query:**
```sql
-- Backfill Candidates - Games Needing Processing
-- Phase 2 exists but Phase 3 missing
WITH phase2_games AS (
  SELECT DISTINCT game_date, game_id
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
phase3_games AS (
  SELECT DISTINCT game_date, game_id
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
  p2.game_date,
  p2.game_id,
  'player_game_summary' as processor,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),
    TIMESTAMP(DATETIME(p2.game_date, TIME(23, 59, 59))),
    HOUR
  ) as hours_since_game
FROM phase2_games p2
LEFT JOIN phase3_games p3 USING (game_date, game_id)
WHERE p3.game_id IS NULL
ORDER BY p2.game_date DESC, p2.game_id;
```

**Alert Configuration:**
- **Warning:** > 50 backfill candidates
- **Critical:** > 100 backfill candidates or any game >72 hours old

---

### Panel 4.2: Backfill Processing History

**Purpose:** Track backfill job execution and success rates

**Query:**
```sql
-- Backfill Job Execution History
-- Shows when backfill jobs ran and how many gaps they filled
SELECT
  DATE(processed_at) as backfill_date,
  COUNT(DISTINCT game_id) as games_processed,
  COUNT(*) as total_records,
  -- Identify backfill by processing old game dates
  COUNTIF(DATE_DIFF(DATE(processed_at), game_date, DAY) > 3) as backfilled_games,
  ROUND(AVG(DATE_DIFF(DATE(processed_at), game_date, DAY)), 2) as avg_processing_delay_days
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY backfill_date
ORDER BY backfill_date DESC;
```

**Insights:**
- Spike in `backfilled_games` = backfill job ran
- `avg_processing_delay_days` > 1 = data processed retroactively

---

## Cost Savings Summary Dashboard

### Panel 5.1: Overall Efficiency Metrics

**Purpose:** Single-number stats for executive summary

**Query:**
```sql
-- Overall Pattern Efficiency Summary (Last 30 Days)
WITH phase2_savings AS (
  SELECT
    COUNT(*) as total_potential_writes,
    -- Estimate based on hash stability
    COUNT(DISTINCT data_hash) as actual_unique_writes,
    COUNT(*) - COUNT(DISTINCT data_hash) as writes_saved
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),
phase3_savings AS (
  SELECT
    COUNT(*) as total_runs,
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id
        ORDER BY processed_at
      )
    ) as processing_skipped
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  -- Phase 2 metrics
  p2.actual_unique_writes,
  p2.writes_saved,
  ROUND(SAFE_DIVIDE(p2.writes_saved, p2.total_potential_writes) * 100, 2) as phase2_skip_rate_pct,

  -- Phase 3 metrics
  p3.total_runs,
  p3.processing_skipped,
  ROUND(SAFE_DIVIDE(p3.processing_skipped, p3.total_runs) * 100, 2) as phase3_skip_rate_pct,

  -- Combined savings
  p2.writes_saved + p3.processing_skipped as total_operations_saved,
  ROUND(SAFE_DIVIDE(
    p2.writes_saved + p3.processing_skipped,
    p2.total_potential_writes + p3.total_runs
  ) * 100, 2) as overall_efficiency_pct
FROM phase2_savings p2, phase3_savings p3;
```

**Grafana Panel Config:**
- **Type:** Stat panels (single number displays)
- **Panels:**
  - Phase 2 Skip Rate (target: 40-60%)
  - Phase 3 Skip Rate (target: 30-50%)
  - Total Operations Saved (higher is better)
  - Overall Efficiency % (target: 35-55%)

---

## Grafana Dashboard Layout Recommendation

### Dashboard: "Processing Pattern Efficiency"

**Row 1: Executive Summary (Single Stats)**
- Phase 2 Skip Rate (30 days)
- Phase 3 Skip Rate (30 days)
- Operations Saved Today
- Current Backfill Queue

**Row 2: Smart Idempotency (Phase 2)**
- Panel 1.1: Skip Rate by Processor (time series)
- Panel 1.2: Hash Stability (bar chart)
- Panel 1.3: Write Operations Saved (stacked bar)

**Row 3: Dependency Tracking**
- Panel 2.1: Dependency Failures (table)
- Panel 2.2: Source Data Age (time series)
- Panel 2.3: Completeness Heatmap

**Row 4: Smart Reprocessing (Phase 3)**
- Panel 3.1: Phase 3 Skip Rate (time series)
- Panel 3.2: Source Change Frequency (stacked area)
- Panel 3.3: Cascade Prevention Impact (bar chart)

**Row 5: Backfill Detection**
- Panel 4.1: Current Backfill Candidates (table, top 20)
- Panel 4.2: Backfill History (time series)

---

## Alert Configuration

### Critical Alerts (PagerDuty/Slack)

1. **Dependency Check Failures**
   - Query: `pattern_2_dependency_failures`
   - Threshold: > 0 in last 6 hours
   - Action: Check Phase 2 scrapers immediately

2. **Backfill Queue Growing**
   - Query: `pattern_4_backfill_candidates`
   - Threshold: > 100 games
   - Action: Run backfill job

3. **Skip Rate Anomaly**
   - Query: `pattern_1_phase2_skip_rate`
   - Threshold: < 10% (suspicious, possible issue)
   - Action: Investigate hash computation

### Warning Alerts (Slack only)

4. **Low Efficiency**
   - Combined skip rate < 25%
   - Action: Review pattern implementation

5. **Stale Data**
   - Phase 2 source age > 24 hours
   - Action: Check Phase 2 processing schedule

---

## Next Steps

1. **Import Queries to Grafana**
   - Create new dashboard: "Processing Pattern Efficiency"
   - Add BigQuery data source connection
   - Import queries as panels

2. **Set Up Alerts**
   - Configure alert rules in Grafana
   - Connect to Slack/PagerDuty
   - Test alert notifications

3. **Establish Baselines**
   - Monitor for 1 week to establish normal ranges
   - Document expected skip rates per processor
   - Tune alert thresholds

4. **Monitor Trends**
   - Weekly review of efficiency metrics
   - Track cost savings over time
   - Identify optimization opportunities

---

**Created with**: Claude Code
**Status**: Production Ready
**Dependencies**: Grafana + BigQuery data source
