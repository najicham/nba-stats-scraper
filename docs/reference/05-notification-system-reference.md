# NBA Notification System Reference

**Created:** 2025-11-21 17:35:00 PST
**Last Updated:** 2025-11-21 17:35:00 PST

Quick reference for integrating multi-channel notifications (Email + Slack) into processors and scrapers.

## Overview

**Purpose:** Multi-channel alerting for processor errors, warnings, and status updates

**Channels:**
- Email (Brevo SMTP) - INFO, WARNING, ERROR, CRITICAL
- Slack (Webhooks) - WARNING, ERROR, CRITICAL
- Console (Logging) - Fallback

**Key Features:**
- Extensible multi-tier Slack routing (level-specific webhooks)
- Singleton pattern (efficient reuse)
- Error protection (never crashes processor)
- HTML escaping (security)
- Automatic fallback to console logging

## Quick Start

### Basic Integration

```python
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class MyProcessor:
    def process_data(self):
        try:
            # Process data
            result = self._do_work()

            # Success notification
            try:
                notify_info(
                    title="Processing Complete",
                    message=f"Processed {len(result)} records",
                    details={'count': len(result)}
                )
            except Exception as e:
                logger.warning(f"Notification failed: {e}")

        except Exception as e:
            # Error notification
            try:
                notify_error(
                    title="Processing Failed",
                    message=f"Error: {str(e)}",
                    details={
                        'error_type': type(e).__name__,
                        'processor': 'MyProcessor'
                    },
                    processor_name="MyProcessor"
                )
            except Exception as notify_ex:
                logger.warning(f"Notification failed: {notify_ex}")
            raise
```

## Notification Levels

### INFO (Email Only)

```python
notify_info(
    title="Daily Summary",
    message="Processed 1,000 games successfully",
    details={'games': 1000, 'duration_seconds': 45}
)
```

**Routes to:** Email recipients (`EMAIL_ALERTS_TO`)

**Use for:** Daily summaries, successful completions, new discoveries

### WARNING (Slack Only by Default)

```python
notify_warning(
    title="High Unresolved Player Count",
    message="50+ unresolved players detected",
    details={'count': 52, 'threshold': 50}
)
```

**Routes to:** Slack webhook (level-specific or default)

**Use for:** Performance issues, data quality warnings, threshold breaches

### ERROR (Both Channels)

```python
notify_error(
    title="Processing Failed",
    message=f"Database operation failed: {error}",
    details={
        'error_type': type(e).__name__,
        'records_attempted': 100,
        'processor': 'MyProcessor'
    },
    processor_name="MyProcessor"
)
```

**Routes to:** Email (`EMAIL_CRITICAL_TO`) + Slack (error webhook)

**Use for:** Processing failures, database errors, data loss

### CRITICAL (Both Channels)

```python
notify_critical(
    title="System Failure",
    message="Cannot connect to BigQuery",
    details={'error': str(e), 'retries': 3},
    processor_name="MyProcessor"
)
```

**Routes to:** Email (`EMAIL_CRITICAL_TO`) + Slack (critical webhook)

**Use for:** System-wide failures, requires immediate action

## Environment Variables

### Required for Email

```bash
# SMTP Configuration
BREVO_SMTP_HOST=smtp-relay.brevo.com
BREVO_SMTP_PORT=587
BREVO_SMTP_USERNAME=your_username@smtp-brevo.com
BREVO_SMTP_PASSWORD=your_password
BREVO_FROM_EMAIL=alert@yourdomain.com
BREVO_FROM_NAME="NBA Platform"

# Email Recipients
EMAIL_ALERTS_ENABLED=true
EMAIL_ALERTS_TO=team@example.com,dev@example.com
EMAIL_CRITICAL_TO=oncall@example.com
```

### Required for Slack

```bash
# Slack Configuration (Extensible)
SLACK_ALERTS_ENABLED=true

# Default webhook (fallback for all levels)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Level-specific webhooks (optional, override default)
SLACK_WEBHOOK_URL_INFO=https://hooks.slack.com/services/.../info
SLACK_WEBHOOK_URL_WARNING=https://hooks.slack.com/services/.../warnings
SLACK_WEBHOOK_URL_ERROR=https://hooks.slack.com/services/.../errors
SLACK_WEBHOOK_URL_CRITICAL=https://hooks.slack.com/services/.../critical
```

**Note:** Level-specific webhooks override the default. If `SLACK_WEBHOOK_URL_ERROR` is set, ERROR notifications use that instead of `SLACK_WEBHOOK_URL`.

### Optional Thresholds

```bash
EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=50
EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=90.0
EMAIL_ALERT_MAX_PROCESSING_TIME=30
```

## Common Patterns

### Pattern 1: Critical Error Handling

**Use:** Processing failures, database errors

```python
def process_data(self):
    try:
        data = self._extract_data()
        self._save_to_bigquery(data)

    except Exception as e:
        logger.error(f"Processing failed: {e}")

        try:
            notify_error(
                title="Processor Failed",
                message=f"Processing failed: {str(e)}",
                details={
                    'processor': self.__class__.__name__,
                    'error_type': type(e).__name__,
                    'records_attempted': len(data) if data else 0,
                    'run_id': self.run_id
                },
                processor_name="MyProcessor"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

        raise  # Re-raise for proper error handling
```

### Pattern 2: Warning on Threshold Breach

**Use:** Data quality issues, performance degradation

```python
def check_data_quality(self, records):
    invalid_count = sum(1 for r in records if not r.is_valid())

    if invalid_count > 100:
        try:
            notify_warning(
                title="High Invalid Record Count",
                message=f"{invalid_count} invalid records detected",
                details={
                    'invalid_count': invalid_count,
                    'total_records': len(records),
                    'invalid_pct': (invalid_count / len(records)) * 100,
                    'processor': self.__class__.__name__
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
```

### Pattern 3: Success Summary

**Use:** Daily summaries, batch completions

```python
def finalize(self):
    """Send completion notification."""
    try:
        notify_info(
            title="Processing Complete",
            message=f"Successfully processed {self.stats['rows_processed']} rows",
            details={
                'rows_processed': self.stats['rows_processed'],
                'rows_skipped': self.stats.get('rows_skipped', 0),
                'duration_seconds': self.stats['total_runtime'],
                'processor': self.__class__.__name__,
                'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}"
            }
        )
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")
```

### Pattern 4: Conditional Notifications

**Use:** Only notify when thresholds exceeded

```python
def check_unresolved_players(self):
    unresolved_count = len(self.registry.get_unresolved_players())
    threshold = 50

    if unresolved_count > threshold:
        try:
            notify_warning(
                title="High Unresolved Player Count",
                message=f"{unresolved_count} unresolved players (threshold: {threshold})",
                details={
                    'count': unresolved_count,
                    'threshold': threshold,
                    'processor': self.__class__.__name__
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
```

## API Reference

### notify_info()

```python
notify_info(
    title: str,                    # Email subject / Slack title
    message: str,                  # Main message content
    details: Dict[str, Any] = None, # Structured details
    processor_name: str = None     # Processor display name
) -> bool
```

**Returns:** `True` if notification sent, `False` if failed

### notify_warning()

```python
notify_warning(
    title: str,
    message: str,
    details: Dict[str, Any] = None,
    processor_name: str = None
) -> bool
```

### notify_error()

```python
notify_error(
    title: str,
    message: str,
    details: Dict[str, Any] = None,
    processor_name: str = None
) -> bool
```

### notify_critical()

```python
notify_critical(
    title: str,
    message: str,
    details: Dict[str, Any] = None,
    processor_name: str = None
) -> bool
```

## Best Practices

### ✅ DO

**Always wrap in try/except:**
```python
try:
    notify_error(...)
except Exception as e:
    logger.warning(f"Notification failed: {e}")
```

**Include useful context:**
```python
notify_error(
    title="Processing Failed",
    message=str(e),
    details={
        'processor': self.__class__.__name__,
        'error_type': type(e).__name__,
        'run_id': self.run_id,
        'date_range': f"{start} to {end}",
        'records_attempted': count
    }
)
```

**Use appropriate levels:**
- INFO: Summaries, successes
- WARNING: Threshold breaches, quality issues
- ERROR: Processing failures
- CRITICAL: System-wide failures

### ❌ DON'T

**Don't let notifications crash processor:**
```python
# Bad - no error handling
notify_error(title, message)

# Good - wrapped
try:
    notify_error(title, message)
except Exception as e:
    logger.warning(f"Notification failed: {e}")
```

**Don't over-notify:**
```python
# Bad - notify for every record
for record in records:
    notify_info(f"Processed {record.id}")

# Good - batch summary
notify_info(f"Processed {len(records)} records")
```

**Don't include sensitive data:**
```python
# Bad - credentials in notification
notify_error(message, details={'password': pw})

# Good - sanitized details
notify_error(message, details={'error': 'Auth failed'})
```

## Slack Webhook Configuration

### Adding New Channels

**No code changes needed** - just add environment variables:

```bash
# Example: Route INFO to #nba-daily-summaries
export SLACK_WEBHOOK_URL_INFO=https://hooks.slack.com/services/.../summaries

# Example: Route CRITICAL to #nba-on-call
export SLACK_WEBHOOK_URL_CRITICAL=https://hooks.slack.com/services/.../oncall
```

### Webhook Priority

1. Level-specific webhook (`SLACK_WEBHOOK_URL_ERROR`)
2. Default webhook (`SLACK_WEBHOOK_URL`)
3. Console logging (if both missing)

### Current Routing

```
INFO      → Email only (no Slack by default)
WARNING   → SLACK_WEBHOOK_URL_WARNING → SLACK_WEBHOOK_URL → console
ERROR     → SLACK_WEBHOOK_URL_ERROR → SLACK_WEBHOOK_URL → console
          + EMAIL_CRITICAL_TO
CRITICAL  → SLACK_WEBHOOK_URL_CRITICAL → SLACK_WEBHOOK_URL → console
          + EMAIL_CRITICAL_TO
```

## Deployment

### Cloud Run Configuration

All deployment scripts should include notification environment variables:

```bash
#!/bin/bash
# Load environment
set -a
source .env
set +a

# Build env vars array
ENV_VARS=()

# Email
ENV_VARS+=("BREVO_SMTP_HOST=${BREVO_SMTP_HOST}")
ENV_VARS+=("BREVO_SMTP_PORT=${BREVO_SMTP_PORT}")
ENV_VARS+=("BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}")
ENV_VARS+=("BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}")
ENV_VARS+=("BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}")
ENV_VARS+=("BREVO_FROM_NAME=${BREVO_FROM_NAME}")
ENV_VARS+=("EMAIL_ALERTS_ENABLED=${EMAIL_ALERTS_ENABLED:-true}")
ENV_VARS+=("EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}")
ENV_VARS+=("EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO}")

# Slack
ENV_VARS+=("SLACK_ALERTS_ENABLED=${SLACK_ALERTS_ENABLED:-false}")
ENV_VARS+=("SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}")
ENV_VARS+=("SLACK_WEBHOOK_URL_ERROR=${SLACK_WEBHOOK_URL_ERROR}")
ENV_VARS+=("SLACK_WEBHOOK_URL_CRITICAL=${SLACK_WEBHOOK_URL_CRITICAL}")

# Deploy
gcloud run jobs update ${JOB_NAME} \
  --region=${REGION} \
  --set-env-vars="$(IFS=,; echo "${ENV_VARS[*]}")"
```

## Troubleshooting

### Notifications Not Sending

**Check environment variables:**
```bash
# View Cloud Run config
gcloud run jobs describe JOB_NAME --region=us-west2 \
  --format="value(template.template.containers[0].env)"
```

**Check logs:**
```bash
gcloud beta run jobs executions logs read EXECUTION_ID \
  --region=us-west2 | grep -i "notification"
```

**Common issues:**
- Missing env vars in deployment script
- `.env` file not loaded
- SMTP credentials incorrect
- Slack webhook URLs incorrect

### Wrong Channel Routing

**Verify webhook configuration:**
```bash
echo "Default: $SLACK_WEBHOOK_URL"
echo "Error: $SLACK_WEBHOOK_URL_ERROR"
echo "Critical: $SLACK_WEBHOOK_URL_CRITICAL"
```

**Check routing logic:**
- INFO → Email only (unless `SLACK_WEBHOOK_URL_INFO` set)
- WARNING → Slack (level webhook → default → console)
- ERROR/CRITICAL → Both channels

### Handler Initialization Failed

**Symptoms:** Warnings in logs about failed handler initialization

**Common causes:**
- Missing SMTP credentials
- Invalid Slack webhook URLs
- Network connectivity issues

**System behavior:** Disables failed channel, continues with others

## System Resilience

### Singleton Pattern

- Reuses NotificationRouter instance across all calls
- Efficient connection pooling for SMTP and webhooks
- No performance impact from multiple notifications

### Error Protection

- All handler initialization wrapped in try/except
- Failed handler initialization disables that channel gracefully
- Null checks before all handler method calls
- Never crashes processor even if notifications completely fail

### Security

- All user-provided content automatically HTML-escaped
- Prevents HTML injection attacks in email/Slack messages
- Timeouts on all network operations (10 seconds)

### Fallback Behavior

- Missing handlers → Console logging
- Missing level-specific webhook → Default webhook
- Missing default webhook → Console logging
- Email failures → Logged, not raised

## Files

**Notification System:**
- `shared/utils/notification_system.py` - Core routing logic
- `shared/utils/email_alerting.py` - Email implementation

**Example Integrations:**
- `data_processors/analytics/analytics_base.py` - Base class integration
- `data_processors/reference/player_reference/gamebook_registry_processor.py`

**Deployment Scripts:**
- `bin/raw/deploy/deploy_processors_simple.sh`
- `bin/analytics/deploy/deploy_analytics_processors.sh`
- `bin/reference/deploy/deploy_reference_processor_backfill.sh`

## See Also

- [Analytics Processors Reference](03-analytics-processors-reference.md)
- [Processors Reference](02-processors-reference.md)
