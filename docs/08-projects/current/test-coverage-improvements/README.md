# Test Coverage Improvements - January 2026

**Created:** 2026-01-24
**Status:** Planning
**Priority:** P2
**Estimated Hours:** 24-32h

---

## Executive Summary

Test infrastructure analysis revealed:
- **3,556 test functions** across 173 files (strong foundation)
- **79 skipped tests** indicating maintenance debt
- **Heavy unit test focus** (75%) with weak E2E coverage (2 files)
- **Service layer undertested** (admin dashboard, grading alerts)

---

## Current State

### Test Statistics

| Metric | Count |
|--------|-------|
| Total test files | 173 |
| Total test functions | 3,556 |
| Skipped tests | 79 |
| conftest.py files | 21 |

### Test Distribution by Type

| Type | Files | Status |
|------|-------|--------|
| Unit tests | 60 | Strong |
| Processor tests | 42 | Strong |
| Integration tests | 8 | Moderate |
| Prediction tests | 13 | Moderate |
| E2E tests | 2 | **Weak** |
| Publishing tests | 1 | **Weak** |
| Service tests | 1 | **Weak** |

### Current Test/Code Ratio: ~75% Unit : 15% Integration : 10% E2E

---

## P0: Fix Critical Skipped Tests

### upcoming_player_game_context (7 Skipped Tests)

| Test | Line | Skip Reason | Fix Needed |
|------|------|-------------|------------|
| `test_successful_full_run` | 144 | Mock DataFrame missing columns | Update mock schema |
| `test_find_player_using_player_lookup` | 214 | .result() iterator pattern | Fix mock pattern |
| `test_find_player_already_cached` | 229 | .result() iterator pattern | Fix mock pattern |
| `test_handle_missing_opening_lines` | 279 | .result() iterator pattern | Fix mock pattern |
| `test_get_team_record` | 399 | API signature changed | Add 8 new arguments |
| `test_handle_invalid_response` | 457 | Exception handling changed | Update test |
| `test_check_source_tracking` | 527 | Expected fields missing | Update assertions |

**File:** `tests/processors/analytics/upcoming_player_game_context/test_integration.py`

### Contract Test (1 Skipped)

| Test | File | Skip Reason | Fix Needed |
|------|------|-------------|------------|
| `test_boxscore_end_to_end` | `tests/contract/test_boxscore_end_to_end.py` | Empty fixtures | Populate fixture files |

### Action Items
- [ ] Fix mock DataFrame schema in upcoming_player_game_context tests
- [ ] Update BigQuery mock to handle .result() iterator pattern
- [ ] Update test_get_team_record with new API signature
- [ ] Populate contract test fixture files
- [ ] Review remaining 70 skipped tests for quick wins

**Estimated Time:** 6-8 hours

---

## P1: E2E Test Expansion

### Current E2E Tests (Only 2 files)
1. `tests/e2e/test_validation_gates.py`
2. `tests/e2e/test_rate_limiting_flow.py`

### Missing E2E Coverage

| Scenario | Priority | Estimated Hours |
|----------|----------|-----------------|
| Scraper → Processor → Prediction flow | P1 | 4h |
| Phase 2 → 3 → 4 → 5 transitions | P1 | 4h |
| Data quality through full pipeline | P2 | 3h |
| Error propagation paths | P2 | 3h |
| Circuit breaker → Recovery | P2 | 2h |

### E2E Test Plan

```python
# tests/e2e/test_full_pipeline.py (NEW)
class TestFullPipeline:
    """End-to-end pipeline tests with mocked external services"""

    def test_scraper_to_processor_flow(self):
        """Scraper data flows correctly to raw processor"""
        # 1. Mock external NBA API
        # 2. Run scraper
        # 3. Verify data in staging
        # 4. Run processor
        # 5. Verify data in final table

    def test_phase_transitions(self):
        """All phases trigger correctly"""
        # 1. Setup Phase 2 completion
        # 2. Verify Phase 3 triggers
        # 3. Setup Phase 3 completion
        # 4. Verify Phase 4 triggers
        # ... continue through Phase 5

    def test_error_recovery_flow(self):
        """System recovers from failures"""
        # 1. Inject failure in Phase 3
        # 2. Verify circuit breaker opens
        # 3. Fix underlying issue
        # 4. Verify circuit breaker closes
        # 5. Verify processing resumes
```

**Estimated Time:** 8-12 hours

---

## P2: Service Layer Tests

### Admin Dashboard (1 test file for 2,718 LOC)

**Current Coverage:** Minimal
**Target Coverage:** 60%+

```python
# tests/services/unit/test_admin_dashboard.py (NEW)
class TestAdminDashboard:
    def test_predictions_endpoint(self):
        """GET /predictions returns correct data"""

    def test_grading_endpoint(self):
        """GET /grading returns accuracy metrics"""

    def test_processor_status_endpoint(self):
        """GET /processors shows all processor status"""

    def test_authentication_required(self):
        """Endpoints require valid API key"""
```

### Grading Alerts Service

**Current Coverage:** 0 tests
**Target Coverage:** 50%+

```python
# tests/services/unit/test_grading_alerts.py (NEW)
class TestGradingAlerts:
    def test_alert_generation(self):
        """Alerts generated for accuracy drops"""

    def test_alert_thresholds(self):
        """Thresholds trigger correctly"""

    def test_alert_delivery(self):
        """Alerts delivered via configured channels"""
```

**Estimated Time:** 8 hours

---

## P3: Integration Test Expansion

### Current Integration Tests
- 8 files exist but coverage is spotty

### Gaps to Address

| Area | Current | Needed |
|------|---------|--------|
| Database integration | Mocked only | Real test DB |
| API integration | Basic | Comprehensive |
| Service mesh | None | Add |
| Pub/Sub integration | Basic | Full coverage |

### New Integration Tests Needed

```python
# tests/integration/test_bigquery_operations.py (NEW)
class TestBigQueryIntegration:
    """Tests against real BigQuery test dataset"""

    def test_processor_writes(self):
        """Processor can write to BigQuery"""

    def test_query_timeouts(self):
        """Timeouts work as expected"""

    def test_retry_on_transient_errors(self):
        """Transient errors trigger retries"""
```

**Estimated Time:** 6 hours

---

## Implementation Schedule

### Week 1
- [ ] Fix 7 skipped tests in upcoming_player_game_context (4h)
- [ ] Populate contract test fixtures (2h)

### Week 2
- [ ] Add E2E pipeline test (4h)
- [ ] Add E2E phase transition test (4h)

### Week 3
- [ ] Add admin dashboard tests (4h)
- [ ] Add grading alerts tests (4h)

### Week 4
- [ ] Add BigQuery integration tests (4h)
- [ ] Review and fix remaining skipped tests (4h)

---

## Test Infrastructure Improvements

### Fixture Management
- [ ] Version fixture files
- [ ] Add fixture refresh automation
- [ ] Create synthetic data generators

### CI/CD Integration
- [ ] Run tests on every PR
- [ ] Track coverage over time
- [ ] Block merges below coverage threshold

### Property-Based Testing
- Already using Hypothesis with 4 profiles
- [ ] Expand property tests to more processors

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Skipped tests | 79 | <20 |
| E2E test files | 2 | 8+ |
| Service test files | 1 | 5+ |
| Integration test files | 8 | 15+ |
| Test balance | 75/15/10 | 60/25/15 |

---

## Related Documentation

- Main Improvement Plan: `../SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md`
- Unit Testing Plan: `../UNIT-TESTING-IMPLEMENTATION-PLAN.md`
- Code Quality: `../code-quality-2026-01/README.md`

---

**Created:** 2026-01-24
**Last Updated:** 2026-01-24
