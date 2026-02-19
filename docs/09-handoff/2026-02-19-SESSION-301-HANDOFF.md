# Session 301 Handoff — 2026-02-19
**Option C: Post-Break Cache Warmup Fix**

## Context

Sessions 298–299 fixed break-day alerting/suppression. Session 300/301 addressed the ASB return-day pipeline. This handoff documents the remaining Option C work: making Phase 4 cache-building resilient to multi-day breaks so the first post-break game day produces full-quality predictions.

---

## What Happened Today (Feb 19 — First Day Back)

**Root cause chain:**
1. `player_daily_cache_processor` ran for 2026-02-19 but the L7d window (last 7 calendar days) had 0 games (Feb 13–19 = All-Star break).
2. Processor wrote cache entries for today, but rolling stats that depend on recent games (e.g., `games_in_last_7_days`, `minutes_avg_last_7d`) were null/zero.
3. `feature_extractor.py:474` queries `WHERE cache_date = '{game_date}'` (exact-date only — Session 291 removed fallback intentionally to prevent silent quality masking).
4. Cache entries exist but have null rolling fields → quality scorer marks as defaults → zero-tolerance blocks 151/153 players.
5. Coordinator ran at 13:26 UTC (Phase 4 not done) → only 6 quality-ready players → Phase 5→6 orchestrator silently skipped (quality gate: completion_pct was bad due to `complete_batch without start_batch` log).

**What we fixed today:**
- Redeployed phase6-export with `ml/` in the deployment package (it was missing → 500 on every invocation).
- Manually re-triggered coordinator → 81 players predicted.
- Manually triggered Phase 6 → picks.json (88KB), tonight.json (1.1MB), signal-best-bets.json published.
- 0 signal best bets today — **correct**: edges are low because post-ASB predictions cluster near the line.
- Fixed `cloudbuild-functions.yaml` to include `ml/` in all CF deployments going forward.

**Commits today (Session 301):**
- `0a94da20` fix: add ml/ to Cloud Function deployment package
- `dda7851c` (Session 299) break-day awareness sweep

---

## Option C: The Real Fix

### Problem Statement

After any multi-day break (ASB, Christmas, long All-Star weekend), Phase 4's `player_daily_cache_processor` writes cache entries for the return date but with nulls in rolling window fields. The result: near-zero quality-ready predictions on the first game day back.

### Root Cause — Two Interacting Decisions

**Decision A (Session 291):** `feature_extractor.py` removed the fallback lookup window from `player_daily_cache`. It now queries exact date only:
```python
# feature_extractor.py:474
WHERE cache_date = '{game_date}'
```
Rationale: fallback was masking missing data from quality scoring.

**Decision B (cache_builder.py):** `PlayerDailyCacheProcessor` computes rolling windows over calendar days. The L7d window (7 calendar days) returns 0 games during/after a break. These empty windows write nulls into the cache entry for the return date.

### Option C1 — Adaptive Lookback in `player_daily_cache_processor` (Recommended)

**Where:** `data_processors/precompute/player_daily_cache/builders/completeness_checker.py` lines 23–28.

**Change:** Before computing windows, check if the current N calendar days are a break period. If so, extend the lookback.

```python
# In completeness_checker.py or player_daily_cache_processor.py
# Add a break-detection helper:

from shared.utils.schedule_guard import has_regular_season_games
from datetime import date, timedelta

def _detect_break_days(game_date: date, client) -> int:
    """Return how many consecutive days before game_date had no regular-season games."""
    for days_back in range(1, 30):
        d = (game_date - timedelta(days=days_back)).isoformat()
        if has_regular_season_games(d, bq_client=client):
            return days_back - 1  # e.g., 7-day ASB returns 6
    return 0

# In the processor's build logic, when computing L7d:
break_days = _detect_break_days(cache_date, bq_client)
effective_l7d_days = 7 + break_days  # e.g., 7+7=14 during/after ASB

WINDOWS = [
    ('L5', 5, 'games'),
    ('L10', 10, 'games'),
    ('L7d', effective_l7d_days, 'days'),   # Extends on break return
    ('L14d', 14 + break_days, 'days'),
]
```

**Risk:** Low — only activates when `break_days > 0`. Normal season behavior unchanged.

**Test:** Run on 2026-02-19 with `break_days=7` → L7d window becomes 14 days, finding Feb 12 data → cache entries populated → feature quality rises → more predictions tomorrow.

---

### Option C2 — Allow Recent Cache Fallback in `feature_extractor.py` (Simpler but riskier)

**Where:** `feature_extractor.py:473–475`

**Change:** Fall back to most-recent-within-N-days when exact date has no entry:

```python
# Instead of:
WHERE cache_date = '{game_date}'

# Use:
WHERE cache_date BETWEEN DATE_SUB('{game_date}', INTERVAL 14 DAY) AND '{game_date}'
ORDER BY cache_date DESC
LIMIT 1 PER player_lookup  -- (or: take first result per player in Python)
```

**Risk:** Higher — Session 291 intentionally removed this pattern. Would need careful testing to ensure it doesn't mask quality issues on non-break game days.

---

### Option C3 — Post-Break Bootstrap Mode (Most Robust, Most Work)

Add a `--post-break-bootstrap` flag to the Phase 4 coordinator that:
1. Detects break ended (first game day back)
2. Copies yesterday-minus-N's cache entries forward to today's date
3. Marks them `is_bootstrap=True` in the cache table
4. Feature extractor uses bootstrap entries with a warning (not blocking)

---

## Recommended Approach for Next Session

1. **Implement Option C1** — adaptive L7d/L14d lookback in `completeness_checker.py` using `schedule_guard.has_regular_season_games()`.
2. **Test:** Query `player_daily_cache` for 2026-02-19 with `effective_l7d_days=14` and verify non-null rolling fields.
3. **Deploy** to nba-phase4-precompute-processors (auto via git push).
4. **Validate** next break: Christmas break (Dec 24–25) or trade deadline downtime.

---

## Other Open Items from Session 301

### Phase 5→6 Orchestrator — Silent Skip Bug

The orchestrator returned HTTP 200 but didn't trigger Phase 6 because `completion_pct` was invalid. The coordinator logs show `complete_batch called without start_batch — skipping` for the manually re-triggered batch. This means `run_history` didn't track the batch properly, and the Pub/Sub payload had a bad `completion_pct`.

**File:** `orchestration/cloud_functions/phase5_to_phase6/main.py` — the gate:
```python
if completion_pct < MIN_COMPLETION_PCT:  # 80.0%
    logger.warning(f"Skipping Phase 6 trigger - completion too low")
    return
```

**Fix:** Add logging of the actual `completion_pct` value received so future failures are diagnosable. Also consider: if `total_players` in the message is > 0 and `status = success`, override a bad `completion_pct` with `100.0` (since the coordinator just told us it succeeded).

**File:** `orchestration/cloud_functions/phase5_to_phase6/main.py`

---

### GCS Files Published — Current State (Feb 19)

| File | Size | Time |
|------|------|------|
| signal-best-bets/2026-02-19.json | 1.1 KB | 20:46 UTC |
| picks/2026-02-19.json | 88.5 KB | 20:45 UTC |
| tonight/2026-02-19.json | 1.16 MB | 20:45 UTC |

0 signal best bets — expected, edges too low post-break. Frontend has data.

---

### `cloudbuild-functions.yaml` Fix (ALREADY COMMITTED)

Added `cp -r ml /workspace/deploy_pkg/` to the deployment package step. All Cloud Functions now include the `ml/` module. This was the root cause of `phase6-export` returning 500 on every invocation.

**Commit:** `0a94da20`

---

## Verification Queries

```sql
-- Check feature quality tomorrow (expect improvement as cache warms)
SELECT game_date,
       COUNT(*) as total,
       COUNTIF(is_quality_ready) as quality_ready,
       COUNTIF(default_feature_count = 0) as zero_defaults,
       COUNTIF(cache_miss_fallback_used) as cache_misses,
       AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2026-02-19'
GROUP BY 1 ORDER BY 1 DESC;

-- Check cache_daily entries for Feb 19 (L7d window quality)
SELECT player_lookup,
       l7d_completeness_pct, l7d_is_complete,
       l14d_completeness_pct, l14d_is_complete,
       games_in_last_7_days, games_in_last_14_days
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2026-02-19'
ORDER BY l7d_completeness_pct ASC
LIMIT 20;
```

---

## Quick Start for Next Session

```bash
# 1. Morning validation
/daily-steering
/validate-daily

# 2. Check if cache warmed up (expect 100+ quality-ready players by Feb 20)
bq query --use_legacy_sql=false "
SELECT game_date, COUNTIF(is_quality_ready) as qr, COUNT(*) as total
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2026-02-19' GROUP BY 1 ORDER BY 1 DESC"

# 3. If implementing Option C1:
#    Edit data_processors/precompute/player_daily_cache/builders/completeness_checker.py
#    Add break_days detection before WINDOWS definition
#    Push → auto-deploys nba-phase4-precompute-processors
```
