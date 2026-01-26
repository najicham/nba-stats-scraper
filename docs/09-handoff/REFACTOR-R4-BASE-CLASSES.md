# Refactor Session R4: Processor Base Classes

**Scope:** 2 files, ~5,543 lines
**Risk Level:** HIGH (all analytics and precompute processors depend on these)
**Estimated Effort:** 3-4 hours
**Model:** Sonnet recommended (consider Opus for complex sections)

---

## Overview

Refactor the two foundational processor base classes that all Phase 3-5 processors inherit from. This is the highest-risk refactoring session.

**WARNING:** These are the most critical files. Every analytics and precompute processor inherits from these. Test extensively.

---

## Files to Refactor

### 1. data_processors/analytics/analytics_base.py (2,947 lines)

**Current State:** `AnalyticsProcessorBase` with multiple responsibilities including dependency validation, metadata tracking, BigQuery operations, notifications, monitoring, and the main `run()` method (536 lines).

**Target Structure:**
```
data_processors/analytics/
├── analytics_base.py            # Core AnalyticsProcessorBase (~400 lines)
├── mixins/
│   ├── __init__.py
│   ├── dependency_mixin.py      # Dependency validation
│   ├── metadata_mixin.py        # Source metadata tracking
│   ├── notification_mixin.py    # Email + Slack notifications
│   ├── quality_mixin.py         # Quality validation and tracking
│   └── monitoring_mixin.py      # Heartbeat, pipeline logging
├── operations/
│   ├── __init__.py
│   ├── bigquery_ops.py          # BigQuery query operations
│   └── failure_handler.py       # Failure categorization
```

**The run() Method (536 lines)**

This is the critical method. Break into orchestrated steps:

```python
# Current: One 536-line method
def run(self):
    # Lines 283-360: Dependency validation
    # Lines 361-380: Run history initialization
    # Lines 381-450: Data loading
    # Lines 451-550: Metric calculation
    # Lines 551-650: Quality validation
    # Lines 651-750: Data saving
    # Lines 751-800: Notifications
    # Lines 801-818: Error recovery

# Target: Orchestrated steps
def run(self):
    try:
        self._validate_dependencies()      # From DependencyMixin
        self._init_run_history()           # From RunHistoryMixin
        data = self._load_source_data()    # From BigQueryOps
        results = self._calculate_metrics(data)  # Subclass implements
        self._validate_quality(results)    # From QualityMixin
        self._save_results(results)        # From BigQueryOps
        self._send_notifications('success') # From NotificationMixin
    except Exception as e:
        self._handle_failure(e)            # From FailureHandler
```

**Methods to Extract:**

| Mixin/Module | Methods |
|--------------|---------|
| `DependencyMixin` | `_check_upstream_dependencies()`, `_validate_source_freshness()`, `_get_required_tables()` |
| `MetadataMixin` | `_load_source_metadata()`, `_track_source_versions()`, `_get_source_hash()` |
| `NotificationMixin` | `_send_email_notification()`, `_send_slack_notification()`, `_format_notification()` |
| `QualityMixin` | `_validate_output_quality()`, `_check_row_counts()`, `_detect_anomalies()` |
| `MonitoringMixin` | `_update_heartbeat()`, `_log_to_pipeline()`, `_record_metrics()` |
| `BigQueryOps` | `_query_raw_table()`, `_merge_to_analytics()`, `_load_batch()` |
| `FailureHandler` | `_categorize_failure()`, `_handle_transient_error()`, `_handle_permanent_error()` |

### 2. data_processors/precompute/precompute_base.py (2,596 lines)

**Current State:** `PrecomputeProcessorBase` with similar responsibilities to AnalyticsProcessorBase.

**Target Structure:**
```
data_processors/precompute/
├── precompute_base.py           # Core PrecomputeProcessorBase (~400 lines)
├── mixins/
│   ├── __init__.py
│   ├── dependency_mixin.py      # Dependency validation (Phase 3 sources)
│   ├── metadata_mixin.py        # Source metadata tracking
│   ├── notification_mixin.py    # Email + Slack notifications
│   └── monitoring_mixin.py      # Heartbeat, pipeline logging
├── operations/
│   ├── __init__.py
│   ├── bigquery_ops.py          # BigQuery operations
│   └── failure_handler.py       # Failure categorization
```

---

## Shared Code Opportunity

Analytics and Precompute bases share significant code. Consider:

```
data_processors/shared/
├── mixins/
│   ├── base_notification_mixin.py   # Shared notification logic
│   ├── base_monitoring_mixin.py     # Shared monitoring logic
│   └── base_metadata_mixin.py       # Shared metadata tracking
├── operations/
│   ├── base_bigquery_ops.py         # Shared BigQuery operations
│   └── base_failure_handler.py      # Shared failure handling
```

Then:
```python
# data_processors/analytics/mixins/notification_mixin.py
from data_processors.shared.mixins.base_notification_mixin import BaseNotificationMixin

class AnalyticsNotificationMixin(BaseNotificationMixin):
    """Analytics-specific notification customizations."""
    pass
```

---

## Critical Inheritance Chains

**Analytics Processors:**
```
TransformProcessorBase
    └── AnalyticsProcessorBase (+ SoftDependencyMixin, RunHistoryMixin)
        ├── PlayerGameSummaryProcessor
        ├── TeamGameSummaryProcessor
        ├── UpcomingPlayerGameContextProcessor
        ├── UpcomingTeamGameContextProcessor
        └── ... (20+ processors)
```

**Precompute Processors:**
```
TransformProcessorBase
    └── PrecomputeProcessorBase (+ SoftDependencyMixin, RunHistoryMixin)
        ├── PlayerCompositFactorsProcessor
        ├── PlayerDailyCacheProcessor
        └── ... (10+ processors)
```

---

## Testing Strategy

**This requires extensive testing:**

```bash
# 1. List all processors that inherit from these bases
grep -r "AnalyticsProcessorBase" data_processors/ --include="*.py" -l
grep -r "PrecomputeProcessorBase" data_processors/ --include="*.py" -l

# 2. Run ALL processor tests
python -m pytest tests/unit/data_processors/analytics/ -v
python -m pytest tests/unit/data_processors/precompute/ -v

# 3. Test a sample processor initialization
python -c "
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
print('PlayerGameSummaryProcessor OK')
"

# 4. Verify mixin method resolution
python -c "
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
print(AnalyticsProcessorBase.__mro__)
"
```

---

## Success Criteria

- [ ] analytics_base.py reduced to <400 lines
- [ ] precompute_base.py reduced to <400 lines
- [ ] run() method reduced to <100 lines (orchestration only)
- [ ] Each mixin file <250 lines
- [ ] ALL processor tests pass
- [ ] Method resolution order (MRO) is correct
- [ ] No import cycles

---

## Files to Create

| File | Purpose | Estimated Lines |
|------|---------|-----------------|
| **Analytics Mixins** | | |
| `analytics/mixins/__init__.py` | Mixin exports | ~20 |
| `analytics/mixins/dependency_mixin.py` | Dependency validation | ~200 |
| `analytics/mixins/metadata_mixin.py` | Metadata tracking | ~150 |
| `analytics/mixins/notification_mixin.py` | Notifications | ~150 |
| `analytics/mixins/quality_mixin.py` | Quality validation | ~200 |
| `analytics/mixins/monitoring_mixin.py` | Monitoring | ~150 |
| `analytics/operations/__init__.py` | Operations exports | ~10 |
| `analytics/operations/bigquery_ops.py` | BigQuery operations | ~300 |
| `analytics/operations/failure_handler.py` | Failure handling | ~100 |
| **Precompute Mixins** | | |
| `precompute/mixins/__init__.py` | Mixin exports | ~20 |
| `precompute/mixins/dependency_mixin.py` | Dependency validation | ~200 |
| `precompute/mixins/metadata_mixin.py` | Metadata tracking | ~150 |
| `precompute/mixins/notification_mixin.py` | Notifications | ~150 |
| `precompute/mixins/monitoring_mixin.py` | Monitoring | ~150 |
| `precompute/operations/__init__.py` | Operations exports | ~10 |
| `precompute/operations/bigquery_ops.py` | BigQuery operations | ~300 |
| `precompute/operations/failure_handler.py` | Failure handling | ~100 |

---

## Refactoring Order

1. **Start with analytics_base.py** - It's slightly larger
2. **Extract failure_handler.py first** - Standalone utility, easy to test
3. **Extract notification_mixin.py** - Clear boundaries
4. **Extract monitoring_mixin.py** - Clear boundaries
5. **Extract metadata_mixin.py** - Some coupling with BigQuery ops
6. **Extract dependency_mixin.py** - Core validation logic
7. **Extract bigquery_ops.py** - Last, as other mixins depend on patterns
8. **Refactor run() method** - Orchestration using extracted components
9. **Repeat for precompute_base.py** - Similar structure

---

## Notes

- **DO NOT** change method signatures - processors depend on them
- **DO NOT** change exception types raised - error handling depends on them
- Existing mixins (`SoftDependencyMixin`, `RunHistoryMixin`) must continue to work
- The `_categorize_failure()` function is module-level - keep it that way or move to failure_handler
- Consider creating shared base mixins in `data_processors/shared/` to reduce duplication
