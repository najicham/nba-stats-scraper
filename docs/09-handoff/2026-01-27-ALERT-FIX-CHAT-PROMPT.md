# Chat 4: Alert Flood Fix - Rate Limiting Implementation

## Copy Everything Below This Line

---

## Context

You are fixing an alert flood issue in an NBA Props Platform. The system sent **~1,000 alerts in 36 hours**, flooding Slack and email inboxes.

**Root Cause Identified**: The `notify_warning()` and `notify_info()` functions bypass rate limiting entirely. Only `notify_error()` applies rate limits.

**Your Role**: Implement rate limiting for all notification levels to prevent future floods.

---

## Current State

### Alert Volume (Jan 26-27)
| Level | Count | Rate Limited? |
|-------|-------|---------------|
| Warning | 922 | **NO** |
| Info | 79 | **NO** |
| Error | 36 | Yes |

### Top Offending Alert
```
"Analytics Processor No Data Extracted: PlayerGameSummaryProcessor"
  → 831 alerts sent to Slack (one every ~2-3 seconds)
```

---

## Your Tasks

### Task 1: Apply Rate Limiting to `notify_warning()` (CRITICAL)

**File**: `shared/utils/notification_system.py`

**Current Code** (lines 760-769):
```python
def notify_warning(title: str, message: str, details: Dict = None):
    """Quick function to send warning notification."""
    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.WARNING,
        notification_type=NotificationType.CUSTOM,
        title=title,
        message=message,
        details=details
    )
```

**Required Change**: Add rate limiting similar to `notify_error()` (lines 696-758).

The new function should:
1. Accept `processor_name` parameter (default: "NBA Platform")
2. Check rate limit via `AlertManager.should_send()`
3. Return `None` if rate limited (instead of sending)
4. Handle aggregation metadata for summary alerts
5. Log when rate limited

### Task 2: Apply Rate Limiting to `notify_info()` (CRITICAL)

**File**: `shared/utils/notification_system.py`

**Current Code** (lines 772-781):
```python
def notify_info(title: str, message: str, details: Dict = None):
    """Quick function to send info notification."""
    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.INFO,
        notification_type=NotificationType.CUSTOM,
        title=title,
        message=message,
        details=details
    )
```

**Required Change**: Same pattern as Task 1.

### Task 3: Update Callers to Pass processor_name (IMPORTANT)

Search for all callers of `notify_warning()` and `notify_info()` and update them to pass the `processor_name` parameter.

```bash
grep -rn "notify_warning\|notify_info" data_processors/ shared/ --include="*.py"
```

Key files to check:
- `data_processors/analytics/analytics_base.py` (line 884-885)
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- Any other processors using these functions

### Task 4: Add Rate Limit Configuration for Warnings/Info (OPTIONAL)

Consider different rate limits per level:
- Errors: 5 per hour (current)
- Warnings: 3 per hour (more aggressive)
- Info: 2 per hour (most aggressive)

This can be done by extending `RateLimitConfig` in `shared/alerts/rate_limiter.py`.

---

## Reference: How notify_error() Does It

Use `notify_error()` (lines 696-758) as a template:

```python
def notify_error(title: str, message: str, details: Dict = None, processor_name: str = "NBA Platform", backfill_mode: bool = False):
    """
    Quick function to send error notification with rate limiting.
    """
    error_type = 'error'
    if details and 'error_type' in details:
        error_type = details['error_type']

    # ALWAYS apply rate limiting
    if ALERT_MANAGER_AVAILABLE:
        alert_mgr = get_alert_manager(backfill_mode=backfill_mode)
        should_send, metadata = alert_mgr.should_send(processor_name, error_type, message)

        if not should_send:
            logger.info(f"Rate limited notification: {processor_name}/{error_type}")
            return None

        # Modify title/message if this is an aggregated summary
        if metadata and metadata.get('is_summary'):
            count = metadata.get('occurrence_count', 0)
            title = f"[AGGREGATED x{count}] {title}"
            # ... add aggregation details

    router = _get_router()
    return router.send_notification(...)
```

---

## Files to Read First

1. **Current notification system**:
   ```bash
   cat shared/utils/notification_system.py
   ```

2. **Rate limiter implementation**:
   ```bash
   cat shared/alerts/rate_limiter.py
   ```

3. **Investigation document**:
   ```bash
   cat docs/09-handoff/2026-01-27-ALERT-FLOOD-INVESTIGATION.md
   ```

4. **Example caller (analytics_base)**:
   ```bash
   grep -n "notify_warning\|notify_info" data_processors/analytics/analytics_base.py
   ```

---

## Implementation Pattern

Here's the pattern to follow for both `notify_warning` and `notify_info`:

```python
def notify_warning(
    title: str,
    message: str,
    details: Dict = None,
    processor_name: str = "NBA Platform"
):
    """
    Send warning notification with rate limiting.

    Rate limiting prevents notification floods.
    Default: Max 5 warnings per hour per unique signature.

    Args:
        title: Alert title
        message: Alert message
        details: Additional context
        processor_name: Name of processor sending alert (for rate limit signature)

    Returns:
        Dict with channel success status, or None if rate limited
    """
    error_type = 'warning'

    # Apply rate limiting
    if ALERT_MANAGER_AVAILABLE:
        alert_mgr = get_alert_manager()
        should_send, metadata = alert_mgr.should_send(processor_name, error_type, message)

        if not should_send:
            logger.info(
                f"Rate limited warning notification: {processor_name}/{error_type} "
                f"(check logs for rate limit stats)"
            )
            return None

        # Modify title if this is an aggregated summary
        if metadata and metadata.get('is_summary'):
            count = metadata.get('occurrence_count', 0)
            suppressed = metadata.get('suppressed_count', 0)
            title = f"[AGGREGATED x{count}] {title}"

            if details is None:
                details = {}
            details['_aggregated'] = True
            details['_occurrence_count'] = count
            details['_suppressed_count'] = suppressed

    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.WARNING,
        notification_type=NotificationType.CUSTOM,
        title=title,
        message=message,
        details=details,
        processor_name=processor_name
    )
```

---

## Testing

### Unit Test
```python
# tests/unit/utils/test_notification_system.py

def test_notify_warning_rate_limited():
    """Test that notify_warning respects rate limits."""
    from shared.utils.notification_system import notify_warning
    from shared.alerts import reset_alert_manager

    reset_alert_manager()

    # First 5 should send
    for i in range(5):
        result = notify_warning(
            title="Test Warning",
            message="Test message",
            processor_name="TestProcessor"
        )
        assert result is not None, f"Alert {i+1} should have sent"

    # 6th should be rate limited
    result = notify_warning(
        title="Test Warning",
        message="Test message",
        processor_name="TestProcessor"
    )
    assert result is None, "6th alert should be rate limited"
```

### Integration Test
After deploying, monitor logs:
```bash
# Should see rate limiting kick in
gcloud logging read 'textPayload:"Rate limited warning"' \
  --project=nba-props-platform --limit=20

# Alert volume should drop dramatically
gcloud logging read 'timestamp>="2026-01-28T00:00:00Z" AND textPayload:"Sending warning"' \
  --project=nba-props-platform --format=json | jq length
```

---

## Deployment

After making changes:

```bash
# Run tests
pytest tests/unit/utils/test_notification_system.py -v

# Deploy (if tests pass)
# The notification_system.py is in shared/, used by all services
# Deploying any service will pick up the change

# For immediate effect, deploy analytics processors:
gcloud run deploy nba-phase3-analytics-processors \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform
```

---

## Success Criteria

After your fix:

- [ ] `notify_warning()` applies rate limiting (max 5 per hour per signature)
- [ ] `notify_info()` applies rate limiting (max 5 per hour per signature)
- [ ] Both functions accept `processor_name` parameter
- [ ] Callers in analytics_base.py pass processor_name
- [ ] Unit tests pass
- [ ] Logs show "Rate limited warning" when appropriate
- [ ] Alert volume drops from ~1000/day to <50/day

---

## Handoff Notes

When complete, create:
`docs/09-handoff/2026-01-27-ALERT-FIX-COMPLETE.md`

Include:
- Changes made (files + line numbers)
- Test results
- Deployment status
- Before/after alert counts (if available)

---

## Bonus: Persistent Rate Limiting (Optional - If Time Permits)

The current rate limiter uses in-memory state, which resets when Cloud Run instances terminate. For a more robust solution, consider migrating to Firestore-based rate limiting.

See `docs/09-handoff/2026-01-27-ALERT-FLOOD-INVESTIGATION.md` for the Firestore implementation pattern.

This is optional for this session - the in-memory rate limiting will provide significant improvement, and Firestore migration can be done in a future session.

---

**END OF CHAT 4 PROMPT**
