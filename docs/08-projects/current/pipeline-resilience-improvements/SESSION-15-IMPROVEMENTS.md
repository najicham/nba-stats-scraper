# Session 15 Pipeline Resilience Improvements

**Date**: 2026-01-29
**Status**: Completed

## Overview

This session implemented three major reliability improvements identified in Session 14:
1. Migrated single-row BigQuery writes to BigQueryBatchWriter
2. Added retry decorators to critical processors
3. Centralized validation thresholds to config module

## Changes Summary

### 1. BigQuery Batch Writer Migration (4 files)

Migrated high-frequency single-row writes to use `BigQueryBatchWriter` for quota protection.

| File | Table | Frequency |
|------|-------|-----------|
| `functions/monitoring/realtime_completeness_checker/main.py` | `nba_orchestration.processor_completions` | Per processor completion |
| `services/admin_dashboard/services/audit_logger.py` | `nba_pipeline.admin_audit_logs` | Per admin action |
| `monitoring/pipeline_latency_tracker.py` | `nba_analytics.pipeline_latency_metrics` | Daily |
| `monitoring/scraper_cost_tracker.py` | `nba_orchestration.scraper_cost_metrics` | Per scraper run |

**Pattern Applied**:
```python
# Before
client.insert_rows_json(table_id, [row])

# After
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(row)
writer.flush()  # Immediate flush for visibility
```

### 2. Retry Decorators (10 files)

Added retry decorators from `shared/utils/bigquery_retry.py` to critical operations.

#### Phase 5 Predictions (5 files)
| File | Functions Decorated | Decorator |
|------|---------------------|-----------|
| `predictions/worker/worker.py` | `write_predictions_to_bigquery()` | `@retry_on_quota_exceeded` |
| `predictions/coordinator/coordinator.py` | `_check_data_completeness_for_predictions()` | `@retry_on_transient` |
| `predictions/worker/data_loaders.py` | `load_features()`, `load_features_batch_for_date()`, `load_historical_games()`, `load_game_context()` | `@retry_on_transient` |
| `predictions/coordinator/player_loader.py` | `create_prediction_requests()`, `_query_players_for_date()`, `get_summary_stats()` | `@retry_on_transient` |
| `predictions/shared/batch_staging_writer.py` | `write_to_staging()`, `_consolidate_with_lock()` | `@retry_on_quota_exceeded`, `@retry_on_serialization` |

#### Analytics/Data Processing (5 files)
| File | Functions Decorated | Decorator |
|------|---------------------|-----------|
| `data_processors/analytics/operations/bigquery_save_ops.py` | `save_analytics()`, `_save_with_proper_merge()`, `_delete_existing_data_batch()` | `@retry_on_quota_exceeded`, `@retry_on_serialization` |
| `data_processors/precompute/operations/bigquery_save_ops.py` | `save_precompute()`, `_save_with_proper_merge()` | `@retry_on_quota_exceeded`, `@retry_on_serialization` |
| `data_processors/raw/processor_base.py` | `save_data()` | `@retry_on_quota_exceeded`, `@retry_on_serialization` |
| `shared/publishers/unified_pubsub_publisher.py` | `_publish()` | google-api-core retry for Pub/Sub |

**Retry Behavior**:
| Decorator | Handles | Strategy |
|-----------|---------|----------|
| `@retry_on_transient` | ServiceUnavailable, DeadlineExceeded | 1s→30s, 3min deadline |
| `@retry_on_quota_exceeded` | 403 quota errors | 2s→120s, 10min deadline |
| `@retry_on_serialization` | 400 serialization conflicts | 1s→32s, 2min deadline |

### 3. Validation Config Centralization (4 files)

Updated validation scripts to use centralized `config/validation_thresholds.yaml`.

| File | Changes |
|------|---------|
| `scripts/validate_tonight_data.py` | Uses `get_minutes_coverage_threshold()`, `get_usage_rate_coverage_threshold()`, `get_spot_check_threshold()`, `get_threshold()` |
| `bin/monitoring/morning_health_check.sh` | Sources thresholds via `get_thresholds.py` |
| `bin/monitoring/daily_health_check.sh` | Sources thresholds via `get_thresholds.py` |
| `bin/monitoring/get_thresholds.py` | **NEW** - Helper to export thresholds as shell variables |

**Thresholds Centralized**:
- Minutes coverage: warning=90%, critical=80%
- Usage rate coverage: warning=90%, critical=80%
- Field completeness: fg/ft/3pt=90%
- Spot check accuracy: pass=95%
- Phase 3 processors: expected=5

## Files Modified

```
bin/monitoring/daily_health_check.sh
bin/monitoring/morning_health_check.sh
bin/monitoring/get_thresholds.py (NEW)
data_processors/analytics/operations/bigquery_save_ops.py
data_processors/precompute/operations/bigquery_save_ops.py
data_processors/raw/processor_base.py
functions/monitoring/realtime_completeness_checker/main.py
monitoring/pipeline_latency_tracker.py
monitoring/scraper_cost_tracker.py
predictions/coordinator/coordinator.py
predictions/coordinator/player_loader.py
predictions/shared/batch_staging_writer.py
predictions/worker/data_loaders.py
predictions/worker/worker.py
scripts/validate_tonight_data.py
services/admin_dashboard/services/audit_logger.py
shared/publishers/unified_pubsub_publisher.py
```

## Benefits

1. **Quota Protection**: BigQueryBatchWriter bypasses load job quota limits
2. **Transient Error Recovery**: Automatic retry with exponential backoff
3. **Serialization Conflict Handling**: Automatic retry on concurrent DML
4. **Single Source of Truth**: All thresholds in one config file
5. **Consistency**: Python and shell scripts use same values

## Remaining Work

From Session 14 findings, these items remain:
- 8 more single-row BQ write locations (lower priority)
- 10 more files needing retry decorators (medium priority)
- 4 more validation scripts with hardcoded thresholds

## Testing

All modified Python files pass syntax validation. Recommend:
1. Run `/validate-daily` to verify pipeline health
2. Monitor Cloud Run logs for retry activity
3. Check BigQuery quota usage after deployment

## Related Documents

- Session 14 Handoff: `docs/09-handoff/2026-01-29-SESSION-14-HANDOFF.md`
- BigQuery Retry Utils: `shared/utils/bigquery_retry.py`
- BigQuery Batch Writer: `shared/utils/bigquery_batch_writer.py`
- Validation Config: `config/validation_thresholds.yaml`
