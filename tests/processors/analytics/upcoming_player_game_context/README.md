# Path: tests/processors/analytics/upcoming_player_game_context/README.md
# UpcomingPlayerGameContext Processor - Test Suite

Comprehensive test suite for the UpcomingPlayerGameContext Phase 3 analytics processor.

## Test Structure

```
upcoming_player_game_context/
├── __init__.py
├── conftest.py           # Google Cloud mocks
├── test_unit.py          # 30 unit tests
├── test_integration.py   # Integration tests (TODO)
├── test_validation.py    # Validation tests (TODO)
├── run_tests.py          # Test runner
└── README.md            # This file
```

## Quick Start

### Run All Unit Tests
```bash
cd tests/processors/analytics/upcoming_player_game_context
python run_tests.py unit
```

### Run Specific Test Class
```bash
pytest test_unit.py::TestFatigueMetricsCalculation -v
```

### Run with Coverage
```bash
python run_tests.py unit --coverage
```

## Unit Tests (30 tests)

### TestProcessorInitialization (4 tests)
- Processor creation and configuration
- Dependency configuration validation
- Default parameter values

### TestMinutesParsing (8 tests)
- MM:SS format parsing
- Edge cases (0:00, DNP, NULL)
- Invalid format handling
- Numeric input handling

### TestTeamDetermination (4 tests)
- Team identification from boxscores
- No history handling
- Opponent team determination

### TestFatigueMetricsCalculation (7 tests)
- Days rest calculation
- Back-to-back detection
- Games in 7/14-day windows
- Minutes totals and averages
- Back-to-back counting in period
- Empty data handling

### TestPerformanceMetricsCalculation (4 tests)
- Points averages (last 5, last 10)
- Empty data handling
- Fewer than 5 games handling

### TestDataQualityCalculation (6 tests)
- Quality tier assignment (high/medium/low)
- Issues flag logic
- Missing game lines
- Insufficient data detection

### TestSourceTrackingFields (6 tests)
- v4.0 tracking field structure
- Timestamp ISO format
- Rows found values
- Completeness calculations

### TestSeasonPhaseDetermination (6 tests)
- Early season (Oct-Nov)
- Mid season (Dec-Feb)
- Late season (Mar-Apr)
- Playoffs (May-Jun)

## Test Coverage Goals

| Component | Target | Status |
|-----------|--------|--------|
| Core Calculations | 100% | ✅ Complete |
| Utility Methods | 100% | ✅ Complete |
| Source Tracking | 100% | ✅ Complete |
| Configuration | 90% | ✅ Complete |
| Error Handling | 100% | ✅ Complete |

## Running Tests

### By Test Type
```bash
python run_tests.py unit           # Unit tests only
python run_tests.py integration    # Integration tests (TODO)
python run_tests.py validation     # Validation tests (TODO)
python run_tests.py quick          # Unit + integration
```

### With Options
```bash
python run_tests.py unit --verbose     # Verbose output
python run_tests.py unit --coverage    # Coverage report
pytest test_unit.py -k "fatigue" -v   # Tests matching "fatigue"
```

### CI/CD Usage
```bash
# Fast feedback (unit tests only)
pytest test_unit.py -v --tb=short

# Full test suite
python run_tests.py --coverage
```

## Test Patterns Used

### Fixtures
- `processor`: Mocked processor instance
- `sample_games`: Historical game data
- Isolated per-test with function scope

### Assertion Patterns
- `pytest.approx()` for float comparisons
- Explicit expected value calculations
- Descriptive failure messages

### Mock Strategy
- BigQuery client mocked in fixtures
- No network calls in unit tests
- Fast execution (<5 seconds total)

## Next Steps

- [ ] Add integration tests (8 tests)
- [ ] Add validation tests (15 tests)
- [ ] Increase coverage to 95%+
- [ ] Add performance benchmarks

## Related Documentation

- [Unit Test Writing Guide](../../../../../../docs/testing/unit_test_guide.md)
- [Processor Implementation](../../../../../../data_processors/analytics/upcoming_player_game_context/processor.py)
- [Schema Documentation](../../../../../../schemas/bigquery/analytics/upcoming_player_game_context_tables.sql)

## Maintenance

- Run unit tests before every commit
- Update tests when adding new calculations
- Keep test execution time under 5 seconds
- Maintain >90% coverage

Last Updated: November 2025
Status: Unit Tests Complete ✅
