# Team Defense Zone Analysis Processor - Test Suite

Comprehensive testing for Phase 4 Team Defense Zone Analysis processor.

## 📋 Test Overview

### Test Files

| File | Type | Purpose | Run Time | Requires BQ |
|------|------|---------|----------|-------------|
| `test_team_defense_unit.py` | Unit | Individual method testing | ~5s | ❌ |
| `test_team_defense_integration.py` | Integration | End-to-end flow with mocks | ~10s | ❌ |
| `test_team_defense_validation.py` | Validation | Data quality checks | ~30s | ✅ |

### Coverage

**Unit Tests:** 25 tests
- Zone defense calculations
- Strengths/weaknesses identification
- Data quality tier assignment
- Source tracking fields (v4.0)
- League average calculation
- Dependency configuration

**Integration Tests:** 8 tests
- Full processing flow
- Early season placeholder generation
- Insufficient games handling
- Dependency checking (custom per_team_game_count)
- Error handling (missing deps, stale data)
- Source tracking integration

**Validation Tests:** 15 tests
- Output data quality (ranges, completeness)
- Source tracking validation
- Early season handling
- Historical consistency
- Cross-team comparisons

**Total: 48 tests**

---

## 🚀 Quick Start

### Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-mock

# For validation tests (optional)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### Run Tests

```bash
# Run unit tests (fast, no dependencies)
pytest tests/precompute/test_team_defense_unit.py -v

# Run integration tests
pytest tests/precompute/test_team_defense_integration.py -v

# Run validation tests (requires BigQuery)
pytest tests/precompute/test_team_defense_validation.py -v --bigquery

# Run all tests
pytest tests/precompute/test_team_defense_*.py -v --bigquery
```

### Using Test Runner

```bash
# Make executable
chmod +x tests/precompute/run_team_defense_tests.py

# Run unit tests
./run_team_defense_tests.py --unit

# Run all tests
./run_team_defense_tests.py --all

# Run with coverage
./run_team_defense_tests.py --unit --coverage

# Run specific test
./run_team_defense_tests.py --test test_team_defense_unit.py::TestZoneDefenseCalculations
```

---

## 📝 Test Details

### Unit Tests (`test_team_defense_unit.py`)

#### TestZoneDefenseCalculations
Tests `_calculate_zone_defense()` method.

**Tests:**
- `test_calculate_zone_defense_basic` - Verify calculations with sample data
- `test_vs_league_average_calculations` - Check percentage point differences
- `test_no_mid_range_attempts` - Handle zero attempts in one zone
- `test_zero_attempts_all_zones` - Handle zero attempts everywhere

**Example:**
```python
def test_calculate_zone_defense_basic(self, processor, sample_team_data):
    result = processor._calculate_zone_defense(sample_team_data, games_count=15)
    
    # Paint defense
    assert result['paint_pct'] == pytest.approx(0.571, abs=0.001)
    assert result['paint_vs_league'] == pytest.approx(-0.9, abs=0.1)
```

#### TestStrengthsWeaknessesIdentification
Tests `_identify_strengths_weaknesses()` method.

**Tests:**
- `test_identify_clear_strength_weakness` - Best/worst zones
- `test_identify_perimeter_strength` - Elite perimeter defense
- `test_identify_with_missing_zone` - Handle NULL zone data
- `test_identify_all_zones_missing` - All zones NULL
- `test_identify_balanced_defense` - Similar performance across zones

#### TestDataQualityTier
Tests `_determine_quality_tier()` method.

**Tests:**
- `test_high_quality_15_games` - 15 games = high
- `test_high_quality_more_games` - 20 games = high
- `test_medium_quality` - 10-14 games = medium
- `test_low_quality` - <10 games = low

#### TestSourceTrackingFields
Tests `build_source_tracking_fields()` method (v4.0).

**Tests:**
- `test_build_source_tracking_normal` - Normal season
- `test_build_source_tracking_early_season` - Early season flags
- `test_build_source_tracking_missing_source` - NULL when missing

#### TestLeagueAverageCalculation
Tests league average calculation logic.

**Tests:**
- `test_league_averages_sufficient_teams` - Normal calculation
- `test_league_averages_insufficient_teams` - Fallback to defaults
- `test_league_averages_empty_result` - Handle empty query

#### TestDependencyConfiguration
Tests dependency configuration structure.

**Tests:**
- `test_get_dependencies_structure` - Verify config format
- `test_get_dependencies_configurable_params` - Dynamic parameters

---

### Integration Tests (`test_team_defense_integration.py`)

#### TestFullProcessingFlow
Tests complete end-to-end processing.

**Tests:**
- `test_successful_processing` - Happy path with 5 teams
- `test_early_season_placeholder_flow` - Placeholder generation
- `test_insufficient_games_handling` - Some teams with <15 games

**Example:**
```python
def test_successful_processing(self, processor, mock_team_defense_data):
    # Setup mocks
    processor.opts = {'analysis_date': date(2025, 1, 27), ...}
    
    # Execute
    processor.extract_raw_data()
    processor.calculate_precompute()
    
    # Verify
    assert len(processor.transformed_data) == 5
    assert processor.transformed_data[0]['games_in_sample'] == 15
```

#### TestDependencyChecking
Tests custom dependency checking logic.

**Tests:**
- `test_check_table_data_per_team_game_count` - Custom check type
- `test_check_table_data_insufficient_teams` - Fails when <25 teams

#### TestErrorHandling
Tests error conditions.

**Tests:**
- `test_missing_critical_dependency` - Raises ValueError
- `test_stale_data_warning` - Logs warning, continues

#### TestSourceTrackingIntegration
Tests v4.0 source tracking in output.

**Tests:**
- `test_source_tracking_populated_in_output` - Fields in records

---

### Validation Tests (`test_team_defense_validation.py`)

⚠️ **Requires BigQuery access and `--bigquery` flag**

#### TestOutputDataQuality
Validates processed data quality.

**Tests:**
- `test_all_30_teams_processed` - 30 unique teams
- `test_no_missing_critical_fields` - Required fields populated
- `test_field_value_ranges` - Metrics within valid ranges
- `test_strengths_weaknesses_identified` - All teams have zones
- `test_data_quality_tier_assignment` - Tiers assigned correctly

**Example:**
```python
def test_field_value_ranges(self, latest_data):
    # Paint FG% should be 40-75%
    assert latest_data['paint_pct_allowed_last_15'].min() >= 0.40
    assert latest_data['paint_pct_allowed_last_15'].max() <= 0.75
```

#### TestSourceTrackingFields
Validates v4.0 source tracking.

**Tests:**
- `test_source_tracking_populated` - All 3 fields present
- `test_source_completeness_is_100` - Completeness >= 95%
- `test_source_data_is_fresh` - Data <24 hours old
- `test_source_rows_found_reasonable` - ~450 rows (30×15)

#### TestEarlySeasonHandling
Validates early season behavior.

**Tests:**
- `test_early_season_placeholders` - NULL metrics, flags set

#### TestHistoricalConsistency
Validates consistency over time.

**Tests:**
- `test_no_duplicate_dates_per_team` - No duplicates
- `test_processed_at_timestamps_sequential` - Timestamps in order
- `test_metrics_reasonable_variance_over_time` - <10pp day-over-day

#### TestCrossTeamComparisons
Validates data across teams.

**Tests:**
- `test_league_average_is_centered` - vs_league_avg near 0
- `test_defensive_rating_distribution` - Reasonable spread
- `test_paint_defense_correlates_with_rating` - Positive correlation

---

## 🎯 Test Strategies

### Unit Testing Strategy
- **Isolation:** Mock all external dependencies (BigQuery, notifications)
- **Coverage:** Test each method independently
- **Edge Cases:** Zero attempts, missing zones, NULL values
- **Fast:** All unit tests complete in <10 seconds

### Integration Testing Strategy
- **End-to-End:** Test full processing flow with realistic mocks
- **Scenarios:** Normal season, early season, insufficient data
- **Dependencies:** Test custom `per_team_game_count` check
- **Error Paths:** Missing deps, stale data, failures

### Validation Testing Strategy
- **Real Data:** Query actual BigQuery tables
- **Data Quality:** Verify ranges, completeness, consistency
- **Source Tracking:** Validate v4.0 metadata
- **Historical:** Check consistency across dates
- **Nightly:** Run after processor completes

---

## 📊 Running Tests in CI/CD

### GitHub Actions Example

```yaml
name: Team Defense Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-cov pytest-mock
    
    - name: Run unit tests
      run: |
        pytest tests/precompute/test_team_defense_unit.py -v --cov
    
    - name: Run integration tests
      run: |
        pytest tests/precompute/test_team_defense_integration.py -v
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

### Cloud Build Example

```yaml
steps:
  # Run unit tests
  - name: 'python:3.9'
    entrypoint: 'pytest'
    args:
      - 'tests/precompute/test_team_defense_unit.py'
      - '-v'
      - '--junitxml=test-results.xml'
  
  # Run validation tests (requires BigQuery)
  - name: 'python:3.9'
    entrypoint: 'pytest'
    args:
      - 'tests/precompute/test_team_defense_validation.py'
      - '-v'
      - '--bigquery'
    env:
      - 'GOOGLE_APPLICATION_CREDENTIALS=/workspace/service-account.json'
```

---

## 🐛 Debugging Failed Tests

### Unit Test Failures

**Symptom:** Calculation tests fail with small differences
```
AssertionError: assert 0.572 == 0.571 ± 0.001
```

**Fix:** Adjust `pytest.approx()` tolerance or check rounding logic

**Symptom:** Import errors
```
ModuleNotFoundError: No module named 'data_processors'
```

**Fix:** Ensure PYTHONPATH includes project root:
```bash
export PYTHONPATH="${PYTHONPATH}:/path/to/nba-stats-scraper"
```

### Integration Test Failures

**Symptom:** Mock not called as expected
```
AssertionError: Expected 'query' to be called 2 times. Called 1 times.
```

**Fix:** Check mock setup and call sequence

**Symptom:** Dependency check fails in test
```
ValueError: Missing critical dependencies
```

**Fix:** Update mock dependency check to return `all_critical_present=True`

### Validation Test Failures

**Symptom:** No data available
```
SKIPPED [1] All data is early season placeholders
```

**Fix:** Normal during early season. Wait for 15+ games.

**Symptom:** BigQuery permission denied
```
google.api_core.exceptions.Forbidden: 403 Permission denied
```

**Fix:** Ensure service account has BigQuery Data Viewer role

**Symptom:** Field value out of range
```
AssertionError: Paint FG% too high
```

**Fix:** Check upstream data quality or adjust thresholds

---

## 📈 Coverage Goals

| Component | Target | Current |
|-----------|--------|---------|
| Overall | 85% | TBD |
| `_calculate_zone_defense` | 100% | ✅ |
| `_identify_strengths_weaknesses` | 100% | ✅ |
| `build_source_tracking_fields` | 100% | ✅ |
| `extract_raw_data` | 90% | ✅ |
| `calculate_precompute` | 90% | ✅ |

Generate coverage report:
```bash
pytest tests/precompute/test_team_defense_*.py --cov --cov-report=html
open htmlcov/index.html
```

---

## 🔄 Test Maintenance

### When to Update Tests

**Processor changes:**
- Add new metrics → Add validation tests
- Change calculation logic → Update unit tests
- Modify dependencies → Update integration tests

**Schema changes:**
- Add fields → Update validation tests
- Change field types → Update assertions
- Add constraints → Add validation

**Configuration changes:**
- Change thresholds (15 games, 30-day window) → Update test fixtures

### Test Naming Convention

```python
# Unit tests
def test_<method>_<scenario>_<expected_result>

# Integration tests  
def test_<feature>_<scenario>

# Validation tests
def test_<assertion>_<condition>
```

### Adding New Tests

1. Identify test type (unit/integration/validation)
2. Create fixture if needed
3. Write test following naming convention
4. Add docstring explaining purpose
5. Run test to verify it works
6. Update this README

---

## 📚 Resources

- **Processor Code:** `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
- **Base Class:** `data_processors/precompute/precompute_base.py`
- **Schema:** `schemas/bigquery/precompute/team_defense_zone_analysis.sql`
- **Implementation Guide:** `docs/phase4/team-defense-zone-analysis-implementation-v4.md`

---

## ❓ FAQ

**Q: Why do unit tests run so fast?**  
A: They mock all external dependencies (BigQuery, notifications), so no network calls.

**Q: Why do validation tests require --bigquery flag?**  
A: They query actual BigQuery tables, so we skip them by default to avoid costs/auth issues.

**Q: What happens if Phase 3 dependency doesn't exist yet?**  
A: Integration tests use mocks, so they pass. Validation tests will skip. Real processor will fail gracefully.

**Q: How do I test early season behavior?**  
A: Use integration test `test_early_season_placeholder_flow` or run validation tests against early season dates.

**Q: Can I run tests locally without BigQuery?**  
A: Yes! Unit and integration tests work without BigQuery. Only validation tests require it.

**Q: How often should validation tests run?**  
A: Nightly after processor completes. They validate production data quality.

---

**Last Updated:** January 2025  
**Test Coverage:** 48 tests (25 unit + 8 integration + 15 validation)  
**Status:** ✅ Ready for use
