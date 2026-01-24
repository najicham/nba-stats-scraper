# Session Handoff: Client Pool Migration

**Priority:** P1
**Estimated Effort:** 4-6 hours
**Goal:** Migrate from direct client instantiation to pooled clients

---

## Quick Start

```bash
# Verify pools work
python3 -c "from shared.clients import get_bigquery_client, get_firestore_client, get_storage_client, get_pubsub_publisher; print('All pools OK')"

# Find direct instantiation counts
grep -r "bigquery.Client()" --include="*.py" | wc -l
grep -r "firestore.Client()" --include="*.py" | wc -l
grep -r "storage.Client()" --include="*.py" | wc -l
```

---

## Problem Summary

Client pools exist but are severely underutilized:

| Client | Pool Usage | Direct Usage | Pool Adoption |
|--------|------------|--------------|---------------|
| BigQuery | 258 calls | 667 direct | 28% |
| Firestore | 24 calls | 116 direct | 17% |
| Storage | 0 calls | 170 direct | 0% |
| Pub/Sub | 24 calls | 101 direct | 19% |

**Impact of pools:** 40%+ connection overhead reduction, thread-safe, automatic cleanup

---

## Files to Study

### Pool Implementations (already done - understand these)
- `shared/clients/__init__.py` - Exports all pools
- `shared/clients/bigquery_pool.py` - BigQuery pool implementation
- `shared/clients/firestore_pool.py` - Firestore pool implementation
- `shared/clients/storage_pool.py` - Storage pool implementation
- `shared/clients/pubsub_pool.py` - Pub/Sub pool implementation

### Example Usage (already migrated)
- `data_processors/publishing/base_exporter.py` - Uses BigQuery pool
- `shared/processors/base/transform_processor_base.py` - Uses BigQuery pool

### High-Priority Migration Targets
1. `predictions/shared/distributed_lock.py` - Firestore direct usage
2. `shared/utils/completion_tracker.py` - Multiple direct usages
3. `shared/validation/firestore_state.py` - Firestore direct usage
4. `shared/monitoring/processor_heartbeat.py` - Multiple direct usages
5. `data_processors/raw/` - Many BigQuery direct usages

---

## Migration Pattern

### Before (Direct Instantiation)
```python
from google.cloud import bigquery
from google.cloud import firestore
from google.cloud import storage

class MyProcessor:
    def __init__(self):
        self.bq_client = bigquery.Client(project=self.project_id)
        self.fs_client = firestore.Client(project=self.project_id)
        self.storage_client = storage.Client(project=self.project_id)
```

### After (Pooled Clients)
```python
from shared.clients import get_bigquery_client, get_firestore_client, get_storage_client

class MyProcessor:
    def __init__(self):
        self.bq_client = get_bigquery_client(self.project_id)
        self.fs_client = get_firestore_client(self.project_id)
        self.storage_client = get_storage_client(self.project_id)
```

---

## Migration Order (by impact)

### Phase 1: Core Shared Utilities (Highest Impact)
These are used everywhere:
- [ ] `shared/utils/completion_tracker.py`
- [ ] `shared/validation/firestore_state.py`
- [ ] `shared/monitoring/processor_heartbeat.py`
- [ ] `shared/endpoints/health.py`

### Phase 2: Predictions System
- [ ] `predictions/shared/distributed_lock.py`
- [ ] `predictions/coordinator/coordinator.py`
- [ ] `predictions/worker/` modules

### Phase 3: Data Processors
- [ ] `data_processors/raw/` (many files)
- [ ] `data_processors/analytics/` (several files)
- [ ] `data_processors/precompute/` (several files)

### Phase 4: Orchestration
- [ ] `orchestration/` modules (after CF consolidation)

---

## Search Commands

```bash
# Find all direct BigQuery instantiation
grep -rn "bigquery.Client()" --include="*.py" | grep -v "test" | grep -v "__pycache__"

# Find all direct Firestore instantiation
grep -rn "firestore.Client()" --include="*.py" | grep -v "test" | grep -v "__pycache__"

# Find all direct Storage instantiation
grep -rn "storage.Client()" --include="*.py" | grep -v "test" | grep -v "__pycache__"

# Find all direct Pub/Sub instantiation
grep -rn "PublisherClient()" --include="*.py" | grep -v "test" | grep -v "__pycache__"
```

---

## Deliverables

1. [ ] Migrate all `shared/` utilities to use pools
2. [ ] Migrate `predictions/` to use pools
3. [ ] Migrate `data_processors/` to use pools (prioritize high-traffic)
4. [ ] Update any tests that mock client instantiation
5. [ ] Document pool usage in code comments

---

## Verification

```bash
# Should return 0 or very few results (only in tests/legacy)
grep -r "bigquery.Client()" --include="*.py" | grep -v test | grep -v pool | wc -l
grep -r "firestore.Client()" --include="*.py" | grep -v test | grep -v pool | wc -l

# Run tests to verify nothing broke
python -m pytest tests/unit/shared/ -q --tb=line
```

---

## Notes

- Pools are thread-safe with double-check locking
- Pools cache clients per-project for multi-tenant support
- Automatic cleanup via `atexit` handlers
- No behavior change expected - just connection reuse

---

**Created:** 2026-01-24
**Session Type:** Infrastructure Migration
