# Backfill Master Plan: 4 Years of NBA Data

**Created:** 2025-11-29 20:30 PST
**Last Updated:** 2025-11-30
**Status:** Ready for Execution (Phase 4 backfill jobs complete)
**Goal:** Backfill 675 game dates (2021-22 through 2024-25) across all phases

---

## Table of Contents

1. [Current State Assessment](#current-state-assessment)
2. [Infrastructure Gaps](#infrastructure-gaps)
3. [Execution Order](#execution-order)
4. [What Could Go Wrong](#what-could-go-wrong)
5. [Safeguards Available](#safeguards-available)
6. [Validation Checkpoints](#validation-checkpoints)
7. [Troubleshooting Guide](#troubleshooting-guide)

---

## Current State Assessment

**Assessment Date:** 2025-11-29

### Phase 2 (Raw Data) - MIXED

| Table | Dates | % Complete | Status |
|-------|-------|------------|--------|
| nbac_team_boxscore | 675/675 | 100% | ✅ Ready |
| nbac_gamebook_player_stats | 712/675 | 105% | ✅ Ready (includes playoffs) |
| bdl_player_boxscores | 668/675 | 99% | ⚠️ 7 dates missing |
| nbac_injury_report | 682/675 | 101% | ✅ Ready |
| odds_api_player_points_props | 271/675 | 40% | ⚠️ Historical odds limited |
| nbac_play_by_play | 1/675 | 0.1% | 🔴 Critical gap |

### Phase 3 (Analytics) - SPARSE

| Table | Dates | % Complete | Status |
|-------|-------|------------|--------|
| player_game_summary | 348/675 | 51.6% | ⚠️ Needs backfill |
| team_defense_game_summary | 0/675 | 0% | 🔴 Needs full backfill |
| team_offense_game_summary | 0/675 | 0% | 🔴 Needs full backfill |
| upcoming_player_game_context | 4/675 | 0.6% | 🔴 Needs full backfill |
| upcoming_team_game_context | 0/675 | 0% | 🔴 Needs full backfill |

### Phase 4 (Precompute) - EMPTY

| Table | Dates | % Complete | Status |
|-------|-------|------------|--------|
| player_shot_zone_analysis | 0/675 | 0% | 🔴 Needs full backfill |
| team_defense_zone_analysis | 0/675 | 0% | 🔴 Needs full backfill |
| player_composite_factors | 0/675 | 0% | 🔴 Needs full backfill |
| player_daily_cache | 0/675 | 0% | 🔴 Needs full backfill |
| ml_feature_store_v2 | 0/675 | 0% | 🔴 Needs full backfill |

### Scraper Status (Phase 1)

| Scraper | Status | Notes |
|---------|--------|-------|
| GetNbaComTeamBoxscore | ✅ 99.9% | 6 Play-In games missing |
| GetNbaComPlayerBoxscore | 🔴 BLOCKED | Wrong endpoint format |
| BdlStandingsScraper | ⏳ Ready to run | 6 seconds |
| GetNbaComPlayByPlay | ⏳ Deferred | 88 min |
| GetEspnBoxscore | ⏳ Deferred | 132 min |

---

## Infrastructure Gaps

### ~~Gap 1: Phase 4 Backfill Jobs Don't Exist~~ - RESOLVED

**Status:** Completed 2025-11-30

All 5 Phase 4 backfill jobs have been created:
- `backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py`
- `backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py`
- `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py`
- `backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py`
- `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py`

**Documentation:** See `PHASE4-BACKFILL-JOBS.md` for usage details.

### Gap 2: Player Boxscore Scraper Broken

**Problem:** `GetNbaComPlayerBoxscore` uses wrong API format (GET with gamedate instead of POST with game_id).

**Impact:** Cannot fill the 7 missing dates in `bdl_player_boxscores`.

**Resolution:** Fix script to use POST /scrape endpoint like team boxscore.

### Gap 3: Play-by-Play Data Sparse

**Problem:** `nbac_play_by_play` has only 0.1% coverage (1 date out of 675).

**Impact:**
- `team_offense_game_summary` shot zones will be NULL
- `player_game_summary` shot zones will be NULL
- Phase 4 shot zone analysis will have reduced quality

**Resolution Options:**
1. Accept NULL shot zones for historical data (recommended)
2. Backfill play-by-play (88+ minutes, may not be available historically)
3. Use BigDataBall play-by-play as alternative source

### ~~Gap 4: Historical Odds Data Limited~~ - RESOLVED

**Problem:** `odds_api_player_points_props` only 40% coverage.

**Solution Found:** BettingPros has 99.7% coverage (673/675 dates).

| Source | Dates | Coverage |
|--------|-------|----------|
| Odds API | 271 | 40% |
| BettingPros | 673 | 99.7% |

**Status:** ✅ IMPLEMENTED (2025-11-30) - See `docs/09-handoff/2025-11-30-bettingpros-fallback-complete.md`

---

## Execution Order

### Phase-by-Phase Strategy (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 1: SCRAPERS                            │
├─────────────────────────────────────────────────────────────────┤
│ Status: Mostly complete                                         │
│ Action: Fix player boxscore, run BDL standings                  │
│ Validation: Check GCS files exist for all dates                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 2: RAW PROCESSORS                      │
├─────────────────────────────────────────────────────────────────┤
│ Status: 99%+ complete for critical tables                       │
│ Action: Fill 7 missing bdl dates after scraper fix              │
│ Validation: Query each table for date count                     │
│ Flag: --skip-downstream-trigger                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
          ┌──────── VALIDATION GATE ────────┐
          │ All Phase 2 tables at 99%+?     │
          │ Run validation queries          │
          │ Document any accepted gaps      │
          └─────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 3: ANALYTICS                           │
├─────────────────────────────────────────────────────────────────┤
│ Can run ALL 5 processors in PARALLEL (no inter-dependencies)    │
│                                                                 │
│ 1. player_game_summary                                          │
│ 2. team_defense_game_summary                                    │
│ 3. team_offense_game_summary                                    │
│ 4. upcoming_player_game_context (limited to dates with odds)    │
│ 5. upcoming_team_game_context                                   │
│                                                                 │
│ Flag: --skip-downstream-trigger                                 │
│ Flag: --backfill-mode=true                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
          ┌──────── VALIDATION GATE ────────┐
          │ All Phase 3 tables at 99%+?     │
          │ Run validation queries          │
          │ Check processor_run_history     │
          └─────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 4: PRECOMPUTE                          │
├─────────────────────────────────────────────────────────────────┤
│ MUST run processors SEQUENTIALLY (has inter-dependencies)       │
│                                                                 │
│ Order (REQUIRED):                                               │
│ 1. team_defense_zone_analysis    (reads Phase 3 only)           │
│ 2. player_shot_zone_analysis     (reads Phase 3 only)           │
│ 3. player_composite_factors      (reads #1, #2, Phase 3)        │
│ 4. player_daily_cache            (reads #1-3, Phase 3)          │
│ 5. ml_feature_store              (reads #1-4)                   │
│                                                                 │
│ Flag: --skip-downstream-trigger                                 │
│ Flag: --backfill-mode=true                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
          ┌──────── VALIDATION GATE ────────┐
          │ All Phase 4 tables populated?   │
          │ Check quality_score distribution│
          │ Verify bootstrap periods handled│
          └─────────────────────────────────┘
```

### Season-by-Season Strategy (Safer)

Process one season at a time for smaller blast radius:

```
Season 2021-22 (Oct 2021 - Apr 2022, ~180 dates)
├── Phase 2: Validate complete → If not, identify gaps
├── Phase 3: All 5 processors → Validate all tables
├── Phase 4: Sequential processors → Validate quality
├── CHECKPOINT: Confirm season complete
└── Note: First 7 days of season will have degraded quality (bootstrap)

Season 2022-23 (Oct 2022 - Apr 2023, ~180 dates)
├── Phase 2: Should already be complete
├── Phase 3: All 5 processors → Now has 2021-22 for context
├── Phase 4: Sequential processors
└── CHECKPOINT: Confirm season complete

Season 2023-24 (Oct 2023 - Apr 2024, ~180 dates)
└── Same pattern...

Season 2024-25 (Oct 2024 - Nov 2024, ~40 dates)
└── Same pattern...
```

---

## What Could Go Wrong

### Category 1: Data Source Issues

#### Issue 1.1: Missing Phase 2 Data Blocks Phase 3

**Scenario:** Run Phase 3 for a date, but Phase 2 table is missing.

**What happens:**
- Processor checks dependencies
- Finds critical source missing
- Raises `DependencyError`
- Processing fails for that date
- Continues to next date (if running batch)

**Detection:**
```sql
SELECT data_date, processor_name, status, errors
FROM nba_reference.processor_run_history
WHERE status = 'failed'
  AND phase = 'phase_3_analytics'
ORDER BY data_date;
```

**Recovery:**
1. Identify missing Phase 2 data
2. Backfill Phase 1 scraper if needed
3. Backfill Phase 2 processor
4. Re-run failed Phase 3 dates

---

#### Issue 1.2: Play-by-Play Missing Causes NULL Shot Zones

**Scenario:** `nbac_play_by_play` is 0.1% complete.

**What happens:**
- `team_offense_game_summary` runs
- Checks for play-by-play data → not found
- Logs warning: "Play-by-play not available, shot zones will be NULL"
- Produces records with NULL shot zone fields
- Processing succeeds (degraded, not failed)

**Detection:**
```sql
SELECT
  COUNT(*) as total,
  COUNTIF(paint_attempts IS NULL) as null_shot_zones,
  ROUND(COUNTIF(paint_attempts IS NULL) * 100.0 / COUNT(*), 1) as pct_null
FROM nba_analytics.team_offense_game_summary
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29';
```

**Recovery:** None needed - this is expected degradation. Shot zones will be NULL for historical data.

---

#### Issue 1.3: Odds Data Limited Blocks upcoming_player_game_context

**Scenario:** Only 40% of dates have `odds_api_player_points_props`.

**What happens:**
- `upcoming_player_game_context` runs
- Checks for props data (DRIVER source)
- No props → no players to process → empty output
- For 60% of dates: produces 0 records

**Detection:**
```sql
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  675 as expected_dates,
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 675, 1) as pct_complete
FROM nba_analytics.upcoming_player_game_context;
```

**Recovery Options:**
1. **Accept limitation:** Only ~40% of historical dates will have player context
2. **Modify processor:** Use all players from boxscores instead of props-driven
3. **Investigate odds sources:** May be able to get more historical odds

---

### Category 2: Processing Errors

#### Issue 2.1: Phase 4 Processors Run Out of Order

**Scenario:** Run `player_composite_factors` before `player_shot_zone_analysis`.

**What happens:**
- Composite factors needs shot zone data
- Queries Phase 4 table → empty
- Either fails or produces degraded output

**Detection:**
- Error logs showing missing Phase 4 dependencies
- NULL values in dependent fields

**Prevention:**
- Always run Phase 4 processors in this order:
  1. team_defense_zone_analysis
  2. player_shot_zone_analysis
  3. player_composite_factors
  4. player_daily_cache
  5. ml_feature_store

**Recovery:**
1. Delete bad data from out-of-order processor
2. Run processors in correct order

---

#### Issue 2.2: Processor Fails Mid-Season

**Scenario:** Processing date 50/180 of a season, processor crashes.

**What happens:**
- 49 dates processed successfully
- Date 50 fails
- Remaining 130 dates not processed
- Script may continue (depending on implementation) or stop

**Detection:**
```sql
SELECT
  data_date,
  status,
  errors
FROM nba_reference.processor_run_history
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND data_date BETWEEN '2022-10-01' AND '2023-04-15'
ORDER BY data_date;
```

**Recovery:**
- Backfill is resumable - just re-run the script
- Already-processed dates will be skipped (idempotency)
- Failed date will be retried

---

#### Issue 2.3: Streaming Buffer Conflicts

**Scenario:** Re-running processor for recently processed date.

**What happens:**
- BigQuery streaming buffer active for ~90 seconds after write
- Processor tries to delete + insert
- Conflict with streaming buffer
- Write fails

**Detection:**
- Error: "streaming buffer" in logs
- `rows_skipped` metric in processor stats

**Prevention:**
- Wait 2+ minutes between re-runs of same date
- Use batch load instead of streaming for backfills

**Recovery:**
- Wait and retry
- Non-blocking - next scheduled run will succeed

---

### Category 3: Silent Failures

#### Issue 3.1: Alerts Suppressed in Backfill Mode

**Scenario:** Real error occurs during backfill, but alerts are suppressed.

**What happens:**
- Error occurs in processor
- Backfill mode = true
- Alert suppression kicks in
- No email notification sent
- Error only visible in logs/run_history

**Detection:**
```sql
-- Monitor during backfill
SELECT
  data_date,
  processor_name,
  status,
  errors
FROM nba_reference.processor_run_history
WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND status = 'failed'
ORDER BY started_at DESC;
```

**Prevention:**
- Run monitoring query every 30 minutes during backfill
- Check `processor_run_history` actively

---

#### Issue 3.2: Degraded Quality Not Detected

**Scenario:** Phase 4 runs but produces low-quality output.

**What happens:**
- Phase 3 has gaps (e.g., only 80% complete for lookback window)
- Phase 4 runs (defensive checks disabled in backfill mode)
- Produces records with `quality_score` = 20 (instead of 90+)
- No error, no alert
- Downstream predictions will be less accurate

**Detection:**
```sql
SELECT
  CASE
    WHEN quality_score >= 90 THEN '90-100 (Good)'
    WHEN quality_score >= 70 THEN '70-89 (Acceptable)'
    WHEN quality_score >= 50 THEN '50-69 (Degraded)'
    ELSE '0-49 (Poor)'
  END as quality_bucket,
  COUNT(*) as records,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_precompute.player_shot_zone_analysis
GROUP BY 1
ORDER BY 1;
```

**Prevention:**
- Validate Phase 3 is 100% complete before Phase 4
- Check quality score distribution after Phase 4

---

#### Issue 3.3: Early Season Data Looks Like Failure

**Scenario:** First 7 days of each season have 0 Phase 4 records.

**What happens:**
- Bootstrap period detection kicks in (days 0-6 of season)
- Phase 4 processors skip entirely
- No records written
- Looks like failure but is expected behavior

**Detection:**
```sql
-- Check if gaps are early season
SELECT
  game_date,
  CASE
    WHEN game_date BETWEEN '2021-10-19' AND '2021-10-25' THEN 'Bootstrap 2021-22'
    WHEN game_date BETWEEN '2022-10-18' AND '2022-10-24' THEN 'Bootstrap 2022-23'
    WHEN game_date BETWEEN '2023-10-24' AND '2023-10-30' THEN 'Bootstrap 2023-24'
    WHEN game_date BETWEEN '2024-10-22' AND '2024-10-28' THEN 'Bootstrap 2024-25'
    ELSE 'Should have data'
  END as status
FROM UNNEST(GENERATE_DATE_ARRAY('2021-10-01', '2024-11-29')) as game_date
WHERE game_date NOT IN (
  SELECT DISTINCT analysis_date
  FROM nba_precompute.player_shot_zone_analysis
);
```

**This is expected behavior - not a failure!**

---

### Category 4: Dependency Cascade Issues

#### Issue 4.1: Phase 3 Gaps Block Phase 4

**Scenario:** Phase 3 has 95% coverage, 5% gaps scattered.

**What happens:**
- Phase 4 runs for a date in the gap
- Lookback window needs 15 games
- Only 12 games available (3 in gaps)
- Produces degraded output with `games_used=12`

**Detection:**
```sql
SELECT
  analysis_date,
  player_lookup,
  games_used,
  expected_games,
  completeness_pct
FROM nba_precompute.player_shot_zone_analysis
WHERE completeness_pct < 90
ORDER BY analysis_date;
```

**Prevention:**
- Validate Phase 3 100% complete before Phase 4
- Use gap detection query before starting Phase 4

---

#### Issue 4.2: Season Boundaries Reset Lookback

**Scenario:** Processing Oct 25, 2022 (start of 2022-23 season).

**What happens:**
- Processor looks for last 15 games
- 2022-23 season only has 3 games so far
- 2021-22 data intentionally not used (cross-season)
- Produces record with `games_used=3`, `quality_score=30`

**This is expected behavior!**
- Season boundaries reset rolling averages
- First 2-3 weeks of each season will have degraded quality
- This is statistically correct (players change teams, rules change)

---

## Safeguards Available

### Safeguard 1: Bootstrap Period Handling

**What it does:** Skips Phase 4 processing for days 0-6 of each season.

**How to use:** Automatic - no action needed.

**Documentation:** `docs/01-architecture/bootstrap-period-overview.md`

---

### Safeguard 2: Cascade Control

**What it does:** Prevents automatic Pub/Sub triggers during backfill.

**How to use:**
```bash
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=2022-10-01 \
  --end-date=2023-04-15 \
  --skip-downstream-trigger=true
```

**Documentation:** `docs/01-architecture/pipeline-integrity.md`

---

### Safeguard 3: Backfill Mode

**What it does:**
- Disables defensive checks (gap detection, upstream status)
- Relaxes dependency thresholds (min=1 instead of configured)
- Suppresses non-critical alerts

**How to use:**
```bash
./bin/run_backfill.sh analytics/player_game_summary \
  --backfill-mode=true
```

**Warning:** This means YOU must validate data, not the system.

---

### Safeguard 4: Gap Detection

**What it does:** Checks for missing dates in a range.

**How to use:**
```python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker(bq_client, project_id)
result = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2022, 10, 1),
    end_date=date(2023, 4, 15)
)

if result['has_gaps']:
    print(f"Missing dates: {result['missing_dates']}")
```

---

### Safeguard 5: Processor Run History

**What it does:** Logs every processor run with status, errors, dependencies.

**How to query:**
```sql
SELECT
  data_date,
  processor_name,
  status,
  duration_seconds,
  dependency_check_passed,
  missing_dependencies,
  errors
FROM nba_reference.processor_run_history
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN '2022-10-01' AND '2023-04-15'
ORDER BY data_date, processor_name;
```

---

## Validation Checkpoints

### Checkpoint 1: Before Phase 3

Run this query to validate Phase 2 is ready:

```sql
WITH expected AS (
  SELECT COUNT(DISTINCT game_date) as cnt
  FROM nba_raw.nbac_schedule
  WHERE game_status = 3
    AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
)
SELECT
  table_name,
  actual_dates,
  (SELECT cnt FROM expected) as expected_dates,
  ROUND(actual_dates * 100.0 / (SELECT cnt FROM expected), 1) as pct_complete
FROM (
  SELECT 'nbac_team_boxscore' as table_name, COUNT(DISTINCT game_date) as actual_dates
  FROM nba_raw.nbac_team_boxscore WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'nbac_gamebook_player_stats', COUNT(DISTINCT game_date)
  FROM nba_raw.nbac_gamebook_player_stats WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'bdl_player_boxscores', COUNT(DISTINCT game_date)
  FROM nba_raw.bdl_player_boxscores WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
)
ORDER BY pct_complete ASC;
```

**Required:** All critical tables at 99%+ before proceeding.

---

### Checkpoint 2: Before Phase 4

Run this query to validate Phase 3 is ready:

```sql
SELECT
  table_name,
  actual_dates,
  675 as expected_dates,
  ROUND(actual_dates * 100.0 / 675, 1) as pct_complete
FROM (
  SELECT 'player_game_summary' as table_name, COUNT(DISTINCT game_date) as actual_dates
  FROM nba_analytics.player_game_summary WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'team_defense_game_summary', COUNT(DISTINCT game_date)
  FROM nba_analytics.team_defense_game_summary WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'team_offense_game_summary', COUNT(DISTINCT game_date)
  FROM nba_analytics.team_offense_game_summary WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  -- upcoming tables may be limited due to odds data
)
ORDER BY pct_complete ASC;
```

**Required:**
- player_game_summary, team_defense, team_offense at 99%+
- upcoming tables may be limited (acceptable)

---

### Checkpoint 3: After Phase 4

Check quality score distribution:

```sql
SELECT
  CASE
    WHEN quality_score >= 90 THEN '90-100 (Good)'
    WHEN quality_score >= 70 THEN '70-89 (Acceptable)'
    WHEN quality_score >= 50 THEN '50-69 (Degraded)'
    ELSE '0-49 (Poor/Bootstrap)'
  END as quality_bucket,
  COUNT(*) as records,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_precompute.player_shot_zone_analysis
GROUP BY 1
ORDER BY 1;
```

**Expected:**
- 80%+ in "Good" bucket (after first 30 days of each season)
- "Poor/Bootstrap" only in first weeks of each season

---

### Checkpoint 4: Find All Failures

Check processor run history for failures:

```sql
SELECT
  phase,
  processor_name,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT CAST(data_date AS STRING) LIMIT 5) as sample_failed_dates,
  ARRAY_AGG(DISTINCT SUBSTR(CAST(errors AS STRING), 1, 100) LIMIT 3) as error_samples
FROM nba_reference.processor_run_history
WHERE status = 'failed'
  AND data_date BETWEEN '2021-10-01' AND '2024-11-29'
GROUP BY phase, processor_name
ORDER BY failure_count DESC;
```

**Required:** Understand and resolve each failure before proceeding.

---

## Troubleshooting Guide

### Problem: Processor fails with DependencyError

**Diagnosis:**
```sql
SELECT data_date, errors, missing_dependencies
FROM nba_reference.processor_run_history
WHERE status = 'failed'
  AND errors LIKE '%DependencyError%'
ORDER BY data_date;
```

**Common causes:**
1. Phase 2 data missing for that date
2. Scraper didn't run for that date
3. GCS file missing

**Resolution:**
1. Check what's missing from error message
2. Backfill the missing Phase 1/2 data
3. Re-run the failed processor

---

### Problem: Quality scores are all low

**Diagnosis:**
```sql
SELECT
  analysis_date,
  AVG(quality_score) as avg_quality,
  AVG(games_used) as avg_games_used,
  AVG(expected_games) as avg_expected_games
FROM nba_precompute.player_shot_zone_analysis
GROUP BY analysis_date
HAVING AVG(quality_score) < 50
ORDER BY analysis_date;
```

**Common causes:**
1. Phase 3 has gaps in the lookback window
2. Running Phase 4 before Phase 3 is complete
3. Early season dates (expected behavior)

**Resolution:**
1. Check Phase 3 completeness for the lookback period
2. Fill Phase 3 gaps
3. Re-run Phase 4

---

### Problem: Phase 4 produces 0 records for some dates

**Diagnosis:**
```sql
-- Check if it's bootstrap period
SELECT
  game_date,
  CASE
    WHEN game_date BETWEEN '2021-10-19' AND '2021-10-25' THEN 'Bootstrap - expected'
    WHEN game_date BETWEEN '2022-10-18' AND '2022-10-24' THEN 'Bootstrap - expected'
    WHEN game_date BETWEEN '2023-10-24' AND '2023-10-30' THEN 'Bootstrap - expected'
    WHEN game_date BETWEEN '2024-10-22' AND '2024-10-28' THEN 'Bootstrap - expected'
    ELSE 'Needs investigation'
  END as status
FROM (
  SELECT DISTINCT game_date
  FROM nba_raw.nbac_schedule
  WHERE game_status = 3
    AND game_date NOT IN (
      SELECT DISTINCT analysis_date FROM nba_precompute.player_shot_zone_analysis
    )
);
```

**Common causes:**
1. Bootstrap period (first 7 days of season) - **expected**
2. Phase 3 data missing - needs backfill
3. Processor error - check run_history

---

### Problem: upcoming_player_game_context has very few records

**Diagnosis:**
```sql
SELECT
  (SELECT COUNT(DISTINCT game_date) FROM nba_analytics.upcoming_player_game_context) as actual,
  (SELECT COUNT(DISTINCT game_date) FROM nba_raw.odds_api_player_points_props) as dates_with_odds,
  (SELECT COUNT(DISTINCT game_date) FROM nba_raw.nbac_schedule WHERE game_status = 3) as total_game_dates;
```

**Expected:** `actual` should be close to `dates_with_odds`.

**Cause:** This processor uses odds data as DRIVER. Without odds, it doesn't know which players to process.

**Resolution:** Accept limitation or modify processor logic.

---

## Pre-Flight Checklist

Before starting backfill:

- [ ] Phase 2 critical tables verified 99%+ complete
- [ ] Player boxscore scraper fix deployed (if needed)
- [ ] Phase 4 backfill jobs created
- [ ] Running in tmux/screen session (long-running)
- [ ] Monitoring query ready to run every 30 min
- [ ] This document open for reference
- [ ] Decided: Season-by-season or all-at-once strategy

---

## Quick Commands Reference

### Check current state
```bash
# Phase 2
bq query --use_legacy_sql=false "SELECT 'nbac_team_boxscore', COUNT(DISTINCT game_date) FROM nba_raw.nbac_team_boxscore"

# Phase 3
bq query --use_legacy_sql=false "SELECT 'player_game_summary', COUNT(DISTINCT game_date) FROM nba_analytics.player_game_summary"

# Phase 4
bq query --use_legacy_sql=false "SELECT 'player_shot_zone_analysis', COUNT(DISTINCT analysis_date) FROM nba_precompute.player_shot_zone_analysis"
```

### Run single date (test)
```bash
./bin/run_backfill.sh analytics/player_game_summary \
  --dates=2023-01-15 \
  --skip-downstream-trigger=true
```

### Run date range
```bash
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=2022-10-01 \
  --end-date=2022-10-31 \
  --skip-downstream-trigger=true
```

### Check failures
```bash
bq query --use_legacy_sql=false "
SELECT data_date, processor_name, status
FROM nba_reference.processor_run_history
WHERE status = 'failed'
ORDER BY data_date DESC
LIMIT 20
"
```

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29 21:12 PST
**Next Review:** After first season backfill complete
