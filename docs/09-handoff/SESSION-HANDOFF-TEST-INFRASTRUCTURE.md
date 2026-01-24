# Session Handoff: Test Infrastructure & Fixes

**Priority:** P1
**Estimated Effort:** 4-6 hours
**Goal:** Fix 37 remaining test failures, improve test infrastructure

---

## Quick Start

```bash
# See current test status
python -m pytest tests/processors/ tests/ml/ -q --tb=no

# Run specific failing areas
python -m pytest tests/processors/analytics/team_defense_game_summary/ -v
python -m pytest tests/processors/grading/ -v
```

---

## Problem Summary

- **37 test failures** remain (down from 66)
- **382 tests skipped** (many intentionally, some need fixing)
- Root causes are mock fixture issues, not fundamental test problems

### Failure Categories

| Category | Count | Root Cause |
|----------|-------|------------|
| Mock returns Mock not proper type | 5+ | `bq_client.project` returns Mock instead of string |
| Mock DataFrame issues | 3+ | `raw_data` returns Mock instead of DataFrame |
| Early exit mixin bypassing | 5+ | Missing `_is_too_historical = Mock(return_value=False)` |
| Missing processor attributes | 5+ | Missing `run_id`, `processor_name` |
| Test isolation bleeding | 4+ | `sys.modules` mocking from other tests bleeds over |

---

## Files to Study

### Test Infrastructure
- `tests/conftest.py` - Root test configuration
- `tests/processors/analytics/team_defense_game_summary/conftest.py` - Example fixture pattern
- `tests/processors/analytics/player_game_summary/conftest.py` - Another fixture pattern

### Failing Test Files (Priority Order)
1. `tests/processors/analytics/team_defense_game_summary/test_unit.py`
2. `tests/processors/analytics/team_defense_game_summary/test_integration.py`
3. `tests/processors/analytics/team_offense_game_summary/test_unit.py`
4. `tests/processors/grading/performance_summary/test_unit.py`
5. `tests/processors/grading/system_daily_performance/test_unit.py`

### Documentation
- `docs/09-handoff/2026-01-24-SESSION7-FINAL-REPORT.md` - Session 7 test fix details
- `docs/09-handoff/2026-01-24-SESSION15-IMPROVEMENTS.md` - Section 5 (Testing)

---

## Specific Fixes Needed

### 1. Fix Mock Project ID Issue
```python
# Problem: bq_client.project returns MagicMock
# Solution in conftest.py:
processor.bq_client = Mock()
processor.bq_client.project = 'test-project'  # String, not Mock
```

### 2. Fix Mock Query Results
```python
# Problem: query().result() returns Mock, not iterable
# Solution:
mock_query_result = Mock()
mock_query_result.result.return_value = []  # Empty iterable
mock_query_result.to_dataframe.return_value = pd.DataFrame()
processor.bq_client.query.return_value = mock_query_result
```

### 3. Bypass Early Exit Mixin
```python
# Add to processor fixtures:
processor._is_too_historical = Mock(return_value=False)
processor._is_offseason = Mock(return_value=False)
processor._has_games_scheduled = Mock(return_value=True)
```

### 4. Add Missing Attributes
```python
processor.run_id = 'test-run-123'
processor.processor_name = 'TestProcessor'
processor.opts = {'start_date': '2025-01-15', 'end_date': '2025-01-15'}
```

### 5. Fix Test Isolation
Create `tests/processors/conftest.py`:
```python
import pytest

@pytest.fixture(autouse=True)
def reset_sys_modules():
    """Reset Google Cloud mocks between tests."""
    import sys
    original_modules = dict(sys.modules)
    yield
    for key in list(sys.modules.keys()):
        if key not in original_modules:
            del sys.modules[key]
```

---

## Deliverables

1. [ ] All 37 failing tests passing
2. [ ] Create `tests/fixtures/bq_mocks.py` - Shared BigQuery mock helpers
3. [ ] Create `tests/processors/conftest.py` - Shared processor test config
4. [ ] Document test patterns in `docs/testing-patterns.md`
5. [ ] Reduce skipped tests where reasonable

---

## Verification

```bash
# Full test run (should be 0 failures)
python -m pytest tests/processors/ tests/ml/ -q --tb=line

# Check for any remaining skips that should be fixed
python -m pytest tests/processors/ --collect-only | grep "skipped"
```

---

**Created:** 2026-01-24
**Session Type:** Test Infrastructure
