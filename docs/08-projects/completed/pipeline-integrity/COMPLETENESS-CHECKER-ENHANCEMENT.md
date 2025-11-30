# Completeness Checker Enhancement Proposal
**Purpose:** Extend existing completeness checker to detect gaps and handle failures
**Created:** 2025-11-27
**Status:** 🎯 Proposed Solution

---

## 🔍 Current Completeness Checker Analysis

### What It Does Now ✅

From `shared/utils/completeness_checker.py`:

```python
class CompletenessChecker:
    def check_completeness(
        self,
        table: str,
        date_column: str,
        analysis_date: date,
        expected_count: int,
        ...
    ) -> Dict:
        """
        Check if upstream data exists and is complete.

        Checks:
        1. Does data exist for this date?
        2. Do we have expected number of records?
        3. Is data stale (too old)?

        Returns:
        {
            'is_complete': bool,
            'actual_count': int,
            'expected_count': int,
            'completeness_pct': float,
            'is_production_ready': bool,
            'issues': List[str]
        }
        """
```

**Strengths:**
- ✅ Checks single-date completeness
- ✅ Calculates completeness percentage
- ✅ Sets production-ready flag
- ✅ Well-tested and widely used

**Limitations:**
- ❌ Only checks ONE date at a time
- ❌ Doesn't check for GAPS in historical ranges
- ❌ Doesn't check if upstream processor FAILED
- ❌ Doesn't STOP processing (just warns)

---

## 🎯 Proposed Solution: Enhance + Add

### Strategy: Two-Pronged Approach

**1. Enhance Completeness Checker (Extend Existing)**
- Add gap detection for date ranges
- Add upstream failure detection
- Keep existing single-date checks

**2. Add Processing Policy (New Behavior)**
- Add "stop on incomplete" mode
- Currently: Warn and continue (soft failure)
- New option: Raise exception (hard failure)

---

## 📝 Proposed API Design

### Enhancement 1: Add Gap Detection

**New method in CompletenessChecker:**

```python
def check_date_range_completeness(
    self,
    table: str,
    date_column: str,
    start_date: date,
    end_date: date,
    expected_frequency: str = 'daily',  # 'daily', 'game_days_only'
    bq_client: Optional[bigquery.Client] = None
) -> Dict:
    """
    Check for gaps in a continuous date range.

    Args:
        table: Fully qualified table name
        date_column: Column name containing dates
        start_date: Start of range to check
        end_date: End of range to check
        expected_frequency: 'daily' or 'game_days_only'

    Returns:
        {
            'has_gaps': bool,
            'missing_dates': List[date],
            'gap_count': int,
            'coverage_pct': float,
            'date_range': (start_date, end_date),
            'is_continuous': bool
        }

    Example:
        >>> checker.check_date_range_completeness(
        ...     table='nba_analytics.player_game_summary',
        ...     date_column='game_date',
        ...     start_date=date(2023, 10, 1),
        ...     end_date=date(2023, 10, 31)
        ... )
        {
            'has_gaps': True,
            'missing_dates': [date(2023, 10, 5), date(2023, 10, 11)],
            'gap_count': 2,
            'coverage_pct': 93.5,  # 29/31 dates
            'date_range': (date(2023, 10, 1), date(2023, 10, 31)),
            'is_continuous': False
        }
    """
    bq_client = bq_client or self.bq_client

    # Query to find missing dates
    query = f"""
    WITH expected_dates AS (
        SELECT date
        FROM UNNEST(GENERATE_DATE_ARRAY(
            @start_date,
            @end_date,
            INTERVAL 1 DAY
        )) as date
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
    """

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

---

### Enhancement 2: Add Upstream Failure Detection

**New method in CompletenessChecker:**

```python
def check_upstream_processor_status(
    self,
    processor_name: str,
    data_date: date,
    bq_client: Optional[bigquery.Client] = None
) -> Dict:
    """
    Check if upstream processor succeeded for a given date.

    Queries processor_run_history to check for failures.

    Args:
        processor_name: Name of upstream processor
        data_date: Date to check

    Returns:
        {
            'processor_succeeded': bool,
            'status': str,  # 'success', 'failed', 'not_found', 'skipped'
            'run_id': str,
            'error_message': Optional[str],
            'started_at': datetime,
            'safe_to_process': bool
        }

    Example:
        >>> checker.check_upstream_processor_status(
        ...     processor_name='player_boxscore_processor',
        ...     data_date=date(2023, 10, 15)
        ... )
        {
            'processor_succeeded': False,
            'status': 'failed',
            'run_id': 'abc123',
            'error_message': 'BigQuery timeout',
            'started_at': datetime(...),
            'safe_to_process': False  # Don't process downstream!
        }
    """
    bq_client = bq_client or self.bq_client

    query = """
    SELECT
        status,
        run_id,
        started_at,
        errors,
        skipped,
        skip_reason
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
            'run_id': None,
            'error_message': f'No run found for {processor_name} on {data_date}',
            'started_at': None,
            'safe_to_process': False
        }

    status = row.status
    succeeded = status == 'success'

    # Extract error message if failed
    error_message = None
    if row.errors:
        try:
            errors = json.loads(row.errors) if isinstance(row.errors, str) else row.errors
            error_message = errors[0].get('message') if errors else None
        except:
            error_message = str(row.errors)

    return {
        'processor_succeeded': succeeded,
        'status': status,
        'run_id': row.run_id,
        'error_message': error_message,
        'started_at': row.started_at,
        'safe_to_process': succeeded
    }
```

---

### Enhancement 3: Add Processing Policy Option

**Add to existing `check_completeness()` method:**

```python
def check_completeness(
    self,
    table: str,
    date_column: str,
    analysis_date: date,
    expected_count: int,
    fail_on_incomplete: bool = False,  # NEW PARAMETER
    check_historical_gaps: bool = False,  # NEW PARAMETER
    historical_lookback_days: int = 30,  # NEW PARAMETER
    upstream_processor: Optional[str] = None,  # NEW PARAMETER
    ...
) -> Dict:
    """
    Check completeness with optional strict mode.

    New Parameters:
        fail_on_incomplete: If True, raise exception instead of warning
        check_historical_gaps: If True, check for gaps in historical data
        historical_lookback_days: How far back to check for gaps
        upstream_processor: Check if upstream processor succeeded

    Raises:
        DependencyError: If fail_on_incomplete=True and data incomplete

    Example (Soft mode - current behavior):
        >>> result = checker.check_completeness(..., fail_on_incomplete=False)
        >>> if not result['is_production_ready']:
        ...     logger.warning("Data incomplete")  # Just warn, continue

    Example (Strict mode - new behavior):
        >>> result = checker.check_completeness(..., fail_on_incomplete=True)
        # Raises DependencyError if incomplete - stops processing!
    """
    # Existing checks
    result = self._run_existing_checks(...)

    # NEW: Check upstream processor status
    if upstream_processor:
        upstream_status = self.check_upstream_processor_status(
            processor_name=upstream_processor,
            data_date=analysis_date
        )
        result['upstream_status'] = upstream_status

        if not upstream_status['safe_to_process']:
            result['is_production_ready'] = False
            result['issues'].append(
                f"Upstream processor '{upstream_processor}' failed or missing"
            )

    # NEW: Check for historical gaps
    if check_historical_gaps:
        start_date = analysis_date - timedelta(days=historical_lookback_days)
        gap_check = self.check_date_range_completeness(
            table=table,
            date_column=date_column,
            start_date=start_date,
            end_date=analysis_date
        )
        result['gap_check'] = gap_check

        if gap_check['has_gaps']:
            result['is_production_ready'] = False
            result['issues'].append(
                f"Found {gap_check['gap_count']} gaps in historical data: "
                f"{gap_check['missing_dates'][:3]}..."
            )

    # NEW: Fail hard if requested
    if fail_on_incomplete and not result['is_production_ready']:
        raise DependencyError(
            f"Completeness check failed for {table}: {result['issues']}"
        )

    return result
```

---

## 🔄 Usage Patterns

### Pattern 1: Current Behavior (Soft - Warn and Continue)

**No changes needed! Existing code still works:**

```python
# Existing processors - no change
checker = CompletenessChecker()
result = checker.check_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    analysis_date=date(2023, 10, 15),
    expected_count=300
)

if not result['is_production_ready']:
    logger.warning("Data incomplete, proceeding anyway")
    # Processor continues, sets flags in output
```

**Behavior:** Same as current - warns but continues ✅

---

### Pattern 2: Backfill Mode (Strict - Stop on Incomplete)

**New usage for backfills:**

```python
# Backfill script - use strict mode
checker = CompletenessChecker()

try:
    result = checker.check_completeness(
        table='nba_analytics.player_game_summary',
        date_column='game_date',
        analysis_date=date(2023, 10, 15),
        expected_count=300,
        fail_on_incomplete=True,  # STRICT MODE
        check_historical_gaps=True,  # Check for gaps
        historical_lookback_days=30,  # Last 30 days
        upstream_processor='player_boxscore_processor'  # Check upstream
    )

    # If we get here, all checks passed!
    logger.info("All completeness checks passed ✅")

except DependencyError as e:
    # Completeness check failed - STOP processing
    logger.error(f"Cannot process: {e}")
    exit(1)  # Exit backfill script
```

**Behavior:** Stops processing if incomplete ✅

---

### Pattern 3: Daily Operations (Strict for Critical Data)

**Production processors can opt-in to strict mode:**

```python
# Critical Phase 4 processor
checker = CompletenessChecker()

try:
    result = checker.check_completeness(
        table='nba_analytics.player_game_summary',
        date_column='game_date',
        analysis_date=date(2023, 10, 15),
        expected_count=300,
        fail_on_incomplete=True,  # Don't process with bad data
        check_historical_gaps=True,  # Ensure continuous history
        historical_lookback_days=10,  # Last 10 games needed
    )

except DependencyError as e:
    # Send alert, don't create bad predictions
    send_alert(f"Phase 4 blocked: {e}")
    raise  # Fail the job
```

**Behavior:** Daily job fails if data incomplete (good!) ✅

---

## 🎛️ Configuration Options

### Option A: Processor-Level Config

**Set default behavior per processor:**

```python
class PlayerDailyCacheProcessor(PrecomputeProcessorBase):
    # Configuration
    COMPLETENESS_MODE = 'strict'  # or 'soft'
    CHECK_HISTORICAL_GAPS = True
    HISTORICAL_LOOKBACK_DAYS = 30
    UPSTREAM_PROCESSOR = 'player_game_summary_processor'

    def extract_raw_data(self):
        # Automatically uses strict mode
        result = self.check_dependencies(
            analysis_date=self.opts['analysis_date']
        )
        # Raises exception if incomplete
```

### Option B: CLI Flag

**Control via command-line:**

```bash
# Soft mode (current behavior)
python processor.py --analysis-date 2023-10-15

# Strict mode (stop on incomplete)
python processor.py --analysis-date 2023-10-15 --strict-completeness

# Extra strict mode (check gaps too)
python processor.py --analysis-date 2023-10-15 --strict-completeness --check-gaps
```

### Option C: Environment Variable

**Control via environment:**

```bash
# Development: Soft mode
export COMPLETENESS_MODE=soft

# Production: Strict mode
export COMPLETENESS_MODE=strict

# Backfills: Extra strict
export COMPLETENESS_MODE=strict
export CHECK_HISTORICAL_GAPS=true
```

---

## 📋 Implementation Checklist

### Phase 1: Add New Methods (Priority 1)

- [ ] Add `check_date_range_completeness()` to CompletenessChecker
- [ ] Add `check_upstream_processor_status()` to CompletenessChecker
- [ ] Add unit tests for new methods
- [ ] Create standalone gap detection CLI tool

**Effort:** 4-6 hours
**Benefit:** New functionality available

### Phase 2: Enhance Existing Method (Priority 2)

- [ ] Add `fail_on_incomplete` parameter to `check_completeness()`
- [ ] Add `check_historical_gaps` parameter
- [ ] Add `upstream_processor` parameter
- [ ] Add `DependencyError` exception class
- [ ] Update docstrings

**Effort:** 2-3 hours
**Benefit:** Backward compatible enhancement

### Phase 3: Update Processors (Priority 3)

- [ ] Add strict mode to Phase 4 processors (opt-in)
- [ ] Update backfill scripts to use strict mode
- [ ] Add configuration options (CLI flags, env vars)
- [ ] Update documentation

**Effort:** 6-8 hours
**Benefit:** Production usage

### Phase 4: Testing & Validation (Priority 4)

- [ ] Test with historical backfills
- [ ] Test daily operation scenarios
- [ ] Verify backward compatibility
- [ ] Performance testing (gap checks can be slow)
- [ ] Update monitoring/alerting

**Effort:** 4-6 hours
**Benefit:** Confident rollout

---

## 🧪 Testing Strategy

### Test 1: Gap Detection

```python
def test_gap_detection():
    checker = CompletenessChecker()

    # Create test data with gap
    # Oct 1-10, Oct 15-20 (missing 11-14)

    result = checker.check_date_range_completeness(
        table='test_table',
        date_column='date',
        start_date=date(2023, 10, 1),
        end_date=date(2023, 10, 20)
    )

    assert result['has_gaps'] == True
    assert result['gap_count'] == 4
    assert date(2023, 10, 11) in result['missing_dates']
    assert result['coverage_pct'] == 80.0  # 16/20 dates
```

### Test 2: Upstream Failure Detection

```python
def test_upstream_failure_detection():
    checker = CompletenessChecker()

    # Create failed run in processor_run_history
    # ...

    result = checker.check_upstream_processor_status(
        processor_name='test_processor',
        data_date=date(2023, 10, 15)
    )

    assert result['processor_succeeded'] == False
    assert result['status'] == 'failed'
    assert result['safe_to_process'] == False
```

### Test 3: Strict Mode

```python
def test_strict_mode_fails():
    checker = CompletenessChecker()

    # Create incomplete data
    # ...

    with pytest.raises(DependencyError):
        checker.check_completeness(
            table='test_table',
            date_column='date',
            analysis_date=date(2023, 10, 15),
            expected_count=100,
            fail_on_incomplete=True  # Should raise
        )
```

### Test 4: Backward Compatibility

```python
def test_backward_compatibility():
    checker = CompletenessChecker()

    # Existing code should still work
    result = checker.check_completeness(
        table='test_table',
        date_column='date',
        analysis_date=date(2023, 10, 15),
        expected_count=100
        # No new parameters - use defaults
    )

    # Should return dict, not raise exception
    assert isinstance(result, dict)
    assert 'is_production_ready' in result
```

---

## 🎯 Recommendation

### Enhance Completeness Checker ✅

**Why enhance instead of creating new utility:**

1. ✅ **Reuse existing infrastructure** - Already integrated into processors
2. ✅ **Backward compatible** - Existing code continues to work
3. ✅ **Logical extension** - Gap detection IS a completeness check
4. ✅ **Consistent API** - Same pattern as existing checks
5. ✅ **Less code duplication** - One place for all completeness logic

**What to add:**
- `check_date_range_completeness()` - New method
- `check_upstream_processor_status()` - New method
- `fail_on_incomplete` parameter - New behavior option

**What NOT to change:**
- Existing `check_completeness()` default behavior
- Existing return format
- Existing integrations

---

## 📊 Summary

| Feature | Current | Proposed | Change Type |
|---------|---------|----------|-------------|
| Single-date check | ✅ Exists | ✅ Keep | No change |
| Soft failure (warn) | ✅ Default | ✅ Still default | No change |
| Gap detection | ❌ Missing | ✅ New method | Addition |
| Upstream failure check | ❌ Missing | ✅ New method | Addition |
| Hard failure (stop) | ❌ Missing | ✅ New parameter | Addition |

**Result:** Backward compatible enhancement that adds powerful new features ✅

---

**Status:** 🎯 Proposed Solution
**Estimated Effort:** 16-23 hours total
**Risk:** LOW (backward compatible)
**Priority:** HIGH (critical for data integrity)

This approach enhances the existing completeness checker without breaking anything. Existing processors continue to work, new features are opt-in!
