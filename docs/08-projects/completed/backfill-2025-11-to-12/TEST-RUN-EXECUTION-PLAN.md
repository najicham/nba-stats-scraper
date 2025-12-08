# Test Run Execution Plan - 14-Day Validation

**Purpose:** Validate complete backfill pipeline before full 4-year execution
**Test Window:** Nov 1-14, 2023 (14 days, Season 2023-24)
**Why This Window:**
- Avoids bootstrap period (Oct 24-30 are first 7 days of 2023-24)
- Has full lookback data available (7+ days into season)
- Tests Phase 4 predictions with sufficient context
- Representative of normal backfill operation

**Expected Duration:** ~2 hours total
**Date:** 2025-11-30

---

## Table of Contents

1. [Pre-Test Verification](#pre-test-verification)
2. [Phase 1: Scrapers (Optional)](#phase-1-scrapers-optional)
3. [Phase 2: Raw Processors (Verify)](#phase-2-raw-processors-verify)
4. [Phase 3: Analytics (Test)](#phase-3-analytics-test)
5. [Phase 4: Precompute (Test)](#phase-4-precompute-test)
6. [Validation Queries](#validation-queries)
7. [Expected Results](#expected-results)
8. [Troubleshooting](#troubleshooting)

---

## Pre-Test Verification

### Step 0.1: Verify Phase 2 Data Exists

**Check if raw data already exists for test window:**

```bash
# Check if Phase 2 data exists for Nov 1-14, 2023
bq query --use_legacy_sql=false "
SELECT
  'nbac_gamebook_player_stats' as source,
  COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT
  'nbac_team_boxscore',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT
  'bigdataball_play_by_play',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT
  'bettingpros_player_points_props',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
ORDER BY source
"
```

**Expected:** All sources should show ~14 dates

**If data missing:** Skip to [Phase 1: Scrapers](#phase-1-scrapers-optional)
**If data exists:** Skip to [Phase 3: Analytics](#phase-3-analytics-test)

### Step 0.2: Verify Current State

```bash
# Check Phase 3 current state
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as phase3_dates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
"

# Check Phase 4 current state
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT analysis_date) as phase4_dates
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN '2023-11-01' AND '2023-11-14'
"
```

**Expected:**
- Phase 3: Some dates may exist (from current production)
- Phase 4: Likely 0 dates (hasn't been run yet)

---

## Phase 1: Scrapers (Optional)

> **Skip this if Phase 2 data already exists for Nov 1-14, 2023**

### When to Run Phase 1

**Run scrapers ONLY if:**
- Phase 2 verification shows missing dates
- You want to test end-to-end from raw data collection

**Skip scrapers if:**
- Phase 2 data already exists (most likely)
- Just testing Phase 3 → Phase 4 pipeline

### If Running Scrapers (Not Recommended for Test)

**Estimated time:** 30+ minutes
**Better approach:** Use existing Phase 2 data

If you must run scrapers, follow existing scraper backfill procedures.
**For this test, we assume Phase 2 data exists.**

---

## Phase 2: Raw Processors (Verify)

> **Most likely: Phase 2 data already exists, just verify it**

### Step 2.1: Verify Phase 2 Completeness

```bash
# Run comprehensive Phase 2 check
bq query --use_legacy_sql=false "
WITH expected AS (
  SELECT COUNT(DISTINCT game_date) as cnt
  FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
  WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
)
SELECT
  'Expected dates (from gamebook)' as metric,
  (SELECT cnt FROM expected) as value
UNION ALL
SELECT
  'Player stats (gamebook)',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT
  'Team stats (nbac)',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT
  'Shot zones (bigdataball)',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT
  'Props (bettingpros)',
  COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
ORDER BY metric
"
```

**Expected results:**
```
metric                          | value
Expected dates                  | 14
Player stats (gamebook)         | 14
Team stats (nbac)              | 14
Shot zones (bigdataball)       | 13-14 (94% coverage = ~13)
Props (bettingpros)            | 14
```

**Decision:**
- ✅ If all critical sources (player/team stats) = 14 → **Proceed to Phase 3**
- ⚠️ If missing dates → Investigate before proceeding

---

## Phase 3: Analytics (Test)

**Goal:** Process 14 dates through all 5 Phase 3 analytics processors

**Estimated time:** 15-30 minutes
**Processing mode:** PARALLEL (all 5 processors can run simultaneously)
**Trigger mode:** MANUAL (skip Pub/Sub triggers)

### Step 3.1: Run All 5 Phase 3 Processors in Parallel

**Option A: Parallel execution (faster, recommended)**

```bash
# Terminal 1: Player Game Summary
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Terminal 2: Team Defense
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Terminal 3: Team Offense
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Terminal 4: Upcoming Player Context
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Terminal 5: Upcoming Team Context
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode
```

**Option B: Sequential execution (simpler, slower)**

```bash
# Run one at a time
for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  echo "Processing: $processor"
  PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/$processor/${processor}_analytics_backfill.py \
    --start-date 2023-11-01 \
    --end-date 2023-11-14 \
    --backfill-mode
done
```

### Step 3.2: Monitor Phase 3 Progress

**In separate terminal:**

```bash
# Watch progress in real-time
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py \
  --season 2023-24 \
  --detailed
```

**Expected output:**
```
📊 OVERALL PROGRESS
🔵 Phase 3 (Analytics): 14/209 dates (6.7%)
   [███░░░░░░░░░░░░░░░░░] 6.7%

📋 TABLE-LEVEL PROGRESS
🔵 Phase 3 Analytics:
   ✅ player_game_summary                        14/209 (6.7%)
   ✅ team_defense_game_summary                  14/209 (6.7%)
   ✅ team_offense_game_summary                  14/209 (6.7%)
   ✅ upcoming_player_game_context               14/209 (6.7%)
   ✅ upcoming_team_game_context                 14/209 (6.7%)
```

### Step 3.3: Validate Phase 3 Completion

```bash
# Check all Phase 3 tables
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as rows
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT 'team_defense_game_summary',
  COUNT(DISTINCT game_date), COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT 'team_offense_game_summary',
  COUNT(DISTINCT game_date), COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT 'upcoming_player_game_context',
  COUNT(DISTINCT game_date), COUNT(*)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
UNION ALL
SELECT 'upcoming_team_game_context',
  COUNT(DISTINCT game_date), COUNT(*)
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
ORDER BY table_name
"
```

**Expected:**
- All tables: 14 dates
- Rows: Varies by table (players per game, teams per game, etc.)

**Quality Gate:** ✅ All 5 tables must have 14 dates before proceeding to Phase 4

---

## Phase 4: Precompute (Test)

**Goal:** Process 14 dates through all 5 Phase 4 processors

**Estimated time:** 30-60 minutes
**Processing mode:** SEQUENTIAL (strict dependency order)
**Trigger mode:** MANUAL (skip Pub/Sub triggers)

### ⚠️ CRITICAL: Sequential Execution Order

**MUST run in this exact order:**

```
1. team_defense_zone_analysis   (reads Phase 3 only)
2. player_shot_zone_analysis    (reads Phase 3 only)
3. player_composite_factors     (reads #1, #2, Phase 3)
4. player_daily_cache           (reads #1, #2, #3, Phase 3)
5. ml_feature_store             (reads #1-4)
```

**DO NOT run in parallel!** Dependencies will cause failures.

### Step 4.1: Run Phase 4 Processor #1

```bash
# Processor 1: Team Defense Zone Analysis
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Wait for completion, verify success before proceeding
```

**Expected:**
- Processes 14 dates
- No bootstrap skip warnings (Nov 1+ is past day 7)
- Success message for all dates

### Step 4.2: Run Phase 4 Processor #2

```bash
# Processor 2: Player Shot Zone Analysis
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Wait for completion
```

### Step 4.3: Run Phase 4 Processor #3

```bash
# Processor 3: Player Composite Factors
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Wait for completion
```

### Step 4.4: Run Phase 4 Processor #4

```bash
# Processor 4: Player Daily Cache
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Wait for completion
```

### Step 4.5: Run Phase 4 Processor #5

```bash
# Processor 5: ML Feature Store
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2023-11-01 \
  --end-date 2023-11-14 \
  --backfill-mode

# Wait for completion
```

### Step 4.6: Monitor Phase 4 Progress

**In separate terminal (during execution):**

```bash
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py \
  --season 2023-24 \
  --detailed \
  --continuous \
  --interval 30
```

**Expected output (after completion):**
```
🟣 Phase 4 Precompute:
   ✅ team_defense_zone_analysis                 14/209 (6.7%)
   ✅ player_shot_zone_analysis                  14/209 (6.7%)
   ✅ player_composite_factors                   14/209 (6.7%)
   ✅ player_daily_cache                         14/209 (6.7%)
   ✅ ml_feature_store                           14/209 (6.7%)
```

---

## Validation Queries

### Comprehensive Test Validation

```bash
# Run full validation
bq query --use_legacy_sql=false "
WITH test_window AS (
  SELECT '2023-11-01' as start_date, '2023-11-14' as end_date, 14 as expected_dates
)
SELECT
  'Phase 3: player_game_summary' as check_name,
  COUNT(DISTINCT game_date) as dates,
  (SELECT expected_dates FROM test_window) as expected,
  CASE WHEN COUNT(DISTINCT game_date) = (SELECT expected_dates FROM test_window)
       THEN '✅ PASS' ELSE '❌ FAIL' END as status
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN (SELECT start_date FROM test_window) AND (SELECT end_date FROM test_window)

UNION ALL

SELECT
  'Phase 3: team_defense_game_summary',
  COUNT(DISTINCT game_date),
  (SELECT expected_dates FROM test_window),
  CASE WHEN COUNT(DISTINCT game_date) = (SELECT expected_dates FROM test_window)
       THEN '✅ PASS' ELSE '❌ FAIL' END
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date BETWEEN (SELECT start_date FROM test_window) AND (SELECT end_date FROM test_window)

UNION ALL

SELECT
  'Phase 3: team_offense_game_summary',
  COUNT(DISTINCT game_date),
  (SELECT expected_dates FROM test_window),
  CASE WHEN COUNT(DISTINCT game_date) = (SELECT expected_dates FROM test_window)
       THEN '✅ PASS' ELSE '❌ FAIL' END
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date BETWEEN (SELECT start_date FROM test_window) AND (SELECT end_date FROM test_window)

UNION ALL

SELECT
  'Phase 4: player_shot_zone_analysis',
  COUNT(DISTINCT analysis_date),
  (SELECT expected_dates FROM test_window),
  CASE WHEN COUNT(DISTINCT analysis_date) = (SELECT expected_dates FROM test_window)
       THEN '✅ PASS' ELSE '❌ FAIL' END
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN (SELECT start_date FROM test_window) AND (SELECT end_date FROM test_window)

UNION ALL

SELECT
  'Phase 4: player_composite_factors',
  COUNT(DISTINCT game_date),
  (SELECT expected_dates FROM test_window),
  CASE WHEN COUNT(DISTINCT game_date) = (SELECT expected_dates FROM test_window)
       THEN '✅ PASS' ELSE '❌ FAIL' END
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date BETWEEN (SELECT start_date FROM test_window) AND (SELECT end_date FROM test_window)

UNION ALL

SELECT
  'Phase 4: player_daily_cache',
  COUNT(DISTINCT cache_date),
  (SELECT expected_dates FROM test_window),
  CASE WHEN COUNT(DISTINCT cache_date) = (SELECT expected_dates FROM test_window)
       THEN '✅ PASS' ELSE '❌ FAIL' END
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date BETWEEN (SELECT start_date FROM test_window) AND (SELECT end_date FROM test_window)

ORDER BY check_name
"
```

### Check for Failures

```bash
# Check processor_run_history for any failures
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  data_date,
  status,
  TO_JSON_STRING(errors) as error_msg
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date BETWEEN '2023-11-01' AND '2023-11-14'
  AND status = 'failed'
ORDER BY started_at DESC
LIMIT 20
"
```

**Expected:** No rows (0 failures)

### Data Quality Spot Check

```bash
# Check quality scores in Phase 4
bq query --use_legacy_sql=false "
SELECT
  game_date,
  AVG(CAST(quality_score AS FLOAT64)) as avg_quality_score,
  COUNT(*) as player_count
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'
GROUP BY game_date
ORDER BY game_date
"
```

**Expected:**
- Quality scores: 70-95% (reasonable for early season with 7+ days lookback)
- Player count: 200-300 players per day

---

## Expected Results

### Phase 3 (Analytics)

| Table | Dates | Rows (approx) | Notes |
|-------|-------|---------------|-------|
| player_game_summary | 14 | ~3,000 | ~200-250 players/day |
| team_defense_game_summary | 14 | ~420 | 30 teams × 14 days |
| team_offense_game_summary | 14 | ~420 | 30 teams × 14 days |
| upcoming_player_game_context | 14 | ~3,000 | Players with prop lines |
| upcoming_team_game_context | 14 | ~420 | Team-level context |

### Phase 4 (Precompute)

| Table | Dates | Rows (approx) | Notes |
|-------|-------|---------------|-------|
| team_defense_zone_analysis | 14 | ~420 | 30 teams × 14 days |
| player_shot_zone_analysis | 14 | ~3,000 | Active players with shot data |
| player_composite_factors | 14 | ~3,000 | All active players |
| player_daily_cache | 14 | ~3,000 | Rolling averages cached |
| ml_feature_store | 14 | ~3,000 | ML features for predictions |

### Quality Expectations

**Phase 3:**
- ✅ Shot zones: ~94% populated (13/14 days from bigdataball)
- ✅ Props: ~100% populated (14/14 days from BettingPros)
- ✅ Player stats: 100% populated (nbac_gamebook)

**Phase 4:**
- ✅ Quality scores: 70-95% (reasonable for early season)
- ✅ No bootstrap skip warnings (Nov 1+ is past day 7)
- ✅ All dates processed successfully

---

## Troubleshooting

### Issue: Phase 3 Processor Fails

**Check logs:**
```bash
# Check recent errors
bq query --use_legacy_sql=false "
SELECT processor_name, data_date, status, TO_JSON_STRING(errors)
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date BETWEEN '2023-11-01' AND '2023-11-14'
  AND status = 'failed'
ORDER BY started_at DESC
"
```

**Common causes:**
- Missing Phase 2 data (check Step 2.1)
- PYTHONPATH not set (add `PYTHONPATH=$(pwd)`)
- Import errors (check dependencies installed)

### Issue: Phase 4 Dependency Errors

**Symptom:** "Required Phase 3 data not found"

**Fix:**
1. Verify Phase 3 completed (Step 3.3)
2. Check you're running Phase 4 in correct order (Step 4.1-4.5)
3. Wait for each processor to finish before starting next

### Issue: Quality Scores Lower Than Expected

**Symptom:** Quality scores <60%

**Check:**
```bash
# Verify lookback data exists
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as lookback_dates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2023-10-24' AND '2023-10-31'
"
```

**Expected:** 7 dates (the bootstrap period)

**If missing:** Quality scores will be lower (expected behavior)

### Issue: Bootstrap Skip Warnings

**Symptom:** "Skipping 2023-11-01 (bootstrap period)"

**This should NOT happen** - Nov 1 is day 8 of the season

**Fix:**
- Check season_year in code
- Verify season start date detection
- Report as bug if persists

---

## Success Criteria

### Test Passes If:

✅ **Phase 3:**
- All 5 tables have 14 dates
- No critical failures in processor_run_history
- Shot zones present for ~13/14 days (94%)
- Props present for all 14 days

✅ **Phase 4:**
- All 5 tables have 14 dates (or 4 tables if ml_feature_store excluded)
- No bootstrap skip warnings (Nov 1+ is past day 7)
- Quality scores 70-95%
- No dependency errors

✅ **Overall:**
- Validation query shows all ✅ PASS
- Monitor shows 14/14 dates for all processors
- Total execution time <2 hours

### Test Fails If:

❌ Any Phase 3 table has <14 dates
❌ Any Phase 4 table has <14 dates
❌ Bootstrap skip warnings for Nov 1-14
❌ Quality scores <60%
❌ Critical dependency errors
❌ Execution time >3 hours

---

## After Test Success

### Next Steps:

1. **Review results:**
   - Check data quality
   - Verify fallbacks worked (check source_* fields)
   - Review any warnings

2. **Document issues:**
   - Any unexpected behavior
   - Performance bottlenecks
   - Data quality concerns

3. **Decide:**
   - ✅ If all green: Proceed with full 4-year backfill
   - ⚠️ If issues: Fix and re-test
   - 🔴 If major problems: Escalate

4. **Clean up (optional):**
   ```bash
   # If you want to delete test data and re-run
   # (NOT recommended - leaves test data for comparison)
   ```

---

## Quick Reference Commands

### Start Test Run

```bash
# 1. Verify Phase 2
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'"

# 2. Run Phase 3 (choose one processor as example)
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py --start-date 2023-11-01 --end-date 2023-11-14 --backfill-mode

# 3. Monitor
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --season 2023-24 --detailed

# 4. Run Phase 4 (sequential)
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py --start-date 2023-11-01 --end-date 2023-11-14 --backfill-mode

# 5. Validate
bq query --use_legacy_sql=false "SELECT 'player_game_summary', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date BETWEEN '2023-11-01' AND '2023-11-14'"
```

---

**Created:** 2025-11-30
**Test Window:** Nov 1-14, 2023 (14 days)
**Estimated Duration:** 2 hours
**Status:** Ready for execution
