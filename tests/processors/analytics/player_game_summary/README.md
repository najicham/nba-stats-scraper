# Player Game Summary Processor - Test Suite

**Version:** 2.0
**Last Updated:** November 2025
**Status:** ✅ Complete (51 unit tests)

## Overview

Comprehensive test suite for the Player Game Summary analytics processor. Tests individual methods in isolation with mocked dependencies for fast, reliable feedback.

## Quick Start

```bash
# Navigate to test directory
cd tests/processors/analytics/player_game_summary/

# Run unit tests
python run_tests.py unit

# Run with coverage report
python run_tests.py unit --coverage

# Run all tests
python run_tests.py
```

## Test Structure

```
player_game_summary/
├── conftest.py           # Google Cloud mocking
├── test_unit.py          # 51 unit tests (~5s)
├── test_integration.py   # Integration tests (~10s) [TODO]
├── test_validation.py    # Validation tests (~30s) [TODO]
├── run_tests.py          # Test runner script
└── README.md             # This file
```

## Unit Test Coverage (51 tests)

### 1. Dependency Configuration (6 tests)
Tests for `get_dependencies()` method:
- ✅ Returns dictionary structure
- ✅ Defines all 6 Phase 2 sources
- ✅ Critical sources marked correctly (NBA.com, BDL)
- ✅ Field prefixes correct for each source
- ✅ Check types are 'date_range'

### 2. Minutes Parsing (8 tests)
Tests for `_parse_minutes_to_decimal()` method:
- ✅ Parse MM:SS format (40:11 → 40.18)
- ✅ Parse zero seconds (35:00 → 35.0)
- ✅ Parse simple numeric (36 → 36.0)
- ✅ Parse float format (36.5 → 36.5)
- ✅ NULL returns None
- ✅ Dash (DNP) returns None
- ✅ Empty string returns None
- ✅ Full game (48:00 → 48.0)

### 3. Plus/Minus Parsing (7 tests)
Tests for `_parse_plus_minus()` method:
- ✅ Positive with + sign (+7 → 7)
- ✅ Positive without + sign (7 → 7)
- ✅ Negative value (-14 → -14)
- ✅ Zero (0 → 0)
- ✅ NULL returns None
- ✅ Dash returns None
- ✅ Empty string returns None

### 4. Numeric Cleaning (4 tests)
Tests for `_clean_numeric_columns()` method:
- ✅ Convert strings to numeric
- ✅ Handle plus signs in plus_minus
- ✅ Invalid values become NaN
- ✅ Preserve existing numeric values

### 5. Validation Methods (6 tests)
Tests for validation methods:
- ✅ Critical fields validation (no nulls)
- ✅ Critical fields validation (with nulls warning)
- ✅ Player data validation (no duplicates)
- ✅ Player data validation (with duplicates warning)
- ✅ Statistical integrity (valid FG stats)
- ✅ Statistical integrity (FGM > FGA warning)

### 6. Calculate Analytics (15 tests)
Tests for `calculate_analytics()` method:
- ✅ Creates output records
- ✅ Includes universal_player_id from registry
- ✅ Parses minutes correctly (MM:SS → integer)
- ✅ Parses plus_minus correctly (removes +)
- ✅ Calculates prop outcome (OVER)
- ✅ Calculates prop outcome (UNDER)
- ✅ Calculates true shooting % (TS%)
- ✅ Calculates effective FG% (eFG%)
- ✅ Includes source tracking fields (18 fields)
- ✅ Skips players not in registry
- ✅ Sets data quality tier 'high' (NBA.com)
- ✅ Sets data quality tier 'medium' (BDL)
- ✅ Handles multiple players
- ✅ Handles missing prop lines
- ✅ Handles NULL statistics

### 7. Source Tracking Fields (3 tests)
Tests for `build_source_tracking_fields()` method:
- ✅ Returns dictionary
- ✅ Has all 18 fields (6 sources × 3 fields)
- ✅ Values match processor attributes

### 8. Analytics Stats (2 tests)
Tests for `get_analytics_stats()` method:
- ✅ Empty data returns empty dict
- ✅ Returns correct record counts

## Test Patterns Used

### Pattern 1: Calculation Validation
```python
def test_calculate_ts_pct(self, processor, sample_data):
    """Test true shooting percentage calculation."""
    result = processor._calculate_ts_pct(sample_data)

    # Show expected calculation
    expected = 25 / (2 * (20 + 0.44 * 4))

    assert result == pytest.approx(expected, abs=0.001)
```

### Pattern 2: NULL/Edge Case Handling
```python
def test_parse_minutes_null_returns_none(self, processor):
    """Test that NULL returns None."""
    assert processor._parse_minutes_to_decimal(None) is None
```

### Pattern 3: Mock External Dependencies
```python
@pytest.fixture
def processor(self):
    """Create processor with mocked registry."""
    proc = PlayerGameSummaryProcessor()
    proc.registry = Mock()
    proc.registry.get_universal_ids_batch = Mock(return_value={
        'lebronjames': 'lebronjames_2024'
    })
    return proc
```

## Fixtures

### Core Fixtures

#### `processor`
Basic processor instance with mocked BigQuery client:
```python
proc = PlayerGameSummaryProcessor()
proc.bq_client = Mock()
proc.project_id = 'test-project'
```

#### `sample_raw_data`
Realistic player game data with all fields:
```python
pd.DataFrame([{
    'game_id': '20250115_LAL_GSW',
    'player_lookup': 'lebronjames',
    'points': 25,
    'assists': 8,
    # ... all fields
}])
```

## Running Tests

### Basic Usage
```bash
# All unit tests
python run_tests.py unit

# Verbose output
python run_tests.py unit --verbose

# With coverage
python run_tests.py unit --coverage
```

### Using pytest directly
```bash
# All tests
pytest test_unit.py -v

# Specific test class
pytest test_unit.py::TestMinutesParsing -v

# Specific test
pytest test_unit.py::TestMinutesParsing::test_parse_mm_ss_format -v

# With coverage
pytest test_unit.py --cov=analytics_processors.player_game_summary --cov-report=html
```

## Coverage Goals

| Component | Target | Actual |
|-----------|--------|--------|
| Core Calculations | 100% | 🎯 TBD |
| Validation Methods | 100% | 🎯 TBD |
| Parsing Methods | 100% | 🎯 TBD |
| Source Tracking | 100% | 🎯 TBD |
| **Overall** | **95%+** | 🎯 TBD |

Run `python run_tests.py unit --coverage` to generate report.

## Test Development Workflow

### 1. Write New Test
```python
def test_new_feature(self, processor):
    """Test description."""
    result = processor._new_method()
    assert result == expected
```

### 2. Run Test
```bash
pytest test_unit.py::TestClassName::test_new_feature -v
```

### 3. Debug Failures
```bash
pytest test_unit.py::TestClassName::test_new_feature -vv --tb=long
```

### 4. Check Coverage
```bash
python run_tests.py unit --coverage
```

## Common Test Patterns

### Float Comparison
```python
# ✅ DO: Use pytest.approx()
assert result == pytest.approx(0.571, abs=0.001)

# ❌ DON'T: Direct comparison
assert result == 0.571
```

### NULL Handling
```python
def test_handles_null(self, processor):
    """Test NULL input handling."""
    result = processor._method(None)
    assert result is None
```

### Mock BigQuery Response
```python
mock_df = pd.DataFrame([{'field': 'value'}])
processor.bq_client.query.return_value.to_dataframe.return_value = mock_df
```

## Troubleshooting

### Import Errors
```
ImportError: cannot import name 'bigquery' from 'google.cloud'
```
**Solution:** Ensure `conftest.py` is in place and mocking Google Cloud modules.

### Test Discovery Issues
```
ERROR: file not found: test_unit.py
```
**Solution:** Run from correct directory: `tests/processors/analytics/player_game_summary/`

### Fixture Not Found
```
fixture 'processor' not found
```
**Solution:** Check fixture is defined in same test class or conftest.py

### Coverage Not Generated
```
Coverage report not found
```
**Solution:** Install coverage: `pip install pytest-cov`

## Next Steps

### Phase 1: Unit Tests ✅
- [x] 51 unit tests complete
- [x] Test runner created
- [x] Documentation complete

### Phase 2: Integration Tests (TODO)
- [ ] Create `test_integration.py`
- [ ] Test full end-to-end flow
- [ ] Mock only BigQuery
- [ ] ~8 integration tests

### Phase 3: Validation Tests (TODO)
- [ ] Create `test_validation.py`
- [ ] Test against real BigQuery data
- [ ] No mocks - production validation
- [ ] ~15 validation tests

## Resources

- **Testing Guide:** `/docs/testing_guide.md`
- **Processor Code:** `analytics_processors/player_game_summary/player_game_summary_processor.py`
- **Schema:** `schemas/bigquery/analytics/player_game_summary_tables.sql`
- **Dependency Tracking Guide:** `/docs/dependency_tracking_guide_v4.md`

## Test Maintenance

### Adding New Tests
1. Identify method to test
2. Create test class if needed
3. Write fixtures for sample data
4. Write 3-5 tests (happy path, edge cases, errors)
5. Run tests: `python run_tests.py unit`
6. Update this README

### Updating Existing Tests
1. Modify test in `test_unit.py`
2. Run affected tests: `pytest test_unit.py::TestClassName -v`
3. Verify coverage: `python run_tests.py unit --coverage`
4. Update documentation if needed

## Version History

- **v2.0** (Nov 2025) - Complete rewrite with 51 unit tests
- **v1.0** (Oct 2025) - Initial test suite (deprecated)

---

**Status:** ✅ Ready for use
**Last Test Run:** 🎯 Run `python run_tests.py unit` to execute
**Coverage:** 🎯 Run with `--coverage` to generate report
