# Architecture Refactoring - January 2026

**Created:** 2026-01-24
**Status:** Planning
**Priority:** P0-P1 (Mixed)
**Estimated Hours:** 48-60h

---

## Executive Summary

Codebase analysis revealed significant architectural issues requiring refactoring:

| Issue Category | Scope | Impact | Priority |
|---------------|-------|--------|----------|
| Cloud Function Duplication | ~30,000 lines | Maintenance nightmare | P0 |
| Large Files (>2000 LOC) | 12 files | Hard to test/maintain | P1 |
| Base Class Overlap | 4 classes, 60% overlap | Code duplication | P2 |
| Monolithic Services | 2 services | Poor separation of concerns | P3 |

---

## P0: Cloud Function Shared Utils Consolidation

### Problem Statement
6 cloud functions each have their own `/shared/utils/` directory with identical files:

| File | Lines | Duplicates | Total Waste |
|------|-------|------------|-------------|
| `completeness_checker.py` | 1,759 | 6 | 10,554 lines |
| `player_registry/reader.py` | 1,078 | 6 | 6,468 lines |
| `terminal.py` | 1,150 | 6 | 6,900 lines |
| `player_name_resolver.py` | 933 | 6 | 5,598 lines |

**Total: ~30,000 lines of duplicate code**

### Affected Cloud Functions
```
orchestration/cloud_functions/
├── phase2_to_phase3/shared/utils/  ← DUPLICATE #1
├── phase3_to_phase4/shared/utils/  ← DUPLICATE #2
├── phase4_to_phase5/shared/utils/  ← DUPLICATE #3
├── phase5_to_phase6/shared/utils/  ← DUPLICATE #4
├── daily_health_summary/shared/utils/  ← DUPLICATE #5
└── self_heal/shared/utils/  ← DUPLICATE #6
```

### Solution Architecture
```
orchestration/
├── shared/                          ← NEW: Central shared code
│   └── utils/
│       ├── completeness_checker.py  ← SINGLE SOURCE
│       ├── player_registry/
│       │   └── reader.py            ← SINGLE SOURCE
│       ├── terminal.py              ← SINGLE SOURCE
│       └── player_name_resolver.py  ← SINGLE SOURCE
└── cloud_functions/
    ├── phase2_to_phase3/
    │   ├── main.py
    │   ├── requirements.txt          ← Add orchestration-shared
    │   └── shared/ → ../shared/      ← SYMLINK or removed
    └── ... (other functions)
```

### Implementation Options

**Option A: Symlinks (Quick)**
- Create symlinks from each function to central shared dir
- Pros: Quick, no package management
- Cons: May not work in Cloud Functions deployment

**Option B: Shared Package (Recommended)**
- Create `orchestration-shared` pip package
- Install in each cloud function's requirements.txt
- Pros: Clean, testable, versioned
- Cons: More setup overhead

### Action Items
- [ ] Create `orchestration/shared/utils/` directory
- [ ] Copy canonical version of each shared file
- [ ] Update cloud function imports to use new path
- [ ] Update each function's requirements.txt
- [ ] Test all phase transitions work
- [ ] Delete old duplicate files
- [ ] Update deployment scripts

### Estimated Time: 8 hours

---

## P1: Large File Refactoring

### Target Files (>2000 lines)

| File | Lines | Status | Refactoring Strategy |
|------|-------|--------|---------------------|
| `analytics_base.py` | ~~3,062~~ 2,870 | ✅ Done | Inherit from TransformProcessorBase |
| `scraper_base.py` | 2,900 | Pending | Extract 3 mixins |
| `admin_dashboard/main.py` | 2,718 | Pending | Flask blueprints |
| `precompute_base.py` | ~~2,665~~ 2,519 | ✅ Done | Inherit from TransformProcessorBase |
| `upcoming_player_game_context_processor.py` | 2,634 | Pending | Extract context classes |
| `player_composite_factors_processor.py` | 2,611 | Pending | Extract calculators |

### Detailed Refactoring Plans

#### 1. analytics_base.py + precompute_base.py Unification ✅ COMPLETED

**Status:** Completed 2026-01-24

**Implementation:**
- Created `shared/processors/base/transform_processor_base.py` (500 lines)
- Both `AnalyticsProcessorBase` and `PrecomputeProcessorBase` now inherit from `TransformProcessorBase`
- Removed ~338 lines of duplicate code total
- Added `processor_name` setter to support child class customization

**Current State:**
- `transform_processor_base.py` (500 lines) - shared base
- `analytics_base.py` (2,870 lines, down from 3,062)
- `precompute_base.py` (2,519 lines, down from 2,665)

**Inherited Methods:**
- `is_backfill_mode` (property)
- `processor_name` (property with setter)
- `get_prefixed_dataset()` / `get_output_dataset()`
- `_execute_query_with_retry()`
- `_sanitize_row_for_json()`
- `_send_notification()`
- `_get_current_step()`
- `mark_time()` / `get_elapsed_seconds()`
- `step_info()` / `report_error()` / `_save_partial_data()`

#### 2. upcoming_player_game_context_processor.py

**Current State:** 2,634 lines handling 5 different context types

**Target Architecture:**
```python
# upcoming_player_game_context/
├── __init__.py
├── processor.py (500 lines)  # Orchestration only
├── contexts/
│   ├── betting_context.py (400 lines)
│   ├── travel_context.py (300 lines)
│   ├── stats_context.py (400 lines)
│   ├── team_context.py (300 lines)
│   └── player_context.py (400 lines)
└── utils/
    └── data_loaders.py (300 lines)
```

#### 3. admin_dashboard/main.py

**Current State:** 2,718 lines in single Flask file

**Target Architecture:**
```python
# services/admin_dashboard/
├── __init__.py
├── app.py (100 lines)  # Flask app factory
├── blueprints/
│   ├── predictions.py (400 lines)
│   ├── grading.py (400 lines)
│   ├── monitoring.py (400 lines)
│   ├── processors.py (400 lines)
│   └── health.py (200 lines)
├── services/
│   └── bigquery_service.py (1,724 → 800 lines)
└── repositories/
    ├── prediction_repository.py
    └── processor_repository.py
```

### Estimated Time: 24 hours total

---

## P2: Base Class Hierarchy Cleanup

### Current State
4 separate base classes with significant overlap:

```
ProcessorBase (raw)
├── Methods: 45
├── Lines: 1,519
└── Patterns: error handling, BigQuery, GCS

AnalyticsProcessorBase
├── Methods: 62
├── Lines: 3,062
└── Patterns: dependencies, notifications, heartbeat + all of ProcessorBase

PrecomputeProcessorBase
├── Methods: 58
├── Lines: 2,665
└── Patterns: same as AnalyticsProcessorBase

RegistryProcessorBase (reference)
├── Methods: 35
├── Lines: ~1,200
└── Patterns: subset of ProcessorBase
```

### Target Hierarchy
```
BaseProcessor (shared/processors/base.py)
├── Core: logging, config, error handling
├── Lines: ~500
└── Abstract methods: run(), validate()

    ├── RawProcessorBase (raw data ingestion)
    │   ├── HTTP handling
    │   ├── Validation
    │   └── Transform patterns
    │
    ├── TransformProcessorBase (analytics + precompute)
    │   ├── Dependency checking
    │   ├── Notifications
    │   ├── Heartbeat
    │   └── Soft dependencies
    │
    └── ReferenceProcessorBase (registry/reference)
        ├── Cache patterns
        └── Lookup optimization
```

### Estimated Time: 16 hours

---

## P3: Service Layer Improvements

### distributed_lock Location
**Current:** `predictions/worker/distributed_lock.py`
**Issue:** Cross-module import (`data_processors/grading/` imports from `predictions/`)
**Target:** `shared/coordination/distributed_lock.py`

### Admin Dashboard Service Splitting
See detailed plan in P1 section above.

### Estimated Time: 8 hours

---

## Implementation Schedule

### Week 1
- [ ] P0: Cloud function consolidation (8h)

### Week 2
- [ ] P1: analytics_base + precompute_base unification (8h)
- [ ] P1: upcoming_player_game_context split (6h)

### Week 3
- [ ] P1: admin_dashboard blueprint refactor (6h)
- [ ] P2: Base class hierarchy (8h)

### Week 4
- [ ] P3: distributed_lock relocation (2h)
- [ ] Testing and validation (8h)

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Duplicate code lines | ~30,000 | 0 |
| Files >2000 lines | 12 | 4 (with documented exceptions) |
| Base class overlap | 60% | <20% |
| Cross-module imports | 1+ | 0 |

---

## Related Documentation

- Main Improvement Plan: `../SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md`
- Code Quality Project: `../code-quality-2026-01/README.md`
- Master Tracker: `../MASTER-PROJECT-TRACKER.md`

---

**Created:** 2026-01-24
**Last Updated:** 2026-01-24
**Status:** In Progress

## Progress Update (Session 12 Afternoon)

### Completed
- [x] Created `shared/processors/base/failure_categorization.py` - Extracted common failure categorization
- [x] Created orchestration/shared/utils/ with canonical shared utilities

### In Progress
- [ ] Full analytics_base.py + precompute_base.py unification (deferred - high risk)
- [ ] Split upcoming_player_game_context_processor.py into modules

---

## Progress Update (Session 16 - 2026-01-24)

### Completed

#### Batch Staging/Distributed Lock Consolidation
- [x] Created `predictions/shared/batch_staging_writer.py` (consolidated from worker + coordinator)
- [x] Created `predictions/shared/distributed_lock.py` (consolidated from worker + coordinator)
- [x] Updated `predictions/shared/__init__.py` with exports
- [x] Created backward-compatibility shims in old locations
- [x] Updated 4 importing files to use new shared location
- **Impact:** ~825 lines of duplication removed

#### Client Pool Creation
- [x] Created `shared/clients/pubsub_pool.py` - Thread-safe PubSub publisher/subscriber pooling
- [x] Created `shared/clients/firestore_pool.py` - Thread-safe Firestore client pooling
- [x] Created `shared/clients/__init__.py` - Unified exports for all pools

#### Exporter Factory Pattern (Partial)
- [x] Created `data_processors/publishing/exporter_utils.py` with shared utilities:
  - safe_float(), safe_int(), format_float_dict()
  - format_percentage(), calculate_edge(), compute_win_rate()
  - get_generated_at(), create_empty_response(), truncate_string()
  - Common constants (CACHE_SHORT, CACHE_MEDIUM, CACHE_LONG, etc.)
- [x] Updated 16 exporters to use shared safe_float utility
- **Impact:** ~150 duplicate method definitions removed

### Analyzed (Deferred)

#### Cloud Function Shared Directory Consolidation
- Analysis complete: 7 CFs have local shared/ directories (37-40 files each)
- These shadow root imports during deployment
- **Recommendation:** Requires deployment configuration changes, tackle in dedicated session

### Remaining Work
- [ ] Complete exporter migration (6 more files)
- [ ] Create SimpleExporter/CompositeExporter template classes
- [ ] Migrate files to use new client pools (88 direct instantiations remain)
- [ ] Cloud function deployment consolidation
