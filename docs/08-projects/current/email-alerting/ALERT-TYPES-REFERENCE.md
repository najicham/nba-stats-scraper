# Email Alert Types - Developer Reference

**Last Updated**: 2026-01-02
**Status**: Production ✅

---

## Quick Start

```python
from shared.utils.email_alerting_ses import EmailAlerterSES

alerter = EmailAlerterSES()

# Auto-detect alert type from error message
alerter.send_error_alert(
    error_message="Zero Rows Saved: Expected 33 rows but saved 0",
    processor_name="OddsApiPropsProcessor"
)
# Result: 📉 No Data Saved (ERROR - Dark Red)

# Explicitly specify alert type
alerter.send_error_alert(
    error_message="Processing failed",
    processor_name="MyProcessor",
    alert_type="database_conflict"  # ❌ Database Conflict
)
```

---

## Alert Type Taxonomy

### 🚨 CRITICAL (Red `#d32f2f`)
**Service down, immediate action required, data loss possible**

| Type | Heading | When to Use |
|------|---------|-------------|
| `service_failure` | 🚨 Service Failure | Service crashed, unavailable, terminated unexpectedly |
| `critical_data_loss` | 🚨 Critical Data Loss | Unrecoverable data loss detected |

**Action Required**: Immediate investigation and remediation

---

### ❌ ERROR (Dark Red `#c82333`)
**Processing failed, data gaps likely, recoverable**

| Type | Heading | When to Use |
|------|---------|-------------|
| `processing_failed` | ❌ Processing Failed | Processor failed to complete, data may be incomplete |
| `no_data_saved` | 📉 No Data Saved | Processor ran but saved zero rows (expected data) |
| `database_conflict` | ❌ Database Conflict | BigQuery serialization conflict, retries exhausted |

**Action Required**: Review error details, verify automatic retry status

**Example Triggers**:
- `"Zero Rows Saved"`
- `"saved 0"`
- `"Could not serialize access"`
- `"concurrent update"`

---

### ⚠️ WARNING (Orange `#ff9800`)
**Needs investigation, not immediately urgent**

| Type | Heading | When to Use |
|------|---------|-------------|
| `data_quality_issue` | ⚠️ Data Quality Issue | Incomplete data, unexpected values, validation concerns |
| `slow_processing` | ⏱️ Slow Processing | Processing slower than expected thresholds |
| `pipeline_stalled` | ⏳ Pipeline Stalled | Pipeline not progressing, waiting on upstream |
| `stale_data` | 🕐 Stale Data Warning | Data not updated within expected timeframe |
| `high_unresolved_count` | ⚠️ High Unresolved Count | Unusually high number of unresolved items |

**Action Required**: Investigate when convenient, may indicate future issues

**Example Triggers**:
- `"data quality"`, `"incomplete"`, `"missing data"`
- `"slow"`, `"timeout"`, `"performance"`
- `"stall"`, `"not progressing"`
- `"stale"`, `"not updated"`
- `"unresolved"` + `"high"`

---

### ℹ️ INFO (Blue `#2196f3`)
**Informational, for awareness, no immediate action**

| Type | Heading | When to Use |
|------|---------|-------------|
| `data_anomaly` | ℹ️ Data Anomaly | Unusual pattern detected, not breaking functionality |
| `validation_notice` | ℹ️ Validation Notice | Validation completed with informational notes |

**Action Required**: Review when convenient

**Example Triggers**:
- `"validation"`, `"anomaly"`

---

### ✅ SUCCESS (Green `#28a745`)
**Positive reports, summaries, confirmations**

| Type | Heading | When to Use |
|------|---------|-------------|
| `daily_summary` | 📊 Daily Summary | Daily processing summary and statistics |
| `health_report` | ✅ Pipeline Health Report | System health check results |
| `completion_report` | 🎯 Completion Report | Batch/backfill operation completed successfully |
| `new_discoveries` | 🆕 New Discoveries | New players or entities discovered and added |

**Action Required**: Review for trends and insights

---

### 🎨 SPECIAL PURPOSE

| Type | Heading | Color | When to Use |
|------|---------|-------|-------------|
| `prediction_summary` | 🏀 Prediction Summary | Purple `#6f42c1` | Prediction batch completion |
| `backfill_progress` | 📦 Backfill Progress | Cyan `#17a2b8` | Backfill operation progress |

---

## Auto-Detection Logic

The system automatically detects alert types from error messages:

```python
from shared.utils.alert_types import detect_alert_type

# Example 1: Zero rows
error = "⚠️ Zero Rows Saved: Expected 33 rows but saved 0"
alert_type = detect_alert_type(error)
# Result: 'no_data_saved' → 📉 No Data Saved

# Example 2: BigQuery conflict
error = "Could not serialize access to table due to concurrent update"
alert_type = detect_alert_type(error)
# Result: 'database_conflict' → ❌ Database Conflict

# Example 3: Service crash
error = "Service crashed due to memory exhaustion"
alert_type = detect_alert_type(error)
# Result: 'service_failure' → 🚨 Service Failure
```

**Detection Priority** (first match wins):
1. Explicit `alert_type` in error_data dict
2. "Zero rows saved" / "saved 0" → `no_data_saved`
3. "Could not serialize" → `database_conflict`
4. "crashed" / "terminated" → `service_failure`
5. "slow" / "timeout" / "performance" → `slow_processing`
6. "stale" / "not updated" → `stale_data`
7. "stall" → `pipeline_stalled`
8. "data quality" / "incomplete" → `data_quality_issue`
9. "validation" / "anomaly" → `data_anomaly`
10. "unresolved" + "high" → `high_unresolved_count`
11. **Default**: `processing_failed`

---

## API Reference

### Using Email Alerter

```python
from shared.utils.email_alerting_ses import EmailAlerterSES

alerter = EmailAlerterSES()

# Method 1: Auto-detect (recommended)
alerter.send_error_alert(
    error_message="Could not serialize access to table",
    error_details={'table': 'nba_raw.br_rosters_current'},
    processor_name="Basketball Reference Roster Processor"
)
# Auto-detects: database_conflict → ❌ Database Conflict

# Method 2: Explicit type
alerter.send_error_alert(
    error_message="Processing failed",
    error_details={'reason': 'API timeout'},
    processor_name="MyProcessor",
    alert_type="slow_processing"  # ⏱️ Slow Processing
)
```

### Programmatic Access

```python
from shared.utils.alert_types import (
    ALERT_TYPES,
    get_alert_config,
    format_alert_heading,
    get_alert_html_heading
)

# Get all available types
all_types = ALERT_TYPES.keys()

# Get config for specific type
config = get_alert_config('no_data_saved')
print(config['emoji'])      # 📉
print(config['heading'])    # No Data Saved
print(config['color'])      # #c82333
print(config['severity'])   # ERROR
print(config['action'])     # Verify source data availability...

# Format heading (text)
heading = format_alert_heading('no_data_saved')
# Result: "📉 No Data Saved"

# Format heading (HTML)
html = get_alert_html_heading('no_data_saved')
# Result: '<h2 style="color: #c82333;">📉 No Data Saved</h2>'
```

---

## Best Practices

### 1. Let Auto-Detection Work
```python
# ✅ GOOD - Auto-detect handles it
alerter.send_error_alert(
    error_message="Zero Rows Saved: Expected 50 but saved 0",
    processor_name="MyProcessor"
)

# ❌ UNNECESSARY - Don't manually specify if auto-detect works
alerter.send_error_alert(
    error_message="Zero Rows Saved: Expected 50 but saved 0",
    processor_name="MyProcessor",
    alert_type="no_data_saved"  # Redundant
)
```

### 2. Use Explicit Types for Ambiguous Cases
```python
# ✅ GOOD - Explicit when message is generic
alerter.send_error_alert(
    error_message="Operation failed",  # Too generic
    error_details={'context': 'During backfill'},
    processor_name="MyProcessor",
    alert_type="processing_failed"  # Explicit
)
```

### 3. Provide Rich Error Details
```python
# ✅ GOOD - Detailed context
alerter.send_error_alert(
    error_message="Zero Rows Saved",
    error_details={
        'expected_rows': 33,
        'actual_rows': 0,
        'game_date': '2026-01-02',
        'api_response_code': 200,
        'api_response_empty': True
    },
    processor_name="OddsApiPropsProcessor"
)
```

### 4. Don't Over-Alarm
```python
# ❌ BAD - Using CRITICAL for non-critical issues
alerter.send_error_alert(
    error_message="Data validation notice",
    alert_type="service_failure"  # Wrong! Not critical
)

# ✅ GOOD - Appropriate severity
alerter.send_error_alert(
    error_message="Data validation notice",
    alert_type="validation_notice"  # INFO level
)
```

---

## Testing

Run the test suite to verify detection logic:

```bash
python test_email_alert_types.py
```

Expected output:
```
================================================================================
EMAIL ALERT TYPE DETECTION TEST
================================================================================

Test Case: Zero Rows Saved
  Detected Type: no_data_saved
  Alert Heading: 📉 No Data Saved
  Severity: ERROR
  ...

✅ Alert type detection test completed!
```

---

## Troubleshooting

### Alert Not Auto-Detecting Correctly

**Problem**: Error message not matching expected alert type

**Solution**: Check detection patterns in `shared/utils/alert_types.py:detect_alert_type()`

**Workaround**: Explicitly specify `alert_type` parameter

### Wrong Severity Level

**Problem**: Warning showing as Critical

**Solution**: Verify the alert type being used - check auto-detection logic

### Email Not Rendering

**Problem**: HTML heading not showing correctly

**Solution**: Check `get_alert_html_heading()` is being used, not `format_alert_heading()`

---

## Migration from Old System

### Before (All errors were critical):
```python
# Old code - everything was 🚨 Critical Error Alert
alerter.send_error_alert(
    error_message="Zero Rows Saved",
    processor_name="MyProcessor"
)
# Subject: MyProcessor - Critical Error
# Heading: 🚨 Critical Error Alert
```

### After (Intelligent detection):
```python
# New code - auto-detects appropriate severity
alerter.send_error_alert(
    error_message="Zero Rows Saved",
    processor_name="MyProcessor"
)
# Subject: MyProcessor - No Data Saved
# Heading: 📉 No Data Saved (ERROR - not CRITICAL)
```

**Backward Compatibility**: ✅ Complete
All existing code continues to work without changes. The `alert_type` parameter is optional.

---

## Related Files

- **Alert Type Config**: `shared/utils/alert_types.py`
- **Email Alerting (Brevo)**: `shared/utils/email_alerting.py`
- **Email Alerting (AWS SES)**: `shared/utils/email_alerting_ses.py`
- **Smart Alerting**: `shared/utils/smart_alerting.py`
- **Processor Alerting**: `shared/utils/processor_alerting.py`
- **Test Suite**: `test_email_alert_types.py`

---

**Questions or Issues?**
See `shared/utils/alert_types.py` for implementation details or add a new alert type to the taxonomy.
