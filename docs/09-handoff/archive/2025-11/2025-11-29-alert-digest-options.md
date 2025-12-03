# Alert Digest Options for Backfill

After implementing alert suppression, you have **3 options** for handling backfill notifications:

---

## Option 1: Complete Silence (Current)

**What happens:**
- No emails during backfill ✅
- No summary email at end ❌

**Code:**
```python
# Your current backfill script
processor.run({
    'date': '2022-02-20',
    'skip_downstream_trigger': True
})
# ... nothing else needed
```

**Pros:**
- ✅ Simple - no code changes needed
- ✅ Zero email spam
- ✅ Logs still capture everything

**Cons:**
- ❌ No confirmation that backfill completed
- ❌ No visibility into error patterns
- ❌ Can't tell if backfill succeeded or silently failed

**Best for:** Small backfills where you're watching logs live

---

## Option 2: Manual Digest (You Call It) ⭐ **RECOMMENDED**

**What happens:**
- No emails during backfill ✅
- ONE summary email at end ✅
- Full control over when/what to send ✅

**Code:**
```python
from shared.alerts import get_alert_manager

def run_backfill(start_date, end_date):
    # Initialize alert manager (singleton)
    alert_mgr = get_alert_manager(backfill_mode=True)

    print("Starting backfill with alert suppression...")

    # Run your backfill
    for date in date_range(start_date, end_date):
        processor.run({
            'date': str(date),
            'skip_downstream_trigger': True
        })

    # SEND DIGEST EMAIL
    print("Sending summary email...")
    alert_mgr.flush_batched_alerts()

    # Optional: Get stats
    stats = alert_mgr.get_alert_stats()
    print(f"Batched alerts sent: {len(stats['batched_alerts'])}")
```

**Digest email will contain:**
```
📊 Batched Alerts Summary

Category: NbacPlayerBoxscoreProcessor_FileNotFoundError
Suppressed: 150 similar alerts

Sample contexts:
  - {'date': '2022-02-20', 'error_type': 'FileNotFoundError', ...}
  - {'date': '2022-03-15', 'error_type': 'FileNotFoundError', ...}
  - {'date': '2022-04-10', 'error_type': 'FileNotFoundError', ...}

Category: BdlPlayersProcessor_DataValidationError
Suppressed: 30 similar alerts

Sample contexts:
  - {'date': '2022-05-01', 'error_type': 'DataValidationError', ...}
  ...
```

**Pros:**
- ✅ You know backfill completed
- ✅ See error breakdown by category
- ✅ Identify patterns (e.g., "all FileNotFoundError before March 2022")
- ✅ Control exactly when digest is sent
- ✅ Can add custom summary info

**Cons:**
- ⚠️ Requires adding 2 lines to your backfill script

**Best for:** Production backfills, scheduled jobs, unattended runs

---

## Option 3: Auto-Digest Context Manager (NEW!)

**What happens:**
- No emails during backfill ✅
- ONE summary email at end (automatic) ✅
- Python context manager handles it ✅

**Code:**
```python
from shared.alerts import get_alert_manager

# Use context manager (with statement)
with get_alert_manager(backfill_mode=True, auto_flush_on_exit=True):
    # Run your backfill
    for date in date_range(start_date, end_date):
        processor.run({
            'date': str(date),
            'skip_downstream_trigger': True
        })
    # Digest automatically sent when exiting 'with' block
```

**Pros:**
- ✅ Automatic - can't forget to send digest
- ✅ Clean Python syntax (context manager)
- ✅ Digest sent even if exception occurs
- ✅ One less thing to remember

**Cons:**
- ⚠️ Less control (digest always sent)
- ⚠️ Need to wrap backfill in `with` statement

**Best for:** Scripts where you want foolproof digest sending

---

## Comparison Table

| Feature | Option 1: Silence | Option 2: Manual | Option 3: Auto |
|---------|-------------------|------------------|----------------|
| Email spam | ✅ None | ✅ None | ✅ None |
| End-of-run confirmation | ❌ No | ✅ Yes | ✅ Yes |
| Error breakdown | ❌ No | ✅ Yes | ✅ Yes |
| Code changes | ✅ None | ⚠️ 2 lines | ⚠️ Wrap in `with` |
| Control timing | N/A | ✅ Full control | ⚠️ Auto |
| Failsafe (can't forget) | N/A | ❌ No | ✅ Yes |

---

## Real-World Example: Full Backfill Script

### Using Option 2 (Manual Digest) - RECOMMENDED

```python
#!/usr/bin/env python3
"""
Backfill historical data with digest email summary.
"""

from datetime import date, timedelta
from shared.alerts import get_alert_manager
from data_processors.raw.nbac_player_boxscore_processor import NbacPlayerBoxscoreProcessor

def backfill_player_boxscores(start_date: str, end_date: str):
    """
    Backfill player boxscores with alert digest.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """

    # Initialize alert manager (backfill mode)
    alert_mgr = get_alert_manager(backfill_mode=True)

    # Parse dates
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    # Track progress
    total_dates = (end - current).days + 1
    success_count = 0
    error_count = 0

    print(f"🚀 Starting backfill: {start_date} to {end_date} ({total_dates} dates)")
    print(f"   Alerts suppressed, digest will be sent at end\n")

    # Process each date
    while current <= end:
        try:
            print(f"Processing {current}...", end=' ')

            processor = NbacPlayerBoxscoreProcessor()
            result = processor.run({
                'date': str(current),
                'skip_downstream_trigger': True,  # Backfill mode
                'group': 'prod'
            })

            if result:
                success_count += 1
                print("✅")
            else:
                error_count += 1
                print("❌")

        except Exception as e:
            error_count += 1
            print(f"❌ {type(e).__name__}")

        current += timedelta(days=1)

    # Backfill complete - send digest
    print(f"\n✅ Backfill complete!")
    print(f"   Success: {success_count}/{total_dates}")
    print(f"   Errors: {error_count}/{total_dates}")
    print(f"   Success rate: {100 * success_count / total_dates:.1f}%\n")

    # Get alert stats
    stats = alert_mgr.get_alert_stats()
    batched_count = len(stats.get('batched_alerts', {}))

    if batched_count > 0:
        print(f"📧 Sending digest email ({batched_count} alert categories)...")
        alert_mgr.flush_batched_alerts()
        print("   Digest sent!\n")
    else:
        print("✨ No errors to report!\n")

    return {
        'total': total_dates,
        'success': success_count,
        'errors': error_count,
        'alert_categories': batched_count
    }


if __name__ == '__main__':
    import sys

    if len(sys.argv) != 3:
        print("Usage: python backfill_player_boxscores.py START_DATE END_DATE")
        print("Example: python backfill_player_boxscores.py 2022-01-01 2022-12-31")
        sys.exit(1)

    start = sys.argv[1]
    end = sys.argv[2]

    results = backfill_player_boxscores(start, end)

    print("=" * 60)
    print("BACKFILL SUMMARY")
    print("=" * 60)
    print(f"Total dates processed: {results['total']}")
    print(f"Successful: {results['success']}")
    print(f"Failed: {results['errors']}")
    print(f"Alert categories: {results['alert_categories']}")
    print("=" * 60)
```

**Usage:**
```bash
python backfill_player_boxscores.py 2022-01-01 2022-12-31
```

**Output:**
```
🚀 Starting backfill: 2022-01-01 to 2022-12-31 (365 dates)
   Alerts suppressed, digest will be sent at end

Processing 2022-01-01... ✅
Processing 2022-01-02... ❌ FileNotFoundError
Processing 2022-01-03... ✅
...
Processing 2022-12-31... ✅

✅ Backfill complete!
   Success: 283/365
   Errors: 82/365
   Success rate: 77.5%

📧 Sending digest email (3 alert categories)...
   Digest sent!

============================================================
BACKFILL SUMMARY
============================================================
Total dates processed: 365
Successful: 283
Failed: 82
Alert categories: 3
============================================================
```

**Email received:**
```
📊 Batched Alerts: NbacPlayerBoxscoreProcessor_FileNotFoundError

Suppressed 75 similar alerts due to rate limiting.

Sample contexts:
  - {'date': '2022-01-02', 'error_type': 'FileNotFoundError', 'processor': '...'}
  - {'date': '2022-02-15', 'error_type': 'FileNotFoundError', 'processor': '...'}
  - {'date': '2022-03-20', 'error_type': 'FileNotFoundError', 'processor': '...'}

---

📊 Batched Alerts: BdlPlayersProcessor_DataValidationError
...
```

---

## My Recommendation

**Use Option 2 (Manual Digest)** because:

1. ✅ **Accountability** - You know the backfill finished
2. ✅ **Visibility** - See error patterns and counts
3. ✅ **Debugging** - Sample contexts help identify issues
4. ✅ **Production-ready** - Professional notification system
5. ✅ **Simple** - Just 2 lines: get manager, flush at end
6. ✅ **Flexible** - Add your own summary stats

**Implementation:**
1. Add `alert_mgr = get_alert_manager(backfill_mode=True)` at start
2. Add `alert_mgr.flush_batched_alerts()` at end
3. Done!

---

## Testing the Digest

Want to see what the digest email looks like?

```python
# Test digest with fake errors
from shared.alerts import get_alert_manager
from shared.utils.notification_system import notify_error

alert_mgr = get_alert_manager(backfill_mode=True, reset=True)

# Simulate backfill with errors
for i in range(10):
    notify_error(
        title=f"Test Error #{i}",
        message="File not found",
        details={'date': f'2022-01-{i:02d}', 'error_type': 'FileNotFoundError'},
        processor_name='TestProcessor',
        backfill_mode=True
    )

# Send digest
print("Sending test digest...")
alert_mgr.flush_batched_alerts()
```

---

## Quick Decision Guide

**Choose based on your needs:**

- **Small test backfill** → Option 1 (Silence)
- **Production backfill** → Option 2 (Manual Digest) ⭐
- **Automated scripts** → Option 3 (Auto Digest)

---

## Next Steps

1. **Choose your option** (I recommend Option 2)
2. **Update your backfill script** (see examples above)
3. **Test with small date range** (verify digest looks good)
4. **Run full backfill** (enjoy spam-free email!)

---

**Questions to consider:**

- How often do you run backfills? (frequent → auto-digest)
- Do you want to add custom stats to summary? (yes → manual digest)
- Do you monitor backfills in real-time? (yes → silence OK)
- Is this for production or testing? (production → digest recommended)

Let me know which option you prefer and I can help implement it!
