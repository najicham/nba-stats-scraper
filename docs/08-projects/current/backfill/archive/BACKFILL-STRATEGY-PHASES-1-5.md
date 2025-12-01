# Comprehensive Backfill Strategy: Phases 1-5

**Created:** 2025-11-28
**Status:** Planning
**Target:** 2021-22 NBA Season (Oct 2021 - June 2022)
**Owner:** Engineering Team

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Phase Overview](#phase-overview)
3. [Backfill Strategy by Phase](#backfill-strategy)
4. [Error Handling & Recovery](#error-handling)
5. [Quality Requirements](#quality-requirements)
6. [Implementation Checklist](#implementation-checklist)
7. [Scripts & Tools](#scripts-tools)
8. [Timeline & Estimates](#timeline)

---

## 🎯 Executive Summary {#executive-summary}

### Objective
Backfill 4 NBA seasons (2021-22 through 2024-25) across all 5 processing phases with comprehensive quality checks and error recovery.

### Approach: Staged Backfill with Quality Gates

```
STAGE 1: Phase 1-2 (Batch with Retry)
├─ Batch load all Phase 1 & 2 for entire season
├─ Retry failed dates automatically (1 retry attempt)
├─ Continue on errors (collect failures for later investigation)
└─ QUALITY GATE: 100% completeness verification before proceeding

STAGE 2: Investigate & Fix
├─ Review all Phase 1-2 failures
├─ Fix issues manually
└─ Re-run failed dates until 100% complete

STAGE 3: Phase 3-4 (Sequential with Defensive Checks)
├─ Process Phase 3 date-by-date (auto-triggers Phase 4 via Pub/Sub)
├─ Defensive checks ENABLED (gap detection, upstream failure detection)
├─ STOP on any error (don't continue to next date)
└─ Fix and retry before continuing

STAGE 4: Validation
├─ Verify all phases complete
├─ Validate data quality across all tables
└─ Generate completeness reports
```

### Key Principles

1. **Safety First:** Never let bad data cascade through phases
2. **Quality Gates:** Verify completeness at each phase boundary
3. **Defensive Checks:** Phase 3 & 4 block processing if upstream incomplete
4. **Automated Retry:** Retry transient failures automatically in Phase 1-2
5. **Manual Fix:** Investigate and fix persistent failures before Phase 3
6. **Phase 5 Exclusion:** Phase 5 (Predictions) is forward-looking only, not part of backfill

---

## 🏗️ Phase Overview {#phase-overview}

### Pipeline Architecture

```
Phase 1: Scrapers (Web → GCS)
   ↓ (pub/sub: scraper-complete)
Phase 2: Raw Processors (GCS → BigQuery nba_raw)
   ↓ (pub/sub: nba-phase2-raw-complete) [OPTIONAL with --skip-downstream-trigger]
Phase 3: Analytics (nba_raw → BigQuery nba_analytics)
   ↓ (pub/sub: nba-phase3-analytics-complete) [OPTIONAL with --skip-downstream-trigger]
Phase 4: Precompute (nba_analytics → BigQuery nba_precompute)
   ↓ (NOT USED - Phase 5 uses Cloud Scheduler, not cascade)
Phase 5: Predictions (FORWARD-LOOKING ONLY - not part of historical backfill)
```

### Dependencies by Phase

| Phase | Depends On | Cross-Date Dependencies | Pub/Sub Trigger |
|-------|-----------|------------------------|-----------------|
| **Phase 1** | External APIs | None | ✅ Yes (to Phase 2) |
| **Phase 2** | Phase 1 (GCS files) | None (single-date) | ✅ Yes (to Phase 3) |
| **Phase 3** | Phase 2 (nba_raw) | ✅ Yes (lookback windows 10-15 games) | ✅ Yes (to Phase 4) |
| **Phase 4** | Phase 3 (nba_analytics) | ✅ Yes (lookback windows 30+ games) | ❌ No |
| **Phase 5** | Phase 3 & 4 | Forward-looking only | ❌ No (Cloud Scheduler) |

### Current Quality Checks Status

| Phase | Dependency Checks | Gap Detection | Upstream Failure Check | Completeness Check | Status |
|-------|------------------|---------------|----------------------|-------------------|--------|
| **Phase 2** | Basic | ❌ No | ❌ No | Basic | ✅ Cascade control implemented |
| **Phase 3** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Defensive checks implemented |
| **Phase 4** | ✅ Yes | ❌ **TODO** | ❌ **TODO** | Partial | ⚠️ **Needs defensive checks** |
| **Phase 5** | ✅ Yes | N/A | N/A | N/A | ✅ Production ready (not used in backfill) |

---

## 📦 Backfill Strategy by Phase {#backfill-strategy}

### STAGE 1: Phase 1-2 Batch Load (With Retry & Continue)

**Goal:** Load all raw data for the season quickly, collecting failures for later investigation.

**Error Policy:**
- ✅ Retry failed dates once (for transient errors)
- ✅ Continue processing even after failures
- ✅ Log all failures for Stage 2 investigation
- ✅ Use `--skip-downstream-trigger` to prevent Phase 3 cascade

**Script:** `bin/backfill/backfill_phase1_phase2.sh`

```bash
#!/bin/bash
# backfill_phase1_phase2.sh
# Backfill Phase 1 & 2 for specified season with retry and continue-on-error

set +e  # DON'T exit on error (continue processing)

SEASON="2021-22"
START_DATE="2021-10-19"
END_DATE="2022-06-17"  # Include playoffs
MAX_RETRIES=1

# Initialize failure tracking
FAILED_DATES_LOG="backfill_failures_${SEASON}.log"
> "$FAILED_DATES_LOG"  # Clear log

echo "═══════════════════════════════════════════════════════════"
echo "STAGE 1: Phase 1-2 Backfill for $SEASON"
echo "Date Range: $START_DATE to $END_DATE"
echo "Error Policy: Retry once, then continue"
echo "═══════════════════════════════════════════════════════════"

# Get all game dates from schedule
GAME_DATES=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT DISTINCT game_date
   FROM \`nba-props-platform.nba_raw.nbac_schedule\`
   WHERE game_date >= '$START_DATE'
     AND game_date <= '$END_DATE'
     AND game_status = 3
   ORDER BY game_date" | tail -n +2)  # Skip CSV header

TOTAL_DATES=$(echo "$GAME_DATES" | wc -l)
CURRENT=0
SUCCESS_COUNT=0
FAILURE_COUNT=0

for game_date in $GAME_DATES; do
  CURRENT=$((CURRENT + 1))
  echo ""
  echo "[$CURRENT/$TOTAL_DATES] Processing $game_date..."
  echo "─────────────────────────────────────────────────────────"

  # Process Phase 2 (Phase 1 scrapers already ran)
  # Use --skip-downstream-trigger to prevent Phase 3 cascade

  # Try Phase 2 processor
  ATTEMPT=1
  SUCCESS=false

  while [ $ATTEMPT -le $((MAX_RETRIES + 1)) ]; do
    echo "  Attempt $ATTEMPT of $((MAX_RETRIES + 1))..."

    # Run Phase 2 processor (example: nbac_player_boxscore)
    # Add other Phase 2 processors as needed
    if python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
        --date "$game_date" \
        --skip-downstream-trigger; then
      echo "  ✅ Success on attempt $ATTEMPT"
      SUCCESS=true
      break
    else
      echo "  ❌ Failed on attempt $ATTEMPT"
      ATTEMPT=$((ATTEMPT + 1))

      if [ $ATTEMPT -le $((MAX_RETRIES + 1)) ]; then
        echo "  ⏳ Waiting 5 seconds before retry..."
        sleep 5
      fi
    fi
  done

  if [ "$SUCCESS" = true ]; then
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    echo "  ⚠️  FAILED after $MAX_RETRIES retries - logging for investigation"
    echo "$game_date" >> "$FAILED_DATES_LOG"
    FAILURE_COUNT=$((FAILURE_COUNT + 1))
  fi

  # Progress update
  echo "  Progress: $SUCCESS_COUNT success, $FAILURE_COUNT failed"
done

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "STAGE 1 COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo "Total dates:    $TOTAL_DATES"
echo "Successful:     $SUCCESS_COUNT"
echo "Failed:         $FAILURE_COUNT"
echo ""

if [ $FAILURE_COUNT -gt 0 ]; then
  echo "⚠️  FAILURES DETECTED"
  echo "Failed dates logged to: $FAILED_DATES_LOG"
  echo ""
  echo "NEXT STEPS:"
  echo "1. Review failed dates in $FAILED_DATES_LOG"
  echo "2. Investigate root causes (check processor_run_history table)"
  echo "3. Fix issues manually"
  echo "4. Re-run failed dates: bin/backfill/retry_failed_dates.sh $FAILED_DATES_LOG"
  echo "5. Verify 100% completeness: bin/backfill/verify_phase2_complete.sh"
  echo ""
  exit 1
else
  echo "✅ ALL DATES SUCCESSFUL"
  echo ""
  echo "NEXT STEPS:"
  echo "1. Verify 100% completeness: bin/backfill/verify_phase2_complete.sh"
  echo "2. Proceed to Phase 3-4: bin/backfill/backfill_phase3_phase4.sh"
  exit 0
fi
```

**Key Features:**
- ✅ Retry logic (1 retry attempt)
- ✅ Continue on error (don't stop entire backfill)
- ✅ Failure logging for investigation
- ✅ Progress tracking
- ✅ `--skip-downstream-trigger` prevents Phase 3 cascade

---

### STAGE 2: Investigate & Fix Phase 1-2 Failures

**Manual Investigation:**

```bash
# View failed dates
cat backfill_failures_2021-22.log

# Check processor run history for a failed date
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  data_date,
  success,
  error_message,
  rows_processed,
  processing_decision,
  created_at
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date = '2021-10-24'
  AND processor_name LIKE '%Boxscore%'
ORDER BY created_at DESC
LIMIT 10
"

# Investigate specific error
# (look at error_message, check GCS files, check source data availability)
```

**Retry Failed Dates:**

Script: `bin/backfill/retry_failed_dates.sh`

```bash
#!/bin/bash
# retry_failed_dates.sh
# Retry all failed dates from a failure log

FAILURE_LOG="$1"

if [ -z "$FAILURE_LOG" ] || [ ! -f "$FAILURE_LOG" ]; then
  echo "Usage: $0 <failure_log_file>"
  exit 1
fi

echo "Retrying failed dates from: $FAILURE_LOG"
echo "─────────────────────────────────────────────"

SUCCESS_COUNT=0
STILL_FAILING=0

while IFS= read -r game_date; do
  echo ""
  echo "Retrying $game_date..."

  if python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
      --date "$game_date" \
      --skip-downstream-trigger; then
    echo "✅ Success"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    echo "❌ Still failing"
    STILL_FAILING=$((STILL_FAILING + 1))
  fi
done < "$FAILURE_LOG"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "RETRY COMPLETE"
echo "Success: $SUCCESS_COUNT"
echo "Still failing: $STILL_FAILING"

if [ $STILL_FAILING -gt 0 ]; then
  echo "⚠️  Some dates still failing - investigate further"
  exit 1
else
  echo "✅ All dates now successful"
  exit 0
fi
```

---

### QUALITY GATE: Phase 2 Completeness Verification

**Script:** `bin/backfill/verify_phase2_complete.sh`

```bash
#!/bin/bash
# verify_phase2_complete.sh
# Verify 100% completeness of Phase 2 before proceeding to Phase 3

SEASON="2021-22"
START_DATE="2021-10-19"
END_DATE="2022-06-17"

echo "═══════════════════════════════════════════════════════════"
echo "QUALITY GATE: Phase 2 Completeness Verification"
echo "Season: $SEASON ($START_DATE to $END_DATE)"
echo "═══════════════════════════════════════════════════════════"

# Use Python with CompletenessChecker for gap detection
python3 << EOF
from datetime import date
from google.cloud import bigquery
from shared.utils.completeness_checker import CompletenessChecker

bq_client = bigquery.Client()
checker = CompletenessChecker(bq_client, 'nba-props-platform')

# Check Phase 2 tables for gaps
tables_to_check = [
    ('nba_raw.nbac_player_boxscore', 'game_date'),
    ('nba_raw.nbac_gamebook_player_stats', 'game_date'),
    # Add other critical Phase 2 tables
]

all_complete = True
for table, date_col in tables_to_check:
    print(f"\nChecking {table}...")
    print("─" * 60)

    result = checker.check_date_range_completeness(
        table=table,
        date_column=date_col,
        start_date=date(2021, 10, 19),
        end_date=date(2022, 6, 17)
    )

    if result['has_gaps']:
        print(f"  ❌ INCOMPLETE: {result['gap_count']} missing dates")
        print(f"     Coverage: {result['coverage_pct']:.1f}%")
        print(f"     Missing: {result['missing_dates'][:10]}...")  # Show first 10
        all_complete = False
    else:
        print(f"  ✅ COMPLETE: 100% coverage")

print("\n" + "═" * 60)
if all_complete:
    print("✅ QUALITY GATE PASSED: Phase 2 100% complete")
    print("\nSafe to proceed to Phase 3-4 backfill")
    exit(0)
else:
    print("❌ QUALITY GATE FAILED: Phase 2 has gaps")
    print("\nDO NOT proceed to Phase 3-4 until gaps are fixed")
    print("\nActions:")
    print("1. Review missing dates above")
    print("2. Investigate root causes")
    print("3. Re-run missing dates")
    print("4. Re-run this verification script")
    exit(1)
EOF
```

**Critical:** Do NOT proceed to Stage 3 until this verification passes!

---

### STAGE 3: Phase 3-4 Sequential Processing (With Defensive Checks)

**Goal:** Process Phase 3 date-by-date, auto-triggering Phase 4 via Pub/Sub. STOP on any error.

**Error Policy:**
- ❌ STOP immediately on any error
- ❌ Do NOT continue to next date
- ✅ Defensive checks ENABLED (gap detection, upstream failure)
- ✅ Fix error before continuing

**Why Sequential:** Phase 3 & 4 have cross-date dependencies (lookback windows). Must ensure each date is complete before processing next date.

**Script:** `bin/backfill/backfill_phase3_phase4.sh`

```bash
#!/bin/bash
# backfill_phase3_phase4.sh
# Sequential Phase 3-4 backfill with defensive checks and strict error handling

set -e  # EXIT on any error (strict mode)

SEASON="2021-22"
START_DATE="2021-10-19"
END_DATE="2022-06-17"

echo "═══════════════════════════════════════════════════════════"
echo "STAGE 3: Phase 3-4 Sequential Backfill for $SEASON"
echo "Date Range: $START_DATE to $END_DATE"
echo "Error Policy: STOP on any error (defensive checks enabled)"
echo "═══════════════════════════════════════════════════════════"

# Get all game dates from schedule
GAME_DATES=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT DISTINCT game_date
   FROM \`nba-props-platform.nba_raw.nbac_schedule\`
   WHERE game_date >= '$START_DATE'
     AND game_date <= '$END_DATE'
     AND game_status = 3
   ORDER BY game_date" | tail -n +2)

TOTAL_DATES=$(echo "$GAME_DATES" | wc -l)
CURRENT=0

for game_date in $GAME_DATES; do
  CURRENT=$((CURRENT + 1))
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "[$CURRENT/$TOTAL_DATES] Processing $game_date"
  echo "═══════════════════════════════════════════════════════════"

  # Process all Phase 3 analytics processors
  # Each will auto-trigger Phase 4 via Pub/Sub (nba-phase3-analytics-complete)
  # Defensive checks are ENABLED by default (strict_mode=true)

  echo ""
  echo "Phase 3: Analytics Processors"
  echo "─────────────────────────────────────────────"

  # 1. Player Game Summary
  echo "  [1/3] player_game_summary..."
  python data_processors/analytics/player_game_summary/player_game_summary_processor.py \
    --start-date "$game_date" \
    --end-date "$game_date" \
    --strict-mode true || {
      echo "❌ FAILED: player_game_summary for $game_date"
      echo "Investigation required before continuing"
      exit 1
    }
  echo "  ✅ player_game_summary complete"

  # 2. Team Defense Summary
  echo "  [2/3] team_defense_game_summary..."
  python data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py \
    --start-date "$game_date" \
    --end-date "$game_date" \
    --strict-mode true || {
      echo "❌ FAILED: team_defense_game_summary for $game_date"
      exit 1
    }
  echo "  ✅ team_defense_game_summary complete"

  # 3. Team Offense Summary
  echo "  [3/3] team_offense_game_summary..."
  python data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py \
    --start-date "$game_date" \
    --end-date "$game_date" \
    --strict-mode true || {
      echo "❌ FAILED: team_offense_game_summary for $game_date"
      exit 1
    }
  echo "  ✅ team_offense_game_summary complete"

  # Phase 4 auto-triggers via Pub/Sub
  # Wait for Phase 4 to complete before next date
  echo ""
  echo "Phase 4: Waiting for auto-triggered precompute processors..."
  echo "(Phase 4 triggered via Pub/Sub: nba-phase3-analytics-complete)"

  # Wait 60 seconds for Phase 4 to complete
  # TODO: Improve this with proper completion checking
  sleep 60

  # Verify Phase 4 completed successfully
  echo "  Verifying Phase 4 completion..."
  python3 << VERIFY_EOF
from datetime import date, datetime, timedelta
from google.cloud import bigquery

bq = bigquery.Client()

# Check if Phase 4 processors completed successfully for this date
query = f"""
SELECT
  processor_name,
  success,
  error_message
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date = '$game_date'
  AND phase = 'phase_4_precompute'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
ORDER BY created_at DESC
"""

results = list(bq.query(query).result())

if not results:
    print(f"  ⚠️  WARNING: No Phase 4 runs found for $game_date")
    print("  (Phase 4 may still be processing...)")
    exit(1)

all_success = all(row.success for row in results)
if not all_success:
    print(f"  ❌ Phase 4 had failures for $game_date:")
    for row in results:
        if not row.success:
            print(f"     - {row.processor_name}: {row.error_message}")
    exit(1)
else:
    print(f"  ✅ Phase 4 complete ({len(results)} processors)")
    exit(0)
VERIFY_EOF

  if [ $? -ne 0 ]; then
    echo "❌ Phase 4 verification failed for $game_date"
    echo "Investigation required before continuing"
    exit 1
  fi

  echo "✅ Date $game_date complete (Phase 3 + Phase 4)"
done

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "STAGE 3 COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo "All dates processed successfully through Phase 3 and Phase 4"
echo ""
echo "NEXT STEPS:"
echo "1. Run final validation: bin/backfill/validate_all_phases.sh"
echo "2. Generate completeness reports"
echo "3. Review data quality metrics"
```

**Key Features:**
- ✅ Sequential date processing (date X complete before date X+1 starts)
- ✅ Defensive checks enabled (`--strict-mode true`)
- ✅ Stop on error (don't cascade bad data)
- ✅ Phase 4 auto-triggered via Pub/Sub
- ✅ Verification of Phase 4 completion before next date

---

## ⚠️ Error Handling & Recovery {#error-handling}

### Error Policies by Stage

| Stage | Error Policy | Retry | Continue on Error | Reason |
|-------|-------------|-------|------------------|---------|
| **Stage 1: Phase 1-2** | Retry once, then continue | ✅ Yes (1 retry) | ✅ Yes | Fast batch load, fix later |
| **Stage 2: Investigation** | Manual fix | N/A | N/A | Investigate root causes |
| **Stage 3: Phase 3-4** | Stop immediately | ❌ No | ❌ No | Prevent cascading bad data |

### Common Failure Scenarios & Recovery

#### Scenario 1: Phase 2 Processor Timeout

**Symptom:** Processor times out querying BigQuery or GCS

**Recovery:**
```bash
# 1. Check processor run history
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date = '2021-10-24'
  AND processor_name = 'NbacPlayerBoxscoreProcessor'
ORDER BY created_at DESC LIMIT 1
"

# 2. Check if source data exists
gsutil ls gs://nba-scrapers-raw-data/nbac_player_boxscore/game_date=2021-10-24/

# 3. Re-run manually
python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
  --date 2021-10-24 \
  --skip-downstream-trigger
```

#### Scenario 2: Phase 3 Blocked by Defensive Check

**Symptom:** Phase 3 raises `DependencyError` due to gap or upstream failure

**Error Message:**
```
⚠️ Analytics BLOCKED: Gap Detected
Missing dates in lookback window: ['2021-10-20', '2021-10-21']
```

**Recovery:**
```bash
# 1. Identify missing dates from error message
MISSING_DATES="2021-10-20 2021-10-21"

# 2. Re-run Phase 2 for missing dates
for date in $MISSING_DATES; do
  python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
    --date "$date" \
    --skip-downstream-trigger
done

# 3. Verify Phase 2 now complete
bin/backfill/verify_phase2_complete.sh

# 4. Retry Phase 3 for blocked date
python data_processors/analytics/player_game_summary/player_game_summary_processor.py \
  --start-date 2021-10-22 \
  --end-date 2021-10-22 \
  --strict-mode true
```

#### Scenario 3: Phase 4 Fails to Trigger

**Symptom:** Phase 3 completes but Phase 4 doesn't run

**Troubleshooting:**
```bash
# 1. Check if Pub/Sub message was published
gcloud pubsub topics list-subscriptions nba-phase3-analytics-complete

# 2. Check Cloud Run service status
gcloud run services list --platform managed --region us-west2 | grep precompute

# 3. Check Cloud Run logs
gcloud run services logs read player-daily-cache-processor --limit 50

# 4. Manually trigger Phase 4 if needed
# (Trigger via Pub/Sub message or direct HTTP request)
```

### Automated Retry Scripts

**Script:** `bin/backfill/retry_all_failures.sh`

```bash
#!/bin/bash
# retry_all_failures.sh
# Query processor_run_history for all failures and retry them

SEASON="2021-22"
START_DATE="2021-10-19"
END_DATE="2022-06-17"
PHASE="${1:-phase_2_raw}"  # Default to Phase 2

echo "Finding all failures for $PHASE between $START_DATE and $END_DATE"

# Query BigQuery for failed runs
FAILED_RUNS=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  DISTINCT data_date,
  processor_name
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE phase = '$PHASE'
  AND data_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND success = false
  AND data_date NOT IN (
    -- Exclude dates that later succeeded
    SELECT data_date
    FROM \`nba-props-platform.nba_reference.processor_run_history\`
    WHERE phase = '$PHASE'
      AND success = true
  )
ORDER BY data_date, processor_name
" | tail -n +2)

if [ -z "$FAILED_RUNS" ]; then
  echo "✅ No failures found"
  exit 0
fi

echo "Found failures:"
echo "$FAILED_RUNS"
echo ""
echo "Retrying..."

# Parse and retry each failure
# (Implementation depends on processor CLI patterns)
# TODO: Implement retry logic based on processor_name
```

---

## 📊 Quality Requirements {#quality-requirements}

### Phase 2 Quality Requirements

**Before proceeding to Phase 3:**
- ✅ 100% date coverage (no gaps)
- ✅ All critical tables populated
- ✅ All processor runs successful

**Tables to verify:**
```python
critical_phase2_tables = [
    'nba_raw.nbac_player_boxscore',
    'nba_raw.nbac_gamebook_player_stats',
    'nba_raw.nbac_team_boxscore',
    'nba_raw.nbac_schedule',
    'nba_raw.espn_team_roster',
]
```

### Phase 3 Quality Requirements

**Defensive checks (automatic):**
- ✅ No gaps in Phase 2 lookback window
- ✅ No upstream Phase 2 failures
- ✅ Completeness threshold met (90%+)

**Manual validation:**
- ✅ All analytics tables have expected row counts
- ✅ No NULL values in critical fields
- ✅ Data matches expected patterns (spot checks)

### Phase 4 Quality Requirements

**Defensive checks (TO BE IMPLEMENTED):**
- ✅ No gaps in Phase 3 lookback window
- ✅ No upstream Phase 3 failures
- ✅ Completeness threshold met (90%+)

**Manual validation:**
- ✅ All precompute tables populated
- ✅ ML feature store has valid features
- ✅ Composite factors within expected ranges

---

## ✅ Implementation Checklist {#implementation-checklist}

### Code Changes Required

- [ ] **Add defensive checks to Phase 4** (`precompute_base.py`)
  - [ ] Add `strict_mode` parameter
  - [ ] Add gap detection (using `CompletenessChecker`)
  - [ ] Add upstream failure detection
  - [ ] Add `DependencyError` exception handling
  - [ ] Add defensive check bypass for backfill mode

- [ ] **Create backfill scripts**
  - [ ] `bin/backfill/backfill_phase1_phase2.sh`
  - [ ] `bin/backfill/verify_phase2_complete.sh`
  - [ ] `bin/backfill/backfill_phase3_phase4.sh`
  - [ ] `bin/backfill/validate_all_phases.sh`

- [ ] **Create retry scripts**
  - [ ] `bin/backfill/retry_failed_dates.sh`
  - [ ] `bin/backfill/retry_all_failures.sh`

### Testing Required

- [ ] Test Phase 2 backfill with simulated failures
- [ ] Test Phase 2 retry logic
- [ ] Test Phase 2 completeness verification (with gaps)
- [ ] Test Phase 3 defensive checks blocking
- [ ] Test Phase 3→4 Pub/Sub cascade
- [ ] Test Phase 4 defensive checks (once implemented)
- [ ] End-to-end test with small date range (1 week)

### Documentation Required

- [ ] Update `docs/02-operations/backfill-guide.md`
- [ ] Create runbook for common failure scenarios
- [ ] Document quality verification queries
- [ ] Create troubleshooting guide for Pub/Sub issues

---

## 🛠️ Scripts & Tools {#scripts-tools}

### Backfill Scripts

| Script | Purpose | Error Policy |
|--------|---------|-------------|
| `backfill_phase1_phase2.sh` | Batch load Phase 1-2 | Retry + Continue |
| `backfill_phase3_phase4.sh` | Sequential Phase 3-4 | Stop on error |
| `verify_phase2_complete.sh` | Quality gate | N/A |
| `validate_all_phases.sh` | Final validation | N/A |

### Retry Scripts

| Script | Purpose |
|--------|---------|
| `retry_failed_dates.sh` | Retry dates from failure log |
| `retry_all_failures.sh` | Query DB and retry all failures |

### Verification Scripts

| Script | Purpose |
|--------|---------|
| `check_phase_completeness.py` | Check gaps for any phase |
| `validate_data_quality.py` | Validate data quality metrics |

---

## ⏱️ Timeline & Estimates {#timeline}

### Time Estimates (2021-22 Season: ~250 game dates)

| Stage | Phase | Duration | Notes |
|-------|-------|----------|-------|
| **Stage 1** | Phase 1-2 Batch | 4-6 hours | Parallel processing possible |
| **Stage 2** | Investigation & Fix | 2-4 hours | Depends on failure count |
| **GATE** | Verification | 10 minutes | Automated |
| **Stage 3** | Phase 3-4 Sequential | 12-18 hours | ~3 min per date * 250 dates |
| **TOTAL** | | **18-28 hours** | ~1-2 days |

### Parallelization Opportunities

**Phase 1-2:** Can parallelize across dates (each date independent)
```bash
# Example: Run 10 dates in parallel
seq 1 10 | xargs -P 10 -I {} bash -c 'process_date.sh date_{}'
```

**Phase 3-4:** CANNOT parallelize (cross-date dependencies require sequential processing)

---

## 🚀 Execution Plan

### Step-by-Step Execution

```bash
# STAGE 1: Phase 1-2 Batch Load
./bin/backfill/backfill_phase1_phase2.sh

# STAGE 2: Investigate & Fix (if failures occurred)
# Manual investigation...
./bin/backfill/retry_failed_dates.sh backfill_failures_2021-22.log

# QUALITY GATE: Verify 100% completeness
./bin/backfill/verify_phase2_complete.sh
# ❌ If fails: Fix issues and re-verify
# ✅ If passes: Proceed to Stage 3

# STAGE 3: Phase 3-4 Sequential Processing
./bin/backfill/backfill_phase3_phase4.sh

# FINAL VALIDATION
./bin/backfill/validate_all_phases.sh
```

---

## 📞 Support & Troubleshooting

### Key References

- **Pipeline Integrity:** `docs/08-projects/current/pipeline-integrity/BACKFILL-STRATEGY.md`
- **Bootstrap Period:** `docs/08-projects/current/bootstrap-period/README.md`
- **Processor Run History:** `docs/07-monitoring/run-history-guide.md`

### Monitoring Queries

```sql
-- Check backfill progress
SELECT
  phase,
  processor_name,
  COUNT(DISTINCT data_date) as dates_processed,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
  SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date BETWEEN '2021-10-19' AND '2022-06-17'
GROUP BY phase, processor_name
ORDER BY phase, processor_name
```

---

**Status:** Ready for Implementation
**Priority:** HIGH
**Owner:** Engineering Team
**Created:** 2025-11-28
