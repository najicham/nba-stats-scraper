# Backfill Execution Runbook

**Created:** 2025-11-29 21:00 PST
**Last Updated:** 2025-11-29 21:12 PST
**Purpose:** Step-by-step instructions for executing the 4-year backfill
**Prerequisites:** Phase 4 backfill jobs created, player boxscore scraper fixed

---

## Overview

**Total Scope:** 675 game dates across 4 seasons
**Strategy:** Season-by-season with validation gates
**Estimated Time:** Several hours per phase (can run overnight)

---

## Pre-Flight Checklist

Before starting, verify:

```bash
# 1. Check Phase 4 backfill jobs exist
./bin/run_backfill.sh --list | grep precompute

# 2. Verify you're in tmux/screen (for long-running jobs)
tmux list-sessions  # or screen -ls

# 3. Set up monitoring in separate terminal
# (see Monitoring section below)
```

---

## Step 1: Validate Phase 2 Data

**Goal:** Confirm Phase 2 has sufficient data before starting Phase 3.

### 1.1 Run Phase 2 Validation Query

```bash
timeout 60 bq query --use_legacy_sql=false --format=pretty "
WITH expected AS (
  SELECT COUNT(DISTINCT game_date) as cnt
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_status = 3
    AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
)
SELECT
  table_name,
  actual_dates,
  (SELECT cnt FROM expected) as expected,
  ROUND(actual_dates * 100.0 / (SELECT cnt FROM expected), 1) as pct
FROM (
  SELECT 'nbac_team_boxscore' as table_name, COUNT(DISTINCT game_date) as actual_dates
  FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\` WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'nbac_gamebook_player_stats', COUNT(DISTINCT game_date)
  FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'bdl_player_boxscores', COUNT(DISTINCT game_date)
  FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\` WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'nbac_schedule', COUNT(DISTINCT game_date)
  FROM \`nba-props-platform.nba_raw.nbac_schedule\` WHERE game_status = 3 AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
)
ORDER BY pct ASC
"
```

### 1.2 Decision Point

| Result | Action |
|--------|--------|
| All critical tables 99%+ | Proceed to Step 2 |
| Any critical table <95% | Fix Phase 2 gaps first |
| Only optional tables low | Document and proceed |

### 1.3 If Gaps Found - Fix Phase 2

```bash
# Find specific missing dates
timeout 60 bq query --use_legacy_sql=false "
WITH expected AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_status = 3 AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
),
actual AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
)
SELECT e.game_date as missing_date
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY e.game_date
LIMIT 20
"

# Then run appropriate scraper/processor for missing dates
```

---

## Step 2: Phase 3 Backfill - Season 2021-22

**Dates:** 2021-10-19 to 2022-04-10 (regular season)
**Note:** First 7 days (Oct 19-25) will have Phase 4 skip due to bootstrap.

### 2.1 Run All 5 Phase 3 Processors (Parallel OK)

```bash
# These can run in parallel - no inter-dependencies
# Run in separate terminals or use & for background

# Terminal 1
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=2021-10-19 \
  --end-date=2022-04-10 \
  --dry-run  # Remove after confirming command looks right

# Terminal 2
./bin/run_backfill.sh analytics/team_defense_game_summary \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Terminal 3
./bin/run_backfill.sh analytics/team_offense_game_summary \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Terminal 4
./bin/run_backfill.sh analytics/upcoming_team_game_context \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Terminal 5 (will be limited by odds data availability)
./bin/run_backfill.sh analytics/upcoming_player_game_context \
  --start-date=2021-10-19 \
  --end-date=2022-04-10
```

### 2.2 Monitor Progress

In a separate terminal, run periodically:

```bash
# Quick progress check
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  COUNTIF(status = 'success') as success,
  COUNTIF(status = 'failed') as failed,
  COUNTIF(status = 'skipped') as skipped,
  MAX(data_date) as latest_date
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN '2021-10-19' AND '2022-04-10'
  AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY processor_name
ORDER BY processor_name
"
```

### 2.3 Validate Phase 3 Complete

After all processors finish:

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  table_name,
  COUNT(DISTINCT game_date) as dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM (
  SELECT 'player_game_summary' as table_name, game_date
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
  UNION ALL
  SELECT 'team_defense_game_summary', game_date
  FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
  UNION ALL
  SELECT 'team_offense_game_summary', game_date
  FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
)
GROUP BY table_name
ORDER BY table_name
"
```

**Expected:** ~170 dates for each table (varies by season length)

### 2.4 Check for Failures

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  data_date,
  processor_name,
  SUBSTR(CAST(errors AS STRING), 1, 100) as error_preview
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE phase = 'phase_3_analytics'
  AND status = 'failed'
  AND data_date BETWEEN '2021-10-19' AND '2022-04-10'
ORDER BY data_date
LIMIT 20
"
```

**If failures found:** Note the dates and errors, decide whether to fix now or continue.

---

## Step 3: Phase 4 Backfill - Season 2021-22

**CRITICAL:** Phase 4 processors MUST run in sequence, not parallel!

### 3.1 Run Phase 4 Processors (Sequential - One at a Time)

```bash
# MUST run in this exact order - each depends on previous

# Step 3.1.1: Team Defense Zone Analysis
./bin/run_backfill.sh precompute/team_defense_zone_analysis \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Wait for completion, then...

# Step 3.1.2: Player Shot Zone Analysis
./bin/run_backfill.sh precompute/player_shot_zone_analysis \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Wait for completion, then...

# Step 3.1.3: Player Composite Factors
./bin/run_backfill.sh precompute/player_composite_factors \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Wait for completion, then...

# Step 3.1.4: Player Daily Cache
./bin/run_backfill.sh precompute/player_daily_cache \
  --start-date=2021-10-19 \
  --end-date=2022-04-10

# Wait for completion, then...

# Step 3.1.5: ML Feature Store
./bin/run_backfill.sh precompute/ml_feature_store \
  --start-date=2021-10-19 \
  --end-date=2022-04-10
```

### 3.2 Validate Phase 4 Complete

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  table_name,
  COUNT(DISTINCT date_col) as dates
FROM (
  SELECT 'team_defense_zone_analysis' as table_name, analysis_date as date_col
  FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
  WHERE analysis_date BETWEEN '2021-10-19' AND '2022-04-10'
  UNION ALL
  SELECT 'player_shot_zone_analysis', analysis_date
  FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
  WHERE analysis_date BETWEEN '2021-10-19' AND '2022-04-10'
  UNION ALL
  SELECT 'player_composite_factors', game_date
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
  UNION ALL
  SELECT 'player_daily_cache', cache_date
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date BETWEEN '2021-10-19' AND '2022-04-10'
)
GROUP BY table_name
ORDER BY table_name
"
```

**Note:** First 7 days (Oct 19-25) will have 0 records due to bootstrap - this is expected!

### 3.3 Check Quality Scores

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  CASE
    WHEN completeness_pct >= 90 THEN '90-100% (Good)'
    WHEN completeness_pct >= 70 THEN '70-89% (OK)'
    WHEN completeness_pct >= 50 THEN '50-69% (Degraded)'
    ELSE '0-49% (Bootstrap/Poor)'
  END as quality_bucket,
  COUNT(*) as records,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-19' AND '2022-04-10'
GROUP BY 1
ORDER BY 1
"
```

**Expected:** Mostly "Good" after first few weeks of season.

---

## Step 4: Repeat for Remaining Seasons

### Season 2022-23

```bash
# Phase 3 (parallel OK)
./bin/run_backfill.sh analytics/player_game_summary --start-date=2022-10-18 --end-date=2023-04-09 &
./bin/run_backfill.sh analytics/team_defense_game_summary --start-date=2022-10-18 --end-date=2023-04-09 &
./bin/run_backfill.sh analytics/team_offense_game_summary --start-date=2022-10-18 --end-date=2023-04-09 &
./bin/run_backfill.sh analytics/upcoming_team_game_context --start-date=2022-10-18 --end-date=2023-04-09 &
./bin/run_backfill.sh analytics/upcoming_player_game_context --start-date=2022-10-18 --end-date=2023-04-09 &
wait

# Validate Phase 3 complete (run validation query)

# Phase 4 (sequential ONLY)
./bin/run_backfill.sh precompute/team_defense_zone_analysis --start-date=2022-10-18 --end-date=2023-04-09
./bin/run_backfill.sh precompute/player_shot_zone_analysis --start-date=2022-10-18 --end-date=2023-04-09
./bin/run_backfill.sh precompute/player_composite_factors --start-date=2022-10-18 --end-date=2023-04-09
./bin/run_backfill.sh precompute/player_daily_cache --start-date=2022-10-18 --end-date=2023-04-09
./bin/run_backfill.sh precompute/ml_feature_store --start-date=2022-10-18 --end-date=2023-04-09

# Validate Phase 4 complete
```

### Season 2023-24

```bash
# Phase 3
./bin/run_backfill.sh analytics/player_game_summary --start-date=2023-10-24 --end-date=2024-04-14 &
./bin/run_backfill.sh analytics/team_defense_game_summary --start-date=2023-10-24 --end-date=2024-04-14 &
./bin/run_backfill.sh analytics/team_offense_game_summary --start-date=2023-10-24 --end-date=2024-04-14 &
./bin/run_backfill.sh analytics/upcoming_team_game_context --start-date=2023-10-24 --end-date=2024-04-14 &
./bin/run_backfill.sh analytics/upcoming_player_game_context --start-date=2023-10-24 --end-date=2024-04-14 &
wait

# Phase 4 (sequential)
./bin/run_backfill.sh precompute/team_defense_zone_analysis --start-date=2023-10-24 --end-date=2024-04-14
./bin/run_backfill.sh precompute/player_shot_zone_analysis --start-date=2023-10-24 --end-date=2024-04-14
./bin/run_backfill.sh precompute/player_composite_factors --start-date=2023-10-24 --end-date=2024-04-14
./bin/run_backfill.sh precompute/player_daily_cache --start-date=2023-10-24 --end-date=2024-04-14
./bin/run_backfill.sh precompute/ml_feature_store --start-date=2023-10-24 --end-date=2024-04-14
```

### Season 2024-25 (Current - Partial)

```bash
# Phase 3
./bin/run_backfill.sh analytics/player_game_summary --start-date=2024-10-22 --end-date=2024-11-29 &
./bin/run_backfill.sh analytics/team_defense_game_summary --start-date=2024-10-22 --end-date=2024-11-29 &
./bin/run_backfill.sh analytics/team_offense_game_summary --start-date=2024-10-22 --end-date=2024-11-29 &
./bin/run_backfill.sh analytics/upcoming_team_game_context --start-date=2024-10-22 --end-date=2024-11-29 &
./bin/run_backfill.sh analytics/upcoming_player_game_context --start-date=2024-10-22 --end-date=2024-11-29 &
wait

# Phase 4 (sequential)
./bin/run_backfill.sh precompute/team_defense_zone_analysis --start-date=2024-10-22 --end-date=2024-11-29
./bin/run_backfill.sh precompute/player_shot_zone_analysis --start-date=2024-10-22 --end-date=2024-11-29
./bin/run_backfill.sh precompute/player_composite_factors --start-date=2024-10-22 --end-date=2024-11-29
./bin/run_backfill.sh precompute/player_daily_cache --start-date=2024-10-22 --end-date=2024-11-29
./bin/run_backfill.sh precompute/ml_feature_store --start-date=2024-10-22 --end-date=2024-11-29
```

---

## Step 5: Final Validation

### 5.1 Overall Coverage Check

```bash
timeout 60 bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Phase 2' as phase,
  'nbac_team_boxscore' as table_name,
  COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'

UNION ALL

SELECT 'Phase 3', 'player_game_summary', COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'

UNION ALL

SELECT 'Phase 3', 'team_defense_game_summary', COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'

UNION ALL

SELECT 'Phase 4', 'player_shot_zone_analysis', COUNT(DISTINCT analysis_date)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-01' AND '2024-11-29'

ORDER BY phase, table_name
"
```

### 5.2 Failure Summary

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  phase,
  processor_name,
  COUNT(*) as failure_count
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'failed'
  AND data_date BETWEEN '2021-10-01' AND '2024-11-29'
GROUP BY phase, processor_name
HAVING COUNT(*) > 0
ORDER BY failure_count DESC
"
```

### 5.3 Quality Distribution

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  EXTRACT(YEAR FROM analysis_date) as year,
  CASE
    WHEN completeness_pct >= 90 THEN 'Good (90%+)'
    WHEN completeness_pct >= 70 THEN 'OK (70-89%)'
    ELSE 'Degraded (<70%)'
  END as quality,
  COUNT(*) as records
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
GROUP BY year, quality
ORDER BY year, quality
"
```

---

## Monitoring Commands

### Active Progress Monitor (Run in Separate Terminal)

```bash
#!/bin/bash
# Save as monitor_backfill.sh

while true; do
  clear
  echo "=== BACKFILL MONITOR - $(date) ==="
  echo ""

  echo "=== RECENT ACTIVITY (last hour) ==="
  bq query --use_legacy_sql=false --format=pretty "
  SELECT
    processor_name,
    COUNTIF(status = 'success') as ok,
    COUNTIF(status = 'failed') as fail,
    MAX(data_date) as latest
  FROM \`nba-props-platform.nba_reference.processor_run_history\`
  WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  GROUP BY processor_name
  ORDER BY processor_name
  " 2>/dev/null

  echo ""
  echo "=== FAILURES (last hour) ==="
  bq query --use_legacy_sql=false --format=pretty "
  SELECT data_date, processor_name, SUBSTR(CAST(errors AS STRING), 1, 60) as error
  FROM \`nba-props-platform.nba_reference.processor_run_history\`
  WHERE status = 'failed'
    AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  ORDER BY started_at DESC
  LIMIT 5
  " 2>/dev/null

  echo ""
  echo "Next refresh in 5 minutes... (Ctrl+C to stop)"
  sleep 300
done
```

---

## Troubleshooting Quick Reference

### Processor Fails with DependencyError

```bash
# Find what's missing
bq query --use_legacy_sql=false "
SELECT data_date, missing_dependencies
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'failed'
  AND errors LIKE '%DependencyError%'
ORDER BY data_date DESC
LIMIT 10
"

# Fix: Backfill the missing Phase 2 data, then re-run
```

### Phase 4 Has 0 Records for Some Dates

```bash
# Check if it's bootstrap period (first 7 days of season)
# Expected: Oct 19-25 (2021), Oct 18-24 (2022), Oct 24-30 (2023), Oct 22-28 (2024)
# These dates SHOULD have 0 Phase 4 records - that's correct behavior!
```

### Re-run Failed Dates Only

```bash
# Get list of failed dates
bq query --use_legacy_sql=false --format=csv "
SELECT DISTINCT CAST(data_date AS STRING)
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND status = 'failed'
" > /tmp/failed_dates.txt

# Then re-run each (or create a loop)
for date in $(cat /tmp/failed_dates.txt | tail -n +2); do
  ./bin/run_backfill.sh analytics/player_game_summary --dates=$date
done
```

---

## Expected Outcomes

After successful backfill:

| Phase | Table | Expected Dates | Notes |
|-------|-------|----------------|-------|
| Phase 3 | player_game_summary | ~650 | All game dates |
| Phase 3 | team_defense_game_summary | ~650 | All game dates |
| Phase 3 | team_offense_game_summary | ~650 | All game dates |
| Phase 3 | upcoming_player_game_context | ~270 | Limited by odds data |
| Phase 3 | upcoming_team_game_context | ~650 | All game dates |
| Phase 4 | player_shot_zone_analysis | ~620 | Minus bootstrap periods |
| Phase 4 | team_defense_zone_analysis | ~620 | Minus bootstrap periods |
| Phase 4 | player_composite_factors | ~620 | Minus bootstrap periods |
| Phase 4 | player_daily_cache | ~620 | Minus bootstrap periods |

**Quality expectations:**
- First 2-3 weeks of each season: degraded quality (limited history)
- After week 3: 80%+ should be "Good" quality
- Shot zones will be NULL for most historical data (play-by-play sparse)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29 21:12 PST
