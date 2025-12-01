# Backfill Execution Runbook

**Created:** 2025-11-29 21:00 PST
**Last Updated:** 2025-11-30
**Purpose:** Step-by-step instructions for executing the 4-year backfill
**Prerequisites:** ~~Phase 4 backfill jobs created~~ ✅, player boxscore scraper fixed

---

## Table of Contents

1. [Overview](#overview)
2. [Why Historical Predictions Matter for ML](#why-historical-predictions-matter-for-ml)
3. [Pre-Flight Checklist](#pre-flight-checklist)
4. [How the Backfill Jobs Work](#how-the-backfill-jobs-work)
5. [Step-by-Step Execution](#step-by-step-execution)
6. [Monitoring](#monitoring)
7. [Troubleshooting](#troubleshooting)
8. [Open Questions](#open-questions)

---

## Overview

**Total Scope:** Season-by-season backfill (2021-22 through current)
**Strategy:** Process each season fully (Phase 3 → Phase 4) before moving to next
**Execution:** Run locally to capture output and errors, with Claude Code monitoring logs

### Seasons to Process

| Season | Date Range | Notes |
|--------|-----------|-------|
| 2021-22 | Oct 2021 - Jun 2022 | First backfill target |
| 2022-23 | Oct 2022 - Jun 2023 | |
| 2023-24 | Oct 2023 - Jun 2024 | |
| 2024-25 | Oct 2024 - Jun 2025 | |
| 2025-26 | Oct 2025 - Present | Current season, process as needed |

**Note:** Backfill may be re-run when data quality improvements are needed or issues arise.

| Phase | Processors | Parallelization | Estimated Time per Season |
|-------|------------|-----------------|---------------------------|
| Phase 3 | 5 processors | Can run in parallel | ~2-3 hours |
| Phase 4 | 5 processors | MUST run sequentially | ~3-4 hours |

---

## Why Historical Predictions Matter for ML

### Goal of the Backfill

The backfill enables three key capabilities:

1. **ML Model Training** - Historical data provides training examples
2. **Backtesting** - See how predictions would have performed historically
3. **Similarity Matching** - Current predictions use historical patterns to find similar game contexts

### How Historical Predictions Help Learning

**Backtesting for Model Validation:**
```
If you predict Player X will score 25.5 points with 70% confidence,
and historically when the model said 70% confidence it was right 68% of the time,
you know the model is well-calibrated.
```

**Error Analysis:**
- Identify patterns where predictions consistently fail
- Example: Model underperforms for back-to-back games? Add fatigue features.
- Example: Model fails for certain matchups? Add opponent-specific features.

**Feature Importance:**
- Which features correlate most with accurate predictions?
- Historical data lets you test feature combinations

**Similarity-Based Predictions:**
- "This player in this situation is similar to 50 historical games"
- Historical features make similarity matching possible

### Preventing Data Leakage

**Important:** Don't train and test on the same data.

**Recommended approach:**
```
Training data:    2021-22, 2022-23 seasons
Validation data:  2023-24 season
Test data:        2024-25 season (current)
```

Or use **rolling windows**:
- Train on games 1-100
- Predict game 101
- Train on games 2-101
- Predict game 102
- etc.

---

## Pre-Flight Checklist

Before starting, verify:

```bash
# 1. Verify backfill jobs exist
ls -la backfill_jobs/analytics/
ls -la backfill_jobs/precompute/  # Phase 4 jobs - you're creating these

# 2. Verify you're in tmux/screen (for long-running jobs)
tmux new-session -s backfill  # or screen -S backfill

# 3. Set up log file location for monitoring
export BACKFILL_LOG="/tmp/backfill_$(date +%Y%m%d_%H%M%S).log"
echo "Logs will be written to: $BACKFILL_LOG"

# 4. Open a second terminal/tmux pane for monitoring
# See Monitoring section below
```

---

## Data Readiness Patterns During Backfill

**Reference:** See [`docs/01-architecture/data-readiness-patterns.md`](../../../01-architecture/data-readiness-patterns.md) for full details on all patterns.

### Which Patterns Are Active During Backfill?

| Pattern | Status During Backfill | Notes |
|---------|------------------------|-------|
| Deduplication Check | ✅ Active | Skips already-processed dates |
| Dependency Checking | ✅ Active (relaxed) | `expected_count_min=1` instead of configured |
| Smart Idempotency | ✅ Active | Skips unchanged data |
| Run History Tracking | ✅ Active | Records all runs |
| **Defensive Checks** | ❌ Disabled | Gap detection + upstream status skipped |
| **Alerts** | ❌ Suppressed | Non-critical alerts not sent |
| **Cascade Control** | ❌ Disabled | `skip_downstream_trigger=true` |
| Bootstrap Period | ✅ Active | Phase 4 skips first 7 days of season |

### Key Implication

**During backfill, YOU must validate data quality manually** - the system trusts you because defensive checks are disabled.

---

## How the Backfill Jobs Work

### Analytics Backfill Pattern (Phase 3)

Based on `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`:

```python
# Key features:
# - Day-by-day processing (avoids BigQuery size limits)
# - Sets backfill_mode=True (disables historical check, suppresses alerts)
# - Tracks failed days for retry
# - Logs progress every 10 days
```

**Usage:**
```bash
# Dry run - check data availability
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --dry-run \
  --start-date 2021-10-19 \
  --end-date 2021-10-25

# Actual run
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2022-04-10

# Retry specific failed dates
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --dates 2022-01-05,2022-01-12
```

**Output includes:**
- Progress every 10 days
- Per-day record counts
- Registry integration stats (players found/not found)
- Failed dates list for retry
- Retry command suggestion

### Scraper Backfill Pattern (Phase 1 Reference)

Based on `backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py`:

```python
# Key features:
# - Parallel execution with workers (ThreadPoolExecutor)
# - Loads game IDs from CSV file
# - GCS skip check (resume logic - skips already-scraped games)
# - Saves failed games to JSON for retry
# - Progress logging every 50 games
```

**Usage:**
```bash
# Dry run
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --dry-run --limit=10

# Parallel execution with 15 workers
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --workers=15

# Season filter
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --season=2024 --workers=15
```

---

## Step-by-Step Execution

### Step 1: Validate Phase 2 Data

**Goal:** Confirm Phase 2 has sufficient data before starting Phase 3.

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
)
ORDER BY pct ASC
"
```

**Decision point:**
- All critical tables 99%+ → Proceed to Step 2
- Any critical table <95% → Fix Phase 2 gaps first

---

### Step 2: Phase 3 Backfill - Season 2021-22

**Dates:** 2021-10-19 to 2022-04-10 (regular season)
**Note:** First 7 days will have Phase 4 skip due to bootstrap period.

#### 2.1 Dry Run First (Recommended)

```bash
# Check data availability for each processor
cd /home/naji/code/nba-stats-scraper

python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --dry-run --start-date 2021-10-19 --end-date 2021-10-25
```

#### 2.2 Run All 5 Phase 3 Processors

**These can run in parallel** (different terminals or background jobs):

```bash
# Terminal 1: player_game_summary
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_pgs_2021.log

# Terminal 2: team_defense_game_summary
python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_tdgs_2021.log

# Terminal 3: team_offense_game_summary
python backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_togs_2021.log

# Terminal 4: upcoming_team_game_context
python backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_utgc_2021.log

# Terminal 5: upcoming_player_game_context (limited by odds data)
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_upgc_2021.log
```

#### 2.3 Validate Phase 3 Complete

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
"
```

**Expected:** ~170 dates per table (varies by season).

---

### Step 3: Phase 4 Backfill - Season 2021-22

**CRITICAL: Phase 4 processors MUST run sequentially!**

Each processor depends on the previous one:
1. team_defense_zone_analysis (reads Phase 3)
2. player_shot_zone_analysis (reads Phase 3)
3. player_composite_factors (reads #1, #2, Phase 3)
4. player_daily_cache (reads #1, #2, #3, Phase 3)
5. ml_feature_store (reads #1, #2, #3, #4)

```bash
# Step 3.1: team_defense_zone_analysis
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_p4_tdza_2021.log

# Wait for completion, then...

# Step 3.2: player_shot_zone_analysis
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_p4_psza_2021.log

# Wait for completion, then...

# Step 3.3: player_composite_factors
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_p4_pcf_2021.log

# Wait for completion, then...

# Step 3.4: player_daily_cache
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_p4_pdc_2021.log

# Wait for completion, then...

# Step 3.5: ml_feature_store
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2022-04-10 \
  2>&1 | tee -a /tmp/backfill_p4_mlfs_2021.log
```

---

### Step 4: Repeat for Remaining Seasons

**Season date ranges:**
- 2022-23: `--start-date 2022-10-18 --end-date 2023-04-09`
- 2023-24: `--start-date 2023-10-24 --end-date 2024-04-14`
- 2024-25: `--start-date 2024-10-22 --end-date 2024-11-29` (current, partial)

For each season:
1. Run Phase 3 (all 5 processors in parallel)
2. Validate Phase 3 complete
3. Run Phase 4 (5 processors sequentially)
4. Validate Phase 4 complete

---

### Step 5: Final Validation

```bash
# Overall coverage check
timeout 60 bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Phase 3' as phase, 'player_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
UNION ALL
SELECT 'Phase 4', 'player_shot_zone_analysis', COUNT(DISTINCT analysis_date)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-01' AND '2024-11-29'
ORDER BY phase, table_name
"
```

---

## Monitoring

### Option 1: Watch Log Files (Claude Code can monitor)

```bash
# In separate terminal, tail the log files
tail -f /tmp/backfill_pgs_2021.log
```

### Option 2: Periodic BigQuery Check

```bash
# Run every 15-30 minutes to check progress
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  COUNTIF(status = 'success') as ok,
  COUNTIF(status = 'failed') as fail,
  MAX(data_date) as latest
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
GROUP BY processor_name
ORDER BY processor_name
"
```

### Option 3: Check for Recent Failures

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT data_date, processor_name, SUBSTR(CAST(errors AS STRING), 1, 80) as error
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'failed'
  AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
ORDER BY started_at DESC
LIMIT 10
"
```

---

## Troubleshooting

### Failed Days - How to Retry

The backfill jobs output failed dates at the end. Use the `--dates` flag:

```bash
# Retry specific failed dates
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --dates 2022-01-05,2022-01-12,2022-01-18
```

### Processor Fails with DependencyError

```bash
# Check what's missing
timeout 30 bq query --use_legacy_sql=false "
SELECT data_date, processor_name, missing_dependencies
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'failed'
  AND errors LIKE '%DependencyError%'
  AND data_date BETWEEN '2021-10-01' AND '2022-04-10'
ORDER BY data_date
LIMIT 10
"
```

**Fix:** Backfill the missing Phase 2 data, then retry.

### Phase 4 Has 0 Records for Early Season Dates

**This is expected!** Bootstrap period (first 7 days of season) intentionally skips Phase 4.

Expected empty Phase 4 dates:
- 2021-10-19 to 2021-10-25
- 2022-10-18 to 2022-10-24
- 2023-10-24 to 2023-10-30
- 2024-10-22 to 2024-10-28

---

## Error Handling

### Error Types and Actions

| Error Type | Example | Action |
|------------|---------|--------|
| **Transient** | BigQuery timeout, network error | Retry same date |
| **Rate limit** | 429 Too Many Requests | Wait 60s, retry |
| **Missing dependency** | Phase 2 data missing | Log, skip, fix later |
| **Invalid data** | Malformed records | Log, investigate |
| **Fatal** | Auth failure, schema mismatch | Stop backfill, fix first |

### When to Stop vs. Continue

**Stop the backfill if:**
- Authentication/credentials error
- Schema mismatch (table structure changed)
- >50% of dates failing in a row
- Disk/memory exhaustion

**Continue (log and skip) if:**
- Individual date fails
- Missing optional data source
- Partial data for a date

---

## Recovery After Interruption

If backfill stops unexpectedly:

### 1. Find Last Successful Date

```bash
timeout 30 bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  MAX(data_date) as last_success
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'success'
  AND data_date BETWEEN '2021-10-01' AND '2024-11-29'
GROUP BY processor_name
ORDER BY processor_name
"
```

### 2. Resume from Next Date

```bash
# If last success was 2022-01-15, resume from 2022-01-16
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-16 --end-date 2022-04-10
```

### 3. The Job Handles Duplicates

The backfill jobs are idempotent - re-running a date that already succeeded will either:
- Skip it (if skip logic is implemented)
- Overwrite with same data (safe)

---

## Quality Validation Queries

Run these after each phase completes.

### Check for NULL Critical Fields

```sql
SELECT game_date, COUNT(*) as null_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE points IS NULL OR minutes IS NULL
GROUP BY game_date
HAVING COUNT(*) > 10
ORDER BY game_date;
```

### Check Record Counts Per Game

```sql
-- Should have ~10-15 players per team (20-30 per game)
SELECT game_date, game_id, COUNT(*) as players
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
GROUP BY game_date, game_id
HAVING COUNT(*) < 15
ORDER BY game_date;
```

### Check Phase 4 Quality Distribution

```sql
SELECT
  CASE
    WHEN completeness_pct >= 90 THEN 'Good (90%+)'
    WHEN completeness_pct >= 70 THEN 'OK (70-89%)'
    WHEN completeness_pct >= 50 THEN 'Degraded (50-69%)'
    ELSE 'Poor (<50%)'
  END as quality,
  COUNT(*) as records,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date BETWEEN '2021-10-01' AND '2024-11-29'
GROUP BY 1
ORDER BY 1;
```

---

## Rollback Procedure

If backfill produces bad data that needs to be deleted and re-run:

### Important: Delete in Reverse Phase Order

```
Phase 4 first → Phase 3 second
(Because Phase 4 depends on Phase 3)
```

### Delete Phase 4 Data

```sql
-- Delete Phase 4 for a date range
DELETE FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date BETWEEN '2022-01-01' AND '2022-01-15';

DELETE FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN '2022-01-01' AND '2022-01-15';

-- Repeat for other Phase 4 tables...
```

### Delete Phase 3 Data

```sql
DELETE FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2022-01-01' AND '2022-01-15';

-- Repeat for other Phase 3 tables...
```

### Then Re-run Backfill

```bash
# Phase 3 first
python backfill_jobs/analytics/player_game_summary/... --start-date 2022-01-01 --end-date 2022-01-15

# Then Phase 4 (after Phase 3 complete)
python backfill_jobs/precompute/team_defense_zone_analysis/... --start-date 2022-01-01 --end-date 2022-01-15
# etc.
```

---

## Resolved Questions

### ~~No Odds Data for Historical Dates~~ - SOLVED

**Solution:** BettingPros has 673/675 dates (99.7% coverage) vs Odds API's 271 dates (40%).

**Coverage comparison:**
| Source | Dates | Coverage |
|--------|-------|----------|
| Odds API | 271 | 40% |
| BettingPros | 673 | 99.7% |

**Status:** ✅ IMPLEMENTED (2025-11-30)

BettingPros fallback has been implemented in `upcoming_player_game_context` processor.
See `docs/09-handoff/2025-11-30-bettingpros-fallback-complete.md` for implementation details and test results.

---

## ~~Open Questions~~ - RESOLVED

### ~~Phase 4 Backfill Jobs~~ - COMPLETE

**Status:** Completed 2025-11-30

All 5 Phase 4 backfill jobs have been created in `backfill_jobs/precompute/`:
- `team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py`
- `player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py`
- `player_composite_factors/player_composite_factors_precompute_backfill.py`
- `player_daily_cache/player_daily_cache_precompute_backfill.py`
- `ml_feature_store/ml_feature_store_precompute_backfill.py`

**Features implemented:**
- Day-by-day processing
- `--dry-run`, `--start-date`, `--end-date`, `--dates` flags
- Progress logging every 10 days
- Failed dates tracking with retry commands
- Bootstrap period handling (skip first 7 days of each season)
- Phase 4 dependency validation

**Documentation:** See `PHASE4-BACKFILL-JOBS.md` for detailed usage.

---

## Expected Outcomes

After successful backfill (per season, ~170 game days):

| Phase | Table | Expected Coverage | Notes |
|-------|-------|-------------------|-------|
| Phase 3 | player_game_summary | 100% | All game dates |
| Phase 3 | team_defense_game_summary | 100% | All game dates |
| Phase 3 | team_offense_game_summary | 100% | All game dates |
| Phase 3 | upcoming_player_game_context | ~99.7% | BettingPros fallback implemented |
| Phase 3 | upcoming_team_game_context | 100% | All game dates |
| Phase 4 | All tables | ~96% | Bootstrap periods (7 days/season) skipped |

**Quality expectations:**
- First 2-3 weeks of each season: degraded quality (limited history)
- After week 3: 80%+ should be "Good" quality
- Shot zones: Will be NULL for most historical data (play-by-play sparse)

---

## Phase 4 Backfill Job Reference

Phase 4 backfill jobs have been created with these features:

### Must Have

1. **Same CLI pattern as Phase 3:**
   - `--dry-run` for testing
   - `--start-date` / `--end-date` for range
   - `--dates` for retry of specific dates
   - `backfill_mode=True` in processor options

2. **Day-by-day processing:**
   - Avoids BigQuery size limits
   - Enables resumability
   - Clear progress visibility

3. **Bootstrap period skip:**
   ```
   2021-10-19 to 2021-10-25
   2022-10-18 to 2022-10-24
   2023-10-24 to 2023-10-30
   2024-10-22 to 2024-10-28
   ```

4. **Phase 3 validation before processing:**
   - Check Phase 3 tables have data for lookback window
   - Log warning if incomplete, but continue

5. **Failed dates tracking:**
   - List failed dates at end
   - Suggest retry command

### Execution Order Reminder

Phase 4 processors MUST run in order:
1. team_defense_zone_analysis
2. player_shot_zone_analysis
3. player_composite_factors
4. player_daily_cache
5. ml_feature_store

---

**Document Version:** 1.4
**Last Updated:** 2025-11-30

## Related Documentation

- [`docs/01-architecture/data-readiness-patterns.md`](../../../01-architecture/data-readiness-patterns.md) - All data safety patterns
- [`docs/01-architecture/pipeline-integrity.md`](../../../01-architecture/pipeline-integrity.md) - Cascade control
- [`docs/01-architecture/bootstrap-period-overview.md`](../../../01-architecture/bootstrap-period-overview.md) - Early season handling
