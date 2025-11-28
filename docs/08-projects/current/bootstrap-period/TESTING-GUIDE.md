## Bootstrap Period Implementation - Testing Guide

**Purpose:** Complete guide for testing the bootstrap period implementation
**Created:** 2025-11-27
**Status:** Ready for Testing

---

## Overview

This guide covers all testing for the bootstrap period implementation:
1. **Unit Tests** - Fast, isolated tests (no database)
2. **Integration Tests** - Tests with BigQuery/GCS (requires access)
3. **SQL Verification** - Database state verification
4. **Manual Testing** - Interactive processor runs

---

## Quick Start

### Run All Unit Tests
```bash
# Run all bootstrap period unit tests (fast, no database needed)
pytest tests/unit/bootstrap_period/ -v

# Run with coverage
pytest tests/unit/bootstrap_period/ --cov=shared.config.nba_season_dates --cov-report=html
```

### Run Integration Tests
```bash
# Run integration tests (requires BigQuery access)
pytest tests/integration/bootstrap_period/ -v -m integration

# Skip integration tests
pytest tests/unit/bootstrap_period/ -v -m "not integration"
```

### Run SQL Verification
```bash
# Run SQL verification tests (requires BigQuery + historical data)
pytest tests/integration/bootstrap_period/test_sql_verification.py -v -m sql
```

---

## Test Suite Details

### 1. Unit Tests (No Database Required)

**Location:** `tests/unit/bootstrap_period/`

**File: test_season_dates.py** - Schedule Service & Season Date Logic

**Test Classes:**
- `TestGetSeasonYearFromDate` - Season year determination
- `TestGetSeasonStartDate` - Season start date retrieval
- `TestIsEarlySeason` - Early season detection logic
- `TestScheduleServiceIntegration` - Service integration (mocked)
- `TestFallbackBehavior` - Three-tier fallback system

**Run:**
```bash
pytest tests/unit/bootstrap_period/test_season_dates.py -v
```

**Expected:** All tests pass (~50 tests, < 1 second)

**Key Tests:**
```bash
# Test specific early season dates
pytest tests/unit/bootstrap_period/test_season_dates.py::TestIsEarlySeason::test_all_test_dates_from_investigation -v

# Test fallback behavior
pytest tests/unit/bootstrap_period/test_season_dates.py::TestFallbackBehavior -v
```

---

**File: test_processor_skip_logic.py** - Processor Skip Verification

**Test Classes:**
- `TestProcessorEarlySeasonSkip` - Processors skip when early season
- `TestMLFeatureStoreEarlySeason` - ML Feature Store creates placeholders
- `TestProcessorSeasonYearDetermination` - Season year logic
- `TestProcessorLogging` - Skip logging verification

**Run:**
```bash
pytest tests/unit/bootstrap_period/test_processor_skip_logic.py -v
```

**Expected:** Most tests pass (some may skip if processors can't be instantiated without full environment)

**Key Tests:**
```bash
# Test all processors skip early season
pytest tests/unit/bootstrap_period/test_processor_skip_logic.py::TestProcessorEarlySeasonSkip::test_processor_skips_early_season -v

# Test ML Feature Store placeholders
pytest tests/unit/bootstrap_period/test_processor_skip_logic.py::TestMLFeatureStoreEarlySeason -v
```

---

### 2. Integration Tests (Requires BigQuery)

**Location:** `tests/integration/bootstrap_period/`

**File: test_schedule_service_integration.py** - Real Schedule Service Tests

**Test Classes:**
- `TestScheduleDatabaseReader` - Database reader with actual queries
- `TestScheduleService` - Schedule service end-to-end
- `TestSeasonDatesConfigIntegration` - Config with real service

**Run:**
```bash
pytest tests/integration/bootstrap_period/test_schedule_service_integration.py -v -m integration
```

**Expected:** All tests pass if BigQuery access available

**Prerequisites:**
- BigQuery access to `nba-props-platform` project
- Credentials configured (`GOOGLE_APPLICATION_CREDENTIALS`)
- Schedule data in `nba_raw.nbac_schedule` table

**Key Tests:**
```bash
# Test actual database queries
pytest tests/integration/bootstrap_period/test_schedule_service_integration.py::TestScheduleDatabaseReader -v

# Verify 2024 season date
pytest tests/integration/bootstrap_period/test_schedule_service_integration.py::TestScheduleDatabaseReader::test_get_season_start_date_2024 -v
```

---

**File: test_sql_verification.py** - Database State Verification

**Test Classes:**
- `TestEarlySeasonSkipVerification` - Verify no records for days 0-6
- `TestMLFeatureStorePlaceholders` - Verify placeholder creation
- `TestRegularSeasonProcessing` - Verify processing after day 7
- `TestProcessorRunHistory` - Verify run history logging

**Run:**
```bash
pytest tests/integration/bootstrap_period/test_sql_verification.py -v -m sql
```

**Expected:** Tests pass after processors have run on historical dates

**Prerequisites:**
- Processors have been run on 2023 season dates
- BigQuery access
- Historical data available

**Key Verification Queries:**
```bash
# Verify no records for early season
pytest tests/integration/bootstrap_period/test_sql_verification.py::TestEarlySeasonSkipVerification -v

# Verify ML Feature Store placeholders
pytest tests/integration/bootstrap_period/test_sql_verification.py::TestMLFeatureStorePlaceholders::test_ml_feature_store_has_placeholder_records -v
```

---

### 3. Manual Testing

#### Test 1: Verify Schedule Service

```python
# Run in Python REPL or script
from shared.config.nba_season_dates import get_season_start_date
from datetime import date

# Test schedule service integration
print("2024 season:", get_season_start_date(2024))
print("2023 season:", get_season_start_date(2023))
print("2022 season:", get_season_start_date(2022))
print("2021 season:", get_season_start_date(2021))

# Expected output:
# 2024 season: 2024-10-22
# 2023 season: 2023-10-24
# 2022 season: 2022-10-18
# 2021 season: 2021-10-19
```

#### Test 2: Verify Early Season Detection

```python
from shared.config.nba_season_dates import is_early_season
from datetime import date

# Days that should SKIP (0-6)
early_dates = [
    date(2023, 10, 24),  # Day 0
    date(2023, 10, 30),  # Day 6
]

for test_date in early_dates:
    result = is_early_season(test_date, 2023, days_threshold=7)
    print(f"{test_date}: Early season = {result}")
    assert result is True

# Days that should PROCESS (7+)
normal_dates = [
    date(2023, 10, 31),  # Day 7
    date(2023, 11, 1),   # Day 8
]

for test_date in normal_dates:
    result = is_early_season(test_date, 2023, days_threshold=7)
    print(f"{test_date}: Early season = {result}")
    assert result is False

print("\n✅ Early season detection working correctly!")
```

#### Test 3: Run Processor with Early Season Date

```bash
# Test player_daily_cache processor
python3 << 'EOF'
from datetime import date
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor

processor = PlayerDailyCacheProcessor()

# Should skip (day 0)
print("\n=== Testing Early Season (Day 0) ===")
result = processor.run({'analysis_date': date(2023, 10, 24)})
print(f"Result: {result}")
print(f"Stats: {processor.stats}")
# Should see: "Skipping 2023-10-24: early season"

# Should process (day 7)
print("\n=== Testing Regular Season (Day 7) ===")
result = processor.run({'analysis_date': date(2023, 10, 31)})
print(f"Result: {result}")
# May fail on dependencies, but should NOT skip
EOF
```

#### Test 4: SQL Verification Queries

```sql
-- Query 1: Verify no records for days 0-6
SELECT COUNT(*) as record_count
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2023-10-24' AND '2023-10-30';
-- Expected: 0

-- Query 2: Verify ML Feature Store placeholders
SELECT
    COUNT(*) as player_count,
    AVG(feature_quality_score) as avg_quality,
    COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = '2023-10-24';
-- Expected: ~450 players, 0.0 quality, all early_season

-- Query 3: Verify processing after day 7
SELECT
    cache_date,
    COUNT(*) as players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2023-10-31' AND '2023-11-06'
GROUP BY cache_date
ORDER BY cache_date;
-- Expected: ~450 players per date

-- Query 4: Verify quality improvement
SELECT
    game_date,
    AVG(feature_quality_score) as avg_quality,
    COUNT(CASE WHEN is_production_ready THEN 1 END) as production_ready
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2023-10-31' AND '2023-11-06'
GROUP BY game_date
ORDER BY game_date;
-- Expected: Quality 70-90%, most production ready
```

---

## Test Scenarios

### Scenario 1: Opening Night (Day 0)

**Date:** 2023-10-24 (2023 season opening night)

**Expected Behavior:**
1. ✅ `is_early_season(2023-10-24, 2023, 7)` returns `True`
2. ✅ All Phase 4 upstream processors skip (no records)
3. ✅ ML Feature Store creates placeholders:
   - 450 records
   - All features = NULL
   - early_season_flag = TRUE
   - feature_quality_score = 0.0
   - is_production_ready = FALSE
4. ✅ Phase 5 skips predictions (validation fails)

**Test:**
```bash
pytest tests/unit/bootstrap_period/ -v -k "opening_night"
```

---

### Scenario 2: Day 6 (Last Early Day)

**Date:** 2023-10-30

**Expected Behavior:**
1. ✅ `is_early_season(2023-10-30, 2023, 7)` returns `True`
2. ✅ Processors still skip (same as day 0)

**Test:**
```bash
pytest tests/unit/bootstrap_period/test_season_dates.py::TestIsEarlySeason::test_day_6_is_early_season -v
```

---

### Scenario 3: Day 7 (Crossover Point)

**Date:** 2023-10-31

**Expected Behavior:**
1. ✅ `is_early_season(2023-10-31, 2023, 7)` returns `False`
2. ✅ All Phase 4 processors run normally
3. ✅ Records created with partial windows:
   - L10 average uses ~7 games
   - Quality score ~70-75%
   - is_production_ready = TRUE
4. ✅ Phase 5 generates predictions

**Test:**
```bash
pytest tests/unit/bootstrap_period/test_season_dates.py::TestIsEarlySeason::test_day_7_is_not_early_season -v
```

---

### Scenario 4: Mid-Season

**Date:** 2023-12-01

**Expected Behavior:**
1. ✅ `is_early_season(2023-12-01, 2023, 7)` returns `False`
2. ✅ All processors run normally
3. ✅ Full quality data:
   - L10 average uses 10 games
   - Quality score 95-100%
   - is_production_ready = TRUE

---

## Debugging Failed Tests

### Test Fails: "Schedule service not available"

**Problem:** Integration test can't connect to BigQuery

**Solution:**
```bash
# Check credentials
echo $GOOGLE_APPLICATION_CREDENTIALS

# Verify BigQuery access
bq ls --project_id=nba-props-platform

# Skip integration tests
pytest tests/unit/bootstrap_period/ -v -m "not integration"
```

---

### Test Fails: "Could not instantiate processor"

**Problem:** Unit test can't create processor without full environment

**Solution:**
- This is expected for some tests
- Tests will skip automatically
- Only critical tests must pass

```bash
# Run only tests that don't require processor instantiation
pytest tests/unit/bootstrap_period/test_season_dates.py -v
```

---

### Test Fails: "No records found in database"

**Problem:** SQL verification fails because processors haven't run yet

**Solution:**
```bash
# Run processors first on historical dates
python3 -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --analysis_date 2023-10-24

# Then run SQL verification
pytest tests/integration/bootstrap_period/test_sql_verification.py -v -m sql
```

---

### Test Fails: "assertion failed: dates don't match"

**Problem:** Actual season dates don't match expected

**Solution:**
```bash
# Check actual dates in database
bq query --use_legacy_sql=false '
  SELECT season_year, MIN(DATE(game_date)) as start_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE is_regular_season = TRUE AND game_status = 3
    AND game_date >= "2021-01-01"
  GROUP BY season_year
  ORDER BY season_year DESC
'

# Update test expectations if database is correct
```

---

## Continuous Integration (CI/CD)

### Recommended pytest.ini Configuration

```ini
[pytest]
markers =
    integration: marks tests that require BigQuery access
    sql: marks tests that query database
    slow: marks tests as slow
    unit: marks unit tests (fast, no external dependencies)

# Default: run only unit tests
addopts = -v -m "not integration and not sql"
```

### CI/CD Pipeline

```yaml
# .github/workflows/test-bootstrap-period.yml
name: Bootstrap Period Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run unit tests
        run: |
          pytest tests/unit/bootstrap_period/ -v --cov

  integration-tests:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'  # Only on main branch
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
      - name: Authenticate to GCP
        uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_CREDENTIALS }}
      - name: Run integration tests
        run: |
          pytest tests/integration/bootstrap_period/ -v -m integration
```

---

## Test Coverage Goals

### Current Coverage

**Unit Tests:**
- ✅ `get_season_year_from_date()` - 100%
- ✅ `get_season_start_date()` - 95% (excluding error paths)
- ✅ `is_early_season()` - 100%
- ⏳ Processor skip logic - 80% (mocked)

**Integration Tests:**
- ⏳ Schedule service - 90%
- ⏳ Database reader - 85%
- ⏳ SQL verification - Depends on historical data

### Coverage Goals

- **Unit Tests:** >95% code coverage
- **Integration Tests:** All critical paths tested
- **SQL Verification:** All tables verified

---

## Performance Benchmarks

### Unit Tests
- Total time: <5 seconds
- Per test: <100ms
- No database calls

### Integration Tests
- Total time: ~30 seconds
- Database queries: ~10-20ms each
- GCS fallback: ~500ms-1s

### SQL Verification
- Total time: ~2 minutes
- Per query: ~5-10 seconds
- Depends on data volume

---

## Success Criteria

**Unit Tests Must:**
- ✅ All season year detection tests pass
- ✅ All early season detection tests pass
- ✅ All fallback tests pass
- ✅ Coverage >95%

**Integration Tests Should:**
- ✅ Schedule service retrieves correct dates
- ✅ Database queries return expected data
- ✅ Fallback chain works correctly

**SQL Verification Should:**
- ✅ No records for days 0-6 in upstream tables
- ✅ Placeholder records in ML Feature Store
- ✅ Records with quality >70% for day 7+
- ✅ Run history logs early season skips

---

## Next Steps After Testing

### If All Tests Pass ✅

1. **Code Review**
   - Review implementation
   - Check test coverage
   - Verify documentation

2. **Deploy to Staging**
   - Run full pipeline
   - Monitor logs
   - Verify database state

3. **Deploy to Production**
   - Schedule deployment
   - Monitor first week
   - Collect metrics

### If Tests Fail ❌

1. **Analyze Failures**
   - Check logs
   - Verify setup
   - Review error messages

2. **Fix Issues**
   - Update code
   - Rerun tests
   - Update documentation

3. **Retest**
   - Run all tests again
   - Verify fixes
   - Update test suite if needed

---

## Quick Reference

### Run Commands

```bash
# All unit tests (fast)
pytest tests/unit/bootstrap_period/ -v

# All integration tests (slow, requires DB)
pytest tests/integration/bootstrap_period/ -v -m integration

# All SQL verification (requires historical data)
pytest tests/integration/bootstrap_period/test_sql_verification.py -v -m sql

# Specific test file
pytest tests/unit/bootstrap_period/test_season_dates.py -v

# Specific test class
pytest tests/unit/bootstrap_period/test_season_dates.py::TestIsEarlySeason -v

# Specific test
pytest tests/unit/bootstrap_period/test_season_dates.py::TestIsEarlySeason::test_day_7_is_not_early_season -v

# With coverage
pytest tests/unit/bootstrap_period/ --cov=shared.config.nba_season_dates --cov-report=html

# Verbose output
pytest tests/unit/bootstrap_period/ -vv

# Show print statements
pytest tests/unit/bootstrap_period/ -v -s

# Stop on first failure
pytest tests/unit/bootstrap_period/ -v -x

# Run failed tests from last run
pytest --lf -v
```

---

**Ready to test! Start with unit tests, then integration tests, then SQL verification.**

**Questions? See:**
- IMPLEMENTATION-COMPLETE.md for implementation details
- IMPLEMENTATION-PLAN.md for design decisions
- Test files for specific test examples
