# ADR 003: Integration Testing for Critical Paths

**Status**: Accepted
**Date**: 2026-02-02
**Decision Makers**: Infrastructure Team, Session 79
**Tags**: testing, quality, prevention

---

## Context

Multiple production issues went undetected:
- **Session 76**: Vegas line coverage dropped from 92% to 44%
- **Session 66**: Data leakage caused fake 84% hit rate
- **Session 64**: Stale code deployed with 50.4% hit rate

**Problem**: No automated tests to catch regressions before/after deployment.

---

## Decision

Implement **integration tests** that:
1. Run against actual BigQuery tables (not mocks)
2. Check critical business metrics (coverage, hit rate, MAE)
3. Fail builds when thresholds violated
4. Provide actionable error messages
5. Can run as smoke tests in CI/CD

---

## Rationale

### Why Integration vs. Unit Tests?

**Chosen**: Integration tests for critical paths

**Alternatives**:
- Unit tests only → Miss system-level issues
- E2E tests only → Too slow, brittle
- Manual testing → Doesn't scale, error-prone

**Why Integration Won**:
- Catches real issues (Vegas coverage, prediction quality)
- Uses production data structure
- Fast enough for CI/CD (<5 minutes)
- Complements existing unit tests

### What to Test?

**Included**:
1. **Vegas Line Coverage** (7 tests)
   - Coverage ≥90% threshold
   - End-to-end pipeline validation
   - Data freshness checks

2. **Prediction Quality** (9 tests)
   - Premium picks ≥55% hit rate
   - High-edge picks ≥72% hit rate
   - MAE <5.0 points
   - Data leakage detection
   - Grading completeness

**Excluded**:
- Low-level logic → Covered by unit tests
- UI/Frontend → Different test suite
- Performance → Separate benchmark tests

### Why BigQuery vs. Mocks?

**Chosen**: Real BigQuery tables

**Alternatives**:
- Mock data → Fast but doesn't catch schema issues
- Local SQLite → Different SQL dialect
- Test database → Maintenance overhead

**Why BigQuery Won**:
- Catches schema mismatches
- Tests actual queries
- Uses production data structure
- Reflects real-world conditions

---

## Implementation

**Test Files**:
- `tests/integration/monitoring/test_vegas_line_coverage.py` (7 tests)
- `tests/integration/predictions/test_prediction_quality_regression.py` (9 tests)

**Markers**:
```python
@pytest.mark.integration  # All integration tests
@pytest.mark.smoke        # Critical path tests
```

**Example Test**:
```python
@pytest.mark.integration
@pytest.mark.smoke
def test_vegas_line_coverage_above_threshold(bq_client):
    """
    CRITICAL: Vegas line coverage must be ≥90%.
    Prevents Session 76 type regressions.
    """
    # Query last 3 days
    # Assert coverage ≥90%
    # Provide actionable error message
```

**Thresholds**:
- Vegas coverage: ≥90%
- Premium picks: ≥55% hit rate
- High-edge picks: ≥72% hit rate
- Overall MAE: <5.0 points
- Grading completeness: ≥80%

---

## Consequences

### Positive
- ✅ 16 integration tests covering critical paths
- ✅ Catches Session 76 (Vegas) and Session 66 (leakage) issues
- ✅ Actionable error messages with diagnostics
- ✅ Can run in CI/CD pipeline
- ✅ Fast enough (<5 min) for pre-deploy checks

### Negative
- ⚠️ Requires BigQuery access (GCP auth)
- ⚠️ Tests skip if no recent data
- ⚠️ Depends on data quality

### Risks Mitigated
- **Vegas coverage drops**: Detected immediately
- **Prediction quality degradation**: Caught before production
- **Data leakage**: Flagged if hit rate >80%
- **Schema mismatches**: Detected at query time

---

## Execution

**Run Smoke Tests**:
```bash
pytest tests/integration/ -v -m smoke
```

**Run All Integration Tests**:
```bash
pytest tests/integration/ -v -m integration
```

**CI/CD Integration**:
```yaml
# In GitHub Actions
- name: Run smoke tests
  run: pytest tests/integration/ -v -m smoke
```

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Integration tests | 0 | 16 |
| Critical paths covered | 0% | 100% |
| Vegas coverage tests | 0 | 7 |
| Prediction quality tests | 0 | 9 |
| Detection time | Never | Pre-deployment |

---

## References

- `tests/integration/monitoring/test_vegas_line_coverage.py`
- `tests/integration/predictions/test_prediction_quality_regression.py`
- Session 76 (Vegas coverage regression)
- Session 66 (Data leakage)
- Session 64 (Stale code deployment)

---

## Future Considerations

- Add tests for Phase 2/3 data quality
- Performance benchmarks
- Chaos testing (simulate failures)
- Contract testing for API boundaries
