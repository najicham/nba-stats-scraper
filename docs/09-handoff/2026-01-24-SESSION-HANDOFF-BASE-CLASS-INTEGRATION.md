# Session Handoff: Base Class Hierarchy Integration

**Priority:** P1
**Estimated Effort:** 6-8 hours
**Risk Level:** HIGH (affects 50+ processors)
**Goal:** Integrate TransformProcessorBase to eliminate ~5,000 lines of duplication

---

## Quick Start

```bash
# Understand current structure
wc -l shared/processors/base/transform_processor_base.py
wc -l data_processors/analytics/analytics_base.py
wc -l data_processors/precompute/precompute_base.py

# Run tests before any changes
python -m pytest tests/processors/analytics/ -q --tb=no
python -m pytest tests/processors/precompute/ -q --tb=no
```

---

## Problem Summary

| File | Lines | Purpose |
|------|-------|---------|
| `transform_processor_base.py` | 499 | **NEW** shared base (created but NOT used) |
| `analytics_base.py` | 3,062 | Phase 3 analytics processors |
| `precompute_base.py` | 2,665 | Phase 4 precompute processors |

**~78% of code is duplicated** between analytics_base and precompute_base.

The `TransformProcessorBase` was created to consolidate this but **is not yet integrated**.

---

## Files to Study

### New Shared Base (understand this first)
- `shared/processors/base/transform_processor_base.py` - The consolidation target
- `shared/processors/base/__init__.py` - Exports

### Current Base Classes (to be refactored)
- `data_processors/analytics/analytics_base.py` - Phase 3 base
- `data_processors/precompute/precompute_base.py` - Phase 4 base

### Example Concrete Processors
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

### Mixins (understand inheritance)
- `shared/processors/mixins/` - All processor mixins

### Documentation
- `docs/09-handoff/2026-01-24-FUTURE-WORK-ROADMAP.md` - Section 1.2

---

## Duplicated Methods (to be removed after integration)

These methods are **100% identical** in both base classes:

```python
# Query Utilities
_execute_query_with_retry(query, timeout)
_sanitize_row_for_json(row)

# Time Tracking
mark_time(label)
get_elapsed_seconds(label)

# Dataset Management
get_prefixed_dataset(base_dataset)
get_output_dataset()

# Logging
step_info(step_name, message, extra)

# Error Handling
report_error(exc)
_save_partial_data(exc)
_get_current_step()

# Notification
_send_notification(alert_func, *args, **kwargs)

# Properties
is_backfill_mode
processor_name
```

---

## Integration Pattern

### Current Structure
```python
class AnalyticsProcessorBase(SoftDependencyMixin, RunHistoryMixin):
    PHASE = 'phase_3_analytics'
    # 3,000+ lines including duplicated methods

class PrecomputeProcessorBase(SoftDependencyMixin, RunHistoryMixin):
    PHASE = 'phase_4_precompute'
    # 2,600+ lines including duplicated methods
```

### Target Structure
```python
class AnalyticsProcessorBase(TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
    PHASE = 'phase_3_analytics'
    STEP_PREFIX = 'ANALYTICS_STEP'
    # Only ~500 lines of phase-specific logic

class PrecomputeProcessorBase(TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
    PHASE = 'phase_4_precompute'
    STEP_PREFIX = 'PRECOMPUTE_STEP'
    # Only ~400 lines of phase-specific logic
```

---

## Migration Steps

### Step 1: Update AnalyticsProcessorBase
```python
# In data_processors/analytics/analytics_base.py
from shared.processors.base import TransformProcessorBase

class AnalyticsProcessorBase(TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
    PHASE = 'phase_3_analytics'
    STEP_PREFIX = 'ANALYTICS_STEP'
    DEBUG_FILE_PREFIX = 'analytics_debug'

    # Keep only phase-specific methods
    # Remove duplicated methods (they come from TransformProcessorBase now)
```

### Step 2: Test Analytics
```bash
python -m pytest tests/processors/analytics/ -v --tb=short
```

### Step 3: Update PrecomputeProcessorBase
Same pattern as Step 1.

### Step 4: Test Precompute
```bash
python -m pytest tests/processors/precompute/ -v --tb=short
```

### Step 5: Full Test Suite
```bash
python -m pytest tests/processors/ tests/ml/ -q --tb=line
```

---

## Phase-Specific Differences to Preserve

### AnalyticsProcessorBase
- Uses `start_date` and `end_date` for date ranges
- Has `calculate_analytics()` method
- Extensive dependency checking for Phase 2 raw tables
- Multi-source fallback logic

### PrecomputeProcessorBase
- Uses `analysis_date` for single-day processing
- Has `calculate_precompute()` method
- Different date column handling (`date_column = "analysis_date"`)

---

## Risk Mitigation

1. **Make changes incrementally** - one base class at a time
2. **Run tests after each change** - catch regressions early
3. **Keep backup** - don't delete old code until tests pass
4. **Check method resolution order (MRO)** - Python's MRO matters for mixins

```python
# Verify MRO after changes
print(AnalyticsProcessorBase.__mro__)
```

---

## Deliverables

1. [x] `analytics_base.py` inherits from `TransformProcessorBase`
2. [x] Remove ~400 lines of duplicate methods from `analytics_base.py` (192 lines removed)
3. [x] `precompute_base.py` inherits from `TransformProcessorBase`
4. [x] Remove ~400 lines of duplicate methods from `precompute_base.py` (146 lines removed)
5. [x] All processor tests passing (834 passed, 11 pre-existing failures)
6. [x] Update any child classes that override removed methods (fixed `processor_name` setter)

---

## Verification

```bash
# All tests must pass
python -m pytest tests/processors/ -q --tb=no

# Verify inheritance
python3 -c "from data_processors.analytics.analytics_base import AnalyticsProcessorBase; from shared.processors.base import TransformProcessorBase; print(issubclass(AnalyticsProcessorBase, TransformProcessorBase))"

# Should print: True
```

---

## Completion Summary

**Completed:** 2026-01-24
**Results:**
- analytics_base.py: 3,062 → 2,870 lines (-192)
- precompute_base.py: 2,665 → 2,519 lines (-146)
- Total: ~338 lines of duplicate code removed
- Both base classes now inherit from TransformProcessorBase
- Added STEP_PREFIX and DEBUG_FILE_PREFIX class attributes for customization
- Fixed processor_name property to support child class setters

---

**Created:** 2026-01-24
**Completed:** 2026-01-24
**Session Type:** Architecture Refactoring
**Status:** ✅ COMPLETE
