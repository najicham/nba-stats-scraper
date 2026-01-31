# Data Quality Self-Healing System

**Created:** 2026-01-30
**Status:** Implemented (Session 48)
**Priority:** P1 - Prevents Production Incidents
**Triggered By:** Session 46 DNP Data Corruption Incident

---

## Problem Statement

The DNP (Did Not Play) data corruption incident revealed critical gaps in our data quality infrastructure:

1. **DNP players got `points = 0` instead of `points = NULL`**
2. **Affected 30-50% of records** in November 2025 - January 2026
3. **Corrupted downstream ML features** (star players appeared to score 0)
4. **Went undetected for months** until model performance collapsed

### Root Cause Analysis

| Layer | What Failed | Why |
|-------|-------------|-----|
| Raw Data | Correct | Gamebook PDFs had DNP info |
| Analytics Processing | **FAILED** | `is_dnp` flag not set, `points` defaulted to 0 |
| Validation | **FAILED** | No business logic validation (points=0 is valid) |
| Monitoring | **FAILED** | No anomaly detection for % zero values |
| Alerting | **FAILED** | No alert threshold for data quality metrics |

---

## Implementation Status

| Phase | Scope | Status | Files |
|-------|-------|--------|-------|
| **Phase 1** | Pre-write validator | COMPLETE | `shared/validation/pre_write_validator.py` |
| **Phase 2** | Daily anomaly detection | COMPLETE | `shared/validation/daily_quality_checker.py` |
| **Phase 3** | Quality event logging | COMPLETE | `shared/utils/data_quality_logger.py` |
| **Phase 4** | Self-healing backfills | COMPLETE | `shared/utils/backfill_queue_manager.py` |

---

## Four-Layer Defense (Implemented)

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 1: PREVENTION                       │
│  Pre-write validation with business logic rules              │
│  Blocks: DNP with points=0, negative minutes, etc.           │
│  File: shared/validation/pre_write_validator.py              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 2: DETECTION                        │
│  Daily anomaly detection queries                             │
│  Catches: Unusual % zeros, missing DNPs, stat distributions  │
│  File: shared/validation/daily_quality_checker.py            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 3: ALERTING                         │
│  Threshold-based alerts to Slack/Email                       │
│  Routes: Critical → Immediate, Warning → Digest              │
│  File: shared/utils/notification_system.py (existing)        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 4: REMEDIATION                      │
│  Automated backfill triggers                                 │
│  Actions: Queue backfill, notify, create ticket              │
│  File: shared/utils/backfill_queue_manager.py                │
└─────────────────────────────────────────────────────────────┘
```

---

## Files Created (Session 48)

### Python Modules

| File | Purpose |
|------|---------|
| `shared/validation/pre_write_validator.py` | Business logic validation before BigQuery writes |
| `shared/validation/daily_quality_checker.py` | Daily anomaly detection with threshold checks |
| `shared/utils/data_quality_logger.py` | Audit log for quality events (detection, healing) |
| `shared/utils/backfill_queue_manager.py` | Automated backfill queue management |

### BigQuery Schemas

| File | Table |
|------|-------|
| `schemas/bigquery/orchestration/data_quality_events.sql` | `nba_orchestration.data_quality_events` |
| `schemas/bigquery/orchestration/data_quality_metrics.sql` | `nba_orchestration.data_quality_metrics` |
| `schemas/bigquery/orchestration/validation_failures.sql` | `nba_orchestration.validation_failures` |
| `schemas/bigquery/orchestration/backfill_queue.sql` | `nba_orchestration.backfill_queue` |

### Integration

| File | Change |
|------|--------|
| `data_processors/analytics/operations/bigquery_save_ops.py` | Added `_validate_before_write()` method |

---

## Business Rules Implemented

### player_game_summary

| Rule | Condition | Severity |
|------|-----------|----------|
| `dnp_null_points` | is_dnp=True → points=NULL | ERROR (blocks) |
| `dnp_null_minutes` | is_dnp=True → minutes=NULL | ERROR |
| `dnp_null_rebounds` | is_dnp=True → rebounds=NULL | ERROR |
| `dnp_null_assists` | is_dnp=True → assists=NULL | ERROR |
| `active_non_negative_points` | is_dnp=False → points>=0 | ERROR |
| `points_range` | points 0-100 | WARNING |
| `minutes_range` | minutes 0-60 | WARNING |

### player_composite_factors

| Rule | Condition | Severity |
|------|-----------|----------|
| `fatigue_score_range` | 0 <= fatigue_score <= 100 | ERROR |
| `matchup_difficulty_range` | -50 <= score <= 50 | ERROR |
| `pace_score_range` | 70 <= pace <= 130 | WARNING |

### ml_feature_store_v2

| Rule | Condition | Severity |
|------|-----------|----------|
| `feature_array_length` | len(features) == 34 | ERROR |
| `no_nan_features` | No NaN/Inf in features | ERROR |
| `feature_fatigue_range` | features[5] 0-100 | ERROR |

---

## Quality Checks Implemented

| Check | Table | Warning | Critical |
|-------|-------|---------|----------|
| `pct_zero_points` | player_game_summary | >15% | >30% |
| `pct_dnp_marked` | player_game_summary | <5% | =0% |
| `record_count` | player_game_summary | <100 | <50 |
| `fatigue_avg` | player_composite_factors | <50 | <30 |
| `fatigue_zero_rate` | player_composite_factors | >5% | >10% |
| `feature_completeness` | ml_feature_store_v2 | <95% | <90% |

---

## Usage Examples

### Run Daily Quality Check

```bash
# Check yesterday's data
python -m shared.validation.daily_quality_checker

# Check specific date with alerts
python -m shared.validation.daily_quality_checker --date 2026-01-22 --alerts

# Enable auto-backfill (use with caution)
python -m shared.validation.daily_quality_checker --alerts --auto-backfill
```

### Queue Manual Backfill

```python
from shared.utils.backfill_queue_manager import queue_backfill

queue_id = queue_backfill(
    table_name='player_game_summary',
    game_date='2026-01-22',
    reason='Manual fix for DNP corruption',
    priority=1
)
```

### Check Quality Events

```sql
-- Recent quality issues
SELECT event_timestamp, table_name, metric_name, metric_value, severity, description
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_type = 'QUALITY_ISSUE_DETECTED'
  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY event_timestamp DESC;

-- Self-healing success rate
SELECT
  DATE(event_timestamp) as date,
  COUNT(CASE WHEN event_type = 'QUALITY_ISSUE_DETECTED' THEN 1 END) as issues,
  COUNT(CASE WHEN event_type = 'SELF_HEALED' THEN 1 END) as healed
FROM `nba-props-platform.nba_orchestration.data_quality_events`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1 ORDER BY 1 DESC;
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_PRE_WRITE_VALIDATION` | `true` | Enable/disable pre-write validation |
| `ENABLE_QUALITY_LOGGING` | `true` | Enable/disable quality event logging |
| `ENABLE_AUTO_BACKFILL` | `true` | Enable/disable backfill queue |

---

## Deployment Steps

### 1. Create BigQuery Tables

```bash
# Run schema files
bq query --use_legacy_sql=false < schemas/bigquery/orchestration/data_quality_events.sql
bq query --use_legacy_sql=false < schemas/bigquery/orchestration/data_quality_metrics.sql
bq query --use_legacy_sql=false < schemas/bigquery/orchestration/validation_failures.sql
bq query --use_legacy_sql=false < schemas/bigquery/orchestration/backfill_queue.sql
```

### 2. Deploy Updated Analytics Processor

```bash
./bin/deploy-service.sh nba-phase3-analytics-processors
```

### 3. Set Up Daily Quality Check

```bash
# Create Cloud Scheduler job
gcloud scheduler jobs create http daily-quality-check \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://YOUR_CLOUD_FUNCTION_URL/check_quality" \
  --http-method=POST
```

---

## Related Projects

- `feature-quality-monitoring/` - ML feature monitoring (complementary, Session 48)
- `data-quality-prevention/` - Earlier prevention patterns
- `validation-framework/` - Core validation infrastructure

---

## Success Criteria

- [x] Pre-write validator module created
- [x] Business rules for DNP handling implemented
- [x] Integration with BigQuerySaveOpsMixin
- [x] Daily quality checker with threshold checks
- [x] Quality event logging (audit trail)
- [x] Backfill queue manager
- [x] BigQuery schemas for all tables
- [ ] Tables created in BigQuery (manual step)
- [ ] Daily check running in production
- [ ] First self-healing cycle verified

---

*Project Owner: Claude Code Sessions*
*Last Updated: 2026-01-30 (Session 48)*
