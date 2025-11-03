# Team Offense Game Summary - Test Suite Documentation

**Processor:** `TeamOffenseGameSummaryProcessor`  
**Location:** `data_processors/analytics/team_offense_game_summary/`  
**Test Directory:** `tests/processors/analytics/team_offense_game_summary/`

---

## 📋 Table of Contents

- [Overview](#overview)
- [Test Suite Structure](#test-suite-structure)
- [Quick Start](#quick-start)
- [Test Types](#test-types)
- [Running Tests](#running-tests)
- [When to Run Which Tests](#when-to-run-which-tests)
- [Test Coverage](#test-coverage)
- [Troubleshooting](#troubleshooting)
- [CI/CD Integration](#cicd-integration)
- [Best Practices](#best-practices)

---

## 🎯 Overview

This test suite provides comprehensive coverage for the Team Offense Game Summary processor, which aggregates team offensive statistics from raw NBA data into analytics-ready format with advanced metrics.

**Total Tests:** 102 tests across 3 test files  
**Total Runtime:** ~75 seconds (fast tests ~15s, validation ~60s)  
**Coverage:** ~95% code coverage

### What We Test

- ✅ **Unit Tests** - Individual method logic (calculations, parsing, validation)
- ✅ **Integration Tests** - Full processor flow with mocked dependencies
- ✅ **Validation Tests** - Production data quality against real BigQuery

---

## 📁 Test Suite Structure

```
tests/processors/analytics/team_offense_game_summary/
├── README.md                    # This file
├── conftest.py                  # Shared pytest fixtures & Google Cloud mocks
├── run_tests.py                 # Test runner script
│
├── test_unit.py                 # 58 unit tests (~3-5s runtime)
│   ├── TestOvertimePeriodParsing (9 tests)
│   ├── TestPossessionsCalculation (6 tests)
│   ├── TestTrueShootingPercentage (8 tests)
│   ├── TestDataQualityTier (7 tests)
│   ├── TestDependencyConfiguration (9 tests)
│   ├── TestSourceTrackingFields (7 tests)
│   └── TestGetAnalyticsStats (12 tests)
│
├── test_integration.py          # 9 integration tests (~10s runtime)
│   ├── TestFullProcessorFlow (3 tests)
│   ├── TestOvertimeGamesProcessing (2 tests)
│   ├── TestMultipleGamesProcessing (2 tests)
│   └── TestErrorHandling (2 tests)
│
└── test_validation.py           # 35 validation tests (~60s runtime)
    ├── TestTableSchema (4 tests)
    ├── TestDataCompleteness (7 tests)
    ├── TestDataQuality (7 tests)
    ├── TestSourceTracking (3 tests)
    ├── TestAdvancedMetrics (4 tests)
    ├── TestShotZones (3 tests)
    ├── TestQualityTiers (2 tests)
    ├── TestQueryPerformance (2 tests)
    └── TestEdgeCases (3 tests)
```

---

## 🚀 Quick Start

### Prerequisites

```bash
# Activate virtual environment
source .venv/bin/activate

# Ensure dependencies installed
pip install pytest pytest-cov google-cloud-bigquery pandas
```

### Run All Fast Tests (Unit + Integration)

```bash
cd tests/processors/analytics/team_offense_game_summary

# Run with test runner
python run_tests.py all --verbose

# Or use pytest directly
pytest test_unit.py test_integration.py -v
```

### Run with Coverage Report

```bash
pytest test_unit.py test_integration.py \
  --cov=data_processors.analytics.team_offense_game_summary \
  --cov-report=html \
  --cov-report=term

# View HTML report
open htmlcov/index.html
```

---

## 🧪 Test Types

### 1. Unit Tests (`test_unit.py`)

**Purpose:** Test individual methods in isolation  
**Runtime:** ~3-5 seconds  
**Dependencies:** None (all mocked)  
**Run:** On every code change

**What They Test:**
- Individual calculation methods (possessions, TS%, ORtg, pace)
- Overtime period parsing logic
- Data quality tier determination
- Dependency configuration
- Source tracking field population
- Stats aggregation methods

**Example:**
```python
def test_one_overtime_265_minutes(self, processor):
    """Test single OT game (240 + 25 = 265)."""
    result = processor._parse_overtime_periods("265:00")
    assert result == 1
```

**Run Command:**
```bash
# All unit tests
pytest test_unit.py -v

# Specific test class
pytest test_unit.py::TestOvertimePeriodParsing -v

# Single test
pytest test_unit.py::TestOvertimePeriodParsing::test_one_overtime_265_minutes -v
```

---

### 2. Integration Tests (`test_integration.py`)

**Purpose:** Test full processor flow with mocked BigQuery  
**Runtime:** ~10 seconds  
**Dependencies:** Mock BigQuery, notifications  
**Run:** Before committing code, in CI/CD

**What They Test:**
- Complete processor execution flow
- Data extraction and transformation
- Shot zone handling (with and without)
- Missing dependency handling
- Overtime game processing
- Multiple games in single run
- Error handling and notifications

**Key Features:**
- ✅ No real BigQuery calls (fast and free)
- ✅ Deterministic results (no flakiness)
- ✅ Tests both success and failure paths
- ✅ Validates source tracking attributes

**Example:**
```python
@patch('data_processors.analytics.analytics_base.bigquery.Client')
def test_successful_processing_with_shot_zones(
    self, mock_bq_client_class, sample_team_boxscore_data, shot_zone_data
):
    """Test successful processing with shot zones available."""
    # ... setup mocks ...
    success = processor.run({'start_date': '2025-01-15', 'end_date': '2025-01-15'})
    assert success is True
    assert len(processor.transformed_data) == 2
    assert processor.shot_zones_available is True
```

**Run Command:**
```bash
# All integration tests
pytest test_integration.py -v

# With detailed output
python run_tests.py integration --verbose

# Specific test
pytest test_integration.py::TestFullProcessorFlow::test_successful_processing_with_shot_zones -v
```

---

### 3. Validation Tests (`test_validation.py`)

**Purpose:** Validate production data quality against real BigQuery  
**Runtime:** ~60 seconds  
**Dependencies:** Real BigQuery table with data  
**Run:** Before deployment, nightly, after processor runs

**What They Test:**
- Table schema and structure
- Data completeness and recency
- Business logic correctness (points calc, win/loss, etc.)
- Source tracking metadata accuracy
- Advanced metrics reasonableness
- Shot zone data quality
- Quality tier logic
- Query performance
- Edge cases (nulls, duplicates)

**Prerequisites:**
1. BigQuery table `nba_analytics.team_offense_game_summary` must exist
2. Table must have recent data (last 7 days recommended)
3. Service account must have BigQuery Data Viewer permissions

**Example:**
```python
def test_points_calculation_correct(self, bq_client, table_id):
    """Test that points = (2PT × 2) + (3PT × 3) + FT."""
    query = f"""
    SELECT game_id, team_abbr, points_scored,
        ((fg_makes - three_pt_makes) * 2) + (three_pt_makes * 3) + ft_makes as calculated_points
    FROM `{table_id}`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        AND points_scored != calculated_points
    """
    result = list(bq_client.query(query).result())
    assert len(result) == 0, f"Points calculation mismatches: {result}"
```

**Run Command:**
```bash
# Enable validation tests
RUN_VALIDATION_TESTS=true pytest test_validation.py -v --capture=no

# Run specific category
RUN_VALIDATION_TESTS=true pytest test_validation.py::TestDataQuality -v

# With verbose output
RUN_VALIDATION_TESTS=true pytest test_validation.py -vv --tb=long
```

---

## 🎬 Running Tests

### Using Test Runner Script

```bash
# Run all tests (unit + integration, no validation)
python run_tests.py all --verbose

# Run only unit tests
python run_tests.py unit --verbose

# Run only integration tests
python run_tests.py integration --verbose

# Run specific test file
python run_tests.py unit --file test_unit.py
```

### Using Pytest Directly

```bash
# Run all fast tests (unit + integration)
pytest test_unit.py test_integration.py -v

# Run with coverage
pytest test_unit.py test_integration.py \
  --cov=data_processors.analytics.team_offense_game_summary \
  --cov-report=html

# Run specific test pattern
pytest -k "overtime" -v

# Run with detailed failure info
pytest -vv --tb=long

# Stop on first failure
pytest -x test_unit.py

# Run in parallel (requires pytest-xdist)
pytest test_unit.py test_integration.py -n auto
```

### Validation Tests (Real BigQuery)

```bash
# Prerequisites: Table must exist with data
bq show nba-props-platform:nba_analytics.team_offense_game_summary

# Run validation tests
RUN_VALIDATION_TESTS=true pytest test_validation.py -v --capture=no

# Run specific validation category
RUN_VALIDATION_TESTS=true pytest test_validation.py::TestDataQuality -v

# Run without stopping on failures (see all issues)
RUN_VALIDATION_TESTS=true pytest test_validation.py -v --maxfail=100
```

---

## 📅 When to Run Which Tests

### During Development (Every Code Change)
```bash
# Fast feedback loop (~5 seconds)
pytest test_unit.py -v
```
**Why:** Catch logic errors immediately while coding

---

### Before Committing (Pre-Commit)
```bash
# Full fast test suite (~15 seconds)
python run_tests.py all --verbose
```
**Why:** Ensure no regressions before pushing code

---

### In CI/CD Pipeline (Every Push)
```bash
# All fast tests with coverage
pytest test_unit.py test_integration.py -v \
  --cov=data_processors.analytics.team_offense_game_summary \
  --cov-report=xml
```
**Why:** Automated quality gate, track coverage trends

---

### Before Deployment (Pre-Production)
```bash
# Validation against staging/production data
RUN_VALIDATION_TESTS=true pytest test_validation.py -v
```
**Why:** Verify processor works with real data and schema

---

### After Processor Runs (Post-Processing)
```bash
# Validate data quality
RUN_VALIDATION_TESTS=true pytest test_validation.py::TestDataQuality -v
```
**Why:** Catch data quality issues in production

---

### Nightly Schedule (Continuous Monitoring)
```bash
# Full validation suite
RUN_VALIDATION_TESTS=true pytest test_validation.py -v --capture=no
```
**Why:** Ongoing production data quality monitoring

---

## 📊 Test Coverage

### Current Coverage: ~95%

**Well Covered (>95%):**
- ✅ Calculation methods (possessions, TS%, ORtg, pace)
- ✅ Overtime period parsing
- ✅ Data quality tier logic
- ✅ Source tracking field population
- ✅ Dependency configuration
- ✅ Transform and validation logic

**Moderate Coverage (80-95%):**
- ⚠️ Error handling edge cases
- ⚠️ Notification delivery paths

**Not Covered:**
- ❌ Main script execution (`if __name__ == "__main__"`)
- ❌ Some complex error recovery scenarios

### View Coverage Report

```bash
# Generate HTML coverage report
pytest test_unit.py test_integration.py \
  --cov=data_processors.analytics.team_offense_game_summary \
  --cov-report=html

# Open in browser
open htmlcov/index.html

# Terminal summary
pytest test_unit.py test_integration.py \
  --cov=data_processors.analytics.team_offense_game_summary \
  --cov-report=term-missing
```

---

## 🐛 Troubleshooting

### Issue 1: ImportError - Module Not Found

**Error:**
```
ModuleNotFoundError: No module named 'data_processors'
```

**Solution:**
```bash
# Make sure you're in the project root
cd ~/code/nba-stats-scraper

# Add project root to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Or run tests from project root
cd ~/code/nba-stats-scraper
pytest tests/processors/analytics/team_offense_game_summary/test_unit.py -v
```

---

### Issue 2: Integration Tests Hitting Real BigQuery

**Error:**
```
404 Not found: Table nba-props-platform:nba_raw.nbac_team_boxscore
```

**Solution:**
Check that `conftest.py` properly mocks Google Cloud modules:
```python
# In conftest.py, should have:
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()
```

If still failing, verify mock patches in test:
```python
@patch('data_processors.analytics.analytics_base.bigquery.Client')  # ✅ Correct
# Not:
@patch('data_processors.analytics.team_offense_game_summary.bigquery.Client')  # ❌ Wrong
```

---

### Issue 3: Validation Tests Skipped

**Error:**
```
SKIPPED [35] - Validation tests disabled. Set RUN_VALIDATION_TESTS=true
```

**Solution:**
```bash
# Enable validation tests
RUN_VALIDATION_TESTS=true pytest test_validation.py -v
```

---

### Issue 4: Validation Tests Fail - Table Not Found

**Error:**
```
❌ Table not found: nba-props-platform:nba_analytics.team_offense_game_summary
```

**Solution:**
```bash
# Create the table
cd ~/code/nba-stats-scraper
bq query --use_legacy_sql=false < schemas/bigquery/analytics/team_offense_game_summary_tables.sql

# Verify table exists
bq show nba-props-platform:nba_analytics.team_offense_game_summary

# Run processor to populate data
python data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py \
  --start-date 2025-01-01 --end-date 2025-01-15
```

---

### Issue 5: Validation Tests Fail - No Data

**Error:**
```
❌ No data found in last 30 days. Run processor first.
```

**Solution:**
```bash
# Run processor to populate recent data
python data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py \
  --start-date $(date -d '7 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d)

# Verify data exists
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
```

---

### Issue 6: Tests Run Slowly

**Problem:** Tests taking longer than expected

**Solutions:**
```bash
# 1. Run tests in parallel (requires pytest-xdist)
pip install pytest-xdist
pytest test_unit.py test_integration.py -n auto

# 2. Run only changed tests (requires pytest-testmon)
pip install pytest-testmon
pytest --testmon

# 3. Skip slow tests temporarily
pytest test_unit.py test_integration.py -v -m "not slow"

# 4. Run specific test classes only
pytest test_unit.py::TestOvertimePeriodParsing -v
```

---

### Issue 7: Permission Denied - BigQuery

**Error (Validation Tests):**
```
403 Permission denied on resource project nba-props-platform
```

**Solution:**
```bash
# Check current service account
gcloud auth list

# Authenticate with correct account
gcloud auth application-default login

# Or set service account key
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"

# Verify permissions
bq ls nba-props-platform:nba_analytics
```

---

## 🔄 CI/CD Integration

### GitHub Actions Workflow (Recommended)

**⚠️ TODO:** Create `.github/workflows/team_offense_tests.yml`

This workflow should:
1. ✅ Run on every push and pull request
2. ✅ Execute unit and integration tests
3. ✅ Generate coverage reports
4. ✅ Upload coverage to Codecov or similar
5. ✅ Fail build if tests fail or coverage drops
6. ✅ Optionally run validation tests on schedule

**Example Workflow Structure:**

```yaml
name: Team Offense Game Summary Tests

on:
  push:
    branches: [ main, develop ]
    paths:
      - 'data_processors/analytics/team_offense_game_summary/**'
      - 'tests/processors/analytics/team_offense_game_summary/**'
  pull_request:
    branches: [ main, develop ]
  schedule:
    # Run validation tests nightly at 2 AM UTC
    - cron: '0 2 * * *'

jobs:
  unit-and-integration-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run unit tests
        run: |
          cd tests/processors/analytics/team_offense_game_summary
          pytest test_unit.py -v --cov --cov-report=xml
      - name: Run integration tests
        run: |
          cd tests/processors/analytics/team_offense_game_summary
          pytest test_integration.py -v --cov --cov-report=xml --cov-append
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
          flags: team_offense
          fail_ci_if_error: true

  validation-tests:
    runs-on: ubuntu-latest
    # Only run on schedule or manual trigger
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - name: Run validation tests
        env:
          RUN_VALIDATION_TESTS: true
        run: |
          cd tests/processors/analytics/team_offense_game_summary
          pytest test_validation.py -v --capture=no
```

**Setup Instructions:**
1. Create `.github/workflows/team_offense_tests.yml` with the above content
2. Add GCP service account key as GitHub secret: `GCP_SA_KEY`
3. Adjust paths and triggers as needed
4. Push to repository to activate

---

### Pre-Commit Hook (Optional)

Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Run tests before allowing commit

echo "🧪 Running pre-commit tests..."

cd tests/processors/analytics/team_offense_game_summary

# Run fast tests
python run_tests.py all

if [ $? -ne 0 ]; then
    echo "❌ Tests failed! Commit aborted."
    echo "Fix failing tests or use 'git commit --no-verify' to skip."
    exit 1
fi

echo "✅ All tests passed!"
exit 0
```

Make executable:
```bash
chmod +x .git/hooks/pre-commit
```

---

## 📚 Best Practices

### 1. **Test-Driven Development (TDD)**
✅ Write tests before implementing features  
✅ Start with failing test, then make it pass  
✅ Refactor with confidence

### 2. **Test Isolation**
✅ Each test should be independent  
✅ Don't rely on test execution order  
✅ Clean up resources (use fixtures)

### 3. **Descriptive Test Names**
```python
# ✅ Good
def test_one_overtime_265_minutes(self, processor):
    """Test single OT game (240 + 25 = 265)."""

# ❌ Bad
def test_ot(self, processor):
    """Test OT."""
```

### 4. **Test What Matters**
✅ Test business logic thoroughly  
✅ Test edge cases and error paths  
⚠️ Don't test framework/library code  
⚠️ Don't test trivial getters/setters

### 5. **Keep Tests Fast**
✅ Mock external dependencies  
✅ Use in-memory data when possible  
✅ Run expensive tests separately (validation)

### 6. **Maintain Tests**
✅ Update tests when code changes  
✅ Remove obsolete tests  
✅ Refactor duplicate test code into fixtures

### 7. **Document Complex Tests**
✅ Add docstrings explaining what's being tested  
✅ Comment why, not what  
✅ Link to related issues/tickets

### 8. **Monitor Test Health**
✅ Track test runtime trends  
✅ Fix flaky tests immediately  
✅ Maintain >90% code coverage  
✅ Review test failures in CI/CD

---

## 📈 Success Metrics

### Test Suite Health Indicators

**🟢 Healthy Test Suite:**
- ✅ All tests passing consistently
- ✅ <15s runtime for unit + integration tests
- ✅ >90% code coverage
- ✅ No flaky tests
- ✅ Validation tests pass nightly
- ✅ Clear, descriptive test names
- ✅ Well-organized test structure

**🟡 Needs Attention:**
- ⚠️ 1-2 failing tests
- ⚠️ 15-30s runtime for fast tests
- ⚠️ 80-90% code coverage
- ⚠️ Occasional flaky test
- ⚠️ Some validation failures (investigate)

**🔴 Critical Issues:**
- ❌ >3 failing tests
- ❌ >30s runtime for fast tests
- ❌ <80% code coverage
- ❌ Frequent flaky tests
- ❌ Validation tests consistently failing
- ❌ Tests blocking development

---

## 🎯 Summary

### Quick Reference Card

```bash
# Development (fast feedback)
pytest test_unit.py -v                                    # ~5s

# Pre-commit (full fast suite)
python run_tests.py all --verbose                         # ~15s

# Coverage report
pytest test_unit.py test_integration.py --cov --cov-report=html

# Before deployment
RUN_VALIDATION_TESTS=true pytest test_validation.py -v   # ~60s

# Troubleshooting
pytest -vv --tb=long --capture=no                         # Verbose output
pytest -x test_unit.py                                    # Stop on first fail
pytest -k "overtime" -v                                   # Run specific pattern
```

---

## 📞 Getting Help

### Common Commands
- **List all tests:** `pytest --collect-only`
- **Run specific test:** `pytest test_unit.py::TestOvertimePeriodParsing::test_one_overtime_265_minutes -v`
- **Debug test:** `pytest test_unit.py::test_name -vv --tb=long --capture=no`
- **See test durations:** `pytest --durations=10`

### Resources
- **Pytest Documentation:** https://docs.pytest.org/
- **Coverage.py Documentation:** https://coverage.readthedocs.io/
- **BigQuery Python Client:** https://cloud.google.com/python/docs/reference/bigquery/latest

### Support
- Check test output for specific error messages
- Review troubleshooting section above
- Check processor logs for runtime issues
- Verify BigQuery table schema matches expectations

---

**Last Updated:** November 2025  
**Test Suite Version:** 2.0  
**Total Tests:** 102 (58 unit + 9 integration + 35 validation)  
**Maintained by:** NBA Props Platform Team

---

## ✨ Recent Changes

### November 2025 - v2.0
- ✅ Added 35 validation tests for production data quality
- ✅ Fixed integration test mocking patterns
- ✅ Implemented side effect pattern for source tracking attributes
- ✅ Added parameterized tests for date ranges
- ✅ Improved edge case coverage (nulls, duplicates)
- ✅ Added performance tests for query speed
- ✅ Enhanced documentation with troubleshooting guide

### Previous Version - v1.0
- ✅ Initial 58 unit tests
- ✅ Initial 9 integration tests
- ✅ Basic test runner script
- ✅ Pytest configuration