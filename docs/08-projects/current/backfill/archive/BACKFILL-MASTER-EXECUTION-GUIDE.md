# Historical Backfill Master Execution Guide

**Created:** 2025-11-29
**Status:** Ready for Execution
**Scope:** 2020-2024 NBA Seasons (4 years of historical data)
**Estimated Total Time:** 16-26 hours (can split across multiple days)

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Data State](#current-data-state)
3. [Backfill Strategy](#backfill-strategy)
4. [Stage 0: Pre-Backfill Verification](#stage-0-pre-backfill-verification)
5. [Stage 1: Phase 3 Analytics Backfill](#stage-1-phase-3-analytics-backfill)
6. [Stage 2: Phase 4 Precompute Backfill](#stage-2-phase-4-precompute-backfill)
7. [Stage 3: Current Season Setup](#stage-3-current-season-setup)
8. [Monitoring & Progress Tracking](#monitoring-progress-tracking)
9. [Quality Gates](#quality-gates)
10. [Troubleshooting](#troubleshooting)

---

## 🎯 Executive Summary {#executive-summary}

### Objective
Backfill 4 seasons of NBA historical data (2020-2024) to enable:
- Complete analytics across all historical seasons
- Full precompute features for predictions
- End-to-end validation of pipeline
- Production-ready system with complete historical context

### Scope: 638 Game Dates

```
Historical Seasons (Oct 2020 - Jun 2024):
┌──────┬─────────────┬──────────────┬──────────────┬───────────────┐
│ Year │ Total Games │ Phase 2 (✅) │ Phase 3 (⚠️) │ Phase 4 (❌)  │
├──────┼─────────────┼──────────────┼──────────────┼───────────────┤
│ 2021 │     72      │   72 (100%) │   34 (47%)  │    0 (0%)    │
│ 2022 │    215      │  215 (100%) │   91 (42%)  │    0 (0%)    │
│ 2023 │    205      │  205 (100%) │  112 (55%)  │    0 (0%)    │
│ 2024 │    146      │  146 (100%) │   74 (51%)  │    0 (0%)    │
├──────┼─────────────┼──────────────┼──────────────┼───────────────┤
│TOTAL │    638      │  638 (100%) │  311 (49%)  │    0 (0%)    │
└──────┴─────────────┴──────────────┴──────────────┴───────────────┘
```

### What Needs Backfilling

- ✅ **Phase 1-2 (Raw Data):** COMPLETE - All 638 dates exist
- ⚠️ **Phase 3 (Analytics):** 327 dates missing (51%)
- ❌ **Phase 4 (Precompute):** 638 dates missing (100%)

### Strategy: Stage-Based with Quality Gates

```
STAGE 0: Pre-Backfill Verification (30 min)
  └─ Verify infrastructure, schemas, Phase 2 completeness

STAGE 1: Phase 3 Analytics Backfill (10-16 hours)
  ├─ Fill 327 missing Phase 3 dates
  ├─ Sequential processing (dependency safety)
  ├─ skip_downstream_trigger=true (don't trigger Phase 4 yet)
  └─ QUALITY GATE: Verify 638/638 Phase 3 dates exist

STAGE 2: Phase 4 Precompute Backfill (6-10 hours)
  ├─ Generate all 638 Phase 4 dates
  ├─ Run after Phase 3 100% verified
  └─ QUALITY GATE: Verify 638/638 Phase 4 dates exist

STAGE 3: Current Season Setup (1 hour)
  ├─ Enable orchestrators for live processing
  ├─ Test end-to-end with current season date
  └─ Validate predictions generate successfully
```

### Timeline

| Stage | Duration | Can Pause? | Dependencies |
|-------|----------|------------|--------------|
| Stage 0 | 30 min | No | None |
| Stage 1 | 10-16 hrs | ✅ Yes | Phase 2 complete |
| Stage 2 | 6-10 hrs | ✅ Yes | Stage 1 complete |
| Stage 3 | 1 hr | No | Stage 2 complete |
| **TOTAL** | **17-27 hrs** | **Can split across 2-3 days** | |

---

## 📊 Current Data State {#current-data-state}

### Actual Coverage (Verified 2025-11-29)

**Phase 2 (Raw Data):** ✅ **100% COMPLETE**
```
2021: 72/72 dates (100%)
2022: 215/215 dates (100%)
2023: 205/205 dates (100%)
2024: 146/146 dates (100%)
Total: 638/638 dates ✅
```

**Phase 3 (Analytics):** ⚠️ **49% COMPLETE**
```
2021: 34/72 dates (47%) - Missing 38 dates
2022: 91/215 dates (42%) - Missing 124 dates
2023: 112/205 dates (55%) - Missing 93 dates
2024: 74/146 dates (51%) - Missing 72 dates
Total: 311/638 dates - Missing 327 dates ⚠️
```

**Phase 4 (Precompute):** ❌ **0% COMPLETE**
```
2021: 0/72 dates (0%)
2022: 0/215 dates (0%)
2023: 0/205 dates (0%)
2024: 0/146 dates (0%)
Total: 0/638 dates ❌
```

### Why This Matters

**Phase 3 Dependencies:**
- Lookback windows: 10-15 games of history
- Cross-date calculations (rolling averages, trends)
- Must process sequentially to satisfy dependencies

**Phase 4 Dependencies:**
- Lookback windows: 30+ games of history
- Requires Phase 3 100% complete
- Defensive checks will block if Phase 3 incomplete

**Conclusion:** Must complete Phase 3 fully before Phase 4

---

## 🎯 Backfill Strategy {#backfill-strategy}

### Core Principles

1. **Stage-Based Processing**
   - Complete each phase fully before moving to next
   - Quality gates between stages
   - Clear visibility of progress

2. **Sequential Within Stages**
   - Process dates in chronological order
   - Satisfies lookback window dependencies
   - Easier to debug and resume

3. **Manual Control**
   - Use `skip_downstream_trigger=true` flag
   - Prevent premature Phase 4 execution
   - Trigger Phase 4 manually after Phase 3 verified

4. **Comprehensive Visibility**
   - Gap analysis before starting
   - Progress tracking during execution
   - Failure detection and recovery
   - Quality verification after each stage

5. **Resumable Design**
   - Track completed dates in processor_run_history
   - Can pause and resume at any point
   - Failure recovery without full restart

### Why This Approach

**✅ Advantages:**
- Clear stage boundaries with quality gates
- No cascading failures across phases
- Easy to identify and fix issues
- Can pause/resume between stages
- Complete visibility at every step

**❌ Previous Approach Issues (Why We Changed):**
- ~~Process all phases for each date~~ - Would trigger Phase 4 prematurely
- ~~Parallel processing~~ - Violates lookback window dependencies
- ~~Auto-trigger orchestrators~~ - Less control, harder to verify completeness

---

## 🔍 Stage 0: Pre-Backfill Verification {#stage-0-pre-backfill-verification}

**Duration:** 30 minutes
**Objective:** Verify all prerequisites before starting backfill

### Checklist

#### 1. Infrastructure Verification

```bash
# Verify schemas
./bin/verify_schemas.sh
# Expected output: ✅ All schemas verified

# Check v1.0 deployment status
gcloud functions describe phase2-to-phase3-orchestrator \
  --region=us-west2 --gen2 --format="value(state)"
# Expected: ACTIVE

gcloud functions describe phase3-to-phase4-orchestrator \
  --region=us-west2 --gen2 --format="value(state)"
# Expected: ACTIVE

gcloud run services describe prediction-coordinator \
  --region=us-west2 --format="value(status.conditions[0].status)"
# Expected: True
```

#### 2. Phase 2 Completeness Verification

```bash
# Run gap analysis query
bq query --use_legacy_sql=false --format=csv '
WITH schedule AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase2 AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  COUNT(DISTINCT s.game_date) as total_dates,
  COUNT(DISTINCT p2.game_date) as phase2_dates,
  COUNT(DISTINCT s.game_date) - COUNT(DISTINCT p2.game_date) as missing
FROM schedule s
LEFT JOIN phase2 p2 ON s.game_date = p2.game_date
'

# Expected output:
# total_dates,phase2_dates,missing
# 638,638,0
```

**If missing > 0:** STOP - Phase 2 incomplete, cannot proceed

#### 3. Phase 3 Gap Analysis

```bash
# Identify exactly which dates are missing
bq query --use_legacy_sql=false --format=csv \
  --max_rows=1000 '
SELECT s.game_date
FROM `nba-props-platform.nba_raw.nbac_schedule` s
WHERE s.game_status = 3
  AND s.game_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND s.game_date NOT IN (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
  )
ORDER BY s.game_date
' > phase3_missing_dates.csv

# Count missing dates
wc -l phase3_missing_dates.csv
# Expected: ~328 lines (327 dates + 1 header)
```

#### 4. Backfill Scripts Verification

```bash
# Verify backfill infrastructure exists
./bin/run_backfill.sh --list

# Expected output should include:
# analytics/player_game_summary
# analytics/team_defense_game_summary
# analytics/team_offense_game_summary
# analytics/upcoming_player_game_context
# analytics/upcoming_team_game_context

# Test with help flag
./bin/run_backfill.sh analytics/player_game_summary --help
# Should show usage and options
```

#### 5. Alert Configuration Check

```bash
# Verify alert suppression system exists
grep -n "backfill_mode" shared/utils/notification_system.py
# Should find backfill_mode parameter

grep -n "skip_downstream_trigger" data_processors/analytics/analytics_base.py
# Should find flag handling
```

### Stage 0 Success Criteria

- [ ] All schemas verified ✅
- [ ] v1.0 infrastructure deployed and ACTIVE ✅
- [ ] Phase 2 completeness: 638/638 dates ✅
- [ ] Phase 3 gap analysis complete: ~327 missing dates identified ✅
- [ ] Backfill scripts verified and working ✅
- [ ] Alert suppression confirmed ✅

**If all checks pass:** Proceed to Stage 1
**If any checks fail:** Fix issues before continuing

---

## 🚀 Stage 1: Phase 3 Analytics Backfill {#stage-1-phase-3-analytics-backfill}

**Duration:** 10-16 hours (327 dates × 2-3 min per date)
**Objective:** Fill all 327 missing Phase 3 analytics dates
**Can Pause:** ✅ Yes - resumable at any point

### Overview

Phase 3 consists of 5 analytics processors:
1. `player_game_summary` - Player stats with context
2. `team_defense_game_summary` - Team defensive metrics
3. `team_offense_game_summary` - Team offensive metrics
4. `upcoming_player_game_context` - Player context for predictions
5. `upcoming_team_game_context` - Team context for predictions

**All 5 must run for each date.**

### Execution Method

#### Option A: Sequential Backfill (RECOMMENDED)

Process one date at a time through all 5 processors.

**Advantages:**
- ✅ Safest for dependencies
- ✅ Easy to debug
- ✅ Easy to resume from failures
- ✅ Clear progress tracking

**Script:**

```bash
#!/bin/bash
# File: bin/backfill/backfill_phase3_historical.sh

set -e  # Exit on error

# Configuration
START_DATE="2020-10-19"
END_DATE="2024-06-17"
LOG_FILE="backfill_phase3_$(date +%Y%m%d_%H%M%S).log"

echo "═══════════════════════════════════════════════════════════"
echo "STAGE 1: Phase 3 Analytics Backfill"
echo "Date Range: $START_DATE to $END_DATE"
echo "Log File: $LOG_FILE"
echo "═══════════════════════════════════════════════════════════"

# Get all game dates from schedule (in order)
GAME_DATES=$(bq query --use_legacy_sql=false --format=csv --max_rows=1000 "
SELECT DISTINCT game_date
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_status = 3
  AND game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND game_date NOT IN (
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  )
ORDER BY game_date
" | tail -n +2)

TOTAL_DATES=$(echo "$GAME_DATES" | wc -l | xargs)
echo "Found $TOTAL_DATES dates to process"
echo ""

CURRENT=0
SUCCESS_COUNT=0
FAILURE_COUNT=0

for game_date in $GAME_DATES; do
  CURRENT=$((CURRENT + 1))
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "[$CURRENT/$TOTAL_DATES] Processing $game_date"
  echo "═══════════════════════════════════════════════════════════"

  # Process all 5 Phase 3 analytics processors for this date
  DATE_SUCCESS=true

  for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
    echo "  [$processor] Processing..."

    if ./bin/run_backfill.sh analytics/$processor \
        --start-date=$game_date \
        --end-date=$game_date \
        --skip-downstream-trigger=true >> "$LOG_FILE" 2>&1; then
      echo "  [$processor] ✅ Success"
    else
      echo "  [$processor] ❌ Failed"
      DATE_SUCCESS=false
      # Continue to next processor (don't exit - process what we can)
    fi
  done

  if [ "$DATE_SUCCESS" = true ]; then
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    echo "✅ Date $game_date complete"
  else
    FAILURE_COUNT=$((FAILURE_COUNT + 1))
    echo "⚠️  Date $game_date had failures - check log"
  fi

  echo "Progress: $SUCCESS_COUNT success, $FAILURE_COUNT failed, $((TOTAL_DATES - CURRENT)) remaining"

  # Small delay to avoid overwhelming BigQuery
  sleep 2
done

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "STAGE 1 COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo "Dates processed: $TOTAL_DATES"
echo "Successful: $SUCCESS_COUNT"
echo "Failed: $FAILURE_COUNT"
echo ""

if [ $FAILURE_COUNT -gt 0 ]; then
  echo "⚠️  FAILURES DETECTED"
  echo "Review log file: $LOG_FILE"
  echo "See BACKFILL-FAILURE-RECOVERY.md for recovery procedures"
  exit 1
else
  echo "✅ ALL DATES SUCCESSFUL"
  echo "Proceed to Quality Gate verification"
  exit 0
fi
```

**To Run:**
```bash
# Make executable
chmod +x bin/backfill/backfill_phase3_historical.sh

# Run backfill
./bin/backfill/backfill_phase3_historical.sh
```

#### Option B: Manual Date-by-Date (For Testing/Recovery)

Process individual dates manually:

```bash
# Process single date
DATE="2023-11-01"

# Run all 5 processors
for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  echo "Processing $processor for $DATE..."
  ./bin/run_backfill.sh analytics/$processor \
    --start-date=$DATE \
    --end-date=$DATE \
    --skip-downstream-trigger=true
done
```

### Progress Monitoring

#### Real-Time Progress Query

Run this periodically during backfill:

```sql
-- Check how many dates have been completed
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
completed AS (
  SELECT COUNT(DISTINCT game_date) as completed_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  c.completed_dates,
  s.total_dates - c.completed_dates as remaining,
  ROUND(100.0 * c.completed_dates / s.total_dates, 1) as pct_complete
FROM schedule s, completed c
```

#### Processor-Level Success Rate

```sql
-- Check success rate by processor
SELECT
  processor_name,
  COUNT(DISTINCT data_date) as dates_processed,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
  SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
  ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND created_at >= TIMESTAMP('2025-11-29 10:00:00')  -- Today's backfill
GROUP BY processor_name
ORDER BY processor_name
```

### Pausing & Resuming

**To Pause:**
- Simply stop the script (Ctrl+C)
- All completed dates are saved in processor_run_history
- Safe to pause at any time

**To Resume:**
- Re-run the script
- It automatically queries for missing dates
- Skips already-completed dates
- Continues from where it left off

### Expected Duration

```
Best case: 327 dates × 2 min/date = 654 min = ~11 hours
Worst case: 327 dates × 3 min/date = 981 min = ~16 hours
Average: ~13 hours
```

**Can split across days:**
- Day 1: Run for 8 hours → ~160-240 dates complete
- Day 2: Resume and complete remaining ~87-167 dates

### Stage 1 Quality Gate

**Before proceeding to Stage 2, verify:**

```sql
-- QUALITY GATE: Phase 3 Must be 100% Complete
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase3 AS (
  SELECT COUNT(DISTINCT game_date) as phase3_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p3.phase3_dates,
  s.total_dates - p3.phase3_dates as missing_dates,
  ROUND(100.0 * p3.phase3_dates / s.total_dates, 1) as completeness_pct,
  CASE
    WHEN p3.phase3_dates = s.total_dates THEN '✅ READY FOR STAGE 2'
    ELSE '⚠️ STAGE 1 INCOMPLETE'
  END as gate_status
FROM schedule s, phase3 p3
```

**Expected Result:**
```
total_dates: 638
phase3_dates: 638
missing_dates: 0
completeness_pct: 100.0
gate_status: ✅ READY FOR STAGE 2
```

**If gate_status is not "READY FOR STAGE 2":**
- Review failures in processor_run_history
- Re-run failed dates
- See BACKFILL-FAILURE-RECOVERY.md for procedures
- Do NOT proceed to Stage 2 until 100% complete

---

## 🔧 Stage 2: Phase 4 Precompute Backfill {#stage-2-phase-4-precompute-backfill}

**Duration:** 6-10 hours (638 dates × 0.5-1 min per date)
**Objective:** Generate all 638 Phase 4 precompute dates
**Prerequisite:** Stage 1 Quality Gate PASSED (Phase 3 100% complete)

### Overview

Phase 4 consists of 5 precompute processors (run in order):
1. `team_defense_zone_analysis` - Team defensive zone metrics
2. `player_shot_zone_analysis` - Player shot distribution
3. `player_composite_factors` - Composite adjustment factors
4. `player_daily_cache` - Cached player data for Phase 5
5. Internal orchestration handles dependencies

### Why After Phase 3 Complete

**Phase 4 defensive checks will BLOCK if:**
- Phase 3 data has gaps in lookback window (30+ days)
- Phase 3 upstream processor failed
- Phase 3 data incomplete

**By completing Phase 3 first:**
- ✅ All Phase 4 defensive checks will pass
- ✅ No blocking or errors
- ✅ Clean execution

### Execution Method

#### Option A: Trigger Via Pub/Sub (RECOMMENDED)

Since Phase 3 is now 100% complete, we can trigger Phase 4 via the orchestrator:

```bash
#!/bin/bash
# File: bin/backfill/backfill_phase4_historical.sh

set -e

echo "═══════════════════════════════════════════════════════════"
echo "STAGE 2: Phase 4 Precompute Backfill"
echo "Method: Manual Pub/Sub trigger for each date"
echo "═══════════════════════════════════════════════════════════"

# Get all dates that need Phase 4
GAME_DATES=$(bq query --use_legacy_sql=false --format=csv --max_rows=1000 "
SELECT DISTINCT game_date
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_status = 3
  AND game_date BETWEEN '2020-10-01' AND '2024-06-17'
ORDER BY game_date
" | tail -n +2)

TOTAL_DATES=$(echo "$GAME_DATES" | wc -l | xargs)
echo "Processing $TOTAL_DATES dates"
echo ""

CURRENT=0

for game_date in $GAME_DATES; do
  CURRENT=$((CURRENT + 1))
  echo "[$CURRENT/$TOTAL_DATES] Triggering Phase 4 for $game_date..."

  # Publish to nba-phase4-trigger topic
  gcloud pubsub topics publish nba-phase4-trigger \
    --message="{\"analysis_date\": \"$game_date\", \"correlation_id\": \"backfill-phase4-$game_date\"}" \
    --project=nba-props-platform

  # Small delay to avoid overwhelming
  sleep 1
done

echo ""
echo "✅ All Phase 4 triggers sent"
echo "Monitor progress with queries in BACKFILL-GAP-ANALYSIS.md"
```

**To Run:**
```bash
chmod +x bin/backfill/backfill_phase4_historical.sh
./bin/backfill/backfill_phase4_historical.sh
```

#### Option B: Direct Processor Calls

Call Phase 4 processors directly:

```bash
# Process single date through Phase 4
DATE="2023-11-01"

python data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py \
  --analysis-date=$DATE

python data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py \
  --analysis-date=$DATE

python data_processors/precompute/player_composite_factors/player_composite_factors_processor.py \
  --analysis-date=$DATE

python data_processors/precompute/player_daily_cache/player_daily_cache_processor.py \
  --analysis-date=$DATE
```

### Progress Monitoring

```sql
-- Check Phase 4 completion progress
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase4 AS (
  SELECT COUNT(DISTINCT game_date) as phase4_dates
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p4.phase4_dates,
  s.total_dates - p4.phase4_dates as remaining,
  ROUND(100.0 * p4.phase4_dates / s.total_dates, 1) as pct_complete
FROM schedule s, phase4 p4
```

### Expected Duration

```
Best case: 638 dates × 0.5 min/date = 319 min = ~5 hours
Worst case: 638 dates × 1 min/date = 638 min = ~11 hours
Average: ~8 hours
```

### Stage 2 Quality Gate

```sql
-- QUALITY GATE: Phase 4 Must be 100% Complete
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase4 AS (
  SELECT COUNT(DISTINCT game_date) as phase4_dates
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total_dates,
  p4.phase4_dates,
  s.total_dates - p4.phase4_dates as missing_dates,
  ROUND(100.0 * p4.phase4_dates / s.total_dates, 1) as completeness_pct,
  CASE
    WHEN p4.phase4_dates = s.total_dates THEN '✅ READY FOR STAGE 3'
    ELSE '⚠️ STAGE 2 INCOMPLETE'
  END as gate_status
FROM schedule s, phase4 p4
```

**Expected Result:**
```
total_dates: 638
phase4_dates: 638
missing_dates: 0
completeness_pct: 100.0
gate_status: ✅ READY FOR STAGE 3
```

---

## 🎯 Stage 3: Current Season Setup {#stage-3-current-season-setup}

**Duration:** 1 hour
**Objective:** Enable orchestrators and validate end-to-end pipeline with current season

### Steps

#### 1. Verify Historical Backfill Complete

```bash
# Run both quality gates
# Stage 1 Quality Gate (from above)
# Stage 2 Quality Gate (from above)
# Both must show 100% completeness
```

#### 2. Enable Orchestrators for Live Processing

The orchestrators are already deployed and active, so no action needed. They will automatically process new dates going forward.

#### 3. Test End-to-End with Current Season Date

```bash
# Pick a recent date from current season (2024-25)
TEST_DATE="2024-11-28"

# Verify Phase 2 exists
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date = '$TEST_DATE'
"
# Expected: count > 0

# Run Phase 3 (will auto-trigger Phase 4 via orchestrator)
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=$TEST_DATE \
  --end-date=$TEST_DATE
  # NOTE: No skip_downstream_trigger flag - let orchestrator work

# Wait 5 minutes for Phase 4 to complete

# Verify Phase 3 exists
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '$TEST_DATE'
"
# Expected: count > 0

# Verify Phase 4 was triggered and completed
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date = '$TEST_DATE'
"
# Expected: count > 0

# Check orchestrator logs
gcloud functions logs read phase3-to-phase4-orchestrator \
  --region=us-west2 \
  --limit=50
# Should see successful orchestration for TEST_DATE
```

#### 4. Validate Current Season

```bash
# Run completeness check for current season
bq query --use_legacy_sql=false "
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total_dates
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_status = 3
    AND game_date >= '2024-10-01'
),
phase3 AS (
  SELECT COUNT(DISTINCT game_date) as phase3_dates
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= '2024-10-01'
),
phase4 AS (
  SELECT COUNT(DISTINCT game_date) as phase4_dates
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date >= '2024-10-01'
)
SELECT
  s.total_dates,
  p3.phase3_dates,
  p4.phase4_dates,
  CASE
    WHEN p3.phase3_dates >= s.total_dates - 2 AND p4.phase4_dates >= s.total_dates - 2
    THEN '✅ Current season ready'
    ELSE '⚠️ Current season incomplete'
  END as status
FROM schedule s, phase3 p3, phase4 p4
"
```

### Stage 3 Success Criteria

- [ ] Historical backfill 100% complete (Stages 1 & 2)
- [ ] Orchestrators active and functioning
- [ ] End-to-end test successful (Phase 2 → 3 → 4 cascade)
- [ ] Current season data up-to-date
- [ ] System ready for daily production processing

---

## 📊 Monitoring & Progress Tracking {#monitoring-progress-tracking}

See `BACKFILL-GAP-ANALYSIS.md` for complete query library.

### Quick Status Check

```sql
-- Overall backfill progress
WITH schedule AS (
  SELECT COUNT(DISTINCT game_date) as total
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3 AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase3 AS (
  SELECT COUNT(DISTINCT game_date) as count
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
),
phase4 AS (
  SELECT COUNT(DISTINCT game_date) as count
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
)
SELECT
  s.total as total_dates,
  p3.count as phase3_complete,
  p4.count as phase4_complete,
  s.total - p3.count as phase3_remaining,
  s.total - p4.count as phase4_remaining
FROM schedule s, phase3 p3, phase4 p4
```

---

## 🚨 Quality Gates {#quality-gates}

### Gate 0: Pre-Backfill (Stage 0)
- [ ] Schemas verified
- [ ] Infrastructure active
- [ ] Phase 2 100% complete (638/638)
- [ ] Gap analysis complete

### Gate 1: Phase 3 Complete (After Stage 1)
- [ ] Phase 3: 638/638 dates (100%)
- [ ] All processors success rate > 99%
- [ ] No unresolved failures

### Gate 2: Phase 4 Complete (After Stage 2)
- [ ] Phase 4: 638/638 dates (100%)
- [ ] All processors success rate > 99%
- [ ] No unresolved failures

### Gate 3: End-to-End Validation (After Stage 3)
- [ ] Current season data up-to-date
- [ ] Orchestrators functioning
- [ ] Phase 2→3→4 cascade working

---

## 🔧 Troubleshooting {#troubleshooting}

See `BACKFILL-FAILURE-RECOVERY.md` for detailed recovery procedures.

### Common Issues

**Issue: Processor fails with "FileNotFoundError"**
- Likely: Phase 2 raw data doesn't exist for that date
- Solution: Verify Phase 2 completeness, may need to backfill that date in Phase 2 first

**Issue: Defensive checks block processing**
- Likely: Gap in lookback window
- Solution: Fill the gap dates first, then retry

**Issue: Query timeout**
- Likely: Processing too many dates in one batch
- Solution: Reduce batch size or process sequentially

**Issue: Script crashes mid-backfill**
- Solution: Simply re-run script - it will resume from last successful date

---

## 📝 Summary

**Total Estimated Time:** 16-26 hours
- Stage 0: 30 min
- Stage 1: 10-16 hours
- Stage 2: 6-10 hours
- Stage 3: 1 hour

**Can Pause/Resume:** ✅ Yes at any point

**Success Criteria:** All quality gates passed, 638/638 dates in Phase 3 and Phase 4

**Next Steps After Completion:**
1. Document completion in handoff doc
2. Archive backfill logs
3. Update monitoring dashboards with historical data
4. Begin using historical data for predictions

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29
**Status:** Ready for Execution
