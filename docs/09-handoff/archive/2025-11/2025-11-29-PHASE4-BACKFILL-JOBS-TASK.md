# Phase 4 Backfill Jobs Creation Task

**Created:** 2025-11-29
**Priority:** CRITICAL - Blocker for historical backfill
**Estimated Time:** 2-3 hours
**Prerequisites:** Review existing Phase 3 backfill jobs as templates

---

## 🎯 Objective

Create 5 backfill job scripts for Phase 4 (Precompute) processors, following the same pattern as existing Phase 3 (Analytics) backfill jobs.

**Why this is critical:** Phase 4 backfill jobs don't exist. Cannot backfill 675 historical dates until these are created.

---

## 📋 Current State

### What Exists ✅
```
backfill_jobs/
├── analytics/
│   ├── player_game_summary/
│   │   └── player_game_summary_analytics_backfill.py ✅ TEMPLATE
│   ├── team_defense_game_summary/
│   ├── team_offense_game_summary/
│   ├── upcoming_player_game_context/
│   └── upcoming_team_game_context/
├── scrapers/ (for reference)
└── precompute/  🔴 EMPTY - NEED TO CREATE
```

### What Needs to be Created 🔴
```
backfill_jobs/precompute/
├── team_defense_zone_analysis/
│   └── team_defense_zone_analysis_precompute_backfill.py
├── player_shot_zone_analysis/
│   └── player_shot_zone_analysis_precompute_backfill.py
├── player_composite_factors/
│   └── player_composite_factors_precompute_backfill.py
├── player_daily_cache/
│   └── player_daily_cache_precompute_backfill.py
└── ml_feature_store/
    └── ml_feature_store_precompute_backfill.py
```

---

## 📖 Reference: Phase 3 Backfill Job Pattern

### Template to Follow

Review this existing job as your template:
```
backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py
```

**Key features it has (Phase 4 jobs must match):**

1. **CLI Arguments:**
   - `--dry-run` - Test without executing
   - `--start-date` - Beginning of date range
   - `--end-date` - End of date range
   - `--dates` - Comma-separated specific dates for retry

2. **Day-by-Day Processing:**
   - Iterates through dates sequentially
   - Processes one date at a time (avoids BigQuery size limits)
   - Logs progress every 10 days

3. **Backfill Mode:**
   - Sets `backfill_mode=True` in processor options
   - Disables defensive checks
   - Relaxes dependency thresholds
   - Suppresses non-critical alerts

4. **Error Tracking:**
   - Tracks failed dates in a list
   - Reports failed dates at end
   - Suggests retry command with `--dates` flag

5. **Progress Logging:**
   - Per-day record counts
   - Success/failure status
   - Elapsed time

6. **Resume Logic:**
   - Can resume from any date
   - Skips already-processed dates (idempotency)

---

## 🔧 Phase 4 Specific Requirements

### Critical Differences from Phase 3

#### 1. **Bootstrap Period Handling** ⚠️ REQUIRED

Phase 4 must **skip the first 7 days of each season**:

```python
# Bootstrap periods to SKIP (return early, don't process)
BOOTSTRAP_PERIODS = [
    (date(2021, 10, 19), date(2021, 10, 25)),  # 2021-22 season start
    (date(2022, 10, 18), date(2022, 10, 24)),  # 2022-23 season start
    (date(2023, 10, 24), date(2023, 10, 30)),  # 2023-24 season start
    (date(2024, 10, 22), date(2024, 10, 28)),  # 2024-25 season start
]

def is_bootstrap_period(analysis_date: date) -> bool:
    """Check if date falls in bootstrap period (should skip)."""
    for start, end in BOOTSTRAP_PERIODS:
        if start <= analysis_date <= end:
            return True
    return False

# In main processing loop:
for current_date in date_range:
    if is_bootstrap_period(current_date):
        logger.info(f"⏭️  Skipping {current_date} (bootstrap period)")
        continue

    # Process the date...
```

**Why:** Phase 4 needs 7+ days of Phase 3 history. First 7 days of season don't have enough context.

#### 2. **Phase 3 Validation Before Processing** ⚠️ RECOMMENDED

Check that Phase 3 data exists for the lookback window:

```python
def validate_phase3_complete(analysis_date: date, lookback_days: int = 30) -> dict:
    """
    Check if Phase 3 has sufficient data for this date's lookback window.

    Returns dict with:
    - complete: bool (True if enough data)
    - available_days: int (how many days of Phase 3 exist)
    - expected_days: int (how many days needed)
    """
    lookback_start = analysis_date - timedelta(days=lookback_days)

    query = f"""
    SELECT COUNT(DISTINCT game_date) as available_days
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date BETWEEN '{lookback_start}' AND '{analysis_date - timedelta(days=1)}'
    """

    result = bq_client.query(query).result()
    row = next(result)
    available_days = row.available_days

    return {
        'complete': available_days >= min(lookback_days * 0.8, 20),  # Need at least 80% or 20 days
        'available_days': available_days,
        'expected_days': lookback_days
    }

# In main loop:
validation = validate_phase3_complete(current_date)
if not validation['complete']:
    logger.warning(f"⚠️  {current_date}: Only {validation['available_days']}/{validation['expected_days']} Phase 3 days available")
    # Continue anyway (processor will handle), but warn
```

**Why:** Prevents running Phase 4 when Phase 3 is incomplete, which would produce degraded quality scores.

#### 3. **Processor-Specific Options**

Each Phase 4 processor may have unique options:

```python
# Example for player_shot_zone_analysis
processor_options = {
    'analysis_date': current_date,
    'backfill_mode': True,
    'skip_downstream_trigger': True,
    # Processor-specific options:
    'min_games': 5,  # Minimum games in lookback
    'quality_threshold': 0,  # Accept any quality in backfill
}
```

Check each processor's `run()` method to see what options it accepts.

---

## 🎯 Required Phase 4 Backfill Jobs

### Job 1: team_defense_zone_analysis

**File:** `backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py`

**Processor:** `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

**Dependencies:**
- Phase 3: `team_defense_game_summary` (lookback: 15 days)

**Lookback Window:** 15 days

**Bootstrap Skip:** YES (first 7 days of each season)

---

### Job 2: player_shot_zone_analysis

**File:** `backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py`

**Processor:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Dependencies:**
- Phase 3: `player_game_summary` (lookback: 10 days)

**Lookback Window:** 10 days

**Bootstrap Skip:** YES (first 7 days of each season)

---

### Job 3: player_composite_factors

**File:** `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py`

**Processor:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Dependencies:**
- Phase 3: `player_game_summary`, `upcoming_player_game_context`
- Phase 4: `team_defense_zone_analysis`, `player_shot_zone_analysis`

**Lookback Window:** 14 days

**Bootstrap Skip:** YES (first 7 days of each season)

**⚠️ CRITICAL:** This processor depends on Phase 4 processors #1 and #2. Must run AFTER them.

---

### Job 4: player_daily_cache

**File:** `backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py`

**Processor:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Dependencies:**
- Phase 3: `player_game_summary`
- Phase 4: All previous Phase 4 tables

**Lookback Window:** 10 days

**Bootstrap Skip:** YES (first 7 days of each season)

**⚠️ CRITICAL:** This processor depends on Phase 4 processors #1, #2, #3. Must run AFTER them.

---

### Job 5: ml_feature_store

**File:** `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py`

**Processor:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Dependencies:**
- Phase 3: All Phase 3 tables
- Phase 4: All Phase 4 tables

**Lookback Window:** 30 days

**Bootstrap Skip:** YES (first 7 days of each season)

**⚠️ CRITICAL:** This processor depends on ALL previous Phase 4 processors. Must run LAST.

---

## 📝 Implementation Checklist

For each of the 5 Phase 4 processors:

- [ ] **Create directory structure**
  ```bash
  mkdir -p backfill_jobs/precompute/{processor_name}
  ```

- [ ] **Create backfill script**
  - Copy `player_game_summary_analytics_backfill.py` as template
  - Update imports to reference correct processor
  - Update processor instantiation
  - Add bootstrap period check
  - Add Phase 3 validation (optional but recommended)
  - Update logging to show processor name

- [ ] **Test dry-run mode**
  ```bash
  python backfill_jobs/precompute/{processor}/...py \
    --dry-run --start-date 2023-11-01 --end-date 2023-11-07
  ```

- [ ] **Test single date**
  ```bash
  python backfill_jobs/precompute/{processor}/...py \
    --dates 2023-11-15
  ```

- [ ] **Verify bootstrap skip works**
  ```bash
  # Should skip without error
  python backfill_jobs/precompute/{processor}/...py \
    --dates 2023-10-24  # First day of 2023-24 season
  ```

---

## 🧪 Testing Requirements

### Test 1: Dry Run (All 5 Jobs)

```bash
# Test each job with --dry-run
for processor in team_defense_zone_analysis player_shot_zone_analysis player_composite_factors player_daily_cache ml_feature_store; do
  echo "Testing $processor..."
  python backfill_jobs/precompute/$processor/${processor}_precompute_backfill.py \
    --dry-run --start-date 2023-11-01 --end-date 2023-11-07
done
```

**Expected:** Each job reports data availability without executing.

---

### Test 2: Bootstrap Period Skip

```bash
# Test that bootstrap periods are skipped
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --dates 2023-10-24,2023-10-25,2023-10-26

# Expected output:
# ⏭️  Skipping 2023-10-24 (bootstrap period)
# ⏭️  Skipping 2023-10-25 (bootstrap period)
# ⏭️  Skipping 2023-10-26 (bootstrap period)
```

---

### Test 3: Single Date Execution (Safe Date)

```bash
# Test actual execution with a single date (not bootstrap, Phase 3 should exist)
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --dates 2023-11-15
```

**Expected:**
- Processes successfully
- Logs show record count
- No errors
- Check BigQuery table has data for that date

---

### Test 4: Sequential Execution (Critical!)

```bash
# Test that Phase 4 processors can run in sequence
DATE="2023-11-15"

# These MUST run in this order:
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py --dates $DATE
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py --dates $DATE
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py --dates $DATE
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py --dates $DATE
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py --dates $DATE
```

**Expected:** Each processor succeeds and can find dependencies from previous processors.

---

## 🎓 Example Implementation

Here's a skeleton for one of the jobs:

```python
#!/usr/bin/env python3
"""
Backfill job for player_shot_zone_analysis (Phase 4 Precompute)

Usage:
  # Dry run
  python player_shot_zone_analysis_precompute_backfill.py --dry-run --start-date 2023-11-01 --end-date 2023-11-07

  # Actual run
  python player_shot_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2022-04-10

  # Retry specific dates
  python player_shot_zone_analysis_precompute_backfill.py --dates 2022-01-05,2022-01-12
"""

import sys
import argparse
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
from shared.clients.bigquery_client import get_bq_client

# Bootstrap periods to skip (first 7 days of each season)
BOOTSTRAP_PERIODS = [
    (date(2021, 10, 19), date(2021, 10, 25)),
    (date(2022, 10, 18), date(2022, 10, 24)),
    (date(2023, 10, 24), date(2023, 10, 30)),
    (date(2024, 10, 22), date(2024, 10, 28)),
]

def is_bootstrap_period(analysis_date: date) -> bool:
    """Check if date falls in bootstrap period."""
    for start, end in BOOTSTRAP_PERIODS:
        if start <= analysis_date <= end:
            return True
    return False

def main():
    parser = argparse.ArgumentParser(description='Backfill player_shot_zone_analysis')
    parser.add_argument('--dry-run', action='store_true', help='Check data availability without processing')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str, help='Comma-separated dates (YYYY-MM-DD,YYYY-MM-DD,...)')
    args = parser.parse_args()

    # Parse dates
    if args.dates:
        dates = [date.fromisoformat(d.strip()) for d in args.dates.split(',')]
    elif args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        dates = [start + timedelta(days=x) for x in range((end - start).days + 1)]
    else:
        print("Error: Provide either --start-date + --end-date or --dates")
        sys.exit(1)

    # Initialize
    bq_client = get_bq_client()
    processor = PlayerShotZoneAnalysisProcessor(bq_client)

    failed_dates = []
    skipped_bootstrap = []

    print(f"Processing {len(dates)} dates...")

    for i, current_date in enumerate(dates, 1):
        # Check bootstrap period
        if is_bootstrap_period(current_date):
            print(f"[{i}/{len(dates)}] ⏭️  Skipping {current_date} (bootstrap period)")
            skipped_bootstrap.append(current_date)
            continue

        if args.dry_run:
            print(f"[{i}/{len(dates)}] 🔍 Would process {current_date}")
            continue

        print(f"[{i}/{len(dates)}] Processing {current_date}...")

        try:
            result = processor.run(
                analysis_date=current_date,
                backfill_mode=True,
                skip_downstream_trigger=True
            )

            if result:
                print(f"  ✅ Success")
            else:
                print(f"  ⚠️  Returned False")
                failed_dates.append(current_date)

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            failed_dates.append(current_date)

    # Summary
    print("\n" + "="*60)
    print("BACKFILL COMPLETE")
    print("="*60)
    print(f"Total dates: {len(dates)}")
    print(f"Skipped (bootstrap): {len(skipped_bootstrap)}")
    print(f"Successful: {len(dates) - len(failed_dates) - len(skipped_bootstrap)}")
    print(f"Failed: {len(failed_dates)}")

    if failed_dates:
        print("\nFailed dates:")
        for d in failed_dates:
            print(f"  - {d}")
        print("\nRetry command:")
        dates_str = ','.join(str(d) for d in failed_dates)
        print(f"  python {__file__} --dates {dates_str}")

if __name__ == '__main__':
    main()
```

---

## 📦 Deliverables

When complete, you should have:

1. **5 Phase 4 backfill job directories**
   ```
   backfill_jobs/precompute/
   ├── team_defense_zone_analysis/
   ├── player_shot_zone_analysis/
   ├── player_composite_factors/
   ├── player_daily_cache/
   └── ml_feature_store/
   ```

2. **5 Working backfill scripts**
   - All support `--dry-run`, `--start-date`, `--end-date`, `--dates`
   - All skip bootstrap periods
   - All set `backfill_mode=True`
   - All track failed dates

3. **Test results documented**
   - Dry run test passed for all 5
   - Bootstrap skip verified
   - Single date execution successful
   - Sequential execution verified

4. **Handoff document**
   ```
   docs/09-handoff/2025-11-29-phase4-backfill-jobs-complete.md
   ```
   - What was created
   - Test results
   - Any issues encountered
   - Ready for backfill execution

---

## 📞 Support

**Reference Documentation:**
- `docs/08-projects/current/backfill/BACKFILL-RUNBOOK.md` - Execution instructions
- `docs/08-projects/current/backfill/BACKFILL-MASTER-PLAN.md` - Overall strategy
- `backfill_jobs/analytics/player_game_summary/` - Template to follow

**Processor Locations:**
- `data_processors/precompute/team_defense_zone_analysis/`
- `data_processors/precompute/player_shot_zone_analysis/`
- `data_processors/precompute/player_composite_factors/`
- `data_processors/precompute/player_daily_cache/`
- `data_processors/precompute/ml_feature_store/` (check if exists)

---

## 🚨 Critical Reminders

1. **Bootstrap periods MUST be skipped** - Phase 4 intentionally doesn't run for first 7 days of season
2. **Processors #3, #4, #5 depend on earlier Phase 4 processors** - Don't parallelize Phase 4!
3. **Follow the template exactly** - Phase 3 jobs work well, match that pattern
4. **Test before full backfill** - Dry run and single date tests are critical

---

**Task Created:** 2025-11-29
**Status:** Ready for New Chat Session
**Priority:** CRITICAL - Blocker for backfill execution
