# Early Exit Pattern

**Status:** Implemented
**Last Updated:** 2025-11-27

## Overview

The Early Exit Pattern prevents processors from wasting resources on unnecessary work. It's implemented via the `EarlyExitMixin` class that processors inherit.

## Problem Statement

Processors can be triggered by:
1. **Daily scheduled runs** - Normal operation
2. **Pub/Sub retries** - Failed messages retry up to 7 days
3. **Manual triggers** - Debugging or backfills
4. **Stale messages** - Old messages that got stuck

Without protection, processors would:
- Query BigQuery for dates with no games (wasted cost)
- Process offseason dates (no meaningful data)
- Reprocess very old data (already done, no value)

## Solution: Three Early Exit Checks

### 1. No Games Check (`ENABLE_NO_GAMES_CHECK`)

**Purpose:** Skip dates with no NBA games scheduled.

```python
ENABLE_NO_GAMES_CHECK = True  # Default

# Checks: SELECT COUNT(*) FROM game_schedule WHERE game_date = ?
# If 0 games → skip processing
```

**Savings:** ~30-40% of daily invocations (off-days, schedule gaps)

### 2. Offseason Check (`ENABLE_OFFSEASON_CHECK`)

**Purpose:** Skip July-September when NBA is not playing.

```python
ENABLE_OFFSEASON_CHECK = True  # Default

# If month in [7, 8, 9] → skip processing
```

**Savings:** 3 months of unnecessary runs if triggered

### 3. Historical Date Check (`ENABLE_HISTORICAL_DATE_CHECK`)

**Purpose:** Skip dates more than 90 days old.

```python
ENABLE_HISTORICAL_DATE_CHECK = True  # Default
HISTORICAL_CUTOFF_DAYS = 90  # Configurable

# If (today - game_date).days > 90 → skip processing
```

**Savings:** Prevents stale Pub/Sub messages from causing reprocessing

## Why Old Messages Are Still Safe

Even if an old message bypasses the historical check (e.g., 89 days old), the system remains safe due to:

### Idempotency via MERGE_UPDATE

```python
processing_strategy = "MERGE_UPDATE"
```

This means:
1. DELETE existing rows for the date/player combination
2. INSERT fresh calculations

**Result:** Running twice produces the same output as running once.

### Fresh Source Data

Analytics processors read from raw tables at execution time:
- Old message triggers processor
- Processor reads CURRENT raw data
- Produces CURRENT correct result

## Configuration

### Per-Processor Settings

Each processor can override defaults in its class definition:

```python
class PlayerGameSummaryProcessor(EarlyExitMixin, AnalyticsProcessorBase):
    # Enable/disable checks
    ENABLE_NO_GAMES_CHECK = True
    ENABLE_OFFSEASON_CHECK = True
    ENABLE_HISTORICAL_DATE_CHECK = True

    # Tune thresholds
    HISTORICAL_CUTOFF_DAYS = 90  # Days before skipping
```

### Runtime Override (Proposed)

For backfills and special cases, we need runtime control:

```python
# Option 1: Constructor parameter
processor = PlayerGameSummaryProcessor(skip_historical_check=True)

# Option 2: opts parameter
processor.run({'start_date': '2021-10-19', 'skip_early_exits': True})

# Option 3: Environment variable
SKIP_HISTORICAL_CHECK=true python backfill.py
```

**Recommendation:** Option 2 (opts parameter) because:
- No code changes to processor class
- Explicit per-run control
- Works with existing backfill scripts

## Backfill Mode (Implemented)

When `backfill_mode=True` is passed in opts, the following checks are modified:

| Check | Production | Backfill Mode |
|-------|------------|---------------|
| Historical date check (>90 days) | Fail/skip | **Disabled** |
| Stale data check | Fail | **Ignored** (logged only) |
| Alert notifications | Sent | **Suppressed** |
| No games check | Active | Active |
| Offseason check | Active | Active |

### Usage

```python
# In backfill script
opts = {
    'start_date': '2021-10-19',
    'end_date': '2025-06-22',
    'backfill_mode': True,  # Disables historical check, stale check, and alerts
}
processor.run(opts)
```

### What Gets Logged

```
INFO: BACKFILL_MODE: Historical date check disabled for 2021-10-20
INFO: BACKFILL_MODE: Ignoring stale data check - [...]
INFO: BACKFILL_MODE: Suppressing alert - Analytics Processor: Missing Dependencies
```

### Files Modified

- `shared/processors/patterns/early_exit_mixin.py` - Historical date check skip
- `data_processors/analytics/analytics_base.py` - Alert suppression + stale check skip
- `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` - Sets backfill_mode=True

## Decision: Backfill Mode Implementation

### Current State
- `ENABLE_HISTORICAL_DATE_CHECK` is a class constant
- Alerts are controlled by environment variables
- No unified "backfill mode"

### Proposed Change

Add `backfill_mode` option that:
1. Disables `ENABLE_HISTORICAL_DATE_CHECK` for this run
2. Disables alert notifications for this run
3. Logs clearly that backfill mode is active

### Implementation Location

```
shared/processors/patterns/early_exit_mixin.py  # Historical check
shared/utils/notification_system.py             # Alert suppression
data_processors/analytics/analytics_base.py     # Integrate both
```

## Open Questions

1. **Should backfill mode disable ALL early exits or just historical?**
   - **Decision:** Just historical. No-games and offseason checks are still useful.

2. **Should we add a `BACKFILL_MODE` environment variable?**
   - **Decision:** No. Use opts parameter for explicit control.

3. **Should backfill mode log to a separate table for monitoring?**
   - Would help distinguish backfill runs from production runs

## Future Enhancement: Bootstrap Period

**Problem:** During backfills, the first N days won't have historical data for rolling averages.

```
Backfill start: 2021-10-19
Rolling average needs: 10 games (~20 days)
Bootstrap period: 2021-10-19 to ~2021-11-08

During bootstrap:
  - "Missing 10-game history" is EXPECTED
  - Should not alert or fail

After bootstrap:
  - Missing history is a REAL problem
  - Should alert
```

**Proposed Configuration:**

```python
opts = {
    'backfill_mode': True,
    'epoch_date': '2021-10-19',      # First date with any data
    'bootstrap_days': 30,             # Days until full history expected
}

# Or in processor class:
class PlayerGameSummaryProcessor:
    ROLLING_WINDOW_GAMES = 10
    BOOTSTRAP_DAYS = 30  # Derived from window size
```

**Deferred:** Implement after basic backfill_mode is working.

## Related Documentation

- [Dependency Precheck Pattern](./dependency-precheck.md)
- [Circuit Breaker Pattern](./circuit-breaker-pattern.md)
- [Run History Guide](../../07-monitoring/run-history-guide.md)
