# Session 12 - Code Quality & Technical Debt Improvements

**Date:** 2026-01-24
**Session:** 12
**Status:** COMPLETE
**Focus:** Code Consolidation, Test Fixes, Error Handling

---

## Executive Summary

Session 12 focuses on reducing technical debt identified through codebase exploration:
- **CRITICAL**: 1,087+ lines of duplicated code across predictions services
- **HIGH**: Empty test stubs, broad exception handling
- **MEDIUM**: Print statements, deprecated code, config inconsistencies

---

## Completed Work

| Task | Status | Impact |
|------|--------|--------|
| Delete duplicate shared modules | ✅ | -77,972 lines of dead code |
| Remove empty test stubs | ✅ | Cleaner test suite |
| Fix bigquery_utils_v2 test | ✅ | Pre-existing test failure fixed |
| Sync pytest config | ✅ | pyproject.toml now matches pytest.ini |
| Push to origin | ✅ | All synced |

### Commits Made
```
71dfde69 refactor: Remove 72,889 lines of dead duplicate code
```

---

## Priority 1: CRITICAL - Code Duplication Fix (COMPLETED)

### Issue: BigQuery Retry Module Duplicated (3 copies)

| Location | Lines | Status |
|----------|-------|--------|
| `shared/utils/bigquery_retry.py` | 447 | ✅ Source of truth (has TRANSIENT_RETRY) |
| `predictions/coordinator/shared/utils/bigquery_retry.py` | 320 | ❌ OUTDATED - missing TRANSIENT_RETRY |
| `predictions/worker/shared/utils/bigquery_retry.py` | 320 | ❌ OUTDATED - missing TRANSIENT_RETRY |

**Root Cause:** Docker builds copy local `shared/` directories instead of importing from the main shared module.

**Fix Options:**
1. **Option A**: Delete duplicates, update Dockerfiles to copy from root `shared/`
2. **Option B**: Create symlinks
3. **Option C**: Publish shared as internal package

**Recommended:** Option A - simplest, most maintainable

### Other Duplicated Modules

| Module | Copies | Total Lines |
|--------|--------|-------------|
| player_registry/ | 3 | 1,527 |
| logging_utils.py | 3 | 321 |
| schedule/ | 3 | ~600 |

---

## Priority 2: HIGH - Test Fixes

### 2.1 Empty Test Stubs (0 bytes)
- [ ] `tests/processors/test_br_roster_processor.py`
- [ ] `tests/processors/test_processor_base.py`

**Action:** Either implement tests or remove stubs

### 2.2 Skipped Integration Tests
- [ ] `tests/processors/analytics/upcoming_player_game_context/test_integration.py`
  - `test_bigquery_query_error` - Exception handling path changed
  - `test_source_tracking_fields_populated` - Output format changed

---

## Priority 3: HIGH - Exception Handling

### Broad Exception Handling (50+ instances)
Files with `except Exception:` that mask root causes:
- `bin/infrastructure/monitoring/backfill_progress_monitor.py:241`
- `data_processors/raw/balldontlie/bdl_live_boxscores_processor.py:368`
- `orchestration/workflow_executor.py:198`
- `ml/train_ensemble_v2_meta_learner.py:169, 181, 193`

**Action:** Replace with specific exception types where appropriate

---

## Priority 4: MEDIUM - Print Statement Cleanup

### 234 Print Statements in Production Code
Key files to fix:
- `data_processors/grading/mlb/mlb_shadow_grading_processor.py`
- `data_processors/grading/system_performance/system_performance_tracker.py`
- `data_processors/grading/performance_summary/performance_summary_processor.py`
- `data_processors/analytics/utils/travel_utils.py`

**Action:** Convert to `logging.info()` or `logging.debug()`

---

## Priority 5: MEDIUM - Deprecated Code Removal

### Coordinator Global State (marked DEPRECATED)
Location: `predictions/coordinator/coordinator.py:220-227`
```python
# Global state (DEPRECATED - use BatchStateManager for persistent state)
current_tracker: Optional[ProgressTracker] = None
current_batch_id: Optional[str] = None
current_correlation_id: Optional[str] = None
current_game_date: Optional[date] = None
```

**Action:** Verify BatchStateManager usage, remove deprecated globals

### Other Deprecated Items
- `data_processors/precompute/ml_feature_store/batch_writer.py:443` - old DELETE+INSERT pattern
- `data_processors/analytics/analytics_base.py:2274` - _delete_existing_data_batch
- `shared/config/orchestration_config.py:261,266` - use_default_line fields
- `scrapers/main_scraper_service.py:690` - old API endpoint

---

## Priority 6: LOW - Test Configuration

### pytest.ini vs pyproject.toml Conflict
- pytest.ini: `testpaths = tests shared/utils/schedule/tests`
- pyproject.toml: `testpaths = ["tests"]`

**Action:** Consolidate into pyproject.toml only

---

## Session 11 Deferred Items (for context)

From `SESSION-11-TODO.md`:
1. [ ] Add `exc_info=True` to error logs (40+ files)
2. [ ] Replace direct `requests` calls with http_pool (22 files)

---

## Implementation Order

1. **Quick Wins (30 min)**
   - [ ] Fix or remove empty test stubs
   - [ ] Push uncommitted changes to origin
   - [ ] Reconcile pytest configuration

2. **Code Consolidation (2-3 hours)**
   - [ ] Audit all duplicate shared modules
   - [ ] Update Dockerfiles to use root shared/
   - [ ] Delete duplicate modules
   - [ ] Test Docker builds locally

3. **Error Handling (1-2 hours)**
   - [ ] Fix critical exception handlers
   - [ ] Add specific exception types

4. **Print Statement Cleanup (1-2 hours)**
   - [ ] Convert high-priority print statements to logging

5. **Documentation**
   - [ ] Update handoff doc
   - [ ] Record what was completed

---

## Success Criteria

- [ ] No duplicate shared modules (or documented reason for keeping)
- [ ] Zero empty test files
- [ ] pytest configuration consolidated
- [ ] Branch pushed and synced with origin
- [ ] Key exception handlers improved

---

## Files to Track

```
# Duplicate modules to consolidate
predictions/coordinator/shared/utils/bigquery_retry.py     # DELETE
predictions/worker/shared/utils/bigquery_retry.py          # DELETE
predictions/coordinator/shared/utils/player_registry/      # DELETE
predictions/worker/shared/utils/player_registry/           # DELETE

# Empty test stubs
tests/processors/test_br_roster_processor.py               # FIX/DELETE
tests/processors/test_processor_base.py                    # FIX/DELETE

# Skipped tests
tests/processors/analytics/upcoming_player_game_context/test_integration.py

# Config to consolidate
pytest.ini                                                 # KEEP
pyproject.toml                                             # UPDATE
```

---

**Created:** 2026-01-24
**Last Updated:** 2026-01-24
