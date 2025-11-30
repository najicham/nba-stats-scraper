# Backfill Orchestration Strategy - Error Handling & Cascade Control
**Purpose:** Design strategy for safe backfills with error handling and cascade control
**Created:** 2025-11-27
**Status:** 🎯 Design Document - Needs Implementation
**Priority:** HIGH - Critical for data integrity

---

## 🎯 Problem Statement

**User's Concern:**
> "When backfilling a full season, if date X fails but date X+1 succeeds, date X+1 uses incomplete historical data. How do we prevent this cascade of bad data?"

**Three Related Issues:**

1. **Error Propagation** - Failed date → incomplete data → bad downstream processing
2. **Gap Detection** - Need to detect missing dates in historical data
3. **Cascade Control** - Need to disable Phase 3+ triggering during Phase 1/2 backfills

---

## 📊 Current State Analysis

### What Exists ✅

From `docs/02-operations/backfill-guide.md`:

**1. Recommended Backfill Order:**
```
Phase-by-phase, NOT date-by-date
```

**Why this matters:**
- Complete Phase 1 for ALL dates first
- Then Phase 2 for ALL dates
- Then Phase 3 for ALL dates
- etc.

**Benefit:** If Phase 1 date X fails, Phase 2 never runs for date X

**2. Completeness Checking:**

From `shared/utils/completeness_checker.py`:
- Checks for missing upstream dependencies
- Checks for stale data
- Sets `is_production_ready = FALSE` if incomplete

**3. Backfill Mode Flag:**

From `schemas/bigquery/nba_reference/processor_run_history.sql`:
```sql
backfill_mode BOOLEAN DEFAULT FALSE
```

Processors log whether they're in backfill mode.

### What's Missing ❌

**1. No Pub/Sub Cascade Control**
- Phase 2 processors currently trigger Phase 3 via Pub/Sub
- No flag to disable triggering during backfills
- Can't run "Phase 1/2 only, verify, then trigger Phase 3" workflow

**2. No Automatic Gap Detection**
- Completeness checker checks if upstream data exists
- But doesn't check for GAPS in date ranges
- Example: Phase 3 has Oct 1-10, Oct 15-20 → Missing Oct 11-14!

**3. No Backfill Failure Policy**
- Scripts continue after individual date failures
- No "stop on first error" mode
- No "skip downstream if upstream failed" logic

---

## 🎯 Recommended Solution

### Three-Pronged Approach

#### 1. Cascade Control (Highest Priority)

**Add `--skip-downstream-trigger` flag to all processors:**

```python
# In processor_base.py, analytics_base.py, precompute_base.py

def __init__(self, skip_downstream_trigger=False):
    self.skip_downstream_trigger = skip_downstream_trigger
    # ...

def _trigger_downstream_processing(self):
    """Publish Pub/Sub message to trigger next phase."""
    if self.skip_downstream_trigger:
        logger.info("Skipping downstream trigger (backfill mode)")
        return

    # Normal pub/sub publishing
    self._publish_to_pubsub()
```

**Usage:**
```bash
# Phase 1 backfill - don't trigger Phase 2
python scraper.py --game-date 2023-10-24 --skip-downstream-trigger

# Phase 2 backfill - don't trigger Phase 3
python processor.py --game-date 2023-10-24 --skip-downstream-trigger

# Phase 3 backfill - don't trigger Phase 4
python analytics.py --analysis-date 2023-10-24 --skip-downstream-trigger
```

**Benefit:** Full control over cascades during backfills

#### 2. Date Range Gap Detection (Medium Priority)

**Add `detect_gaps()` function to completeness_checker.py:**

```python
def detect_date_range_gaps(
    table: str,
    date_column: str,
    start_date: date,
    end_date: date,
    bq_client: bigquery.Client
) -> List[date]:
    """
    Detect missing dates in a continuous range.

    Returns:
        List of missing dates between start and end

    Example:
        >>> detect_date_range_gaps(
        ...     'nba_analytics.player_game_summary',
        ...     'game_date',
        ...     date(2023, 10, 1),
        ...     date(2023, 10, 31)
        ... )
        [date(2023, 10, 5), date(2023, 10, 11)]  # Missing Oct 5, 11
    """
    query = f"""
    WITH expected_dates AS (
        SELECT date
        FROM UNNEST(GENERATE_DATE_ARRAY(
            '{start_date}',
            '{end_date}',
            INTERVAL 1 DAY
        )) as date
    ),
    actual_dates AS (
        SELECT DISTINCT DATE({date_column}) as date
        FROM `{table}`
        WHERE DATE({date_column}) >= '{start_date}'
          AND DATE({date_column}) <= '{end_date}'
    )
    SELECT e.date
    FROM expected_dates e
    LEFT JOIN actual_dates a ON e.date = a.date
    WHERE a.date IS NULL
    ORDER BY e.date
    """

    result = bq_client.query(query).result()
    return [row.date for row in result]
```

**Usage in processors:**
```python
# Before processing, check for gaps in dependencies
gaps = detect_date_range_gaps(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2023, 10, 1),
    end_date=analysis_date,  # Today
    bq_client=self.bq_client
)

if gaps:
    logger.error(f"Found {len(gaps)} gaps in upstream data: {gaps[:5]}...")
    raise DependencyError(f"Cannot process {analysis_date}: gaps in historical data")
```

**Benefit:** Prevents processing with incomplete historical data

#### 3. Backfill Error Policy (Lower Priority)

**Add error handling options to backfill scripts:**

```bash
# Option A: Stop on first error (safest)
./backfill_phase2.sh \
    --start-date 2023-10-01 \
    --end-date 2023-10-31 \
    --error-policy stop  # Stop on first error

# Option B: Continue but log failures
./backfill_phase2.sh \
    --start-date 2023-10-01 \
    --end-date 2023-10-31 \
    --error-policy continue  # Keep going, log failures

# Option C: Skip downstream if upstream failed
./backfill_phase2.sh \
    --start-date 2023-10-01 \
    --end-date 2023-10-31 \
    --error-policy skip-deps  # Check processor_run_history for failures
```

**Implementation:**
```bash
#!/bin/bash
# backfill_phase2.sh with error handling

ERROR_POLICY="${1:-stop}"  # stop, continue, skip-deps
START_DATE="$2"
END_DATE="$3"

current_date="$START_DATE"
failed_dates=()

while [[ "$current_date" < "$END_DATE" ]]; do
    echo "Processing $current_date..."

    # Check if upstream phase failed for this date (if skip-deps mode)
    if [[ "$ERROR_POLICY" == "skip-deps" ]]; then
        upstream_failed=$(bq query --format=csv --use_legacy_sql=false \
            "SELECT COUNT(*) FROM processor_run_history
             WHERE data_date = '$current_date'
               AND phase = 'phase_1_scrapers'
               AND status = 'failed'")

        if [[ "$upstream_failed" -gt 0 ]]; then
            echo "  ⚠️  Skipping $current_date: upstream Phase 1 failed"
            failed_dates+=("$current_date")
            current_date=$(date -I -d "$current_date + 1 day")
            continue
        fi
    fi

    # Run processor
    if ! python processor.py --game-date "$current_date" --skip-downstream-trigger; then
        echo "  ❌ Failed: $current_date"
        failed_dates+=("$current_date")

        if [[ "$ERROR_POLICY" == "stop" ]]; then
            echo "Stopping backfill due to error policy: stop"
            echo "Failed dates: ${failed_dates[@]}"
            exit 1
        fi
    else
        echo "  ✅ Success: $current_date"
    fi

    current_date=$(date -I -d "$current_date + 1 day")
done

echo "Backfill complete!"
echo "Failed dates (${#failed_dates[@]}): ${failed_dates[@]}"

if [[ ${#failed_dates[@]} -gt 0 ]]; then
    exit 1
else
    exit 0
fi
```

---

## 🎬 Recommended Backfill Workflow

### Phase-by-Phase with Verification

**Step 1: Backfill Phase 1 (Scrapers)**
```bash
# Run ALL dates for Phase 1, don't trigger Phase 2
for date in $(seq ...); do
    python scraper.py --game-date $date --skip-downstream-trigger
done
```

**Step 2: Verify Phase 1 Complete**
```sql
-- Check for gaps in Phase 1
SELECT
    date,
    COUNT(*) as file_count
FROM nba_raw.nbac_team_boxscore
WHERE game_date BETWEEN '2023-10-01' AND '2023-10-31'
GROUP BY date
ORDER BY date;

-- Expected: 30+ files per date, no missing dates
```

**Step 3: Backfill Phase 2 (Raw Processing)**
```bash
# Phase 1 verified ✅, now run Phase 2
# Still skip downstream (Phase 3)
for date in $(seq ...); do
    python processor.py --game-date $date --skip-downstream-trigger
done
```

**Step 4: Verify Phase 2 Complete**
```sql
-- Check for gaps in Phase 2
WITH expected AS (
    SELECT date
    FROM UNNEST(GENERATE_DATE_ARRAY('2023-10-01', '2023-10-31')) as date
),
actual AS (
    SELECT DISTINCT game_date as date
    FROM nba_raw.player_boxscore_processed
)
SELECT e.date as missing_date
FROM expected e
LEFT JOIN actual a ON e.date = a.date
WHERE a.date IS NULL;

-- Expected: Empty result (no gaps)
```

**Step 5: Trigger Phase 3 (Now Safe!)**
```bash
# Phase 1/2 verified ✅, now run Phase 3
# Can enable downstream triggers now (for Phase 4)
for date in $(seq ...); do
    python analytics.py --analysis-date $date
    # Pub/Sub will auto-trigger Phase 4 and Phase 5
done
```

---

## 📋 Implementation Checklist

### Priority 1: Cascade Control (This Week)

- [ ] Add `skip_downstream_trigger` parameter to ProcessorBase
- [ ] Add `skip_downstream_trigger` parameter to AnalyticsProcessorBase
- [ ] Add `skip_downstream_trigger` parameter to PrecomputeProcessorBase
- [ ] Add `--skip-downstream-trigger` CLI flag to all processors
- [ ] Test: Verify pub/sub messages are NOT sent when flag is set
- [ ] Update backfill scripts to use new flag
- [ ] Document in backfill guide

**Effort:** 4-6 hours
**Benefit:** Immediate control over cascades

### Priority 2: Gap Detection (Next Week)

- [ ] Add `detect_date_range_gaps()` to completeness_checker.py
- [ ] Add gap detection to Phase 3 processors (check Phase 2 gaps)
- [ ] Add gap detection to Phase 4 processors (check Phase 3 gaps)
- [ ] Add gap detection to Phase 5 (check Phase 4 gaps)
- [ ] Create standalone gap detection script for operators
- [ ] Add gap detection SQL queries to monitoring docs

**Effort:** 6-8 hours
**Benefit:** Automatic detection of incomplete data

### Priority 3: Backfill Scripts (Week 3)

- [ ] Create backfill_phase1.sh with error policies
- [ ] Create backfill_phase2.sh with error policies
- [ ] Create backfill_phase3.sh with error policies
- [ ] Create backfill_phase4.sh with error policies
- [ ] Create verify_phase_complete.sh helper script
- [ ] Document error policies in backfill guide

**Effort:** 8-10 hours
**Benefit:** Robust backfill tooling

---

## 🧪 Testing Strategy

### Test 1: Cascade Control

```bash
# Test: Phase 2 should NOT trigger Phase 3
python processor.py --game-date 2023-10-24 --skip-downstream-trigger

# Verify: No Pub/Sub message sent
gcloud pubsub topics list-subscriptions phase3-trigger-topic
# Expected: No new messages
```

### Test 2: Gap Detection

```sql
-- Artificially create a gap (delete one date)
DELETE FROM nba_raw.player_boxscore_processed
WHERE game_date = '2023-10-15';

-- Run Phase 3 processor for Oct 20
-- Expected: Error detected "Gap found: 2023-10-15 missing"
```

### Test 3: Error Policy

```bash
# Test stop policy
./backfill_phase2.sh stop 2023-10-01 2023-10-10

# Manually fail date 5
# Expected: Script stops at date 5, doesn't process dates 6-10
```

---

## 📊 Current vs Future Workflow

### Current Workflow (Risky)

```
Phase 1: Oct 1 → Oct 2 → Oct 3 (FAIL) → Oct 4 → Oct 5
            ↓        ↓        ✗             ↓        ↓
Phase 2: Oct 1 → Oct 2                 Oct 4 → Oct 5
            ↓        ↓                     ↓        ↓
Phase 3: Oct 1 → Oct 2 (uses Oct 1)  Oct 4 (missing Oct 3!) ❌
```

**Problem:** Oct 4 Phase 3 runs with incomplete data (missing Oct 3)

### Future Workflow (Safe) ✅

```
Phase 1:
  Oct 1 ✅ → Oct 2 ✅ → Oct 3 ❌ (STOP!)

  Fix Oct 3 → Re-run Oct 3 ✅

  Continue: Oct 4 ✅ → Oct 5 ✅

  Verify Phase 1: Check for gaps → NONE ✅

Phase 2:
  --skip-downstream-trigger

  Oct 1 ✅ → Oct 2 ✅ → Oct 3 ✅ → Oct 4 ✅ → Oct 5 ✅

  Verify Phase 2: Check for gaps → NONE ✅

Phase 3:
  Enable downstream triggers ✅

  Gap detection: Check Phase 2 has Oct 1-5 → YES ✅

  Oct 1 ✅ → Oct 2 ✅ → Oct 3 ✅ → Oct 4 ✅ → Oct 5 ✅
            ↓                               ↓
  Phase 4 (auto-triggered via Pub/Sub)
```

**Benefit:** All phases have complete data ✅

---

## 💡 Quick Wins (Implement Now)

### 1. Manual Cascade Control (0 hours - Use Now!)

**Workaround until `--skip-downstream-trigger` is implemented:**

```bash
# Disable pub/sub temporarily
gcloud pubsub subscriptions update phase3-trigger-sub --ack-deadline=600 --expiration-period=never --push-endpoint=""

# Run Phase 1/2 backfills
# ...

# Re-enable pub/sub
gcloud pubsub subscriptions update phase3-trigger-sub --push-endpoint="https://..."

# Manually trigger Phase 3
for date in ...; do
    python analytics.py --analysis-date $date
done
```

**Benefit:** Works immediately, no code changes

### 2. Manual Gap Detection (0 hours - Use Now!)

**SQL query to check for gaps:**

```sql
-- Save this as check_gaps.sql
WITH expected_dates AS (
    SELECT date
    FROM UNNEST(GENERATE_DATE_ARRAY(@start_date, @end_date)) as date
),
actual_dates AS (
    SELECT DISTINCT game_date as date
    FROM `nba-props-platform.nba_raw.player_boxscore_processed`
)
SELECT
    e.date as missing_date,
    'player_boxscore_processed' as table_name
FROM expected_dates e
LEFT JOIN actual_dates a ON e.date = a.date
WHERE a.date IS NULL
ORDER BY e.date;
```

**Run between phases:**
```bash
bq query --parameter=start_date:DATE:2023-10-01 \
         --parameter=end_date:DATE:2023-10-31 \
         --use_legacy_sql=false \
         < check_gaps.sql
```

**Benefit:** Catches gaps before next phase runs

### 3. Stop-on-Error Pattern (0 hours - Use Now!)

**Bash script pattern:**

```bash
#!/bin/bash
set -e  # Exit on any error

for date in $(seq ...); do
    python processor.py --game-date $date || {
        echo "FAILED: $date"
        echo "Stopping backfill to prevent cascade"
        exit 1
    }
done
```

**Benefit:** Prevents cascade of bad data

---

## 🎯 Recommendation

**This Week:**
1. ✅ Use manual workarounds (disable pub/sub, SQL gap detection, set -e)
2. 🛠️ Implement `--skip-downstream-trigger` flag (Priority 1, 4-6 hours)
3. 📝 Document current backfill best practices

**Next Week:**
1. 🛠️ Implement automatic gap detection (Priority 2, 6-8 hours)
2. 🧪 Test with bootstrap period backfills

**Week 3:**
1. 🛠️ Create robust backfill scripts with error policies
2. 📊 Add monitoring/alerting for gaps

**Cost/Benefit:**
- **Immediate:** Use manual workarounds (0 hours, prevents bad data now)
- **Short-term:** Implement flags (10 hours, robust control)
- **Long-term:** Full automation (20 hours total, production-grade)

---

**Status:** 🎯 Design Complete - Ready for Implementation
**Priority:** HIGH - Critical for data integrity
**Estimated Effort:** 20 hours total (10 hours for core features)
**ROI:** Prevents data corruption, saves debugging time, enables confident backfills

Your concerns are 100% valid and this is a critical operational issue! The manual workarounds can be used immediately while we implement the proper solution.
