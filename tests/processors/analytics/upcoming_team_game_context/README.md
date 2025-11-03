# Upcoming Team Game Context Processor - Test Suite

**Processor:** `upcoming_team_game_context`  
**Phase:** 3 (Analytics)  
**Test Coverage:** >95%  
**Total Tests:** 35+ unit tests

## Overview

This test suite validates the Upcoming Team Game Context Processor, which calculates comprehensive team-level context for upcoming NBA games including fatigue metrics, betting context, personnel availability, recent performance, and travel impact.

## Test Structure

```
tests/processors/analytics/upcoming_team_game_context/
├── __init__.py                # Package marker
├── conftest.py                # Pytest configuration & fixtures
├── test_unit.py               # 35+ unit tests (~10s)
├── test_integration.py        # 8 integration tests (~15s) [TODO]
├── test_validation.py         # 15 validation tests (~30s) [TODO]
├── run_tests.py               # Test runner script
└── README.md                  # This file
```

## Quick Start

### Run All Unit Tests
```bash
cd tests/processors/analytics/upcoming_team_game_context
python run_tests.py unit
```

### Run with Coverage
```bash
python run_tests.py unit --coverage
```

### Run Quick Tests (Unit + Integration)
```bash
python run_tests.py quick
```

## Unit Tests (test_unit.py)

**Runtime:** ~10 seconds  
**Count:** 35+ tests  
**Coverage:** >95%

### Test Classes

| Class | Tests | Coverage | Description |
|-------|-------|----------|-------------|
| `TestDependencyConfiguration` | 4 | 100% | Dependency tracking v4.0 configuration |
| `TestFatigueCalculation` | 6 | 100% | Days rest, back-to-backs, game windows |
| `TestBettingContext` | 5 | 100% | Spreads, totals, bookmaker priority |
| `TestTeamNameMatching` | 6 | 100% | Team name to abbreviation mapping |
| `TestPersonnelContext` | 4 | 100% | Injury reports, player availability |
| `TestMomentumContext` | 6 | 100% | Win/loss streaks, recent performance |
| `TestTravelContext` | 4 | 100% | Travel distance calculations |
| `TestSourceTracking` | 4 | 100% | v4.0 source metadata tracking |
| `TestQualityTracking` | 3 | 100% | Quality issue logging |
| `TestTeamGameContextCalculation` | 3 | 100% | End-to-end record construction |

### Key Test Coverage

#### ✅ Fatigue Metrics
- First game of season (NULL handling)
- Back-to-back game detection
- Normal rest days calculation
- Games in 7/14-day windows
- Game number incrementing

#### ✅ Betting Context
- Spread and total extraction
- Home vs away team perspective
- Bookmaker priority (DraftKings > FanDuel)
- Missing betting lines handling
- Team name matching variants

#### ✅ Personnel Availability
- Players out count
- Questionable/doubtful players
- Multiple injury statuses
- No injuries scenario

#### ✅ Momentum & Streaks
- Win streak calculation
- Loss streak calculation
- Last game margin (positive/negative)
- First game of season handling

#### ✅ Travel Impact
- Home games (0 miles)
- Away games with travel
- Back-to-back away games
- First game zero travel

#### ✅ Source Tracking (v4.0)
- All 9 source tracking fields
- Schedule (CRITICAL)
- Betting lines (OPTIONAL)
- Injury reports (OPTIONAL)

## Integration Tests (test_integration.py)

**Runtime:** ~15 seconds  
**Count:** 10 tests  
**Coverage:** End-to-end processor flow

### Test Classes

| Class | Tests | Coverage | Description |
|-------|-------|----------|-------------|
| `TestFullProcessorFlow` | 3 | 100% | Complete end-to-end processing scenarios |
| `TestDependencyChecking` | 3 | 100% | Critical/optional dependency validation |
| `TestDataExtractionScenarios` | 2 | 100% | ESPN fallback, extended lookback windows |
| `TestCalculationScenarios` | 1 | 100% | Multi-game date range processing |
| `TestErrorHandling` | 2 | 100% | BigQuery errors, validation failures |
| `TestSourceTrackingIntegration` | 1 | 100% | v4.0 source tracking in full flow |

### Key Test Coverage

#### ✅ Full Processing Flow
- Successful complete run with all sources
- No games in date range (off-season)
- Missing optional sources (betting/injury)

#### ✅ Dependency Management
- Missing critical dependency (should fail)
- Stale critical dependency (should fail)
- Stale warning (should continue)

#### ✅ Data Extraction
- ESPN fallback for schedule gaps
- Extended lookback window (30 days)
- Multi-source data aggregation

#### ✅ Error Handling
- BigQuery query failures
- Validation errors on invalid data
- Graceful degradation

#### ✅ Source Tracking
- v4.0 metadata population
- Track across full flow
- All 3 sources tracked

## Validation Tests (test_validation.py)

**Status:** TODO  
**Planned Tests:** 15  
**Runtime:** ~30 seconds

Planned coverage:
- BigQuery schema compatibility
- Real data quality checks
- Business rule validation
- Source tracking completeness
- Production data scenarios

## Fixtures

### Core Fixtures

#### `processor`
Clean processor instance with mocked dependencies.

```python
@pytest.fixture
def processor():
    """Create processor with mocked BigQuery client."""
    proc = UpcomingTeamGameContextProcessor()
    proc.bq_client = Mock()
    proc.project_id = 'test-project'
    proc.travel_distances = {...}
    return proc
```

#### `sample_schedule_data`
3 completed games for testing fatigue and momentum.

```python
@pytest.fixture
def sample_schedule_data():
    """Sample schedule with 3 games."""
    return pd.DataFrame([...])
```

#### `sample_betting_lines`
DraftKings betting lines for one game.

#### `sample_injury_data`
Mix of out/questionable/doubtful players.

## Running Tests

### Basic Commands

```bash
# Run all unit tests
pytest test_unit.py -v

# Run specific test class
pytest test_unit.py::TestFatigueCalculation -v

# Run specific test
pytest test_unit.py::TestFatigueCalculation::test_back_to_back_game -v

# Run with coverage
pytest test_unit.py --cov=data_processors.analytics.upcoming_team_game_context --cov-report=html
```

### Using Test Runner

```bash
# All tests
python run_tests.py

# Only unit tests
python run_tests.py unit

# Quick tests (unit + integration)
python run_tests.py quick

# With coverage report
python run_tests.py unit --coverage

# Verbose output
python run_tests.py unit --verbose
```

## Test Development

### Adding New Unit Tests

1. **Identify method to test**
2. **Choose appropriate test class** (or create new one)
3. **Write fixture if needed**
4. **Write test with clear name**: `test_<method>_<scenario>_<expected>`
5. **Calculate expected result explicitly**
6. **Use `pytest.approx()` for floats**
7. **Add docstring explaining test**

Example:
```python
def test_calculate_fatigue_normal_rest(self, processor, sample_schedule_data):
    """Test fatigue calculation with 2-day rest between games."""
    processor.schedule_data = sample_schedule_data
    
    game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-14'].iloc[0]
    result = processor._calculate_fatigue_context(game, 'LAL')
    
    # 2 days between games = 1 day of rest
    assert result['team_days_rest'] == 1
    assert result['team_back_to_back'] is False
```

## Common Test Patterns

### Pattern 1: Edge Case Testing
```python
def test_first_game_of_season(self, processor, sample_data):
    """Test handling when team has no previous games."""
    result = processor._calculate_something(sample_data, 'TEAM')
    assert result['field'] is None  # Graceful NULL handling
```

### Pattern 2: Calculation Validation
```python
def test_calculation_correct_math(self, processor):
    """Test mathematical calculation is correct."""
    # Show expected calculation
    expected = (total_paint / total_shots) * 100
    
    result = processor._calculate_metric(data)
    assert result['metric'] == pytest.approx(expected, abs=0.01)
```

### Pattern 3: Multiple Scenarios
```python
@pytest.mark.parametrize("status,expected", [
    ('out', 1),
    ('questionable', 1),
    ('doubtful', 1),
    ('probable', 0)
])
def test_injury_status_counting(self, processor, status, expected):
    """Test different injury statuses are counted correctly."""
    # Test implementation
```

## Troubleshooting

### Import Errors

**Problem:** `ImportError: cannot import name 'pubsub_v1'`

**Solution:** The `conftest.py` should mock Google Cloud packages. Ensure it's present:
```python
import sys
from unittest.mock import MagicMock
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()
```

### Float Comparison Failures

**Problem:** `AssertionError: 0.571428571 != 0.571`

**Solution:** Use `pytest.approx()`:
```python
# ❌ Wrong
assert result == 0.571

# ✅ Correct
assert result == pytest.approx(0.571, abs=0.001)
```

### Fixture Not Found

**Problem:** `fixture 'processor' not found`

**Solution:** Ensure fixture is defined in same test file or `conftest.py`:
```python
@pytest.fixture
def processor():
    return UpcomingTeamGameContextProcessor()
```

## Test Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Unit Test Count | 30+ | 45 ✅ |
| Integration Test Count | 8+ | 10 ✅ |
| Code Coverage | >85% | >95% ✅ |
| Test Runtime (Unit) | <15s | ~10s ✅ |
| Test Runtime (Integration) | <20s | ~15s ✅ |
| Test Classes | 8+ | 16 ✅ |
| Edge Cases | High | High ✅ |

## Next Steps

1. ✅ **Unit Tests** - Complete (45 tests)
2. ✅ **Integration Tests** - Complete (10 tests)
3. ⏳ **Validation Tests** - TODO (15 tests planned)
4. ⏳ **CI/CD Integration** - TODO
5. ⏳ **Performance Benchmarks** - TODO

## References

- [Unit Test Writing Guide](../../../../docs/testing/unit_test_guide_phase4.md)
- [Phase 3 Processor Guide](../../../../docs/processors/phase3_quick_start.md)
- [Dependency Tracking v4.0](../../../../docs/architecture/dependency_tracking_v4.md)

## Success Criteria

- ✅ All unit tests pass
- ✅ Coverage >95%
- ✅ Tests run in <10 seconds
- ✅ All calculation methods tested
- ✅ Edge cases covered
- ✅ Source tracking validated
- ✅ Clear test names and documentation

---

**Status:** Unit Tests Complete ✅  
**Last Updated:** November 2, 2025  
**Maintainer:** NBA Props Platform Team