# Session 163: Schedule Processor Method Signature Fix

**Date:** December 24, 2025
**Status:** Complete
**Focus:** Fix NbacScheduleProcessor causing 600+ error emails

---

## Executive Summary

Fixed a critical method signature bug in NbacScheduleProcessor that caused ~600 error emails overnight. The processor's `transform_data()` method expected arguments but ProcessorBase calls it with none.

### Key Accomplishments
1. Identified root cause of "missing 2 required positional arguments" error
2. Fixed transform_data() to follow ProcessorBase contract
3. Deployed Phase 2 and verified schedule data is now fresh
4. Verified Dec 23 box score data is flowing (11 games, 387 player rows)

---

## The Bug

### What Happened

```python
# ProcessorBase.run() calls:
self.transform_data()  # NO arguments

# NbacScheduleProcessor expected:
def transform_data(self, raw_data: dict, file_path: str) -> list:  # 2 arguments
```

Result: `TypeError: transform_data() missing 2 required positional arguments: 'raw_data' and 'file_path'`

### Why It Wasn't Caught

- `process_file()` (used by backfills) called `transform_data(raw_data, file_path)` directly - worked fine
- `run()` (used by Pub/Sub automation) relies on ProcessorBase - broke

### Timeline

- Session 162 (Dec 23): Modified schedule processor with timezone fixes
- Dec 23 19:XX ET: First errors start appearing
- Dec 24 08:XX ET: ~600 emails accumulated
- Dec 24 09:06 ET: Fix deployed

---

## The Fix

Changed `transform_data()` to follow ProcessorBase contract:

**Before:**
```python
def transform_data(self, raw_data: dict, file_path: str) -> list:
```

**After:**
```python
def transform_data(self) -> None:
    raw_data = self.raw_data
    file_path = self.opts.get('file_path', '')
    # ... rest of transform logic
```

---

## Commits

| Commit | Description |
|--------|-------------|
| `73af391` | fix: NbacScheduleProcessor transform_data() follows ProcessorBase contract |

---

## Why 600+ Emails

1. **Schedule scraper runs every ~30 minutes**
2. **Each failure = 1 email** (no rate limiting)
3. **Pub/Sub retries** generate additional failures
4. **~600 / 18 hours = ~33 emails/hour**

---

## Recommendations for Prevention

### Testing
- [ ] Add integration test calling `processor.run(opts)` not just `process_file()`
- [ ] Add contract validation ensuring all processors follow ProcessorBase signature

### Notification System
- [ ] Rate limiting: Max N emails/hour for same error
- [ ] Deduplication: Same traceback = 1 aggregated email
- [ ] Exponential backoff for recurring errors

### Deployment
- [ ] Commit SHA in Cloud Run labels/env for version tracking
- [ ] Pre-deploy smoke test processing synthetic message

### Monitoring
- [ ] Error rate spike detection vs historical baseline
- [ ] Anomaly alerting when error counts exceed threshold

---

## Verification

### Schedule Data Fresh
```sql
SELECT game_date, game_status_text, last_update
FROM nba_raw.nbac_schedule
WHERE game_date = '2025-12-23'
-- Shows: Final status, updated 12:38 ET
```

### Dec 23 Box Scores Present
```sql
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(*) as rows
FROM nba_raw.bdl_player_boxscores
WHERE game_date = '2025-12-23'
-- Shows: 11 games, 387 player rows
```

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/raw/nbacom/nbac_schedule_processor.py` | Fixed transform_data() signature, updated process_file() |

---

## Lessons Learned

### Interface Contract Violations Are Silent Until Production

The processor worked fine for manual/backfill runs (`process_file()`) but broke for automated Pub/Sub runs (`run()`). Different code paths exercised different entry points.

**Key Insight:** When overriding a base class method, ALWAYS verify the signature matches the expected contract, not just that your specific use case works.

### Notification Fatigue Is Real

600 emails is too many. The notification system needs:
- Rate limiting per error type
- Aggregation of similar errors
- Severity escalation (first = info, 100th = critical)

---

## Todo for Next Session

### High Priority
1. Implement notification rate limiting
2. Add integration test for processor.run() path

### Medium Priority
3. Add commit SHA tracking to deployments
4. Monitor Christmas Day data flow (first early game at 12:00 PM ET)

---

**Session Duration:** ~1 hour
**Pipeline Status:** Fully operational, Dec 23 data flowing correctly
