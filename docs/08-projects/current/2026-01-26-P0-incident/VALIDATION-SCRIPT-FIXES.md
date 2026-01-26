# Validation Script Timing Fixes

**Date:** 2026-01-26
**Status:** ✅ Complete
**File:** `scripts/validate_tonight_data.py`

---

## Problem

The validation script was run at 10:20 AM, **before the pipeline completed**, causing a false alarm P0 incident.

**Root causes:**
1. Script comment said "Run after 2 PM ET" but was run at 10:20 AM
2. No prominent warning when running too early
3. Predictions check failed even though they run tomorrow (expected behavior)

---

## Changes Made

### 1. Updated Docstring with Clear Timing Guidance

**Before:**
```python
"""
Run after 2 PM ET to verify tonight's predictions are ready.
"""
```

**After:**
```python
"""
TIMING GUIDANCE:
  Pre-Game Check:  Run after 5 PM ET (before games start at 7 PM)
  Post-Game Check: Run after 6 AM ET next day (after predictions generated)

Running earlier may show false alarms as workflows haven't completed yet.
"""
```

### 2. Added Early-Run Warning

Added prominent warning at start of validation when run too early:

```python
if hour_et < 17:  # Before 5 PM ET
    print(f"⚠️  WARNING: Running validation at {hour_et:02d}:{current_time_et.minute:02d} ET")
    print(f"    Recommended times:")
    print(f"      Pre-game check:  5 PM ET or later (betting data + Phase 3)")
    print(f"      Post-game check: 6 AM ET next day (predictions)")
    print(f"    Data may not be available yet - expect false alarms!\n")
```

**Example output:**
```
============================================================
TONIGHT'S DATA VALIDATION - 2026-01-26
============================================================

⚠️  WARNING: Running validation at 10:20 ET
    Recommended times:
      Pre-game check:  5 PM ET or later (betting data + Phase 3)
      Post-game check: 6 AM ET next day (predictions)
    Data may not be available yet - expect false alarms!
```

### 3. Made Predictions Check Timing-Aware

**Before:**
```python
if total_rows == 0:
    self.add_issue('predictions', f'No predictions for {self.target_date}')
    return 0, 0
```

**After:**
```python
if total_rows == 0:
    # Check if this is expected (same day as target date)
    if self.target_date >= date.today():
        # Predictions for today/future - expected to be missing
        print(f"ℹ️  Predictions: Not generated yet (run tomorrow morning after games complete)")
        return 0, 0
    else:
        # Historical date - predictions should exist
        self.add_issue('predictions', f'No predictions for {self.target_date}')
        return 0, 0
```

### 4. Added Missing Import

Added `timedelta` to imports (was missing):
```python
from datetime import date, datetime, timezone, timedelta
```

---

## Testing

Tested with `python scripts/validate_tonight_data.py --date 2026-01-26`:

**Results:**
- ✅ Early-run warning displayed correctly
- ✅ Predictions check no longer fails (shows info message)
- ✅ Betting data check uses existing workflow timing logic
- ✅ Script completes without errors

---

## Separate Issue Discovered

During testing, discovered **game_id format mismatch** in `check_game_context()`:
- Schedule table: `0022500661` (NBA official format)
- Player context table: `20260126_MEM_HOU` (date format)
- **Result:** JOIN fails, shows 0 players even when data exists

**Status:** Not fixed (out of scope for timing fix)
**Priority:** P2 - Validation script bug (doesn't affect pipeline)
**Recommendation:** Fix in separate task to use correct game_id mapping

---

## Impact

### Before Fix
- Validation run at 10:20 AM shows failures
- No indication that timing is wrong
- Predictions failure looks like real issue
- Created unnecessary P0 incident

### After Fix
- Clear warning if run too early
- Predictions check explains expected behavior
- Users know to run at correct times
- Prevents future false alarms

---

## Recommendations for Future

### Short-Term
1. **Document recommended run times in runbooks**
   - Pre-game validation: 5-6 PM ET
   - Post-game validation: 6-7 AM ET next day

2. **Fix game_id mismatch bug** (separate task)
   - Use proper game_id mapping in JOIN
   - Or convert between formats

### Long-Term
1. **Automated validation scheduling**
   - Cloud Scheduler job at 6 PM ET (pre-game)
   - Cloud Scheduler job at 6 AM ET (post-game)
   - Auto-post results to Slack

2. **Phase-aware validation modes**
   - `--phase pre-game` - Only check Phase 2/3
   - `--phase post-game` - Only check Phase 4/5
   - Different expectations for each mode

3. **Better timing integration**
   - Use workflow_timing for all checks (not just betting data)
   - Show expected completion times in output
   - Color-code: red=failure, yellow=too early, green=success

---

## Files Changed

**Modified:**
- `scripts/validate_tonight_data.py` (lines 8-12, 22, 610-626, 187-199)

**No new files created.**

---

## Commit Message

```
fix: Add timing warnings to validation script to prevent false alarms

The validation script was run at 10:20 AM before pipeline completed,
causing a false P0 incident. Added clear timing guidance and warnings.

Changes:
1. Updated docstring with clear timing guidance (5 PM pre-game, 6 AM post-game)
2. Added prominent warning when run too early (<5 PM ET)
3. Made predictions check timing-aware (doesn't fail if checking same day)
4. Added missing timedelta import

Result: Users will now see clear warnings if running too early, preventing
future false alarm incidents like 2026-01-26.

Separate issue discovered: game_id format mismatch in check_game_context()
causing JOIN to fail. Noted for future fix but not addressed here (out of scope).

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

**Status:** ✅ Complete
**Testing:** ✅ Verified
**Documentation:** ✅ Complete
**Next:** Commit changes
