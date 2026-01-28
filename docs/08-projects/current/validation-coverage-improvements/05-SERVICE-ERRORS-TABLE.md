# Service Errors Table - Centralized Error Logging

**Priority**: P1
**Effort**: 8-10 hours
**Status**: Investigation

---

## Problem Statement

Service errors are scattered across Cloud Run logs. Debugging the Jan 25-28 stall required manually checking logs for 5+ services. We need centralized error visibility.

---

## Proposed Solution

Create BigQuery table for all service errors with structured logging.

### Schema
```sql
CREATE TABLE nba_orchestration.service_errors (
  error_id STRING NOT NULL,
  service_name STRING NOT NULL,
  error_timestamp TIMESTAMP NOT NULL,
  error_type STRING NOT NULL,           -- 'ModuleNotFoundError', 'TimeoutError', etc.
  error_category STRING NOT NULL,       -- 'transient', 'permanent', 'resource', 'dependency'
  severity STRING NOT NULL,             -- 'critical', 'high', 'medium', 'low'
  error_message STRING NOT NULL,
  stack_trace STRING,
  game_date DATE,
  processor_name STRING,
  phase STRING,
  correlation_id STRING,
  recovery_attempted BOOLEAN,
  recovery_successful BOOLEAN,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(error_timestamp)
CLUSTER BY service_name, error_category, severity;
```

### Error Categories
| Category | Examples | Recovery |
|----------|----------|----------|
| transient | Network timeout, 429 rate limit | Auto-retry |
| permanent | ModuleNotFoundError, SyntaxError | Manual fix required |
| resource | Memory exceeded, quota exceeded | Increase resources |
| dependency | Upstream service down | Wait/escalate |

---

## Implementation Plan

### Step 1: Create Table and Utility
```python
# shared/utils/service_error_logger.py
class ServiceErrorLogger:
    def log_error(self, error, context):
        # Write to BigQuery
        pass
```

### Step 2: Integrate with Base Classes
Add error logging to:
- `AnalyticsProcessorBase`
- Cloud Function exception handlers
- Orchestrator error handlers

### Step 3: Create Error Dashboard
Query for recent errors, patterns, and trends.

---

## Investigation Questions

1. What services should log to this table?
2. What's the retention policy? (30 days? 90 days?)
3. Should we use streaming inserts or batch?
4. How do we prevent duplicate error entries?
5. What alerts should fire on error patterns?

---

## Success Criteria

- [ ] All services log errors to central table
- [ ] Error dashboard shows recent issues
- [ ] Recurring error patterns trigger alerts
