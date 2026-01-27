# Alert Flood Investigation - January 27, 2026

**Investigator**: Claude Opus
**Date**: January 27, 2026
**Status**: ROOT CAUSE IDENTIFIED - FIX NEEDED

---

## Executive Summary

The system sent **~1,000+ alerts** over ~36 hours (Jan 26-27), flooding Slack and email. The root cause is that **`notify_warning()` and `notify_info()` bypass rate limiting entirely**, while only `notify_error()` applies rate limits.

**Alert Breakdown (Jan 26-27):**
| Level | Count | Rate Limited? |
|-------|-------|---------------|
| Warning | 922 | **NO** |
| Info | 79 | **NO** |
| Error | 36 | Yes |
| **Total** | **1,037** | - |

---

## Root Cause Analysis

### Primary Issue: Rate Limiting Not Applied to Warnings/Info

**File**: `shared/utils/notification_system.py`

```python
# Lines 696-758: notify_error() - HAS rate limiting
def notify_error(title: str, message: str, details: Dict = None, ...):
    # ... applies rate limiting via AlertManager
    if ALERT_MANAGER_AVAILABLE:
        alert_mgr = get_alert_manager(backfill_mode=backfill_mode)
        should_send, metadata = alert_mgr.should_send(processor_name, error_type, message)
        if not should_send:
            return None  # Rate limited
    # ... then sends notification

# Lines 760-769: notify_warning() - NO rate limiting
def notify_warning(title: str, message: str, details: Dict = None):
    """Quick function to send warning notification."""
    router = _get_router()
    return router.send_notification(...)  # Sends EVERY time

# Lines 772-781: notify_info() - NO rate limiting
def notify_info(title: str, message: str, details: Dict = None):
    """Quick function to send info notification."""
    router = _get_router()
    return router.send_notification(...)  # Sends EVERY time
```

### Secondary Issue: In-Memory Rate Limiter State Lost

**File**: `shared/alerts/rate_limiter.py`

The `AlertManager` uses an in-memory dictionary to track alert state:
```python
class AlertManager:
    def __init__(self, ...):
        self._error_states: Dict[str, ErrorState] = {}  # IN-MEMORY
```

**Problem**: Cloud Run instances are ephemeral:
1. Instance starts → empty rate limiter state
2. Instance sends 5 alerts (rate limit per hour)
3. Instance scales to zero → state lost
4. New instance starts → rate limit resets
5. Repeat → floods

### Triggering Alerts

**Top Alert by Volume:**
```
"Analytics Processor No Data Extracted: PlayerGameSummaryProcessor"
  → 831 alerts to Slack (one every ~2-3 seconds)
```

**Source**: `data_processors/analytics/analytics_base.py:884-897`
```python
def validate_extracted_data(self) -> None:
    if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
        self._send_notification(
            notify_warning,  # ← Uses notify_warning (NO rate limiting!)
            title=f"Analytics Processor No Data Extracted: {self.__class__.__name__}",
            ...
        )
        raise ValueError("No data extracted")
```

This fires every time:
- PlayerGameSummaryProcessor runs for a date with no raw data
- The processor retries after failure
- Each retry triggers another alert

---

## Alert Distribution by Type

### Slack Alerts (Since Jan 26)
| Alert | Count | Root Cause |
|-------|-------|------------|
| No Data Extracted: PlayerGameSummaryProcessor | 831 | Processor retrying constantly |
| No Data to Save: TeamOffenseGameSummaryProcessor | 10 | Same issue |
| Analytics Processor Failed: PlayerGameSummaryProcessor | 25 | Actual failures |
| **Total Slack** | **~866** | - |

### Email Alerts (Since Jan 26)
| Alert | Count | Root Cause |
|-------|-------|------------|
| Phase 1→2 Boundary Validation Warning | 38 | Normal monitoring |
| ESPN Roster API Scraped Successfully | 30 | INFO level (success) |
| Phase 1 Cleanup: Multiple Files Republished | 25 | Normal cleanup |
| Player Game Summary: Complete | 25 | INFO level (success) |
| GetNbaComGamebookPdf: Zero Rows Scraped | 14 | Expected (no games) |
| **Total Email** | **~170** | - |

---

## Rate Limiter Log Evidence

The rate limiter IS working for errors, but only on individual instances:
```
Rate limit exceeded for ae4cf8c3fb27f06a..., suppressed 220 alerts (total occurrences: 225)
Rate limit exceeded for ae4cf8c3fb27f06a..., suppressed 210 alerts (total occurrences: 215)
Rate limit exceeded for f69baebf3bdbd62b..., suppressed 180 alerts (total occurrences: 185)
```

These suppressions happened **per-instance**. When instances terminated, the counts reset.

---

## Impact Assessment

### Quantified Impact
- **Slack**: 866 messages to `#warning-alerts` channel in 36 hours
- **Email**: ~170 emails (to configured recipients)
- **User Experience**: Inbox flooded, alert fatigue, important alerts buried

### Business Impact
- Critical alerts may be missed due to noise
- Team loses confidence in alerting system
- Slack channel becomes unusable

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Current Alert Flow                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Processor Error                                                │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────┐                                           │
│  │ notify_error()  │──► AlertManager ──► Rate Limited ──► Send │
│  └─────────────────┘         │                                  │
│                              │                                  │
│       OR                     │ IN-MEMORY                        │
│       │                      │ (lost on scale-to-zero)          │
│       ▼                      │                                  │
│  ┌──────────────────┐        │                                  │
│  │ notify_warning() │────────┼────► DIRECTLY SENT (no limit!)  │
│  └──────────────────┘        │                                  │
│                              │                                  │
│       OR                     │                                  │
│       │                      │                                  │
│       ▼                      │                                  │
│  ┌─────────────────┐         │                                  │
│  │ notify_info()   │─────────┼────► DIRECTLY SENT (no limit!)  │
│  └─────────────────┘         │                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Recommended Fixes

### Fix 1: Apply Rate Limiting to All Notification Levels (HIGH PRIORITY)

Modify `notify_warning()` and `notify_info()` to use rate limiting like `notify_error()`.

**File**: `shared/utils/notification_system.py`

```python
def notify_warning(title: str, message: str, details: Dict = None, processor_name: str = "NBA Platform"):
    """Quick function to send warning notification WITH rate limiting."""
    # Apply rate limiting
    if ALERT_MANAGER_AVAILABLE:
        error_type = 'warning'
        alert_mgr = get_alert_manager()
        should_send, metadata = alert_mgr.should_send(processor_name, error_type, message)

        if not should_send:
            logger.info(f"Rate limited warning: {processor_name}/{error_type}")
            return None

        # Handle aggregation
        if metadata and metadata.get('is_summary'):
            title = f"[AGGREGATED x{metadata['occurrence_count']}] {title}"

    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.WARNING,
        notification_type=NotificationType.CUSTOM,
        title=title,
        message=message,
        details=details
    )
```

### Fix 2: Persistent Rate Limiter State (MEDIUM PRIORITY)

Replace in-memory state with Firestore for cross-instance persistence.

**New File**: `shared/alerts/firestore_rate_limiter.py`

```python
from google.cloud import firestore
from datetime import datetime, timedelta

class FirestoreRateLimiter:
    """Persistent rate limiting using Firestore."""

    def __init__(self, collection_name: str = 'alert_rate_limits'):
        self.db = firestore.Client()
        self.collection = self.db.collection(collection_name)
        self.rate_limit_per_hour = 5
        self.cooldown_minutes = 60

    def should_send(self, signature: str) -> tuple[bool, dict]:
        """Check if alert should be sent, with persistent state."""
        doc_ref = self.collection.document(signature[:50])  # Firestore doc ID limit
        doc = doc_ref.get()

        now = datetime.utcnow()

        if not doc.exists:
            # First occurrence - create and allow
            doc_ref.set({
                'first_seen': now,
                'last_seen': now,
                'count': 1,
                'alerts_sent': 1,
                'last_alert_time': now
            })
            return True, None

        data = doc.to_dict()

        # Check if cooldown expired (reset)
        last_seen = data['last_seen']
        if isinstance(last_seen, datetime):
            if now - last_seen > timedelta(minutes=self.cooldown_minutes):
                # Reset state
                doc_ref.set({
                    'first_seen': now,
                    'last_seen': now,
                    'count': 1,
                    'alerts_sent': 1,
                    'last_alert_time': now
                })
                return True, None

        # Update count
        new_count = data.get('count', 0) + 1
        alerts_sent = data.get('alerts_sent', 0)

        # Check rate limit
        if alerts_sent < self.rate_limit_per_hour:
            doc_ref.update({
                'last_seen': now,
                'count': new_count,
                'alerts_sent': alerts_sent + 1,
                'last_alert_time': now
            })
            return True, {'occurrence_count': new_count} if new_count >= 3 else None

        # Rate limited
        doc_ref.update({
            'last_seen': now,
            'count': new_count
        })
        return False, None
```

### Fix 3: Reduce Alert Noise at Source (LOW PRIORITY)

The "No Data Extracted" alert is often expected (no games on that date). Consider:

1. **Downgrade to DEBUG level** when expected (no games scheduled)
2. **Add context checking** - don't alert if no games were scheduled
3. **Use a separate channel** for routine/expected warnings

**Example change in `analytics_base.py`:**
```python
def validate_extracted_data(self) -> None:
    if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
        # Check if this is expected (no games scheduled)
        if self._is_no_games_expected():
            logger.info(f"No data expected for {self.opts.get('start_date')} (no games)")
            raise ValueError("No data extracted")  # Still raise, but don't alert

        # Only alert if unexpected
        self._send_notification(...)
```

### Fix 4: Add Alert Digest (NICE TO HAVE)

Instead of individual alerts, send hourly/daily digests:
- Aggregate all alerts of same type
- Send one summary email/Slack message
- Include counts and first/last occurrence times

---

## Implementation Priority

| Fix | Priority | Effort | Impact |
|-----|----------|--------|--------|
| Apply rate limiting to warning/info | **HIGH** | 1-2 hours | Immediate flood reduction |
| Persistent rate limiter (Firestore) | MEDIUM | 2-4 hours | Cross-instance consistency |
| Context-aware alerting | LOW | 4-6 hours | Reduces noise at source |
| Alert digest system | NICE | 8+ hours | Better UX for monitoring |

---

## Verification After Fix

### Check Rate Limiting Applied
```bash
gcloud logging read 'textPayload:"Rate limited warning"' \
  --project=nba-props-platform --limit=20
```

### Check Alert Volume Reduced
```bash
gcloud logging read 'timestamp>="2026-01-28T00:00:00Z" AND textPayload:"Sending warning"' \
  --project=nba-props-platform --format=json | jq length
```

Expected: <50 per day (down from 900+)

### Monitor Slack Channel
- `#warning-alerts` should have <10 messages per hour
- No more rapid-fire duplicate alerts

---

## Files to Modify

1. **`shared/utils/notification_system.py`**
   - Add rate limiting to `notify_warning()` (line 760)
   - Add rate limiting to `notify_info()` (line 772)
   - Update function signatures to include `processor_name`

2. **`shared/alerts/rate_limiter.py`** (optional)
   - Add Firestore backend option
   - Add `should_send_warning()` and `should_send_info()` functions

3. **`data_processors/analytics/analytics_base.py`** (optional)
   - Add context checking before alerting
   - Pass processor_name to notify_warning

---

## Related Documentation

- Rate Limiter Design: `shared/alerts/rate_limiter.py` (lines 1-60)
- Notification System: `shared/utils/notification_system.py`
- Alert Types: `shared/utils/alert_types.py`

---

**Investigation Complete**: 2026-01-27
**Ready for Implementation**: Yes
**Estimated Fix Time**: 2-4 hours
