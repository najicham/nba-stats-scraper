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

| File | Lines | Refactoring Strategy |
|------|-------|---------------------|
| `analytics_base.py` | 3,062 | Extract 4 mixins |
| `scraper_base.py` | 2,900 | Extract 3 mixins |
| `admin_dashboard/main.py` | 2,718 | Flask blueprints |
| `precompute_base.py` | 2,665 | Unify with analytics_base |
| `upcoming_player_game_context_processor.py` | 2,634 | Extract context classes |
| `player_composite_factors_processor.py` | 2,611 | Extract calculators |

### Detailed Refactoring Plans

#### 1. analytics_base.py + precompute_base.py Unification

**Current State:**
- `analytics_base.py` (3,062 lines)
- `precompute_base.py` (2,665 lines)
- ~60% code overlap (dependency checking, notifications, heartbeat)

**Target Architecture:**
```python
# shared/processors/base/shared_processor_base.py (1,500 lines)
class SharedProcessorBase:
    """Common processor functionality"""
    # Dependency checking
    # Error categorization
    # Notification system
    # Heartbeat integration
    # Soft dependencies

# data_processors/analytics/analytics_base.py (800 lines)
class AnalyticsProcessorBase(SharedProcessorBase):
    """Analytics-specific logic only"""
    # Analytics-specific methods

# data_processors/precompute/precompute_base.py (600 lines)
class PrecomputeProcessorBase(SharedProcessorBase):
    """Precompute-specific logic only"""
    # Feature calculation patterns
```

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
