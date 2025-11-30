# Pipeline Integrity - Implementation Plan
**Purpose:** Step-by-step implementation guide with file changes and priorities
**Created:** 2025-11-27
**Status:** 🎯 Ready for Implementation
**Estimated Effort:** 30 hours total

---

## 📋 Implementation Overview

### Three Phases

**Phase 1:** Cascade Control (Backfills) - 6-8 hours
- Add `--skip-downstream-trigger` flag to all processors
- Enable controlled backfill workflows

**Phase 2:** Completeness Enhancements - 12-16 hours
- Add gap detection to CompletenessChecker
- Add upstream failure detection
- Add strict mode option

**Phase 3:** Backfill Tooling - 8-10 hours
- Create robust backfill scripts with error policies
- Add verification helpers
- Update documentation

**Total:** 26-34 hours (estimate: 30 hours)

---

## 🎯 Phase 1: Cascade Control (Priority 1)

**Goal:** Add ability to disable Pub/Sub triggers during backfills

**Effort:** 6-8 hours
**Files to modify:** 3-4 files

### Files to Modify

#### 1. `data_processors/raw/processor_base.py`

**Location:** Line ~537 (`_publish_completion_event`)

**Change:**
```python
class ProcessorBase:
    def __init__(self, skip_downstream_trigger=False):
        """Initialize processor."""
        self.skip_downstream_trigger = skip_downstream_trigger
        # ... existing code

    def _publish_completion_event(self) -> None:
        """
        Publish Phase 2 completion event to trigger Phase 3 analytics.

        Can be disabled with skip_downstream_trigger flag for backfills.
        """
        if self.skip_downstream_trigger:
            logger.info("Skipping downstream trigger (backfill mode)")
            return

        # Existing pub/sub code
        # ...
```

**Add CLI support:**
```python
# In CLI argument parsing
parser.add_argument(
    '--skip-downstream-trigger',
    action='store_true',
    help='Disable Pub/Sub trigger to downstream phase (for backfills)'
)

# Pass to processor
processor = MyProcessor(
    skip_downstream_trigger=args.skip_downstream_trigger
)
```

#### 2. `data_processors/analytics/analytics_base.py`

**Same pattern as above:**

```python
class AnalyticsProcessorBase:
    def __init__(self, skip_downstream_trigger=False):
        """Initialize analytics processor."""
        self.skip_downstream_trigger = skip_downstream_trigger
        # ... existing code

    def _trigger_downstream(self):
        """Trigger Phase 4 precompute processors."""
        if self.skip_downstream_trigger:
            logger.info("Skipping downstream trigger (backfill mode)")
            return

        # Existing trigger code
        # ...
```

#### 3. `data_processors/precompute/precompute_base.py`

**Same pattern:**

```python
class PrecomputeProcessorBase:
    def __init__(self, skip_downstream_trigger=False):
        """Initialize precompute processor."""
        self.skip_downstream_trigger = skip_downstream_trigger
        # ... existing code

    def _trigger_downstream(self):
        """Trigger Phase 5 predictions."""
        if self.skip_downstream_trigger:
            logger.info("Skipping downstream trigger (backfill mode)")
            return

        # Existing trigger code
        # ...
```

#### 4. Update ALL Processor CLIs

**Pattern for each processor:**

```python
# In __main__ section
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # ... existing args
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger (for backfills)'
    )
    args = parser.parse_args()

    # Pass to processor
    processor = MyProcessor(
        skip_downstream_trigger=args.skip_downstream_trigger
    )
```

**Processors to update:**
- All Phase 2 raw processors (~10 processors)
- All Phase 3 analytics processors (~4 processors)
- All Phase 4 precompute processors (~5 processors)

### Testing Checklist

- [ ] Test Phase 2 processor with `--skip-downstream-trigger`
  - Verify: No Pub/Sub message sent
  - Verify: Processing completes normally
- [ ] Test Phase 3 processor with flag
- [ ] Test Phase 4 processor with flag
- [ ] Test normal mode (without flag)
  - Verify: Pub/Sub messages ARE sent
- [ ] Test backfill workflow end-to-end

---

## 🎯 Phase 2: Completeness Enhancements (Priority 2)

**Goal:** Add gap detection and strict mode to CompletenessChecker

**Effort:** 12-16 hours
**Files to modify:** 2 files + tests

### Files to Modify

#### 1. `shared/utils/completeness_checker.py`

**Add new methods (end of class):**

**Method 1: Gap Detection**
```python
def check_date_range_completeness(
    self,
    table: str,
    date_column: str,
    start_date: date,
    end_date: date,
    bq_client: Optional[bigquery.Client] = None
) -> Dict:
    """
    Check for gaps in a continuous date range.

    Returns:
        {
            'has_gaps': bool,
            'missing_dates': List[date],
            'gap_count': int,
            'coverage_pct': float,
            'is_continuous': bool
        }
    """
    bq_client = bq_client or self.bq_client

    query = """
    WITH expected_dates AS (
        SELECT date
        FROM UNNEST(GENERATE_DATE_ARRAY(@start_date, @end_date)) as date
    ),
    actual_dates AS (
        SELECT DISTINCT DATE({date_column}) as date
        FROM `{table}`
        WHERE DATE({date_column}) >= @start_date
          AND DATE({date_column}) <= @end_date
    )
    SELECT e.date as missing_date
    FROM expected_dates e
    LEFT JOIN actual_dates a ON e.date = a.date
    WHERE a.date IS NULL
    ORDER BY e.date
    """.format(date_column=date_column, table=table)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    result = bq_client.query(query, job_config=job_config).result()
    missing_dates = [row.missing_date for row in result]

    expected_days = (end_date - start_date).days + 1
    actual_days = expected_days - len(missing_dates)

    return {
        'has_gaps': len(missing_dates) > 0,
        'missing_dates': missing_dates,
        'gap_count': len(missing_dates),
        'coverage_pct': (actual_days / expected_days) * 100,
        'date_range': (start_date, end_date),
        'is_continuous': len(missing_dates) == 0
    }
```

**Method 2: Upstream Failure Detection**
```python
def check_upstream_processor_status(
    self,
    processor_name: str,
    data_date: date,
    bq_client: Optional[bigquery.Client] = None
) -> Dict:
    """
    Check if upstream processor succeeded for a given date.

    Returns:
        {
            'processor_succeeded': bool,
            'status': str,
            'safe_to_process': bool,
            'error_message': Optional[str]
        }
    """
    bq_client = bq_client or self.bq_client

    query = """
    SELECT status, run_id, started_at, errors
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE processor_name = @processor_name
      AND data_date = @data_date
    ORDER BY started_at DESC
    LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
            bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
        ]
    )

    result = bq_client.query(query, job_config=job_config).result()
    row = next(result, None)

    if not row:
        return {
            'processor_succeeded': False,
            'status': 'not_found',
            'safe_to_process': False,
            'error_message': f'No run found for {processor_name} on {data_date}'
        }

    succeeded = row.status == 'success'
    return {
        'processor_succeeded': succeeded,
        'status': row.status,
        'safe_to_process': succeeded,
        'error_message': str(row.errors) if row.errors else None
    }
```

**Enhancement to existing method:**

Find the `check_completeness()` method signature and add parameters:

```python
def check_completeness(
    self,
    entity_ids: List[str],
    entity_type: str,
    upstream_table: str,
    upstream_entity_field: str,
    analysis_date: date,
    lookback_window: int,
    window_type: str = 'games',
    season_start_date: Optional[date] = None,
    fail_on_incomplete: bool = False,  # NEW
    check_historical_gaps: bool = False,  # NEW
    historical_lookback_days: int = 30,  # NEW
    upstream_processor: Optional[str] = None,  # NEW
    bq_client: Optional[bigquery.Client] = None
) -> Dict:
```

Add at the end of the method (before return):

```python
    # NEW: Check upstream processor status
    if upstream_processor:
        upstream_status = self.check_upstream_processor_status(
            processor_name=upstream_processor,
            data_date=analysis_date
        )

        if not upstream_status['safe_to_process']:
            for entity_id in results:
                results[entity_id]['is_production_ready'] = False

            logger.warning(
                f"Upstream processor '{upstream_processor}' failed or missing"
            )

    # NEW: Check for historical gaps
    if check_historical_gaps:
        gap_start = analysis_date - timedelta(days=historical_lookback_days)
        gap_check = self.check_date_range_completeness(
            table=upstream_table,
            date_column=upstream_entity_field,
            start_date=gap_start,
            end_date=analysis_date
        )

        if gap_check['has_gaps']:
            logger.warning(
                f"Found {gap_check['gap_count']} gaps in historical data"
            )
            for entity_id in results:
                results[entity_id]['is_production_ready'] = False

    # NEW: Fail hard if requested
    if fail_on_incomplete:
        incomplete_entities = [
            eid for eid, r in results.items()
            if not r['is_production_ready']
        ]
        if incomplete_entities:
            raise DependencyError(
                f"Completeness check failed for {len(incomplete_entities)} entities"
            )

    return results
```

**Add exception class at top of file:**

```python
class DependencyError(Exception):
    """Raised when dependency checks fail in strict mode."""
    pass
```

#### 2. Create Tests

**New file:** `tests/unit/completeness/test_gap_detection.py`

```python
"""Tests for completeness checker gap detection."""
import pytest
from datetime import date
from shared.utils.completeness_checker import CompletenessChecker

def test_gap_detection_finds_missing_dates():
    """Test that gap detection identifies missing dates."""
    # Setup: Create test data with gaps
    # ...

    checker = CompletenessChecker()
    result = checker.check_date_range_completeness(
        table='test_table',
        date_column='date',
        start_date=date(2023, 10, 1),
        end_date=date(2023, 10, 20)
    )

    assert result['has_gaps'] == True
    assert result['gap_count'] > 0
    assert result['is_continuous'] == False

def test_no_gaps_returns_continuous():
    """Test that complete data returns is_continuous=True."""
    # Setup: Create complete test data
    # ...

    result = checker.check_date_range_completeness(...)

    assert result['has_gaps'] == False
    assert result['gap_count'] == 0
    assert result['is_continuous'] == True
    assert result['coverage_pct'] == 100.0
```

**New file:** `tests/unit/completeness/test_upstream_failure_detection.py`

```python
"""Tests for upstream processor failure detection."""
import pytest
from datetime import date
from shared.utils.completeness_checker import CompletenessChecker

def test_detects_failed_processor():
    """Test detection of failed upstream processor."""
    # Setup: Insert failed run in processor_run_history
    # ...

    checker = CompletenessChecker()
    result = checker.check_upstream_processor_status(
        processor_name='test_processor',
        data_date=date(2023, 10, 15)
    )

    assert result['processor_succeeded'] == False
    assert result['status'] == 'failed'
    assert result['safe_to_process'] == False

def test_detects_successful_processor():
    """Test detection of successful processor."""
    # Setup: Insert successful run
    # ...

    result = checker.check_upstream_processor_status(...)

    assert result['processor_succeeded'] == True
    assert result['status'] == 'success'
    assert result['safe_to_process'] == True
```

**New file:** `tests/unit/completeness/test_strict_mode.py`

```python
"""Tests for strict mode (fail_on_incomplete)."""
import pytest
from shared.utils.completeness_checker import CompletenessChecker, DependencyError

def test_strict_mode_raises_on_incomplete():
    """Test that strict mode raises exception when data incomplete."""
    checker = CompletenessChecker()

    with pytest.raises(DependencyError):
        checker.check_completeness(
            ...,
            fail_on_incomplete=True  # Should raise
        )

def test_soft_mode_does_not_raise():
    """Test that default mode does not raise exception."""
    checker = CompletenessChecker()

    # Should not raise
    result = checker.check_completeness(
        ...,
        fail_on_incomplete=False  # Default
    )

    assert isinstance(result, dict)
```

### Testing Checklist

- [ ] Unit tests for `check_date_range_completeness()`
- [ ] Unit tests for `check_upstream_processor_status()`
- [ ] Unit tests for strict mode (`fail_on_incomplete`)
- [ ] Integration test with real BigQuery data
- [ ] Backward compatibility test (existing code still works)
- [ ] Performance test (gap checks on large date ranges)

---

## 🎯 Phase 3: Backfill Tooling (Priority 3)

**Goal:** Create production-ready backfill scripts with error handling

**Effort:** 8-10 hours
**Files to create:** 4-6 new scripts

### Scripts to Create

#### 1. `bin/backfill/backfill_phase1.sh`

```bash
#!/bin/bash
# Backfill Phase 1 (scrapers) with error handling

set -e

# Configuration
ERROR_POLICY="${1:-stop}"  # stop, continue
START_DATE="$2"
END_DATE="$3"

if [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
    echo "Usage: $0 <error_policy> <start_date> <end_date>"
    echo "  error_policy: stop (default) | continue"
    echo "  Example: $0 stop 2023-10-01 2023-10-31"
    exit 1
fi

echo "=========================================="
echo "Phase 1 Backfill"
echo "=========================================="
echo "Start Date: $START_DATE"
echo "End Date: $END_DATE"
echo "Error Policy: $ERROR_POLICY"
echo "=========================================="

failed_dates=()
current_date="$START_DATE"

while [[ "$current_date" < "$END_DATE" ]] || [[ "$current_date" == "$END_DATE" ]]; do
    echo ""
    echo "Processing $current_date..."

    # Run all Phase 1 scrapers for this date
    if ! python -m data_processors.raw.scrapers \
        --game-date "$current_date" \
        --skip-downstream-trigger; then

        echo "  ❌ FAILED: $current_date"
        failed_dates+=("$current_date")

        if [[ "$ERROR_POLICY" == "stop" ]]; then
            echo ""
            echo "=========================================="
            echo "STOPPED due to error policy: stop"
            echo "Failed date: $current_date"
            echo "=========================================="
            exit 1
        fi
    else
        echo "  ✅ SUCCESS: $current_date"
    fi

    current_date=$(date -I -d "$current_date + 1 day")
done

echo ""
echo "=========================================="
echo "Phase 1 Backfill Complete"
echo "=========================================="
echo "Failed dates (${#failed_dates[@]}): ${failed_dates[@]}"

if [[ ${#failed_dates[@]} -gt 0 ]]; then
    echo ""
    echo "To retry failed dates:"
    for date in "${failed_dates[@]}"; do
        echo "  $0 stop $date $date"
    done
    exit 1
fi

echo "All dates processed successfully! ✅"
```

#### 2. `bin/backfill/backfill_phase2.sh`

**Similar structure to Phase 1, but for Phase 2 processors**

#### 3. `bin/backfill/backfill_phase3.sh`

**Similar structure for Phase 3 analytics**

#### 4. `bin/backfill/verify_phase_complete.sh`

```bash
#!/bin/bash
# Verify a phase is complete (no gaps)

set -e

PHASE="$1"
START_DATE="$2"
END_DATE="$3"

if [[ -z "$PHASE" ]] || [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
    echo "Usage: $0 <phase> <start_date> <end_date>"
    echo "  phase: phase2 | phase3 | phase4"
    echo "  Example: $0 phase2 2023-10-01 2023-10-31"
    exit 1
fi

# Map phase to table
case "$PHASE" in
    phase2)
        TABLE="nba_raw.player_boxscore_processed"
        DATE_COLUMN="game_date"
        ;;
    phase3)
        TABLE="nba_analytics.player_game_summary"
        DATE_COLUMN="game_date"
        ;;
    phase4)
        TABLE="nba_precompute.player_daily_cache"
        DATE_COLUMN="cache_date"
        ;;
    *)
        echo "Unknown phase: $PHASE"
        exit 1
        ;;
esac

echo "Checking $PHASE for gaps..."
echo "Table: $TABLE"
echo "Date range: $START_DATE to $END_DATE"
echo ""

# Run gap detection query
bq query --use_legacy_sql=false --format=csv \
    "WITH expected AS (
        SELECT date
        FROM UNNEST(GENERATE_DATE_ARRAY('$START_DATE', '$END_DATE')) as date
    ),
    actual AS (
        SELECT DISTINCT DATE($DATE_COLUMN) as date
        FROM \`nba-props-platform.$TABLE\`
    )
    SELECT e.date as missing_date
    FROM expected e
    LEFT JOIN actual a ON e.date = a.date
    WHERE a.date IS NULL
    ORDER BY e.date" > /tmp/gaps.txt

# Check results
gap_count=$(wc -l < /tmp/gaps.txt)
gap_count=$((gap_count - 1))  # Subtract header

if [[ $gap_count -gt 0 ]]; then
    echo "❌ GAPS FOUND: $gap_count missing dates"
    echo ""
    cat /tmp/gaps.txt
    exit 1
else
    echo "✅ NO GAPS: All dates present"
    exit 0
fi
```

#### 5. `bin/backfill/full_backfill_workflow.sh`

**Master script that orchestrates all phases with verification:**

```bash
#!/bin/bash
# Full backfill workflow with verification between phases

set -e

START_DATE="$1"
END_DATE="$2"

echo "=========================================="
echo "Full Backfill Workflow"
echo "=========================================="
echo "Date range: $START_DATE to $END_DATE"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Phase 1
echo ""
echo "========== PHASE 1: Scrapers =========="
./bin/backfill/backfill_phase1.sh stop "$START_DATE" "$END_DATE"
./bin/backfill/verify_phase_complete.sh phase1 "$START_DATE" "$END_DATE"

# Phase 2
echo ""
echo "========== PHASE 2: Raw Processing =========="
./bin/backfill/backfill_phase2.sh stop "$START_DATE" "$END_DATE"
./bin/backfill/verify_phase_complete.sh phase2 "$START_DATE" "$END_DATE"

# Phase 3
echo ""
echo "========== PHASE 3: Analytics =========="
./bin/backfill/backfill_phase3.sh stop "$START_DATE" "$END_DATE"
./bin/backfill/verify_phase_complete.sh phase3 "$START_DATE" "$END_DATE"

# Phase 4 (can enable downstream triggers now)
echo ""
echo "========== PHASE 4: Precompute =========="
./bin/backfill/backfill_phase4.sh stop "$START_DATE" "$END_DATE"
./bin/backfill/verify_phase_complete.sh phase4 "$START_DATE" "$END_DATE"

echo ""
echo "=========================================="
echo "✅ FULL BACKFILL COMPLETE"
echo "=========================================="
```

#### 6. Make all scripts executable

```bash
chmod +x bin/backfill/*.sh
```

### Testing Checklist

- [ ] Test Phase 1 backfill script with stop policy
- [ ] Test Phase 1 backfill script with continue policy
- [ ] Test verify script detects gaps
- [ ] Test verify script passes when complete
- [ ] Test full workflow with small date range (3 days)
- [ ] Document usage in operations guide

---

## 📝 Documentation Updates

### Update Existing Docs

#### 1. `docs/02-operations/backfill-guide.md`

**Add section:**
```markdown
## Using --skip-downstream-trigger Flag

During backfills, use this flag to prevent automatic Pub/Sub cascades:

\`\`\`bash
# Phase 2 backfill - don't trigger Phase 3
python processor.py --game-date 2023-10-24 --skip-downstream-trigger
\`\`\`

This allows you to:
1. Complete Phase 2 for all dates
2. Verify Phase 2 is gap-free
3. Then manually trigger Phase 3

See: docs/08-projects/current/pipeline-integrity/ for details
```

#### 2. `docs/07-monitoring/completeness-validation.md`

**Add section:**
```markdown
## Gap Detection

Use the enhanced completeness checker to detect gaps:

\`\`\`python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker()
gaps = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2023, 10, 1),
    end_date=date(2023, 10, 31)
)

if gaps['has_gaps']:
    print(f"Found {gaps['gap_count']} gaps!")
\`\`\`
```

### Create New Docs

#### 1. `docs/08-projects/current/pipeline-integrity/QUICK-START.md`

**Manual workarounds guide for immediate use**

#### 2. `docs/08-projects/current/pipeline-integrity/OPERATIONS-GUIDE.md`

**User guide for ops team once implemented**

---

## 🎯 Implementation Order

### Week 1: Core Features
1. ✅ Phase 1: Cascade control (6-8 hours)
   - Modify base classes
   - Add CLI flags
   - Test

### Week 2: Completeness Enhancements
2. ✅ Phase 2: Completeness checker (12-16 hours)
   - Add gap detection
   - Add failure detection
   - Add strict mode
   - Write tests

### Week 3: Tooling & Documentation
3. ✅ Phase 3: Backfill scripts (8-10 hours)
   - Create backfill scripts
   - Create verification helpers
   - Test workflows
4. ✅ Documentation updates (2-3 hours)
   - Update existing guides
   - Create operations guide

---

## 📊 Summary

**Total Effort:** 28-37 hours (estimate: 30 hours)

**Files to Modify:** ~8 files
- 3 base classes (cascade control)
- 1 completeness checker (enhancements)
- 4+ processor CLIs (add flag)

**Files to Create:** ~10 files
- 5-6 backfill scripts
- 3-4 test files
- 2-3 documentation files

**Risk:** LOW
- Backward compatible changes
- Opt-in features
- Well-tested components

**Benefit:** HIGH
- Prevents data corruption
- Enables confident backfills
- Improves daily operations

---

**Status:** 🎯 Ready for Implementation
**Next Step:** Review plan, then start with Phase 1 (cascade control)
