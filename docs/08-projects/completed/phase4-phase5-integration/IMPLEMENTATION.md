# Phase 4→5 Integration - Implementation Guide

**For full implementation details, see the original comprehensive spec:**
- External AI Analysis: `/docs/10-prompts/2025-11-28-phase4-to-phase5-integration-review.md`
- Full Specification: Section 5 "Detailed Design" (contains all code snippets)

This document provides quick-reference implementation steps.

---

## Files to Modify

### 1. Phase 4: ml_feature_store_processor.py
**Location:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Add to `post_process()` method:**
```python
def post_process(self) -> None:
    super().post_process()
    self._publish_completion_event()  # NEW

def _publish_completion_event(self) -> None:
    """Publish Phase 4 completion to Pub/Sub."""
    # See full spec Section 5.1 for complete implementation
```

### 2. Phase 5: coordinator.py
**Location:** `predictions/coordinator/coordinator.py`

**New Endpoints:**
- `/trigger` - Primary Pub/Sub path (Section 5.2.1)
- `/retry` - Incremental processing (Section 5.2.3)

**Updated Endpoints:**
- `/start` - Add validation + 30-min wait (Section 5.2.2)

**New Helper Functions:**
- `_validate_phase4_ready()` - Check Phase 4 status (Section 5.3)
- `_get_batch_status()` - Deduplication check (Section 5.3)
- `_wait_for_phase4()` - 30-min polling loop (Section 5.3)
- `_get_players_needing_retry()` - Find missing players (Section 5.3)

### 3. Pub/Sub Infrastructure Script
**Location:** `bin/phase5/deploy_pubsub_infrastructure.sh` (create new)

**See:** Section 5.4 for complete script

---

## Deployment Sequence

1. Create `bin/phase5/deploy_pubsub_infrastructure.sh`
2. Modify `ml_feature_store_processor.py` (add publishing)
3. Modify `coordinator.py` (add endpoints + helpers)
4. Write unit tests
5. Deploy infrastructure: `./bin/phase5/deploy_pubsub_infrastructure.sh`
6. Deploy Phase 4: `./bin/precompute/deploy_precompute_processors.sh`
7. Deploy Phase 5: `./bin/predictions/deploy/deploy_prediction_coordinator.sh`
8. Test end-to-end

---

## Quick Reference: Code Locations

| Function | File | Section in Full Spec |
|----------|------|---------------------|
| `_publish_completion_event()` | ml_feature_store_processor.py | 5.1 |
| `/trigger` endpoint | coordinator.py | 5.2.1 |
| `/start` endpoint (updated) | coordinator.py | 5.2.2 |
| `/retry` endpoint | coordinator.py | 5.2.3 |
| `_validate_phase4_ready()` | coordinator.py | 5.3 |
| `_get_batch_status()` | coordinator.py | 5.3 |
| `_wait_for_phase4()` | coordinator.py | 5.3 |
| Infrastructure script | deploy_pubsub_infrastructure.sh | 5.4 |

---

**For complete code snippets with full error handling, see the full specification.**
