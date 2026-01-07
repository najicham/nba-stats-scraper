# Session 163: Schedule Processor Fix, Rate Limiting & Integration Tests

**Date:** December 24, 2025
**Status:** Complete
**Focus:** Fix 600+ email flood, add rate limiting, add integration tests, prepare Christmas Day

---

## Executive Summary

Fixed a critical method signature bug in NbacScheduleProcessor that caused ~600 error emails overnight. Then implemented comprehensive prevention measures: rate limiting, integration tests, and orchestration documentation.

### Key Accomplishments
1. Identified root cause of "missing 2 required positional arguments" error
2. Fixed transform_data() to follow ProcessorBase contract
3. Deployed Phase 2 and verified schedule data is now fresh
4. Verified Dec 23 box score data is flowing (11 games, 387 player rows)
5. **Implemented notification rate limiting** (max 5 emails/hr per error type)
6. **Fixed early game workflows** for Christmas Day (wrong attribute name)
7. **Added integration tests** to catch contract violations
8. **Created orchestration documentation** project

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
- Dec 23 19:XX ET: First errors start appearing (revision 00031-00033)
- Dec 24 08:XX ET: ~600 emails accumulated
- Dec 24 09:XX ET: Fix committed (73af391) but **NOT deployed**
- Dec 24 12:10 ET: Revision 00034 deployed (partial fix attempt)
- Dec 24 13:50 ET: Rate limiter committed (36962e1)
- Dec 24 13:54 ET: Revision 00035 deployed **(fix + rate limiter active)**
- Dec 24 14:16 ET: Last error email received (from before 00035)

**CRITICAL NOTE:** The original handoff incorrectly stated "09:06 ET: Fix deployed".
The fix was committed at ~09:00 ET but actual deployment to Cloud Run was delayed
until 13:54 ET (revision 00035). This 4-5 hour gap caused continued email flood.

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
| `36962e1` | feat: Add notification rate limiting to prevent email floods |
| `615856d` | docs: Add rate limiting documentation |
| `9421572` | fix: Early game workflows use correct NBAGame attribute (commence_time) |
| `da084a3` | docs: Add orchestration documentation project |
| `3ff0086` | test: Add integration tests for processor.run() path |

---

## Why 600+ Emails

1. **Schedule scraper runs every ~30 minutes**
2. **Each failure = 1 email** (no rate limiting)
3. **Pub/Sub retries** generate additional failures
4. **~600 / 18 hours = ~33 emails/hour**

---

## Prevention Measures Implemented

### Notification Rate Limiting (COMPLETED)

Added `shared/alerts/rate_limiter.py` with:
- [x] **Rate limiting**: Max 5 emails/hour per error signature
- [x] **Aggregation**: After 3 occurrences, sends summary with count
- [x] **Auto-cleanup**: Expired entries removed after 60 min cooldown
- [x] **Thread-safe**: Uses locks for concurrent access

Configuration via environment variables:
```bash
NOTIFICATION_RATE_LIMIT_PER_HOUR=5      # Max emails/hr per signature
NOTIFICATION_COOLDOWN_MINUTES=60        # Reset after 60 min
NOTIFICATION_AGGREGATE_THRESHOLD=3      # Send summary after 3 occurrences
```

Documentation: `docs/03-configuration/notification-rate-limiting.md`

### Integration Tests (COMPLETED)

Added `tests/integration/test_processor_run_path.py` with 6 tests:

| Test | Purpose |
|------|---------|
| `test_transform_data_signature_no_arguments` | Validates ALL processors have correct signature |
| `test_load_data_signature_no_arguments` | Validates load_data() signature |
| `test_run_calls_transform_data_without_arguments` | Verifies ProcessorBase.run() behavior |
| `test_run_fails_if_transform_data_requires_arguments` | Simulates the bug - proves it fails |
| `test_schedule_processor_transform_data_signature` | Specific check for NbacScheduleProcessor |
| `test_schedule_processor_uses_self_raw_data` | Verifies self.raw_data usage |

Run tests: `PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_processor_run_path.py -v`

### Early Game Workflow Fix (COMPLETED)

Fixed `_evaluate_early_game()` in master_controller.py:
- Was checking for `game_date_et` attribute (doesn't exist)
- Now correctly uses `commence_time` (UTC) and converts to ET

Christmas Day workflows now correctly detect:
- 3 PM window: Noon game (CLE @ NYK)
- 6 PM window: 2:30 PM game (SAS @ OKC)
- 9 PM window: 5 PM game (DAL @ GSW)

### Orchestration Documentation (COMPLETED)

Created `docs/00-orchestration/` with:
- `README.md` - Overview and quick links
- `services.md` - Complete services inventory
- `monitoring.md` - Health checks and alerting
- `troubleshooting.md` - Common issues runbook
- `postmortems/2025-12-24-email-flood.md` - Incident write-up

### Still TODO

#### Deployment
- [ ] Commit SHA in Cloud Run labels/env for version tracking
- [ ] Pre-deploy smoke test processing synthetic message

#### Monitoring
- [ ] Error rate spike detection vs historical baseline
- [ ] Anomaly alerting when error counts exceed threshold
- [ ] Create monitoring dashboard (BigQuery + Looker?)

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

### Session 164 Re-verification (17:24 ET Dec 24)
Confirmed fix is active:
- No Phase 2 errors in 4+ hours since revision 00035 deployed
- Schedule processor successfully processed at 21:08 UTC (1231 rows)
- Phase 3 analytics ran successfully at 18:10 UTC (501 players)
- All Cloud Run services healthy
- Pub/Sub pipeline connectivity verified

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/raw/nbacom/nbac_schedule_processor.py` | Fixed transform_data() signature |
| `shared/alerts/__init__.py` | New: Rate limiting module entry point |
| `shared/alerts/rate_limiter.py` | New: Core rate limiting logic |
| `shared/utils/notification_system.py` | Integrated rate limiting into notify_error() |
| `orchestration/master_controller.py` | Fixed early game workflow attribute |
| `tests/integration/test_processor_run_path.py` | New: Integration tests for run() path |
| `docs/03-configuration/notification-rate-limiting.md` | New: Rate limiting documentation |
| `docs/00-orchestration/*` | New: Orchestration documentation project |

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

### Commit ≠ Deploy

A git commit does NOT mean the fix is live. Always verify:
1. Check Cloud Run revision timestamp: `gcloud run services describe SERVICE --format="value(status.latestReadyRevisionName)"`
2. Check revision creation time: `gcloud run revisions describe REVISION --format="value(metadata.creationTimestamp)"`
3. Verify logs show expected behavior after deployment

In this incident, a 4-5 hour gap between commit and deploy allowed hundreds more error emails.

---

## Todo for Next Session

### Completed This Session
1. ~~Implement notification rate limiting~~ **DONE**
2. ~~Add integration test for processor.run() path~~ **DONE**
3. ~~Fix early game workflows for Christmas~~ **DONE**
4. ~~Create orchestration documentation~~ **DONE**

### Still TODO
1. Add commit SHA tracking to deployments
2. Create monitoring dashboard
3. Add pre-deploy smoke tests

---

## Christmas Day Readiness

| Component | Status | Revision/Details |
|-----------|--------|------------------|
| Schedule data | ✅ Fresh | 5 games: 12, 2:30, 5, 8, 10:30 PM ET |
| Early game workflows | ✅ Fixed | Uses `commence_time` attribute correctly |
| Rate limiting | ✅ Active | Max 5 emails/hr/error signature |
| Phase 1 Scrapers | ✅ Healthy | Revision 00033 |
| Phase 2 Processors | ✅ Fixed | Revision 00035 (deployed 13:54 ET) |
| Phase 3 Analytics | ✅ Running | Revision 00019 |
| Phase 4 Precompute | ✅ Healthy | Revision 00016 |
| Prediction Coordinator | ✅ Healthy | Revision 00003 |
| Pub/Sub connectivity | ✅ Verified | All Phase 1→6 subscriptions active |
| Integration tests | ✅ Passing | 6 tests for processor.run() path |

### Christmas Day Schedule
| Time (ET) | Game | Early Game? |
|-----------|------|-------------|
| 12:00 PM | CLE @ NYK | ✅ Yes (before 7 PM) |
| 2:30 PM | SAS @ OKC | ✅ Yes |
| 5:00 PM | DAL @ GSW | ✅ Yes |
| 8:00 PM | HOU @ LAL | No |
| 10:30 PM | MIN @ DEN | No |

### First Activity Timeline (Dec 25)
| Time (ET) | Action |
|-----------|--------|
| ~6:00 AM | `betting_lines` workflow starts (6 hrs before noon game) |
| 12:00 PM | First game tips off (CLE @ NYK) |
| ~3:00 PM | `early_game_window_1` collects noon game box scores |
| ~6:00 PM | `early_game_window_2` collects 2:30 PM game |
| ~9:00 PM | `early_game_window_3` collects 5:00 PM game |

---

**Session 163 Duration:** ~4 hours
**Session 164 Update:** Verified deployment timeline, confirmed fix active
**Pipeline Status:** Fully operational, rate limiting active, Christmas Day ready
**Last Verified:** Dec 24, 2025 17:24 ET
