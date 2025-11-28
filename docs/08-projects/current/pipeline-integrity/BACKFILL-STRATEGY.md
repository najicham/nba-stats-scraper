# Backfill Strategy for NBA Stats Pipeline

**Created:** 2025-11-28
**Status:** Production Ready
**Owner:** Engineering Team

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Historical Backfill Strategy (4 Seasons)](#historical-backfill)
3. [Daily Operations Strategy](#daily-operations)
4. [Defensive Checks Configuration](#defensive-checks)
5. [Phase-by-Phase Details](#phase-details)
6. [Failure Recovery Procedures](#failure-recovery)
7. [Timeline Estimates](#timeline-estimates)

---

## 🎯 Executive Summary {#executive-summary}

### The Challenge

Multi-phase data pipelines with cross-date dependencies require careful coordination during backfills:
- **Phase 2 (Raw):** Independent, single-date processing
- **Phase 3 (Analytics):** Requires lookback windows (e.g., last 10-15 games)
- **Phase 4 (Precompute):** Requires even longer lookbacks (e.g., last 30+ games)
- **Phase 5 (Predictions):** Forward-looking only (not relevant for historical backfills)

### The Solution

**Hybrid Batch-Then-Cascade Approach:**
1. ✅ Batch load ALL Phase 2 (all 4 seasons)
2. ✅ Verify 100% Phase 2 completeness
3. ✅ Process Phase 3 date-by-date (auto-triggers Phase 4)

**Key Features:**
- Uses `--skip-downstream-trigger` for Phase 2 batch loading
- Uses defensive checks (`strict_mode`) for daily operations
- Phase 4 auto-triggered by Phase 3 via Pub/Sub
- Phase 5 uses Cloud Scheduler (not part of backfill workflow)

---

## 📚 Historical Backfill Strategy (4 Seasons) {#historical-backfill}

### Overview

**Target:** Backfill 4 NBA seasons (2021-22 through 2024-25)
**Approach:** Batch Phase 2, then sequential Phase 3+4
**Estimated Time:** 1-2 days total

---

### Step 1: Batch Load Phase 2 (All Seasons)

**Why Batch:** Phase 2 has no cross-date dependencies - each game processes independently.

**Command Pattern:**
```bash
#!/bin/bash
# backfill_phase2_all_seasons.sh

set -e  # Exit on any error

echo "═══════════════════════════════════════════════════════════"
echo "STEP 1: Batch Load Phase 2 (All 4 Seasons)"
echo "═══════════════════════════════════════════════════════════"

for season in "2021-22" "2022-23" "2023-24" "2024-25"; do
  echo ""
  echo "Processing Phase 2 for season $season..."
  echo "----------------------------------------"

  # Determine season start/end dates
  case $season in
    "2021-22")
      START_DATE="2021-10-19"
      END_DATE="2022-04-10"
      ;;
    "2022-23")
      START_DATE="2022-10-18"
      END_DATE="2023-04-09"
      ;;
    "2023-24")
      START_DATE="2023-10-24"
      END_DATE="2024-04-14"
      ;;
    "2024-25")
      START_DATE="2024-10-22"
      END_DATE="2025-04-13"  # Adjust as needed
      ;;
  esac

  # Get all game dates for season (from schedule table)
  GAME_DATES=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT DISTINCT game_date
     FROM \`nba-props-platform.nba_raw.nbac_schedule\`
     WHERE game_date >= '$START_DATE'
       AND game_date <= '$END_DATE'
       AND game_status = 3
     ORDER BY game_date")

  # Process each game date
  for game_date in $GAME_DATES; do
    if [ "$game_date" != "game_date" ]; then  # Skip header
      echo "  Processing $game_date..."

      # Run Phase 2 processor with --skip-downstream-trigger
      python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
        --date $game_date \
        --skip-downstream-trigger

      # Add other Phase 2 processors as needed
    fi
  done

  echo "✅ Season $season Phase 2 complete"
done

echo ""
echo "✅ Phase 2 batch load complete for all 4 seasons!"
```

**Key Points:**
- `--skip-downstream-trigger` prevents Phase 3 auto-trigger
- Processes all dates quickly in parallel (if needed)
- Can be parallelized across multiple workers for speed

**Estimated Time:** 4-6 hours (all 4 seasons, ~1,300 game dates)

---

### Step 2: Verify Phase 2 Completeness

**CRITICAL:** Do NOT proceed to Phase 3 until Phase 2 is 100% complete.

**Verification Script:**
```python
#!/usr/bin/env python3
# verify_phase2_completeness.py

from datetime import date
from google.cloud import bigquery
from shared.utils.completeness_checker import CompletenessChecker

# Initialize
bq_client = bigquery.Client()
checker = CompletenessChecker(bq_client, 'nba-props-platform')

# Define season boundaries
seasons = [
    ('2021-22', date(2021, 10, 19), date(2022, 4, 10)),
    ('2022-23', date(2022, 10, 18), date(2023, 4, 9)),
    ('2023-24', date(2023, 10, 24), date(2024, 4, 14)),
    ('2024-25', date(2024, 10, 22), date(2025, 1, 28)),  # Current
]

print("═" * 70)
print("PHASE 2 COMPLETENESS VERIFICATION")
print("═" * 70)

all_complete = True

for season_name, start_date, end_date in seasons:
    print(f"\n{season_name}: {start_date} to {end_date}")
    print("-" * 70)

    # Check player boxscore completeness
    gaps = checker.check_date_range_completeness(
        table='nba_raw.nbac_player_boxscore',
        date_column='game_date',
        start_date=start_date,
        end_date=end_date
    )

    if gaps['has_gaps']:
        print(f"  ❌ INCOMPLETE: {gaps['gap_count']} missing dates")
        print(f"     Missing: {gaps['missing_dates']}")
        all_complete = False
    else:
        print(f"  ✅ COMPLETE: 100% coverage ({gaps['coverage_pct']}%)")

print("\n" + "═" * 70)
if all_complete:
    print("✅ ALL SEASONS COMPLETE - Safe to proceed to Phase 3")
    exit(0)
else:
    print("❌ GAPS DETECTED - Fix Phase 2 before proceeding")
    exit(1)
```

**Run:**
```bash
python verify_phase2_completeness.py
```

**If Gaps Found:**
1. Review missing dates from output
2. Re-run Phase 2 for those specific dates
3. Re-verify until 100% complete

---

### Step 3: Process Phase 3 Date-by-Date (Auto-triggers Phase 4)

**Why Date-by-Date:** Phase 3 needs complete lookback windows. Processing sequentially ensures each date has full historical context.

**Command Pattern:**
```bash
#!/bin/bash
# backfill_phase3_all_seasons.sh

set -e  # Exit on any error

echo "═══════════════════════════════════════════════════════════"
echo "STEP 3: Process Phase 3 Date-by-Date (Auto-triggers Phase 4)"
echo "═══════════════════════════════════════════════════════════"

for season in "2021-22" "2022-23" "2023-24" "2024-25"; do
  echo ""
  echo "Processing Phase 3+4 for season $season..."
  echo "--------------------------------------------"

  # Get all game dates for season (from schedule)
  GAME_DATES=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT DISTINCT game_date
     FROM \`nba-props-platform.nba_raw.nbac_schedule\`
     WHERE game_date >= '$START_DATE'
       AND game_date <= '$END_DATE'
       AND game_status = 3
     ORDER BY game_date")

  for game_date in $GAME_DATES; do
    if [ "$game_date" != "game_date" ]; then  # Skip header
      echo "  Processing $game_date..."

      # Run Phase 3 (will auto-trigger Phase 4 via Pub/Sub)
      python data_processors/analytics/player_game_summary/player_game_summary_processor.py \
        --start-date $game_date \
        --end-date $game_date
        # NO --skip-downstream-trigger! Let it cascade to Phase 4

      # Wait for Phase 4 to complete via Pub/Sub
      # (monitor Cloud Run logs or use completion tracking)
      sleep 30  # Give Phase 4 time to process

      echo "  ✅ $game_date complete (Phase 3 + Phase 4)"
    fi
  done

  echo "✅ Season $season complete"
done

echo ""
echo "✅ All seasons backfilled through Phase 4!"
```

**Key Points:**
- NO `--skip-downstream-trigger` flag - let Phase 3 → Phase 4 cascade happen
- Process one date at a time to ensure complete lookback windows
- Monitor for failures - if any date fails, fix before continuing

**Estimated Time:** 12-24 hours (sequential processing, ~1,300 dates)

---

### Step 4: Verify Completeness

**Verification Script:**
```bash
# Verify Phase 3
python verify_phase_completeness.py --phase 3 --start 2021-10-19 --end 2025-01-28

# Verify Phase 4
python verify_phase_completeness.py --phase 4 --start 2021-10-19 --end 2025-01-28
```

---

### What About Phase 5?

**Phase 5 is NOT included in historical backfills.**

**Why:**
- Phase 5 is **forward-looking only** (predicts upcoming games)
- Uses Cloud Scheduler trigger (6:15 AM ET daily)
- Queries Phase 3 `upcoming_player_game_context` for today's games
- Not relevant for past dates

**For historical analysis:** Query Phase 4 (`nba_precompute.*`) tables directly.

---

## 🔄 Daily Operations Strategy {#daily-operations}

### Scenario A: Normal Daily Flow

**How It Works:**
```
6:00 AM: Phase 2 scrapers run (yesterday's games)
         ↓ (Pub/Sub trigger)
7:00 AM: Phase 3 analytics processes yesterday
         ↓ (Pub/Sub trigger)
7:30 AM: Phase 4 precompute processes yesterday
         ↓ (No trigger)
6:15 AM: Phase 5 coordinator runs (today's upcoming games) via Cloud Scheduler
```

**Defensive Checks Enabled:**
- Phase 3 runs with `strict_mode=True` (default)
- Checks yesterday's Phase 2 status before processing
- Checks for gaps in lookback window
- **Blocks processing** if problems detected

---

### Scenario B: Same-Day Failure & Retry

**Problem:**
```
Monday 8am:  Phase 2 for Sunday FAILS ❌
Monday 10am: Ops team notices, investigates
```

**Solution:**
```bash
# Simply re-run the failed Phase 2 processor
python phase2_processor.py --game-date 2025-01-26

# Cascade happens automatically:
# Phase 2 → Phase 3 → Phase 4
```

**Result:** Pipeline recovers automatically.

---

### Scenario C: Next Day Runs But Yesterday Failed

**Problem:**
```
Monday:    Phase 2 for Sunday FAILS ❌
Tuesday:   Scheduled Phase 3 for Monday tries to run
           → Needs Sunday in 15-game lookback
           → Sunday is MISSING!
```

**Solution: Defensive Checks Block Processing**

```
🔒 STRICT MODE: Running defensive checks...
⚠️  Upstream processor NbacPlayerBoxscoreProcessor failed for 2025-01-26
❌ Analytics BLOCKED: Upstream Failure

   Resolution: Fix NbacPlayerBoxscoreProcessor for 2025-01-26 first
```

**Process STOPS. Alert sent to ops team.**

**Recovery Steps:**
1. Check alert details for failed date and processor
2. Re-run Phase 2 for the failed date
3. Verify Phase 2 succeeded (check processor_run_history)
4. Manually trigger blocked Phase 3
5. Phase 4 will auto-trigger via Pub/Sub

---

### Scenario D: Gap in Middle of Season

**Problem:**
```
Oct 1-14:  ✅ Complete
Oct 15:    ❌ Missing (scraper failed, never re-run)
Oct 16-30: ✅ Complete
Oct 31:    Phase 3 tries to run
           → Needs Oct 15 in lookback
```

**Solution: Gap Detection Blocks Processing**

```
🔒 STRICT MODE: Running defensive checks...
⚠️  16 gaps in nba_raw.nbac_player_boxscore lookback window
❌ Analytics BLOCKED: Data Gaps

   Missing dates: ['2025-10-15']
   Resolution: Backfill missing dates first
```

**Process STOPS. Alert sent to ops team.**

**Recovery Steps:**
1. Backfill Oct 15 Phase 2
2. Verify Oct 15 Phase 2 complete
3. Backfill Oct 15-31 Phase 3 (to get complete windows)
4. Resume daily operations

---

## 🛡️ Defensive Checks Configuration {#defensive-checks}

### How It Works

Defensive checks are **automatically enabled** in Phase 3 analytics processors:

```python
# In analytics_base.py run() method
strict_mode = self.opts.get('strict_mode', True)  # Default: ENABLED

if strict_mode and not self.is_backfill_mode:
    # DEFENSE 1: Check upstream processor status
    # DEFENSE 2: Check for gaps in data range
    # → Raises DependencyError if problems found
```

### When Defensive Checks Run

**✅ Enabled (blocks processing):**
- Daily scheduled operations
- Manual CLI runs (unless explicitly disabled)
- Production Cloud Run instances

**⏭️ Skipped:**
- Backfill mode (`backfill_mode=True`)
- Explicit disable (`strict_mode=False`)

### Disabling for Testing

```bash
# Disable strict mode for testing/development
python processor.py --start-date 2023-10-15 --end-date 2023-10-15 --strict-mode false
```

**⚠️ Warning:** Only disable for testing. Production should ALWAYS use strict mode.

---

### Configuration Per Processor

Processors can define these attributes to enable defensive checks:

```python
class MyAnalyticsProcessor(AnalyticsProcessorBase):
    # Required for upstream status check
    upstream_processor_name = 'NbacPlayerBoxscoreProcessor'

    # Required for gap detection
    upstream_table = 'nba_raw.nbac_player_boxscore'
    lookback_days = 15  # Check last 15 days for gaps
```

---

## 📊 Phase-by-Phase Details {#phase-details}

### Phase 2 (Raw): Single-Date Processing

**Characteristics:**
- No cross-date dependencies
- Each game processes independently
- Can batch load all dates quickly

**Backfill Strategy:**
- ✅ Batch load entire season at once
- ✅ Use `--skip-downstream-trigger`
- ✅ Verify 100% complete before Phase 3

**Daily Strategy:**
- ✅ Auto-triggered by scrapers via Pub/Sub
- ✅ Retry on failure (no cascading issues)

---

### Phase 3 (Analytics): Lookback Windows

**Characteristics:**
- Requires lookback windows (10-15 games)
- Cross-date dependencies
- Must have complete historical data

**Backfill Strategy:**
- ✅ Process date-by-date (sequential)
- ✅ Let auto-cascade to Phase 4 happen
- ✅ Ensures each date has full lookback window

**Daily Strategy:**
- ✅ Defensive checks enabled (strict_mode)
- ✅ Blocks if upstream failed
- ✅ Blocks if gaps detected
- ✅ Auto-triggered by Phase 2 via Pub/Sub

---

### Phase 4 (Precompute): Longer Lookbacks

**Characteristics:**
- Requires even longer lookbacks (30+ games)
- More complex cross-date dependencies
- Builds on Phase 3 data

**Backfill Strategy:**
- ✅ Auto-triggered by Phase 3 via Pub/Sub
- ✅ No manual intervention needed
- ✅ Processes as Phase 3 completes

**Daily Strategy:**
- ✅ Auto-triggered by Phase 3
- ✅ Inherits Phase 3's defensive check protection
- ✅ No additional checks needed (Phase 3 already validated)

---

### Phase 5 (Predictions): Forward-Looking Only

**Characteristics:**
- Forward-looking predictions for upcoming games
- Uses Cloud Scheduler (not Pub/Sub cascade)
- Queries Phase 3 `upcoming_player_game_context`

**Backfill Strategy:**
- ❌ NOT applicable for historical backfills
- ✅ Only relevant for current/future dates

**Daily Strategy:**
- ✅ Cloud Scheduler triggers at 6:15 AM ET
- ✅ Queries today's upcoming games
- ✅ Independent of Phase 4 completion

---

## 🚨 Failure Recovery Procedures {#failure-recovery}

### Recovery Runbook

#### Alert: "Analytics BLOCKED: Upstream Failure"

**Diagnosis:**
- Yesterday's Phase 2 processor failed
- Phase 3 detected failure via defensive check

**Resolution:**
```bash
# 1. Check alert details for failed date
FAILED_DATE="2025-01-26"  # From alert

# 2. Re-run Phase 2 for failed date
python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
  --date $FAILED_DATE

# 3. Verify Phase 2 succeeded
bq query --use_legacy_sql=false \
  "SELECT status, run_id, errors
   FROM \`nba-props-platform.nba_reference.processor_run_history\`
   WHERE processor_name = 'NbacPlayerBoxscoreProcessor'
     AND data_date = '$FAILED_DATE'
   ORDER BY started_at DESC
   LIMIT 1"

# 4. Manually trigger Phase 3 for blocked date
BLOCKED_DATE="2025-01-27"  # From alert
python data_processors/analytics/player_game_summary/player_game_summary_processor.py \
  --start-date $BLOCKED_DATE \
  --end-date $BLOCKED_DATE

# 5. Phase 4 will auto-trigger via Pub/Sub
# Monitor Cloud Run logs to verify completion
```

---

#### Alert: "Analytics BLOCKED: Data Gaps"

**Diagnosis:**
- Missing dates detected in lookback window
- Phase 3 blocked to prevent incomplete analysis

**Resolution:**
```bash
# 1. Identify missing dates from alert
MISSING_DATES="2025-10-15 2025-10-16"  # From alert

# 2. Backfill missing dates (Phase 2)
for date in $MISSING_DATES; do
  python data_processors/raw/nbacom/nbac_player_boxscore_processor.py \
    --date $date \
    --skip-downstream-trigger
done

# 3. Verify all gaps filled
python verify_phase2_completeness.py \
  --start-date 2025-10-01 \
  --end-date 2025-10-31

# 4. Backfill affected Phase 3 dates
# (All dates from first gap to today)
FIRST_GAP="2025-10-15"
TODAY=$(date +%Y-%m-%d)

python backfill_phase3_range.py \
  --start-date $FIRST_GAP \
  --end-date $TODAY

# 5. Monitor completion
```

---

## ⏱️ Timeline Estimates {#timeline-estimates}

### Historical Backfill (4 Seasons)

| Phase | Task | Time | Notes |
|-------|------|------|-------|
| Phase 2 | Batch load all seasons | 4-6 hours | Parallelizable |
| Verify | Check completeness | 10 minutes | Critical checkpoint |
| Phase 3+4 | Date-by-date processing | 12-24 hours | Sequential, ~1,300 dates |
| **Total** | **End-to-end backfill** | **1-2 days** | Includes verification |

### Daily Operations

| Scenario | Time to Recover | Effort |
|----------|-----------------|--------|
| Same-day retry | 30-60 minutes | Low (simple re-run) |
| Next-day detection | 1-2 hours | Medium (blocked, need recovery) |
| Gap detection | 2-4 hours | High (backfill range) |

---

## 🔗 Related Documents

- **[Pipeline Integrity README](./README.md)** - Project overview
- **[DESIGN.md](./DESIGN.md)** - Technical design
- **[PHASE1-IMPLEMENTATION-SUMMARY.md](./PHASE1-IMPLEMENTATION-SUMMARY.md)** - Cascade control
- **[Handoff Doc](../../../09-handoff/2025-11-27-pipeline-integrity-implementation-handoff.md)** - Implementation guide

---

**Last Updated:** 2025-11-28
**Status:** Production Ready
**Owner:** Engineering Team
