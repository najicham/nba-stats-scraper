# Service Errors Table - Investigation Findings

**Investigated**: 2026-01-28
**Status**: Ready for Implementation
**Priority**: P1 (High ROI, Low Effort)

---

## Key Finding: Infrastructure 80% Ready, Just Need BigQuery Persistence

Failure categorization, error context tracking, alert deduplication all exist. Just missing the BigQuery persistence layer.

---

## 1. Services Count

| Type | Count |
|------|-------|
| Cloud Run Services | 7 |
| Cloud Functions | 46+ |
| **Total** | 53+ services |

**Major Function Groups:**
- Phase Orchestration: 8 functions
- Monitoring & Alerts: 15+ functions
- Self-Healing: 6 functions
- Data Operations: 8+ functions

---

## 2. Current Error Logging

| Method | Purpose | Limitation |
|--------|---------|------------|
| `structured_logging.py` | JSON logs for Cloud Logging | Not persisted long-term |
| `processor_alerting.py` | Slack + email alerts | Not searchable |
| `scraper_logging.py` | GCS bucket logs | Scraper-specific only |
| Sentry | Exception tracking | External service |
| Cloud Logging | Automatic capture | 30-day retention |

**Critical Gap**: No centralized BigQuery table for error persistence.

---

## 3. Existing Error Infrastructure

**Failure Categorization** (`failure_categorization.py`):
- `NO_DATA_AVAILABLE` - Expected, don't alert
- `UPSTREAM_FAILURE` - Dependency failed
- `PROCESSING_ERROR` - Real error (ALERT!)
- `TIMEOUT` - Operation timed out
- `CONFIGURATION_ERROR` - Missing config
- `UNKNOWN` - Unclassified

**This system reduces false alerts by 90%+**

**Alert Deduplication**: 15-minute window (hash-based, in-memory)

---

## 4. Base Classes for Integration

| Base Class | Coverage | Integration Point |
|------------|----------|-------------------|
| `TransformProcessorBase` | Phase 3 & 4 processors | `report_error()` method |
| Cloud Function wrapper | All functions | Decorator pattern |
| `processor_alerting` | All processors | `send_error_alert()` |

---

## 5. Estimated Error Volume

| Condition | Volume |
|-----------|--------|
| Normal operations | 10-42 errors/day |
| During incidents | 220-450 errors/day |
| Peak (major outage) | 500-1000 errors/day |

**Storage**: ~2-27 MB/month, **Cost**: <$0.01/month

---

## 6. Recommended Schema

```sql
CREATE TABLE nba_orchestration.service_errors (
  error_id STRING NOT NULL,
  service_name STRING NOT NULL,
  error_timestamp TIMESTAMP NOT NULL,
  error_type STRING NOT NULL,
  error_category STRING NOT NULL,  -- Use existing categorization
  severity STRING NOT NULL,
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

---

## 7. Implementation Plan

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Create table | 30 min |
| 2 | Create `ServiceErrorLogger` utility | 2 hours |
| 3 | Integrate with TransformProcessorBase | 1 hour |
| 4 | Create Cloud Function decorator | 2 hours |
| 5 | Add to processor_alerting | 1 hour |
| 6 | Testing | 2 hours |
| 7 | Documentation | 30 min |
| **Total** | | **~9 hours** |

---

## 8. Recommended Alerts

1. **Burst Alert**: >10 errors from same service in 5 minutes
2. **Novel Error Alert**: New error_type not seen in 7 days
3. **Recurring Error Alert**: Same error >5 times in 1 hour
4. **Service Down Alert**: >50% of services reporting errors
5. **Phase Failure Alert**: All processors in a phase failing

---

## 9. Key Decisions

| Question | Answer |
|----------|--------|
| Streaming vs Batch? | **Streaming** (low volume, immediate visibility) |
| Retention? | **90 days** (minimal cost) |
| Deduplication? | Hash(service + error_type + message + timestamp_minute) |

---

## Summary

| Component | Status |
|-----------|--------|
| Failure categorization | ✅ Exists |
| Error context tracking | ✅ Exists |
| Alert deduplication | ✅ Exists |
| Base class hooks | ✅ Exists |
| BigQuery persistence | ❌ New (this project) |

**ROI**: High value (immediate incident visibility) / Low effort (9 hours)
