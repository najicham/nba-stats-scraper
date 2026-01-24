# Resilience Improvements - Session Handoff

**Date:** 2026-01-24
**Focus:** Pipeline reliability, error handling, and validation improvements

## Summary

This session implemented 8 improvements from the resilience phase 2 backlog, focusing on exception handling, retry logic, validation, and monitoring.

## Changes Made

### 1. Specific Exception Handling (Task #1)

Replaced bare `except Exception as e:` with specific exception types in critical files:

| File | Exceptions Used |
|------|-----------------|
| `orchestration/master_controller.py` | `GoogleAPIError` |
| `orchestration/cleanup_processor.py` | `GoogleAPIError`, `TimeoutError` |
| `orchestration/workflow_executor.py` | `RequestException`, `GoogleAPIError`, `CircuitBreakerOpenError` |
| `data_processors/grading/mlb/main_mlb_grading_service.py` | `GoogleAPIError`, `ValueError`, `json.JSONDecodeError` |
| `shared/utils/processor_alerting.py` | `RequestException`, `SMTPException`, `socket.error` |

**Impact:** Prevents masking of specific failure modes, improves debuggability.

### 2. BigQuery Retry Decorators (Task #2)

Added `@retry_with_jitter` to core BigQuery utility functions:

```python
# shared/utils/bigquery_utils.py
@retry_with_jitter(max_attempts=3, base_delay=1.0, max_delay=15.0,
                   exceptions=(ServiceUnavailable, DeadlineExceeded))
def _execute_bigquery_internal(...)
def _insert_bigquery_rows_internal(...)
def _execute_bigquery_with_params_internal(...)
def _update_bigquery_rows_internal(...)

# shared/utils/bigquery_utils_v2.py
def _execute_bigquery_v2_internal(...)
```

**Impact:** Automatic retry on transient failures (503, deadline exceeded).

### 3. MLB Unresolved Player Persistence (Task #3)

Implemented `flush_unresolved_to_bigquery()` in `shared/utils/mlb_player_registry/reader.py`:

- Inserts unresolved player records to `mlb_reference.unresolved_players`
- Provides audit trail for data quality monitoring
- Schema already exists in `schemas/bigquery/mlb_reference/unresolved_players_table.sql`

### 4. Config Consolidation (Task #4)

Added `sport_config.py` to `bin/maintenance/sync_shared_utils.py`:

```python
FILES_TO_SYNC = {
    'sport_config.py': 'config',  # Added
    # ... other files
}
```

Run `python bin/maintenance/sync_shared_utils.py` to sync all 8 copies.

### 5. Pydantic Validation (Task #6)

Created `shared/validation/pubsub_models.py` with typed message schemas:

- `Phase2CompletionMessage` - Phase 2 processor completion events
- `Phase3CompletionMessage` - Phase 3 processor completion events
- `Phase3AnalyticsMessage` - Phase 3 trigger events
- `ScraperCompletionMessage` - Phase 1 scraper completion events
- `GradingTriggerMessage` - Phase 6 grading triggers

Added validation to cloud functions:
- `orchestration/cloud_functions/phase2_to_phase3/main.py`
- `orchestration/cloud_functions/phase3_to_phase4/main.py`
- `orchestration/cloud_functions/phase4_to_phase5/main.py`
- `orchestration/cloud_functions/phase5_to_phase6/main.py`

### 6. DLQ Monitor Expansion (Task #7)

Extended `orchestration/cloud_functions/dlq_monitor/main.py` to monitor Cloud Logging:

```python
CLOUD_LOGGING_FILTERS = {
    'bigquery_errors': {...},
    'firestore_errors': {...},
    'gcs_errors': {...},
}

def check_cloud_logging_errors(lookback_minutes=15) -> Dict:
    # Queries Cloud Logging for errors from BQ/Firestore/GCS
```

**Impact:** Unified error monitoring beyond Pub/Sub DLQs.

### 7. Query Optimization Analysis (Task #8)

Analyzed `data_processors/` for queries without date filters:
- **Finding:** Most queries already have proper `WHERE game_date` filters
- **One exception:** `feature_extractor.py` total_games count intentionally scans full history for bootstrap detection

## Files Modified

```
orchestration/master_controller.py
orchestration/cleanup_processor.py
orchestration/workflow_executor.py
orchestration/cloud_functions/phase2_to_phase3/main.py
orchestration/cloud_functions/phase3_to_phase4/main.py
orchestration/cloud_functions/phase4_to_phase5/main.py
orchestration/cloud_functions/phase5_to_phase6/main.py
orchestration/cloud_functions/dlq_monitor/main.py
data_processors/grading/mlb/main_mlb_grading_service.py
shared/utils/bigquery_utils.py
shared/utils/bigquery_utils_v2.py
shared/utils/processor_alerting.py
shared/utils/mlb_player_registry/reader.py
shared/validation/pubsub_models.py (new)
bin/maintenance/sync_shared_utils.py
```

## Testing

All modified files compile successfully. Validated:
- Retry decorator works with exponential backoff
- Pydantic validates messages correctly (rejects invalid, accepts valid)
- Sync script identifies all 8 sport_config.py copies

## Remaining Opportunities

### High Priority
1. **Exception handling:** 5 files updated, ~1057 files still have bare `except Exception`. Priority files:
   - `orchestration/parameter_resolver.py` (4 handlers)
   - `orchestration/schedule_locker.py` (2 handlers)
   - `data_processors/precompute/ml_feature_store/feature_extractor.py`

2. **BigQuery direct calls:** 287 direct `client.query()` calls bypass retry utilities. Could wrap in `@retry_with_jitter` or refactor to use `execute_bigquery()`.

### Medium Priority
3. **Pydantic validation:** Extended to 4 cloud functions. Remaining:
   - `self_heal/main.py`
   - `daily_health_summary/main.py`
   - `scraper_availability_monitor/main.py`

4. **Unit test coverage:** Tests exist but have import path issues. Fix `PYTHONPATH` in pytest or add `conftest.py` path setup.

### Where to Study
- **Handoff docs:** `docs/09-handoff/` - Previous session summaries
- **Architecture:** `docs/01-architecture/` - System design
- **Resilience plan:** `docs/08-projects/current/pipeline-reliability-improvements/`
- **Config:** `orchestration/config/` and `shared/config/`

### Commands for Next Session
```bash
# Find bare exceptions
grep -r "except Exception" --include="*.py" orchestration/ data_processors/ | wc -l

# Find direct BQ calls
grep -r "client\.query(" --include="*.py" data_processors/ | wc -l

# Run sync to propagate shared utils
python bin/maintenance/sync_shared_utils.py --dry-run

# Test compilation
python -m py_compile <file>
```

## Deployment Notes

1. Deploy updated cloud functions:
   ```bash
   gcloud functions deploy phase2-to-phase3 --source orchestration/cloud_functions/phase2_to_phase3
   gcloud functions deploy phase3-to-phase4 --source orchestration/cloud_functions/phase3_to_phase4
   gcloud functions deploy dlq-monitor --source orchestration/cloud_functions/dlq_monitor
   ```

2. Run sync script before deployment:
   ```bash
   python bin/maintenance/sync_shared_utils.py
   ```

3. Monitor Cloud Logging for retry behavior after deployment.
