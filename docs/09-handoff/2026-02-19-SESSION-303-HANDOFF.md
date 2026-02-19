# Session 303 Handoff — 2026-02-19
**Focus:** Option C1 post-break cache warmup fix, Phase5→6 silent-skip fix, coordinator cross-instance visibility fix.

---

## Commits This Session

```
b33e78ab fix: adaptive L7d/L14d lookback in player_daily_cache post-break warmup (Option C1)
5b71787d fix: phase5→6 orchestrator silent-skip when completion_pct=0 on re-triggered batches
9d488003 fix: coordinator /status cross-instance visibility + /start cross-instance dedup
```

---

## Fix 1: Option C1 — Adaptive Lookback Post-Break (DEPLOYED)

**File:** `data_processors/precompute/player_daily_cache/builders/completeness_checker.py`

**Problem:** After a multi-day break (ASB, Christmas), `PlayerDailyCacheProcessor` ran for the return date but the L7d window (7 calendar days) found 0 games. Cache entries were written with null rolling fields → zero-tolerance quality gate blocked 151/153 players → only 6 predictions on Feb 19.

**Fix:** Added `_detect_break_days(game_date, bq_client)` static method. One BQ query finds `MAX(game_date)` in the 30 days before `game_date`. If break detected, `L7d` and `L14d` windows are extended by `break_days` (e.g. ASB 6-day gap → L7d becomes 13 days, L14d becomes 20 days). L5/L10 game-count windows are unchanged. Fail-open on any BQ error.

**Expected effect Feb 20:** Phase 4 detects 6 break days, extends L7d to 13 days, finds Feb 12 game data → cache populated with real values → 100+ quality-ready players instead of 6.

**Verification query for Feb 20:**
```sql
SELECT game_date, COUNTIF(is_quality_ready) as qr, COUNT(*) as total,
       AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2026-02-20'
GROUP BY 1 ORDER BY 1 DESC;
-- Expect: qr >= 100 (vs 6 on Feb 19)
```

---

## Fix 2: Phase5→6 Orchestrator Silent Skip (DEPLOYED)

**Files:** `orchestration/cloud_functions/phase5_to_phase6/main.py`, `predictions/coordinator/coordinator.py`

**Problem:** On Feb 19, manually re-triggered batch had `completion_pct = 0` in the Pub/Sub message (coordinator's `start_batch` was never called so run_history computed 0% completion). Orchestrator blocked Phase 6 because `0 < MIN_COMPLETION_PCT (80.0)`. 81 predictions existed but no export fired automatically.

**Also:** The coordinator's Firestore path sent key `completion_percentage` but the orchestrator reads `completion_pct` — key mismatch.

**Fixes:**
1. Orchestrator: if `status='success'` and `completed_predictions > 0` and `completion_pct < 80%`, override to `100.0` with a warning log. Trusts the coordinator's success signal.
2. Coordinator Firestore path: changed `completion_percentage` → `completion_pct` and added `completed_predictions` key to match what the orchestrator reads.

---

## Fix 3: Coordinator Cross-Instance Visibility (DEPLOYED)

**File:** `predictions/coordinator/coordinator.py`

**Problem:** Cloud Run routes requests to any instance. Batch state lives in-memory on the instance that created it. On Feb 19, `/status` returned `no_active_batch` while another instance was actively processing 334 players. Also, `/start` had no cross-instance dedup, allowing two instances to independently start the same game_date batch.

### Fix A — `/status` Firestore fallback

**Before:** Only checked `current_tracker` (in-memory on this instance).

**After:** If no matching in-memory batch:
1. If specific `batch_id` requested → look up in Firestore → return Firestore state with `source='firestore'`
2. No specific batch → check `get_active_batches()` → return first active batch with `note='Batch processing on a different instance'`
3. If Firestore fails → fall back to `no_active_batch` (fail-open)

### Fix B — `/start` Firestore cross-instance dedup

**Before:** Only checked `ENABLE_MULTI_INSTANCE=true` path (which is `false` in prod), so no cross-instance protection.

**After:** Always checks Firestore for an active same-date batch before creating a new one (regardless of `ENABLE_MULTI_INSTANCE`). Returns `already_running` with Firestore batch info if found. Fail-open on Firestore errors.

---

## Coordinator Dual-Batch Root Cause (P5 from Session 302)

The full diagnosis from the agent investigation:
- `current_tracker` is in-memory, instance-local. Firestore `BatchStateManager` (`prediction_batches` collection) has the persistent state.
- `/status` only checked `current_tracker` — cross-instance blind.
- `/start` Firestore transaction protection gated behind `ENABLE_MULTI_INSTANCE=true` — disabled in prod.
- `BatchStateManager.get_active_batches()` and `get_batch_state()` already existed; just weren't wired to `/status`.
- `/reset` was already Firestore-aware (already called `state_manager.get_active_batches()`) — no fix needed.

---

## Still Running

Two backfill processes alive from Session 302:
- PID 3603292: `--start-date 2025-11-02 --end-date 2026-02-12` (started 09:48 UTC)
- PID 3704808: `--start-date 2026-01-05 --end-date 2026-02-07` (started 13:07 UTC)

Weeks Jan 26 and Feb 02 still at 2 books (down from 12 needed). Processes are running; just slow. Verify with:
```sql
SELECT DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start, COUNT(DISTINCT bookmaker) as books
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN '2026-01-18' AND '2026-02-12' AND points_line IS NOT NULL
GROUP BY 1 ORDER BY 1;
-- Expected: all weeks at 12 books
```

---

## Next Session Priorities

### P0: Verify Feb 20 pipeline ran correctly
```bash
# Morning check — expect qr >= 100
bq query --use_legacy_sql=false --project_id=nba-props-platform \
'SELECT game_date, COUNTIF(is_quality_ready) as qr, COUNT(*) as total
 FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
 WHERE game_date >= "2026-02-20" GROUP BY 1 ORDER BY 1 DESC'
```

### P1: Verify backfill complete (Jan 26, Feb 02 weeks at 12 books)
If processes died, restart:
```bash
PYTHONPATH=. python scripts/backfill_odds_api_props.py --start-date 2026-01-25 --end-date 2026-02-07 --historical
```

### P2: Grade Feb 19 games
```sql
SELECT game_date, COUNT(*) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9'
GROUP BY 1;
```
Note: 0 edge 3+ predictions on Feb 19, so edge3_hr will be NULL.

### P3: Multi-Book Line Feature Architecture (research, not urgent)
With 12 books loaded, research queries can now run. Questions:
- Does high `line_std` (cross-book disagreement) correlate with model accuracy?
- Sharp vs soft book signal — do certain books move first?
- Juice asymmetry (-115 one side) vs actual results
Feature f50 (`multi_book_line_std`) is already in production. Consider `player_line_summary` table.

### P4: Retrain Shadow Models (~Feb 22-23)
Wait for 2-3 days of post-ASB graded data. Champion is 35+ days stale. Run:
```bash
./bin/retrain.sh --promote
```
