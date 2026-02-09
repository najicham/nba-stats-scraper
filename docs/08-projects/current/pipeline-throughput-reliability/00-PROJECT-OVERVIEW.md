# Pipeline Throughput & Reliability Improvements

**Created:** 2026-02-09
**Session:** 171
**Priority:** P1 - Affects prediction throughput and worker resource waste
**Status:** Fixes + Monitoring Applied (commits 75c6218c, 6e2b3900, 9795ea60)

---

## Problem Statement

Four issues degrading pipeline throughput and reliability, discovered during Feb 9 BACKFILL attempts:

1. **Same-day BACKFILL silently downgraded to RETRY** -- the date guard in `coordinator.py` used `>=` instead of `>`, blocking same-day backfills even when games were already Final
2. **Pub/Sub publish loop wastes ~45s per batch** -- `time.sleep(0.1)` per player (added Session 101 for cold-start protection) is 5x too conservative with `minScale=1` already set
3. **Stale Pub/Sub messages stuck in infinite retry** -- Feb 6/7 messages failed permanently but kept retrying, consuming worker resources
4. **Feature validation failures retried forever** -- `invalid_features` and `quality_too_low` not classified as permanent skip reasons, causing infinite retry loops

---

## Root Causes

| # | Root Cause | Impact |
|---|-----------|--------|
| 1 | BACKFILL date guard used `>=` instead of `>` | Same-day backfills silently downgraded to RETRY mode |
| 2 | Pub/Sub publish delay (0.1s/msg) added in Session 101 was 5x too conservative with `minScale=1` | 45s wasted per 450-player batch |
| 3 | `invalid_features` and `quality_too_low` not in `PERMANENT_SKIP_REASONS` | Worker retried these forever despite being permanent failures |
| 4 | No staleness check on message date | Worker retried messages for past dates (Feb 6/7) that would never succeed |
| 5 | Line quality validation failures for past dates retried forever | `validate_line_quality()` returns 500 for past dates where data will never improve |

---

## Changes Made (Session 171)

### Commit 1: `75c6218c` -- Core throughput and reliability fixes

| File | Line(s) | Change |
|------|---------|--------|
| `predictions/coordinator/coordinator.py` | 1218-1219 | BACKFILL date guard `>=` changed to `>` -- allows same-day backfills |
| `predictions/coordinator/coordinator.py` | 1222 | Updated log message: "requires game_date < today" changed to "requires game_date <= today" |
| `predictions/coordinator/coordinator.py` | 3288 | Publish delay reduced from `time.sleep(0.1)` to `time.sleep(0.02)` (~50 req/s) |
| `predictions/worker/worker.py` | 176 | Added `'invalid_features'` to `PERMANENT_SKIP_REASONS` |
| `predictions/worker/worker.py` | 177 | Added `'quality_too_low'` to `PERMANENT_SKIP_REASONS` |
| `predictions/worker/worker.py` | 809-816 | Stale message ACK for line quality validation failures on past dates |
| `predictions/worker/worker.py` | 955-965 | Stale message ACK for general exceptions on dates >1 day old |

### Commit 2: `6e2b3900` -- Publish metrics and stale transient failure ACKing

| File | Line(s) | Change |
|------|---------|--------|
| `predictions/coordinator/coordinator.py` | 3254 | Added `publish_start_time = time.time()` before publish loop |
| `predictions/coordinator/coordinator.py` | 3304-3308 | `PUBLISH_METRICS` structured log: duration, rate (req/s), batch_id, mode |
| `predictions/worker/worker.py` | 852-859 | Stale transient failure ACK for past dates (transient section) |

---

## Performance Impact

| Metric | Before | After |
|--------|--------|-------|
| Publish loop for 450 players | ~45s | ~9s |
| Stale message retries (Feb 6/7) | Infinite | ACK immediately |
| Same-day BACKFILL | Blocked (downgraded to RETRY) | Allowed |
| Worker resource waste | Feb 6/7 messages consuming workers | Stopped |
| Feature validation retries | Infinite for invalid_features/quality_too_low | ACK immediately (permanent skip) |
| Publish observability | None | PUBLISH_METRICS log with duration, rate, batch context |

---

## Stale Message ACK Logic

Three layers of staleness protection, each with a `STALE_MESSAGE` log tag:

| Location | Condition | Behavior |
|----------|-----------|----------|
| Line quality validation (`worker.py:809`) | `game_date < today` | ACK (204) instead of retry (500) |
| Transient failure handler (`worker.py:852`) | `game_date < today` | ACK (204) instead of retry (500) |
| General exception handler (`worker.py:955`) | `game_date < today - 1 day` | ACK (204) instead of retry (500) |

The general exception handler uses a 1-day buffer (vs same-day for the others) to avoid ACKing messages for games still in progress on the same day.

---

## Future Improvements (Evaluated)

| Improvement | Priority | Status | Notes |
|-------------|----------|--------|-------|
| DLQ monitoring depth metrics | DO LATER | 90% exists | Queue depth trends, not blocking |
| Batch consolidation metrics | DO NOW | Wiring up | Existing metrics not called |
| End-to-end trace IDs | DO LATER | 70% exists | Short UUIDs, incomplete |
| Adaptive publish rate | SKIP | 95% exists | Backoff already solid |
| Pub/Sub subscription config | NO ACTION | 100% done | Already has DLQ + 15 max attempts |

---

## Verification Queries

### Verify same-day BACKFILL works

```sql
-- Check Feb 9 BACKFILL predictions exist (should not be RETRY mode)
SELECT game_date, prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09' AND is_active = TRUE
GROUP BY 1, 2;
```

### Verify publish metrics appear in logs

```
-- Cloud Logging query
resource.labels.service_name="prediction-coordinator"
textPayload=~"PUBLISH_METRICS"
```

### Verify stale messages are being ACKed

```
-- Cloud Logging query
resource.labels.service_name="prediction-worker"
textPayload=~"STALE_MESSAGE"
```

### Verify no more Feb 6/7 retries

```sql
-- Check prediction_accuracy for Feb 6/7 (should be stable, no new attempts)
SELECT game_date, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-06', '2026-02-07')
GROUP BY 1;
```

---

## Related Files

- `predictions/coordinator/coordinator.py` -- BACKFILL date guard, publish delay, publish metrics
- `predictions/worker/worker.py` -- PERMANENT_SKIP_REASONS, stale message ACKing
- `docs/08-projects/current/pubsub-reliability-fixes/README.md` -- Session 101 original Pub/Sub fixes (0.1s delay origin)
- `docs/09-handoff/2026-02-09-SESSION-171-HANDOFF.md` -- Session handoff

---

## Related Sessions

| Session | Contribution |
|---------|-------------|
| 101 | Original Pub/Sub reliability: minScale=1, retry policy, 0.1s publish delay |
| 139 | BACKFILL date guard added (`>=` -- overly restrictive) |
| 170 | Multi-line bug fix, Vegas hardening, hit rate investigation |
| **171** | **This session: throughput 5x, stale message ACKing, same-day BACKFILL** |
