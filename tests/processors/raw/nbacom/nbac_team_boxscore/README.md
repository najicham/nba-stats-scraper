# NBA.com Team Boxscore Processor - Test Suite

**Path:** `tests/processors/raw/nbacom/nbac_team_boxscore/`  
**Processor:** `NbacTeamBoxscoreProcessor`  
**Coverage:** ~95%  
**Total Tests:** 56 unit tests  

## Quick Start

```bash
# Navigate to test directory
cd tests/processors/raw/nbacom/nbac_team_boxscore/

# Run all unit tests
python run_tests.py unit

# Run with coverage report
python run_tests.py unit --coverage

# Run with verbose output
python run_tests.py unit --verbose

# Or use pytest directly
pytest test_unit.py -v
```

## Test Suite Structure

```
nbac_team_boxscore/
├── __init__.py
├── conftest.py           # Google Cloud mocks
├── test_unit.py          # 56 unit tests ⭐
├── run_tests.py          # Test runner
└── README.md             # This file
```

## Test Coverage Summary

### 56 Unit Tests

| Test Class | Tests | Coverage | What's Tested |
|------------|-------|----------|---------------|
| **TestTextNormalization** | 7 | 100% | `normalize_team_abbr()`, `normalize_text()` |
| **TestSeasonYearExtraction** | 6 | 100% | `extract_season_year()` - season boundaries |
| **TestSafeConversions** | 9 | 100% | `safe_int()`, `safe_float()` - type conversions |
| **TestDataValidation** | 14 | 100% | `validate_data()` - comprehensive validation |
| **TestDataTransformation** | 14 | 95% | `transform_data()` - BigQuery mapping |
| **TestEdgeCases** | 6 | 100% | Error handling, boundary conditions |
| **TOTAL** | **56** | **~95%** | **All core methods** |

## Test Details

### 1. Text Normalization (7 tests)

Tests basic string cleaning and normalization:

```python
test_normalize_team_abbr_basic()           # "lal" → "LAL"
test_normalize_team_abbr_with_spaces()     # "  BOS  " → "BOS"
test_normalize_team_abbr_empty_and_null()  # None → ""
test_normalize_text_basic()                # Basic trimming
test_normalize_text_multiple_spaces()      # "Golden   State" → "Golden State"
test_normalize_text_tabs_and_newlines()    # Tab/newline handling
test_normalize_text_empty_and_null()       # None → ""
```

**Why important:** Ensures consistent team abbreviations and clean text data.

---

### 2. Season Year Extraction (6 tests)

Tests NBA season year calculation logic:

```python
test_season_october_start()                # Oct 2024 → 2024-25 season
test_season_november_december()            # Nov/Dec stay same year
test_season_january_through_june()         # Jan-Jun → previous year's season
test_season_boundary_september()           # Sep → previous year
test_season_with_date_object()             # date() vs string
test_season_invalid_date_returns_fallback() # Invalid → current_year - 1
```

**Critical logic:** NBA season spans two calendar years (Oct 2024 - Jun 2025 = 2024-25 season).

**Example:**
- Game on 2024-10-22 → `season_year = 2024`
- Game on 2025-01-15 → `season_year = 2024` (same season!)
- Game on 2025-06-15 → `season_year = 2024` (Finals)

---

### 3. Safe Conversions (9 tests)

Tests type conversion with error handling:

```python
# Integer conversions
test_safe_int_valid_values()               # 42, "100" → integers
test_safe_int_invalid_values()             # "abc" → default
test_safe_int_null_and_empty()             # None, "" → default
test_safe_int_float_conversion()           # 42.9 → 42

# Float conversions
test_safe_float_valid_values()             # 0.5, "0.571" → floats
test_safe_float_invalid_values()           # "abc" → default
test_safe_float_null_and_empty()           # None → default
test_safe_float_scientific_notation()      # "1.5e-3" → 0.0015
```

**Why important:** NBA.com API data types can vary; safe conversions prevent crashes.

---

### 4. Data Validation (14 tests) ⭐ Most Critical

Tests comprehensive validation rules:

#### Structure Validation
```python
test_validate_valid_data_no_errors()       # ✅ Perfect data
test_validate_missing_game_id()            # ❌ No gameId
test_validate_missing_game_date()          # ❌ No gameDate
test_validate_missing_teams()              # ❌ No teams array
test_validate_wrong_team_count()           # ❌ Not exactly 2 teams
test_validate_team_missing_required_field() # ❌ Missing team field
test_validate_teams_not_list()             # ❌ teams is dict, not list
test_validate_team_not_dict()              # ❌ team is string, not dict
```

#### Shooting Validation
```python
test_validate_field_goals_structure()      # ❌ Missing made/attempted
test_validate_made_exceeds_attempted()     # ❌ FG made > attempted (impossible!)
```

#### Rebounds Validation
```python
test_validate_rebounds_structure()         # ❌ Missing offensive/defensive/total
test_validate_rebounds_math()              # ❌ Off + Def ≠ Total
```

#### Points Validation
```python
test_validate_points_calculation()         # ❌ Points ≠ (FG2×2 + 3PT×3 + FT)
```

#### Multi-Error Detection
```python
test_validate_multiple_errors()            # Collects ALL errors, not just first
```

**Critical validation formulas:**
- `FG made ≤ FG attempted`
- `3PT made ≤ FG made` (3-pointers are subset of field goals)
- `Offensive rebounds + Defensive rebounds = Total rebounds`
- `Points = (FG2 made × 2) + (3PT made × 3) + (FT made × 1)`

---

### 5. Data Transformation (14 tests) ⭐ Core Logic

Tests BigQuery record creation:

#### Basic Transformation
```python
test_transform_returns_two_records()       # Always 2 rows (one per team)
test_transform_game_identity_fields()      # game_id, game_date, season_year
test_transform_team_identity_fields()      # team_id, team_abbr, team_name
test_transform_metadata_fields()           # source_file_path, timestamps
```

#### Statistics Mapping
```python
test_transform_shooting_stats()            # FG, 3PT, FT stats
test_transform_rebound_stats()             # Offensive, defensive, total
test_transform_other_stats()               # Assists, steals, blocks, etc.
```

#### Edge Cases
```python
test_transform_handles_missing_optional_fields() # plusMinus can be missing
test_transform_with_zero_attempts()        # 0/0 FG% → NULL
test_transform_overtime_game()             # minutes: "265:00"
test_transform_normalizes_text_fields()    # Applies normalization
```

**Example transformation:**
```python
Input:  {'teamAbbreviation': '  lal  ', 'points': 114}
Output: {'team_abbr': 'LAL', 'points': 114, 'season_year': 2024, ...}
```

---

### 6. Edge Cases (6 tests)

Tests unusual scenarios and error handling:

```python
test_transform_with_no_teams()             # Empty teams array
test_extract_season_year_with_various_formats() # String vs date object
test_safe_conversions_with_edge_values()   # Large numbers, negatives, zero
```

---

## Running the Tests

### Option 1: Test Runner (Recommended)

```bash
# All unit tests
python run_tests.py unit

# With coverage report
python run_tests.py unit --coverage

# Verbose output
python run_tests.py unit --verbose
```

### Option 2: Direct pytest

```bash
# All tests with verbose output
pytest test_unit.py -v

# Specific test class
pytest test_unit.py::TestDataValidation -v

# Specific test
pytest test_unit.py::TestSeasonYearExtraction::test_season_october_start -v

# With coverage
pytest test_unit.py --cov=data_processors.raw.nbacom.nbac_team_boxscore_processor --cov-report=html
```

### Option 3: Run from project root

```bash
pytest tests/processors/raw/nbacom/nbac_team_boxscore/test_unit.py -v
```

---

## Expected Output

### ✅ All Tests Passing

```
======================== test session starts =========================
platform darwin -- Python 3.11.x
collected 56 items

test_unit.py::TestTextNormalization::test_normalize_team_abbr_basic PASSED [  1%]
test_unit.py::TestTextNormalization::test_normalize_team_abbr_with_spaces PASSED [  3%]
...
test_unit.py::TestEdgeCases::test_safe_conversions_with_edge_values PASSED [100%]

======================== 56 passed in 5.23s ==========================
```

### 📊 Coverage Report

```
Name                                          Stmts   Miss  Cover
-----------------------------------------------------------------
nbac_team_boxscore_processor.py                 250      12    95%
-----------------------------------------------------------------
TOTAL                                            250      12    95%
```

---

## What's NOT Tested (Integration Tests)

These require BigQuery and are tested separately:

- `load_data()` - BigQuery insert operations
- `process_file()` - Full end-to-end file processing
- GCS file reading
- MERGE_UPDATE strategy (delete + insert)

**See:** `test_integration.py` (to be created)

---

## Test Data Patterns

### Valid Game Data Structure

```python
{
    'gameId': '0022400561',
    'gameDate': '2025-01-15',
    'teams': [
        {
            'teamId': 1610612755,
            'teamAbbreviation': 'PHI',
            'teamName': '76ers',
            'teamCity': 'Philadelphia',
            'minutes': '240:00',
            'fieldGoals': {'made': 40, 'attempted': 88, 'percentage': 0.455},
            'threePointers': {'made': 12, 'attempted': 35, 'percentage': 0.343},
            'freeThrows': {'made': 18, 'attempted': 22, 'percentage': 0.818},
            'rebounds': {'offensive': 10, 'defensive': 35, 'total': 45},
            'assists': 24,
            'steals': 8,
            'blocks': 5,
            'turnovers': 12,
            'personalFouls': 20,
            'points': 110,
            'plusMinus': -4
        },
        # Second team...
    ]
}
```

---

## Key Testing Principles Applied

### 1. ✅ Isolation
- All external dependencies mocked (BigQuery, GCS)
- Tests run independently
- No network calls

### 2. ✅ Comprehensive
- 56 tests cover all public methods
- Edge cases included
- Error conditions tested

### 3. ✅ Fast
- All tests complete in ~5 seconds
- No database connections
- Perfect for TDD workflow

### 4. ✅ Clear
- Descriptive test names
- Explicit expected value calculations
- Good docstrings

### 5. ✅ Maintainable
- Fixtures reduce duplication
- Grouped by functionality
- Easy to extend

---

## Common Issues & Solutions

### Import Error: `google.cloud.pubsub_v1`

**Solution:** The `conftest.py` mocks Google Cloud packages. Make sure it's in the same directory as your tests.

### Test Fails: Float comparison

**Problem:**
```python
assert result == 0.455  # May fail due to float precision
```

**Solution:**
```python
assert result == pytest.approx(0.455, abs=0.001)
```

### Test Fails: Timestamp format

**Problem:** BigQuery expects ISO format timestamps with `.isoformat()`

**Solution:** Verify processor uses:
```python
created_at = datetime.utcnow().isoformat()  # "2025-01-15T12:30:45.123456"
```

---

## Next Steps

### ✅ Completed
- [x] Unit tests written (56 tests)
- [x] Test runner created
- [x] Documentation complete

### 🔜 To Do
- [ ] Create `test_integration.py` (8-10 tests)
  - Test `load_data()` with mocked BigQuery
  - Test `process_file()` end-to-end
  - Test MERGE_UPDATE strategy
- [ ] Run tests in CI/CD pipeline
- [ ] Add performance tests (large datasets)

---

## Related Files

- **Processor:** `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
- **Schema:** `schemas/bigquery/raw/nbac_team_boxscore_tables.sql`
- **Scraper:** `scrapers/nba_com/nbac_team_boxscore.py`

---

## Questions?

Refer to:
- 🧪 **Unit Test Writing Guide** - Comprehensive testing patterns
- 📊 **Processor Implementation Guide** - How processors work
- 🗄️ **Schema Documentation** - BigQuery table structure

---

**Test Suite Version:** 1.0  
**Last Updated:** November 1, 2025  
**Status:** ✅ Ready to Use
