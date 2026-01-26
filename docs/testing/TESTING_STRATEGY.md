# Testing Strategy

Comprehensive testing strategy for the NBA Stats Scraper platform.

## Table of Contents

1. [Testing Philosophy](#testing-philosophy)
2. [Test Pyramid](#test-pyramid)
3. [Coverage Goals](#coverage-goals)
4. [Test Organization](#test-organization)
5. [Quality Gates](#quality-gates)
6. [Testing Principles](#testing-principles)
7. [Anti-Patterns to Avoid](#anti-patterns-to-avoid)

---

## Testing Philosophy

### Core Principles

1. **Test Behavior, Not Implementation**
   - Focus on what the code does, not how it does it
   - Tests should survive refactoring
   - Mock external dependencies, not internal methods

2. **Fast Feedback Loop**
   - Unit tests run in milliseconds
   - Integration tests run in seconds
   - Full suite completes in minutes

3. **Fail-Fast Strategy**
   - Tests stop at first failure (`pytest -x`)
   - Run failed tests first (`pytest --ff`)
   - Smoke tests run before deployment

4. **Test Isolation**
   - Each test is independent
   - No shared state between tests
   - Tests can run in any order

5. **Realistic Testing**
   - Integration tests use realistic data
   - Validation tests query real BigQuery
   - Smoke tests verify critical paths

### Testing Goals

| Goal | Target | Current Status |
|------|--------|----------------|
| Unit Test Coverage | 85% | In Progress |
| Integration Coverage | 70% | In Progress |
| Critical Path Coverage | 100% | Achieved |
| Test Suite Runtime | < 5 minutes | Achieved |
| Deployment Gate Pass Rate | > 95% | Achieved |

---

## Test Pyramid

We follow the test pyramid strategy: many unit tests, fewer integration tests, minimal E2E tests.

```
           /\
          /  \     E2E Tests (Slow, Expensive)
         /    \    - Complete workflows
        /------\   - Real services (sometimes)
       /        \  - Run before deployment
      /  Integ-  \
     /   ration   \ Integration Tests (Medium)
    /    Tests     \- Multiple components
   /--------------\ - Mocked external services
  /                \- Realistic scenarios
 /   Unit Tests     \
/____________________\ Unit Tests (Fast, Cheap)
                       - Individual functions
                       - Fully mocked
                       - High coverage
```

### Level Breakdown

#### Layer 1: Unit Tests (70% of tests)

**Purpose:** Test individual functions and methods in isolation

**Characteristics:**
- Fast: < 1 second per test, < 30 seconds total
- Isolated: All dependencies mocked
- Comprehensive: Test all code paths
- High volume: 70% of total tests

**What to Test:**
- Calculation logic
- Data transformations
- Validation rules
- Edge cases and boundary conditions
- Error handling

**Example:**
```python
def test_calculate_zone_defense_basic():
    """Unit test: zone defense calculation logic"""
    processor = TeamDefenseProcessor()
    sample_data = {'paint_attempts': 100, 'paint_makes': 57}

    result = processor._calculate_zone_defense(sample_data, games_count=15)

    assert result['paint_pct'] == pytest.approx(0.57, abs=0.01)
```

**Coverage Target:** 85%+

#### Layer 2: Integration Tests (25% of tests)

**Purpose:** Test multiple components working together

**Characteristics:**
- Medium speed: 1-30 seconds per test
- Realistic: Use realistic data and workflows
- Partial mocking: Mock external services only
- End-to-end: Test complete processing flows

**What to Test:**
- Complete processing workflows
- Component interactions
- Dependency management
- Error propagation
- Data flow through system

**Example:**
```python
def test_full_processing_flow():
    """Integration test: complete processor flow"""
    processor = TeamDefenseProcessor()
    processor.bq_client = create_mock_bq_client()

    # Setup realistic data
    processor.opts = {'analysis_date': date(2025, 1, 27)}

    # Execute full flow
    processor.extract_raw_data()
    processor.calculate_precompute()

    # Verify end-to-end behavior
    assert len(processor.transformed_data) == 30
    assert all('team_id' in record for record in processor.transformed_data)
```

**Coverage Target:** 70%+

#### Layer 3: E2E Tests (5% of tests)

**Purpose:** Test critical user journeys end-to-end

**Characteristics:**
- Slow: 30+ seconds per test
- Expensive: May use real services
- Critical paths only: Focus on must-work scenarios
- Pre-deployment: Run before release

**What to Test:**
- Complete workflows from trigger to output
- Orchestration flows (Phase 1 → Phase 2 → Phase 3...)
- Critical business logic
- Deployment readiness

**Example:**
```python
def test_orchestrator_phase_transition():
    """E2E test: Phase 2 to Phase 3 transition"""
    # Trigger Phase 2
    response = trigger_phase2_orchestrator()
    assert response.status_code == 200

    # Wait for completion
    wait_for_phase2_completion()

    # Verify Phase 3 triggered
    phase3_runs = get_phase3_runs()
    assert len(phase3_runs) > 0
```

**Coverage Target:** Critical paths only (not percentage-based)

---

## Coverage Goals

### By Module Type

| Module Type | Coverage Target | Rationale |
|-------------|----------------|-----------|
| **Processors** | 85% | Business logic, high value |
| **Scrapers** | 80% | External dependencies, flakiness |
| **Orchestrators** | 90% | Critical to pipeline flow |
| **Utilities** | 85% | Reusable, widely used |
| **Shared Modules** | 85% | Foundation for other code |
| **Models/Schemas** | 50% | Mostly data structures |
| **Scripts** | 50% | One-off tools, low criticality |

### Coverage Exceptions

**What NOT to Test:**
- Third-party library code
- Auto-generated code
- Deployment scripts (test via deployment)
- Debug/development-only code
- Simple property getters/setters

**Coverage Exclusions (pytest.ini):**
```ini
[coverage:report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    @abstract
```

### Critical Modules (100% Coverage Required)

These modules must have 100% test coverage due to high criticality:

1. **Orchestration Logic**
   - `orchestration/cloud_functions/phase*_to_phase*/main.py`
   - Phase transitions
   - Self-healing logic

2. **Data Quality Validators**
   - `shared/validation/phase_boundary_validator.py`
   - Completeness checkers
   - Data validators

3. **Prediction Coordinators**
   - `predictions/coordinator/coordinator.py`
   - Batch processing logic
   - Circuit breakers

4. **Rate Limiting**
   - `shared/utils/rate_limit_handler.py`
   - Rate limiter logic
   - Circuit breakers

---

## Test Organization

### Directory Structure

```
tests/
├── README.md                           # Test guide (this doc)
├── conftest.py                         # Global fixtures
├── fixtures/
│   ├── bq_mocks.py                     # BigQuery mocking utilities
│   └── scrapers/                       # Scraper test fixtures
│       └── espn/                       # ESPN sample responses
├── unit/                               # Unit tests
│   ├── conftest.py
│   ├── patterns/                       # Pattern tests
│   │   ├── test_early_exit_mixin.py
│   │   └── test_smart_skip_mixin.py
│   ├── shared/                         # Shared module tests
│   ├── data_processors/                # Processor tests
│   └── scrapers/                       # Scraper tests
├── integration/                        # Integration tests
│   ├── conftest.py
│   ├── test_orchestrator_transitions.py
│   └── test_processor_workflows.py
├── e2e/                                # End-to-end tests
│   └── test_critical_flows.py
├── property/                           # Property-based tests
│   ├── conftest.py
│   └── test_data_invariants.py
├── processors/                         # Processor-specific tests
│   ├── conftest.py
│   ├── precompute/
│   │   ├── team_defense_zone_analysis/
│   │   │   ├── conftest.py
│   │   │   ├── test_team_defense_unit.py
│   │   │   ├── test_team_defense_integration.py
│   │   │   └── test_team_defense_validation.py
│   │   └── README.md                   # Processor test documentation
│   └── analytics/
├── validation/                         # Validation tests (require BQ)
│   └── validators/
└── samples/                            # Test data samples
    ├── espn_scoreboard_api/
    └── nbac_schedule_cdn/
```

### File Naming

```
test_<module_name>.py          # Unit tests for module
test_<module_name>_unit.py     # Explicit unit tests
test_<module_name>_integration.py  # Integration tests
test_<module_name>_validation.py   # Validation tests (BigQuery)
test_<module_name>_e2e.py      # End-to-end tests
```

### Test Naming

```python
# Unit tests: test_<method>_<scenario>_<expected>
def test_calculate_zone_defense_with_zero_attempts_returns_null()

# Integration tests: test_<feature>_<scenario>
def test_full_processing_flow_successful()

# Validation tests: test_<assertion>_<condition>
def test_all_30_teams_processed()
```

---

## Quality Gates

### Pre-Commit Gates

Run locally before committing:

```bash
# 1. Smoke tests
pytest -m smoke -v

# 2. Unit tests
pytest tests/unit/ -v --timeout=60

# 3. Linting
ruff check .
```

**Pass Criteria:**
- All smoke tests pass
- Unit tests pass with > 80% coverage
- No critical linting errors

### Pull Request Gates

Run in CI/CD on every PR:

```bash
# 1. Unit tests with coverage
pytest tests/unit/ -v --cov=. --cov-report=xml

# 2. Integration tests
pytest tests/integration/ -v --timeout=120

# 3. Linting
ruff check --select=E9,F63,F7,F82 .
```

**Pass Criteria:**
- All unit tests pass
- Coverage maintained or improved
- Integration tests pass
- No critical lint errors

**GitHub Action:** `.github/workflows/test.yml`

### Pre-Deployment Gates

Run before deploying to production:

```bash
# 1. Pre-deployment validation
python bin/validation/pre_deployment_check.py

# 2. Orchestrator tests (24 tests)
pytest tests/integration/test_orchestrator_transitions.py -v

# 3. Smoke tests
pytest -m smoke -v

# 4. Integration tests
pytest tests/integration/ -v
```

**Pass Criteria:**
- Pre-deployment validation passes
- All 24 orchestrator tests pass
- All smoke tests pass
- Integration tests pass

**GitHub Action:** `.github/workflows/deployment-validation.yml`

### Post-Deployment Validation

Run after deployment to verify production:

```bash
# 1. Production smoke tests
pytest -m smoke --production

# 2. Validation tests (real BigQuery)
pytest tests/processors/*/test_*_validation.py --bigquery

# 3. E2E tests
pytest tests/e2e/ --production
```

**Pass Criteria:**
- Smoke tests against production pass
- Data validation tests pass
- E2E tests verify critical flows work

---

## Testing Principles

### 1. Test Behavior, Not Implementation

**Good:**
```python
def test_processor_generates_output_for_all_teams():
    """Test that processor generates records for all 30 teams"""
    processor = TeamDefenseProcessor()
    result = processor.run()

    team_ids = {record['team_id'] for record in result}
    assert len(team_ids) == 30
```

**Bad:**
```python
def test_processor_calls_internal_methods():
    """Test implementation details (brittle)"""
    processor = TeamDefenseProcessor()
    processor._calculate_zone_defense = Mock()
    processor._identify_strengths_weaknesses = Mock()

    processor.run()

    # Breaks when refactoring, doesn't test behavior
    processor._calculate_zone_defense.assert_called()
    processor._identify_strengths_weaknesses.assert_called()
```

### 2. Keep Tests Simple

**Good:**
```python
def test_early_season_generates_placeholders():
    """Simple, clear test"""
    processor = TeamDefenseProcessor()
    processor.opts = {'analysis_date': date(2024, 10, 15)}  # Early season

    result = processor.run()

    assert all(record['is_early_season_estimate'] is True for record in result)
```

**Bad:**
```python
def test_complex_scenario_with_many_assertions():
    """Too complex, tests multiple things"""
    # 50 lines of setup...
    # Multiple unrelated assertions...
    # Hard to understand what's being tested
```

### 3. One Assertion Per Test (Generally)

**Good:**
```python
def test_paint_percentage_in_valid_range():
    """Test one specific thing"""
    result = calculate_paint_pct(makes=50, attempts=100)
    assert 0.0 <= result <= 1.0

def test_paint_percentage_calculation_accuracy():
    """Different test for different concern"""
    result = calculate_paint_pct(makes=50, attempts=100)
    assert result == pytest.approx(0.50, abs=0.01)
```

**Acceptable (related assertions):**
```python
def test_zone_defense_calculation():
    """Multiple related assertions OK if testing same calculation"""
    result = calculate_zone_defense(sample_data)

    assert result['paint_pct'] == pytest.approx(0.57)
    assert result['mid_range_pct'] == pytest.approx(0.42)
    assert result['three_pt_pct'] == pytest.approx(0.36)
```

### 4. Use Descriptive Names

**Good:**
```python
def test_insufficient_games_raises_value_error()
def test_early_season_generates_placeholder_records()
def test_vs_league_average_calculated_correctly()
```

**Bad:**
```python
def test_1()
def test_edge_case()
def test_it_works()
```

### 5. Arrange-Act-Assert Pattern

```python
def test_example():
    """Clear AAA structure"""
    # Arrange: Setup test data and mocks
    processor = TeamDefenseProcessor()
    sample_data = create_sample_data()

    # Act: Execute the code being tested
    result = processor.process(sample_data)

    # Assert: Verify the results
    assert result is not None
    assert len(result) == expected_count
```

### 6. Mock External Dependencies Only

**Good:**
```python
def test_processor_with_mocked_bigquery():
    """Mock external BigQuery service"""
    processor = TeamDefenseProcessor()
    processor.bq_client = create_mock_bq_client()

    result = processor.run()

    assert result is not None
```

**Bad:**
```python
def test_processor_with_everything_mocked():
    """Don't mock internal methods"""
    processor = TeamDefenseProcessor()
    processor._calculate_zone_defense = Mock(return_value={})
    processor._identify_strengths = Mock(return_value={})
    # Now you're not testing actual processor logic!
```

### 7. Test Edge Cases

Always test:
- Empty inputs
- Null/None values
- Zero values
- Maximum values
- Boundary conditions
- Error conditions

```python
def test_zero_attempts_handled():
    """Test division by zero edge case"""
    result = calculate_percentage(makes=0, attempts=0)
    assert result is None or result == 0.0

def test_null_input_handled():
    """Test None input"""
    result = process_data(None)
    assert result == []

def test_empty_list_handled():
    """Test empty input"""
    result = process_data([])
    assert result == []
```

---

## Anti-Patterns to Avoid

### 1. Don't Test Third-Party Libraries

**Bad:**
```python
def test_pandas_dataframe_works():
    """Don't test pandas - it's already tested"""
    df = pd.DataFrame({'a': [1, 2, 3]})
    assert len(df) == 3
```

**Good:**
```python
def test_our_data_transformation():
    """Test our code that uses pandas"""
    raw_data = {'team_id': [1, 2, 3]}
    result = transform_to_dataframe(raw_data)
    assert 'team_name' in result.columns
```

### 2. Don't Test Configuration

**Bad:**
```python
def test_config_values():
    """Don't test static configuration"""
    assert TEAM_COUNT == 30
    assert SEASON_START_MONTH == 10
```

**Good:**
```python
def test_handles_configured_team_count():
    """Test behavior with configuration"""
    processor = TeamDefenseProcessor(team_count=TEAM_COUNT)
    result = processor.run()
    assert len(result) == TEAM_COUNT
```

### 3. Don't Use Sleep in Tests

**Bad:**
```python
def test_async_operation():
    """Don't use sleep - brittle and slow"""
    trigger_async_operation()
    time.sleep(5)  # Hope it's done by now...
    assert operation_completed()
```

**Good:**
```python
def test_async_operation():
    """Use proper async testing or mocks"""
    with patch('module.async_call') as mock_async:
        mock_async.return_value = Mock(result=lambda: {'status': 'done'})
        result = trigger_async_operation()
        assert result['status'] == 'done'
```

### 4. Don't Share State Between Tests

**Bad:**
```python
# Module-level shared state
shared_processor = TeamDefenseProcessor()

def test_first():
    shared_processor.config = {'value': 1}
    assert shared_processor.run()

def test_second():
    # Fails if test_first ran first and modified state!
    assert shared_processor.config is None
```

**Good:**
```python
@pytest.fixture
def processor():
    """Create fresh processor for each test"""
    return TeamDefenseProcessor()

def test_first(processor):
    processor.config = {'value': 1}
    assert processor.run()

def test_second(processor):
    # Gets fresh processor, no shared state
    assert processor.config is None
```

### 5. Don't Make Tests Depend on Execution Order

**Bad:**
```python
def test_1_create_record():
    global created_id
    created_id = create_record()

def test_2_update_record():
    update_record(created_id)  # Depends on test_1!

def test_3_delete_record():
    delete_record(created_id)  # Depends on test_1 and test_2!
```

**Good:**
```python
def test_create_record():
    """Independent test"""
    record_id = create_record()
    assert record_id is not None

def test_update_record():
    """Independent test with its own setup"""
    record_id = create_record()  # Own setup
    result = update_record(record_id)
    assert result is True

def test_delete_record():
    """Independent test with its own setup"""
    record_id = create_record()  # Own setup
    result = delete_record(record_id)
    assert result is True
```

### 6. Don't Ignore Failing Tests

**Bad:**
```python
@pytest.mark.skip(reason="TODO: fix later")
def test_important_feature():
    """Never skip tests indefinitely"""
    pass
```

**Good:**
```python
@pytest.mark.xfail(reason="Known issue #123, fix in progress")
def test_important_feature():
    """Mark as expected failure with tracking issue"""
    pass

# Or better: Fix it immediately!
def test_important_feature():
    """Test that works"""
    assert important_feature() is True
```

---

## Summary

### Quick Reference

| Test Type | % of Tests | Speed | Coverage Target | Example |
|-----------|-----------|-------|-----------------|---------|
| Unit | 70% | < 1s | 85% | `test_calculate_zone_defense()` |
| Integration | 25% | 1-30s | 70% | `test_full_processing_flow()` |
| E2E | 5% | 30s+ | Critical paths | `test_orchestrator_transition()` |

### Testing Checklist

- [ ] Tests are fast and focused
- [ ] Tests are isolated (no shared state)
- [ ] External dependencies are mocked
- [ ] Edge cases are covered
- [ ] Tests have descriptive names
- [ ] One logical assertion per test
- [ ] Arrange-Act-Assert structure
- [ ] Coverage meets targets
- [ ] All quality gates pass

### Next Steps

1. **Read:** `tests/README.md` - Quick start guide
2. **Review:** `tests/processors/precompute/README.md` - Excellent example
3. **Explore:** `tests/fixtures/bq_mocks.py` - Mocking utilities
4. **Practice:** Write tests for new features
5. **Iterate:** Improve test coverage over time

---

**Related Documentation:**
- [Test README](../../tests/README.md) - Quick start guide
- [CI/CD Testing](./CI_CD_TESTING.md) - GitHub Actions setup
- [Test Utilities](./TEST_UTILITIES.md) - Mocking and fixtures
- [Testing Guide](../TESTING-GUIDE.md) - General testing guide

**Last Updated:** January 2025
**Status:** Active
