# Alert System Documentation

Complete guide to the NBA Props Platform intelligent alerting system.

**Last Updated:** 2025-10-14

---

## Table of Contents
- [The Problem](#the-problem)
- [Solution Overview](#solution-overview)
- [Architecture](#architecture)
- [Components](#components)
- [Implementation Guide](#implementation-guide)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)

---

## The Problem

### Email Flood Scenario

**Before the alert system:**
```
Backfill runs → 500 dates fail → 500 individual emails → Gmail blocks/delays them
```

**Issues:**
- Hundreds of error emails flood your inbox
- Gmail rate limits cause delays (emails arrive a day later)
- Hard to see patterns in individual error emails
- Can't distinguish critical from non-critical issues
- Miss important alerts buried in spam

**Real example from your system:**
- Scraper fails for 100 games
- Each game triggers 3 processor errors
- Result: 300 emails in 10 minutes
- Gmail delays delivery by 12-24 hours

---

## Solution Overview

### Three-Tier Alert Strategy

```
┌─────────────────────────────────────────────────────┐
│                    Alert Flow                        │
└─────────────────────────────────────────────────────┘

Processor Error
     │
     ▼
┌─────────────────┐
│ Alert Severity? │
└─────────────────┘
     │
     ├─── CRITICAL ───→ 🚨 Immediate Email + Slack
     │
     ├─── ERROR ──────→ 🔔 Slack (batched hourly)
     │                  └─→ Daily digest email
     │
     ├─── WARNING ────→ 🔔 Slack (batched 3h)
     │                  └─→ Daily digest email
     │
     └─── INFO ───────→ 📊 Daily digest email only
```

### Result

**After the alert system:**
```
500 errors → Batched & rate-limited → 1 digest email + periodic Slack updates
```

---

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────┐
│                    Alert System                          │
└──────────────────────────────────────────────────────────┘

┌─────────────────┐
│   Processors    │  ← Your code
│   & Scrapers    │
└────────┬────────┘
         │ send_alert()
         ▼
┌─────────────────────────────────────┐
│     AlertAggregator                 │
│  (shared/utils/alert_aggregator.py) │
│                                     │
│  • Rate limiting                    │
│  • Severity routing                 │
│  • Batch detection                  │
│  • Alert queuing                    │
└─────────────────────────────────────┘
         │
         ├──── Immediate? ───→ Email/Slack NOW
         │
         └──── Queue ────────→ GCS (pending-alerts/)
                                    │
                                    ▼
                         ┌───────────────────────┐
                         │  Daily Digest Job     │
                         │  (Cloud Scheduler)    │
                         │  Runs: 9am daily      │
                         └───────────────────────┘
                                    │
                                    ▼
                            📧 Summary Email
```

### Data Flow

1. **Error Occurs** → Processor catches exception
2. **Alert Created** → `AlertAggregator.send_alert()` called
3. **Severity Check** → Routes based on severity level
4. **Rate Limit Check** → Has this alert been sent recently?
5. **Batch Detection** → Are we in high-volume mode?
6. **Delivery:**
   - **Immediate:** Send email/Slack now
   - **Queued:** Store in GCS for digest

---

## Components

### 1. AlertAggregator (Core)

**File:** `shared/utils/alert_aggregator.py`

**Purpose:** Central alert routing and batching

**Key Features:**
- Rate limiting per alert type
- Automatic batch mode during high volume (>10 alerts in 5 min)
- Severity-based routing
- Intelligent deduplication

**Methods:**
```python
send_alert(source, message, severity, metadata)  # Send an alert
send_digest(hours=24)                           # Send digest email
```

### 2. SmartAlertManager (Simple Version)

**File:** `shared/utils/smart_alerting.py`

**Purpose:** Simple batching for backfill jobs

**Key Features:**
- Enable/disable batch mode
- Queue errors during batch mode
- Send summary email when done

**Methods:**
```python
enable_backfill_mode()                # Start batching
record_error(error_data)              # Queue an error
disable_backfill_mode(send_summary)   # Send summary
```

### 3. Alert Configuration

**File:** `shared/config/alert_config.py`

**Purpose:** Configure routing rules and channels

**What it defines:**
- Which severity goes to which channel
- Rate limits per severity
- Digest schedule
- Email/Slack configuration

### 4. Daily Digest Job

**Deployment:** Cloud Scheduler + Cloud Function

**Purpose:** Send daily summary of all queued alerts

**Schedule:** Daily at 9am PT

---

## Implementation Guide

### Quick Start: Fix Email Floods Today

**Step 1: Use SmartAlertManager in Backfill Jobs**

```python
# File: backfill_jobs/raw/bdl_boxscores/backfill.py

from shared.utils.smart_alerting import SmartAlertManager
from datetime import datetime, timedelta

def backfill_box_scores(start_date, end_date):
    """Backfill box scores without email flood"""
    
    alert_mgr = SmartAlertManager()
    
    # Enable batch mode
    alert_mgr.enable_backfill_mode()
    
    # Generate date range
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    
    try:
        for date in dates:
            try:
                scrape_box_scores(date)
                print(f"✓ {date}")
            except Exception as e:
                # Queue error (doesn't send email yet)
                alert_mgr.record_error({
                    "scraper": "bdl_box_scores",
                    "date": str(date),
                    "error_type": type(e).__name__,
                    "error": str(e)
                })
                print(f"✗ {date}: {e}")
    
    finally:
        # Send ONE summary email with all errors
        alert_mgr.disable_backfill_mode(send_summary=True)

# Usage
backfill_box_scores(
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 3, 31)  # 90 days
)
```

**Result:** 90 errors → 1 email with summary

---

### Full Implementation: Production System

**Step 2: Use AlertAggregator in All Processors**

```python
# File: data_processors/raw/balldontlie/bdl_box_scores.py

from shared.utils.alert_aggregator import AlertAggregator
from flask import Flask, request

app = Flask(__name__)
alerts = AlertAggregator()

@app.route('/process', methods=['POST'])
def process_box_scores():
    """Process box scores with intelligent alerting"""
    
    data = request.get_json()
    date = data.get('date')
    
    try:
        # Your processing logic
        raw_data = load_from_gcs(f"raw/bdl_box_scores/{date}/data.json")
        processed = process_data(raw_data)
        save_to_bigquery(processed)
        
        return {"status": "success", "records": len(processed)}, 200
        
    except FileNotFoundError as e:
        # WARNING: Missing data (might be expected)
        alerts.send_alert(
            source="bdl_box_scores_processor",
            message=f"No data found for {date}",
            severity="WARNING",
            metadata={"date": date, "expected": is_game_day(date)}
        )
        return {"status": "warning", "message": str(e)}, 200
        
    except Exception as e:
        # ERROR: Unexpected failure
        alerts.send_alert(
            source="bdl_box_scores_processor",
            message=f"Processing failed: {str(e)}",
            severity="ERROR",
            metadata={"date": date, "error_type": type(e).__name__}
        )
        return {"status": "error", "message": str(e)}, 500
```

**Step 3: Configure Alert Routing**

```python
# File: shared/config/alert_config.py

ALERT_ROUTING = {
    "CRITICAL": {
        "channels": ["email", "slack"],  # Both immediately
        "rate_limit_minutes": 0,         # No limit
        "immediate": True
    },
    "ERROR": {
        "channels": ["slack"],           # Slack only
        "rate_limit_minutes": 60,        # Max 1 per hour
        "batch": True                    # Queue for digest
    },
    "WARNING": {
        "channels": ["slack"],
        "rate_limit_minutes": 180,       # Max 1 per 3 hours
        "batch": True
    },
    "INFO": {
        "channels": [],                  # No immediate alert
        "batch": True                    # Digest only
    }
}

EMAIL_CONFIG = {
    "to": ["your-email@gmail.com"],
    "from": "nba-alerts@yourproject.com",
    "subject_prefix": "[NBA Props]"
}

SLACK_CONFIG = {
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK",
    "channel": "#nba-alerts",
    "critical_channel": "#nba-critical"
}
```

**Step 4: Deploy Daily Digest**

```bash
# Create Cloud Function for digest
cat > digest_function/main.py << 'EOF'
from shared.utils.alert_aggregator import AlertAggregator

def send_digest(request):
    """Cloud Function to send daily digest"""
    alerts = AlertAggregator()
    alerts.send_digest(hours=24)
    return {"status": "success"}
EOF

# Deploy function
gcloud functions deploy send-alert-digest \
  --runtime=python312 \
  --trigger-http \
  --entry-point=send_digest \
  --region=us-west2

# Schedule it
gcloud scheduler jobs create http daily-alert-digest \
  --schedule="0 9 * * *" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/send-alert-digest" \
  --http-method=POST \
  --location=us-west2 \
  --time-zone="America/Los_Angeles"
```

---

## Configuration

### Severity Levels

| Severity | When to Use | Example | Delivery |
|----------|-------------|---------|----------|
| **CRITICAL** | System down, revenue impact | Database unreachable, All scrapers failing | Immediate email + Slack |
| **ERROR** | Unexpected failure | Scraper failed, Processing error | Slack (rate-limited) + Daily digest |
| **WARNING** | Expected issue | No data for off-season date | Slack (rate-limited) + Daily digest |
| **INFO** | Informational | Scraper completed with 0 records | Daily digest only |

### Rate Limits

Configure how often alerts of the same type can be sent:

```python
rate_limits = {
    AlertSeverity.CRITICAL: 0,    # No limit - always send
    AlertSeverity.ERROR: 60,      # Max 1 per hour
    AlertSeverity.WARNING: 180,   # Max 1 per 3 hours
    AlertSeverity.INFO: 360       # Max 1 per 6 hours
}
```

### Batch Thresholds

System automatically switches to batch mode during high volume:

```python
batch_threshold = 10   # If >10 alerts in 5 minutes
batch_window = 300     # 5 minute window
```

When batch mode is active:
- Non-critical alerts are queued
- Sent in next digest instead of immediately

---

## Usage Examples

### Example 1: Simple Error in Processor

```python
from shared.utils.alert_aggregator import AlertAggregator

alerts = AlertAggregator()

try:
    result = call_api()
except APIError as e:
    alerts.send_alert(
        source="bdl_api_client",
        message=f"API call failed: {e}",
        severity="ERROR",
        metadata={
            "endpoint": "box_scores",
            "retry_count": 3
        }
    )
```

**Result:**
- First occurrence: Sent to Slack immediately
- Similar errors within 1 hour: Queued for digest
- All queued errors: Sent in daily digest email

### Example 2: Critical System Failure

```python
try:
    connect_to_database()
except ConnectionError as e:
    alerts.send_alert(
        source="database_connection",
        message="Cannot connect to BigQuery",
        severity="CRITICAL",
        metadata={
            "service": "bigquery",
            "project": "nba-props-platform"
        }
    )
```

**Result:**
- Sent immediately via email AND Slack
- No rate limiting (critical always goes through)

### Example 3: Backfill with Batching

```python
from shared.utils.smart_alerting import SmartAlertManager

def backfill_season(season):
    alert_mgr = SmartAlertManager()
    alert_mgr.enable_backfill_mode()
    
    errors = []
    
    try:
        for game in get_season_games(season):
            try:
                scrape_game(game)
            except Exception as e:
                alert_mgr.record_error({
                    "game_id": game.id,
                    "date": game.date,
                    "error": str(e)
                })
                errors.append(game.id)
    finally:
        alert_mgr.disable_backfill_mode(send_summary=True)
    
    return {
        "total_games": len(get_season_games(season)),
        "errors": len(errors),
        "failed_games": errors
    }
```

**Result:**
- 82 games processed
- 15 errors occurred
- 1 summary email sent with all 15 errors grouped

### Example 4: Workflow Integration

```python
# In your workflow's error handling
try:
    scraper_result = call_scraper()
except Exception as e:
    alerts.send_alert(
        source="morning_operations_workflow",
        message=f"Scraper failed in workflow: {e}",
        severity="ERROR",
        metadata={
            "workflow": "morning-operations",
            "execution_id": execution_id,
            "scraper": "bdl_box_scores"
        }
    )
```

---

## Best Practices

### 1. Choose Appropriate Severity

```python
# ❌ BAD - Everything is CRITICAL
alerts.send_alert(..., severity="CRITICAL")  # For minor issues

# ✅ GOOD - Use appropriate levels
alerts.send_alert(..., severity="WARNING")   # Expected off-season
alerts.send_alert(..., severity="ERROR")     # Unexpected failure
alerts.send_alert(..., severity="CRITICAL")  # System down
```

### 2. Include Useful Metadata

```python
# ❌ BAD - No context
alerts.send_alert(
    source="processor",
    message="Failed",
    severity="ERROR"
)

# ✅ GOOD - Rich context
alerts.send_alert(
    source="bdl_box_scores_processor",
    message="Processing failed: Invalid JSON",
    severity="ERROR",
    metadata={
        "date": "2025-10-14",
        "game_id": "12345",
        "file_path": "gs://bucket/path/to/file.json",
        "error_type": "JSONDecodeError",
        "retry_count": 3
    }
)
```

### 3. Use Batch Mode for Bulk Operations

```python
# ❌ BAD - Individual alerts for each failure
for date in date_range:
    try:
        process(date)
    except Exception as e:
        alerts.send_alert(...)  # 100 emails!

# ✅ GOOD - Batch mode
alert_mgr = SmartAlertManager()
alert_mgr.enable_backfill_mode()

for date in date_range:
    try:
        process(date)
    except Exception as e:
        alert_mgr.record_error(...)  # Queued

alert_mgr.disable_backfill_mode(send_summary=True)  # 1 email
```

### 4. Don't Alert on Expected Conditions

```python
# ❌ BAD - Alert when no games scheduled
if not games_today:
    alerts.send_alert(
        message="No games found",
        severity="ERROR"  # This is expected!
    )

# ✅ GOOD - Only alert on unexpected conditions
if not games_today and is_regular_season():
    alerts.send_alert(
        message="No games found during regular season",
        severity="WARNING",
        metadata={"date": today, "expected_games": True}
    )
```

### 5. Test Alert System

```python
# Test with low severity first
alerts.send_alert(
    source="test_processor",
    message="Testing alert system",
    severity="INFO"  # Won't spam email
)

# Check that it appears in digest
alerts.send_digest(hours=1)
```

---

## Monitoring the Alert System

### Check Alert State

```bash
# View pending alerts
gsutil ls gs://nba-alerts/pending-alerts/

# View recent alerts
gsutil cat gs://nba-alerts/pending-alerts/2025-10-14/alerts.jsonl | jq .

# Check last sent times
gsutil cat gs://nba-alerts/alert-state/last-sent.json | jq .
```

### View Digest History

```bash
# Check digest was sent
gcloud scheduler jobs describe daily-alert-digest --location=us-west2

# View execution history
gcloud scheduler jobs list --location=us-west2 | grep digest
```

### Test Digest Manually

```python
from shared.utils.alert_aggregator import AlertAggregator

alerts = AlertAggregator()
alerts.send_digest(hours=24)
```

---

## Troubleshooting

### Problem: Not Receiving Digest Emails

**Check:**
1. Scheduler is running: `gcloud scheduler jobs list --location=us-west2`
2. Cloud Function deployed: `gcloud functions list`
3. Email configuration: Check `shared/config/alert_config.py`

**Fix:**
```bash
# Manually trigger digest
gcloud scheduler jobs run daily-alert-digest --location=us-west2
```

### Problem: Too Many Slack Messages

**Solution:** Increase rate limits in `alert_config.py`:

```python
ALERT_ROUTING = {
    "ERROR": {
        "rate_limit_minutes": 180,  # Increase from 60 to 180
    }
}
```

### Problem: Missing Critical Alerts

**Check:**
1. Severity is actually "CRITICAL"
2. Email configuration is correct
3. Check spam folder

**Debug:**
```python
# Add logging
import logging
logging.basicConfig(level=logging.DEBUG)

alerts.send_alert(..., severity="CRITICAL")
```

---

## Migration Guide

### Migrate Existing Processors

**Before:**
```python
def process_data():
    try:
        do_work()
    except Exception as e:
        send_email(f"Error: {e}")  # Direct email
```

**After:**
```python
def process_data():
    alerts = AlertAggregator()
    try:
        do_work()
    except Exception as e:
        alerts.send_alert(
            source="my_processor",
            message=str(e),
            severity="ERROR"
        )
```

### Priority Order for Migration

1. **Backfill jobs** - Biggest email generators
2. **High-frequency processors** - Run many times per day
3. **Low-frequency processors** - Run once daily
4. **Scrapers** - Last (usually fewer errors)

---

## Summary

### Key Benefits

✅ **No More Email Floods**
- 500 errors = 1 digest email
- Gmail never blocks delivery

✅ **Better Visibility**
- Grouped by severity and source
- Easy to spot patterns
- Historical tracking

✅ **Appropriate Urgency**
- Critical = Immediate
- Errors = Batched
- Warnings = Digest only

✅ **Multi-Channel**
- Slack for quick awareness
- Email for comprehensive summary
- Choose what works for you

### Quick Reference

```python
# Simple batching (backfills)
from shared.utils.smart_alerting import SmartAlertManager
alert_mgr = SmartAlertManager()
alert_mgr.enable_backfill_mode()
# ... your code ...
alert_mgr.disable_backfill_mode(send_summary=True)

# Full system (processors)
from shared.utils.alert_aggregator import AlertAggregator
alerts = AlertAggregator()
alerts.send_alert(source, message, severity, metadata)

# Daily digest (scheduled)
alerts.send_digest(hours=24)
```

---

## Related Documentation

- [Workflow Monitoring Guide](./WORKFLOW_MONITORING.md) - Daily monitoring procedures
- [Troubleshooting Guide](./TROUBLESHOOTING.md) - Common issues
- [Monitoring Tools](../monitoring/scripts/README.md) - CLI tools

---

**Questions?** Check the troubleshooting section or review example implementations in the codebase.

**Last Updated:** 2025-10-14
