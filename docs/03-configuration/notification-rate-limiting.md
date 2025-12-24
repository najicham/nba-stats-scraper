# Notification Rate Limiting

Prevents email floods by limiting notifications per error type.

## Problem Solved

On Dec 24, 2025, a single bug caused **600+ error emails** in 18 hours. Each schedule processor failure triggered an email, and with 30-minute scraper intervals plus Pub/Sub retries, the inbox was flooded.

## Solution

Rate limiting is now applied to ALL `notify_error()` calls:

```
Error #1: SENT (first occurrence)
Error #2: SENT 
Error #3: SENT [AGGREGATED] (summary with count)
Error #4: SENT
Error #5: SENT (rate limit)
Error #6-N: SUPPRESSED (logged but not emailed)
```

After 60 minutes cooldown, the counter resets.

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTIFICATION_RATE_LIMIT_PER_HOUR` | 5 | Max emails per hour per error signature |
| `NOTIFICATION_COOLDOWN_MINUTES` | 60 | Minutes before resetting count |
| `NOTIFICATION_AGGREGATE_THRESHOLD` | 3 | Send summary after N occurrences |
| `NOTIFICATION_RATE_LIMITING_ENABLED` | true | Enable/disable rate limiting |

## Error Signature

Errors are grouped by signature = hash of:
- Processor name (e.g., "NbacScheduleProcessor")
- Error type (e.g., "TypeError")
- First 100 chars of message

Same signature = same rate limit bucket.

## Usage

Rate limiting is automatic - no code changes needed:

```python
from shared.utils.notification_system import notify_error

# This is automatically rate limited
notify_error(
    title="Processor Failed",
    message="Some error",
    details={'error_type': 'TypeError'},
    processor_name="MyProcessor"
)
```

For backfill mode (more aggressive limiting):

```python
notify_error(..., backfill_mode=True)
# Uses 1 email/hour instead of 5
```

## Monitoring

Rate limit stats are logged:

```
INFO: Rate limited notification: NbacScheduleProcessor/TypeError (check logs for rate limit stats)
WARNING: Rate limit exceeded for abc123..., suppressed 50 alerts (total occurrences: 100)
```

## Files

- `shared/alerts/__init__.py` - Module entry point
- `shared/alerts/rate_limiter.py` - Core rate limiting logic
- `shared/utils/notification_system.py` - Integration point

## Testing

```bash
PYTHONPATH=. .venv/bin/python -c "
from shared.alerts import AlertManager, RateLimitConfig

config = RateLimitConfig(rate_limit_per_hour=3)
mgr = AlertManager(config)

for i in range(10):
    should_send, _ = mgr.should_send('TestProcessor', 'TestError', 'test')
    print(f'{i+1}: {\"SEND\" if should_send else \"SUPPRESSED\"}')

print(mgr.get_stats())
"
```
