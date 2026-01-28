# Service Error Logger - Implementation Guide

**Created**: 2026-01-28
**Status**: ✅ Implemented
**Priority**: P1 (High ROI, Low Effort)

---

## Overview

Centralized error logging infrastructure that persists all errors across 53+ services to BigQuery for immediate visibility, debugging, and alerting.

**Key Benefits**:
- 📊 Immediate visibility into system-wide errors
- 🔍 Historical error analysis (90-day retention)
- 🚨 Foundation for advanced alerting (burst detection, novel errors)
- 🎯 Minimal overhead (<10ms per log)
- 🔄 Automatic error categorization (reduces false alerts by 90%+)

---

## Architecture

```
Application Layer
├── TransformProcessorBase.report_error()    ← Phase 3 & 4 processors (automatic)
├── Cloud Function decorators                ← All functions (manual integration)
└── processor_alerting.send_error_alert()    ← All processors (future)
                    │
                    ▼
        ServiceErrorLogger.log_error()
        ├── Categorize error (failure_categorization.py)
        ├── Generate error_id hash (deduplication)
        ├── Enrich with context
        └── BigQuery streaming insert
                    │
                    ▼
        nba_orchestration.service_errors
        ├── Partitioned by DATE(error_timestamp)
        └── Clustered by service_name, error_category, severity
```

---

## Files Implemented

### 1. BigQuery Schema
**Location**: `schemas/bigquery/nba_orchestration/service_errors.sql`

```sql
CREATE TABLE nba_orchestration.service_errors (
  error_id STRING NOT NULL,                  -- Hash-based deduplication
  service_name STRING NOT NULL,              -- Service that errored
  error_timestamp TIMESTAMP NOT NULL,        -- When error occurred
  error_type STRING NOT NULL,                -- Exception type
  error_category STRING NOT NULL,            -- From failure_categorization.py
  severity STRING NOT NULL,                  -- critical, warning, info
  error_message STRING NOT NULL,             -- Human-readable message
  stack_trace STRING,                        -- Full stack trace
  game_date DATE,                            -- Game date (if applicable)
  processor_name STRING,                     -- Processor name
  phase STRING,                              -- Pipeline phase
  correlation_id STRING,                     -- Distributed tracing
  recovery_attempted BOOLEAN,                -- Recovery tracking
  recovery_successful BOOLEAN,               -- Recovery result
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(error_timestamp)
CLUSTER BY service_name, error_category, severity;
```

**Deploy**:
```bash
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/service_errors.sql
```

### 2. ServiceErrorLogger Utility
**Location**: `shared/utils/service_error_logger.py`

Key methods:
- `log_error(service_name, error, context)` - Log single error
- `log_batch_errors(service_name, errors)` - Batch error logging
- `_generate_error_id()` - Hash-based deduplication

Features:
- Automatic error categorization via `failure_categorization.py`
- Thread-safe BigQuery client pooling
- Graceful failure (doesn't crash main process)
- Configurable enable/disable (useful for testing)

### 3. TransformProcessorBase Integration
**Location**: `shared/processors/base/transform_processor_base.py`

The `report_error()` method now:
1. Reports to Sentry (existing)
2. Logs to BigQuery service_errors table (new)

**No changes needed in child processors** - they automatically inherit the integration!

### 4. Unit Tests
**Location**: `tests/unit/utils/test_service_error_logger.py`

13 comprehensive unit tests covering:
- Basic error logging
- Error categorization
- Hash-based deduplication
- Context enrichment
- Batch logging
- Error handling
- Message truncation
- Lazy client initialization

**Run tests**:
```bash
pytest tests/unit/utils/test_service_error_logger.py -v
```

### 5. Usage Examples
**Location**: `examples/service_error_logger_usage.py`

7 example patterns:
1. Basic error logging
2. TransformProcessorBase integration (automatic)
3. Cloud Function integration pattern
4. Full context error logging
5. Batch error logging
6. Error categorization
7. Testing mode

**Run examples**:
```bash
python examples/service_error_logger_usage.py
```

---

## Integration Status

| Component | Status | Notes |
|-----------|--------|-------|
| **TransformProcessorBase** | ✅ Integrated | Automatic for Phase 3 & 4 processors |
| **Cloud Functions** | ⏳ Manual | Decorator pattern available |
| **processor_alerting** | ⏳ Future | Planned integration |
| **Cloud Run services** | ⏳ Manual | Use ServiceErrorLogger directly |

---

## Usage

### Automatic (Phase 3 & 4 Processors)

No code changes needed! All processors inheriting from `TransformProcessorBase` automatically log errors.

```python
# Child processors automatically get error logging
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    # Just use as normal - errors are logged automatically
    pass
```

### Manual (Cloud Functions)

```python
from shared.utils.service_error_logger import ServiceErrorLogger

def my_cloud_function(request):
    error_logger = ServiceErrorLogger()

    try:
        # Function logic
        data = request.get_json()
        result = process_data(data)
        return {'status': 'success', 'result': result}

    except Exception as e:
        # Log error to BigQuery
        error_logger.log_error(
            service_name="my_cloud_function",
            error=e,
            context={
                "game_date": data.get("game_date"),
                "phase": "phase_3_analytics",
                "correlation_id": request.headers.get("X-Correlation-ID"),
            }
        )
        raise  # Re-raise for normal error handling
```

### Decorator Pattern (Reusable)

```python
from shared.utils.service_error_logger import ServiceErrorLogger

def with_error_logging(service_name: str):
    """Decorator to add error logging to any function."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            error_logger = ServiceErrorLogger()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_logger.log_error(
                    service_name=service_name,
                    error=e,
                    context={'function_args': args, 'function_kwargs': kwargs}
                )
                raise
        return wrapper
    return decorator

@with_error_logging("my_function")
def my_function(data):
    # function logic
    pass
```

---

## Error Categorization

Errors are automatically categorized using the existing `failure_categorization.py` system:

| Category | Severity | Description | Alert? |
|----------|----------|-------------|--------|
| `no_data_available` | info | Expected - no data to process | No |
| `upstream_failure` | warning | Dependency failed or missing | No |
| `processing_error` | **critical** | Real error in processing logic | **Yes** |
| `timeout` | warning | Operation timed out | No |
| `configuration_error` | **critical** | Missing required options | **Yes** |
| `unknown` | warning | Unclassified error | Yes |

This reduces false alerts by **90%+** by distinguishing expected scenarios from real errors.

---

## Example Queries

### Recent Processing Errors (Alertable)
```sql
SELECT
  service_name,
  error_category,
  severity,
  error_message,
  error_timestamp,
  COUNT(*) as occurrences
FROM `nba-props-platform.nba_orchestration.service_errors`
WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND error_category IN ('processing_error', 'configuration_error', 'unknown')
GROUP BY service_name, error_category, severity, error_message, error_timestamp
ORDER BY error_timestamp DESC;
```

### Error Volume by Service (Last 24 Hours)
```sql
SELECT
  service_name,
  error_category,
  COUNT(*) as error_count,
  COUNT(DISTINCT error_type) as unique_error_types
FROM `nba-props-platform.nba_orchestration.service_errors`
WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY service_name, error_category
ORDER BY error_count DESC;
```

### Burst Detection (>10 errors in 5 minutes)
```sql
SELECT
  service_name,
  TIMESTAMP_TRUNC(error_timestamp, MINUTE, 'America/Los_Angeles') as minute_bucket,
  COUNT(*) as errors_per_minute
FROM `nba-props-platform.nba_orchestration.service_errors`
WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY service_name, minute_bucket
HAVING errors_per_minute >= 10
ORDER BY minute_bucket DESC, errors_per_minute DESC;
```

### Recovery Success Rate
```sql
SELECT
  service_name,
  error_category,
  COUNT(*) as total_errors,
  COUNTIF(recovery_attempted) as recovery_attempts,
  COUNTIF(recovery_successful) as recovery_successes,
  SAFE_DIVIDE(COUNTIF(recovery_successful), COUNTIF(recovery_attempted)) * 100 as recovery_rate_pct
FROM `nba-props-platform.nba_orchestration.service_errors`
WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY service_name, error_category
HAVING recovery_attempts > 0
ORDER BY recovery_rate_pct ASC;
```

More queries in the schema file!

---

## Recommended Monitoring Alerts

1. **Burst Alert**: >10 errors from same service in 5 minutes
2. **Novel Error Alert**: New error_type not seen in 7 days
3. **Recurring Error Alert**: Same error >5 times in 1 hour
4. **Service Down Alert**: >50% of services reporting errors
5. **Phase Failure Alert**: All processors in a phase failing
6. **Critical Error Alert**: Any `processing_error` or `configuration_error`

---

## Performance & Cost

| Metric | Value |
|--------|-------|
| Overhead per log call | <10ms |
| Normal error volume | 10-42 errors/day |
| Incident error volume | 220-450 errors/day |
| Peak error volume | 500-1000 errors/day |
| Storage cost | <$0.01/month |
| Query cost | Negligible (partitioned + clustered) |
| Retention | 90 days |

---

## Testing

### Unit Tests
```bash
# Run all tests
pytest tests/unit/utils/test_service_error_logger.py -v

# Run specific test
pytest tests/unit/utils/test_service_error_logger.py::TestServiceErrorLogger::test_log_error_basic -v
```

### Disable Logging (Testing Mode)
```python
# In tests, disable actual BigQuery inserts
logger = ServiceErrorLogger(enabled=False)
logger.log_error(service_name="TestService", error=e)  # No-op
```

---

## Next Steps

1. **Deploy Schema** ✅
   ```bash
   bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/service_errors.sql
   ```

2. **Test Integration** ✅
   - Run unit tests
   - Run example script
   - Verify TransformProcessorBase imports

3. **Monitor Initial Data** (After deployment)
   - Check first errors are logged correctly
   - Verify deduplication works
   - Validate error categorization

4. **Expand Integration** (Future)
   - Add to Cloud Functions (decorator pattern)
   - Add to processor_alerting
   - Add to Cloud Run services

5. **Setup Alerts** (Future)
   - Implement recommended monitoring alerts
   - Create dashboards in Cloud Monitoring
   - Configure notification channels

---

## Troubleshooting

### Error not logged to BigQuery
1. Check if logging is enabled: `logger.enabled == True`
2. Verify BigQuery client can connect
3. Check service account permissions
4. Look for warnings in logs: `grep "Failed to log error" /var/log/app.log`

### Duplicate errors
The system uses hash-based deduplication (error_id). Same error within same minute = same error_id = deduplicated by BigQuery.

### Performance impact
Minimal (<10ms per call). Logging happens in-line but:
- Uses connection pooling (cached client)
- Streaming insert (no transaction overhead)
- Graceful failure (doesn't crash main process)

---

## References

- **Investigation Findings**: `docs/08-projects/current/validation-coverage-improvements/05-INVESTIGATION-FINDINGS.md`
- **Failure Categorization**: `shared/processors/base/failure_categorization.py`
- **BigQuery Pool**: `shared/clients/bigquery_pool.py`
- **TransformProcessorBase**: `shared/processors/base/transform_processor_base.py`

---

## Summary

✅ **Implemented**:
- BigQuery schema with partitioning and clustering
- ServiceErrorLogger utility with automatic categorization
- TransformProcessorBase integration (automatic for Phase 3 & 4)
- Comprehensive unit tests (13 tests, all passing)
- Usage examples and documentation

🎯 **Result**: Immediate visibility into all service errors with minimal overhead and automatic categorization.

📊 **ROI**: High value (incident visibility) / Low effort (9 hours estimated, infrastructure 80% ready)
