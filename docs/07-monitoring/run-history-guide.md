# Processor Run History Guide

**Created:** 2025-11-27
**Last Updated:** 2025-11-27
**Purpose:** Guide for using `processor_run_history` table for debugging and investigation
**Status:** Implemented

---

## Overview

All processor base classes (Phase 2, 3, 4) now automatically log runs to `nba_reference.processor_run_history`. This provides comprehensive audit trails for:

- **Debugging alerts:** Trace an alert email back to what caused it
- **Dependency failures:** See what dependencies were missing and why
- **Performance analysis:** Track duration, records processed, etc.
- **Trigger correlation:** Link Pub/Sub messages to processor runs

## Schema Quick Reference

### Key Debugging Columns

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | STRING | Unique run identifier (use to trace alerts) |
| `processor_name` | STRING | Which processor ran |
| `phase` | STRING | phase_2_raw, phase_3_analytics, phase_4_precompute |
| `status` | STRING | success, failed, skipped |
| `data_date` | DATE | Date being processed |
| `started_at` | TIMESTAMP | When the run started |
| `duration_seconds` | FLOAT | How long it took |

### Trigger Tracing Columns

| Column | Type | Description |
|--------|------|-------------|
| `trigger_source` | STRING | pubsub, scheduler, manual, api |
| `trigger_message_id` | STRING | Pub/Sub message ID for correlation |
| `parent_processor` | STRING | Upstream processor that triggered this |

### Dependency Tracking Columns

| Column | Type | Description |
|--------|------|-------------|
| `dependency_check_passed` | BOOLEAN | Did all critical dependencies pass? |
| `missing_dependencies` | JSON | Array of missing table names |
| `stale_dependencies` | JSON | Array of stale table names |
| `upstream_dependencies` | JSON | Full dependency check results |

### Alert Tracking Columns

| Column | Type | Description |
|--------|------|-------------|
| `alert_sent` | BOOLEAN | Was an alert sent during this run? |
| `alert_type` | STRING | error, warning, info |

### Cloud Run Metadata

| Column | Type | Description |
|--------|------|-------------|
| `cloud_run_service` | STRING | K_SERVICE environment variable |
| `cloud_run_revision` | STRING | K_REVISION environment variable |

---

## Common Queries

### 1. Trace an Alert Back to Its Cause

When you receive an error email with a `run_id` like `fea26b01`:

```sql
SELECT
    processor_name,
    phase,
    status,
    trigger_source,
    trigger_message_id,
    parent_processor,
    dependency_check_passed,
    missing_dependencies,
    stale_dependencies,
    alert_sent,
    alert_type,
    errors,
    started_at,
    duration_seconds
FROM nba_reference.processor_run_history
WHERE run_id LIKE '%fea26b01%'
ORDER BY started_at DESC;
```

### 2. Find All Failed Runs for Today

```sql
SELECT
    processor_name,
    run_id,
    status,
    dependency_check_passed,
    missing_dependencies,
    errors,
    started_at
FROM nba_reference.processor_run_history
WHERE data_date = CURRENT_DATE()
  AND status = 'failed'
ORDER BY started_at DESC;
```

### 3. Find Runs Where Alerts Were Sent

```sql
SELECT
    processor_name,
    run_id,
    alert_type,
    status,
    dependency_check_passed,
    missing_dependencies,
    started_at
FROM nba_reference.processor_run_history
WHERE alert_sent = TRUE
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY started_at DESC;
```

### 4. Find All Runs Triggered by Same Pub/Sub Message

```sql
SELECT
    processor_name,
    phase,
    status,
    started_at,
    duration_seconds
FROM nba_reference.processor_run_history
WHERE trigger_message_id = '12345678901234567'
ORDER BY started_at;
```

### 5. Find Dependency Failures by Processor

```sql
SELECT
    processor_name,
    data_date,
    missing_dependencies,
    stale_dependencies,
    started_at
FROM nba_reference.processor_run_history
WHERE dependency_check_passed = FALSE
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY started_at DESC;
```

### 6. Track a Specific Processor's Recent Runs

```sql
SELECT
    run_id,
    status,
    trigger_source,
    dependency_check_passed,
    duration_seconds,
    records_processed,
    started_at
FROM nba_reference.processor_run_history
WHERE processor_name = 'MLFeatureStoreProcessor'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY started_at DESC
LIMIT 50;
```

### 7. Find Most Common Missing Dependencies

```sql
SELECT
    JSON_EXTRACT_SCALAR(dep, '$') as missing_dependency,
    COUNT(*) as failure_count,
    COUNT(DISTINCT processor_name) as affected_processors
FROM nba_reference.processor_run_history,
UNNEST(JSON_EXTRACT_ARRAY(missing_dependencies)) as dep
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND missing_dependencies IS NOT NULL
GROUP BY missing_dependency
ORDER BY failure_count DESC
LIMIT 20;
```

### 8. Performance Analysis by Phase

```sql
SELECT
    phase,
    processor_name,
    COUNT(*) as runs,
    AVG(duration_seconds) as avg_duration,
    MAX(duration_seconds) as max_duration,
    COUNTIF(status = 'failed') as failures
FROM nba_reference.processor_run_history
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY phase, processor_name
ORDER BY phase, avg_duration DESC;
```

---

## Investigation Workflow

When you receive an alert email:

### Step 1: Get the Run ID

From the alert email, find the `run_id` (e.g., `fea26b01`).

### Step 2: Query Run Details

```sql
SELECT *
FROM nba_reference.processor_run_history
WHERE run_id LIKE '%fea26b01%';
```

### Step 3: Check Dependencies

Look at:
- `dependency_check_passed`: Did dependencies pass?
- `missing_dependencies`: What was missing?
- `stale_dependencies`: What was stale?

### Step 4: Find Trigger Source

Look at:
- `trigger_source`: Was it pubsub, scheduler, or manual?
- `trigger_message_id`: What Pub/Sub message triggered it?
- `parent_processor`: What upstream processor triggered this?

### Step 5: Correlate with Upstream

If triggered by Pub/Sub, find the upstream run:

```sql
SELECT *
FROM nba_reference.processor_run_history
WHERE trigger_message_id = '[message_id_from_step_4]'
ORDER BY started_at;
```

### Step 6: Check Cloud Logs

Use the `cloud_run_service` and `cloud_run_revision` to query Cloud Logging:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND
  resource.labels.service_name="[cloud_run_service]" AND
  jsonPayload.run_id="[run_id]"' \
  --project=nba-props-platform --limit=50
```

---

## Phase 5 (Predictions) Run Tracking

Phase 5 uses a separate table optimized for per-player predictions:

**Table:** `nba_predictions.prediction_worker_runs`

Key tracing columns:
- `trigger_source`: What triggered the prediction
- `trigger_message_id`: Pub/Sub message ID
- `cloud_run_service`: Cloud Run service name
- `cloud_run_revision`: Cloud Run revision
- `retry_attempt`: Which retry attempt
- `batch_id`: Batch ID for bulk requests

```sql
SELECT
    request_id,
    player_lookup,
    game_date,
    success,
    trigger_source,
    trigger_message_id,
    cloud_run_service,
    run_date
FROM nba_predictions.prediction_worker_runs
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND success = FALSE
ORDER BY run_date DESC;
```

---

## Implementation Details

### RunHistoryMixin

All processor base classes inherit from `RunHistoryMixin`:

```python
class ProcessorBase(RunHistoryMixin):          # Phase 2
class AnalyticsProcessorBase(RunHistoryMixin): # Phase 3
class PrecomputeProcessorBase(RunHistoryMixin): # Phase 4
```

**Location:** `shared/processors/mixins/run_history_mixin.py`

### Automatic Logging

The mixin automatically:
1. Calls `start_run_tracking()` at the beginning of `run()`
2. Captures Cloud Run metadata from environment
3. Records dependency check results
4. Tracks when alerts are sent
5. Calls `record_run_complete()` at the end (success or failure)

### Schema Migration

To add the new columns to an existing table:

```bash
python scripts/migrations/add_run_history_columns.py
```

---

## See Also

- [Monitoring & Error Handling Design](../01-architecture/monitoring-error-handling-design.md)
- [Alert System Documentation](./alerting/alert-system.md)
- [Processor Development Guide](../05-development/guides/processor-development.md)
