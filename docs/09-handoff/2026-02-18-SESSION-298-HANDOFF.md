# Session 298 Handoff — All-Star Break Graceful Handling Fixes

**Date:** 2026-02-18
**Session:** 298
**Focus:** All-Star break audit + graceful handling improvements

---

## Summary

Diagnosed and fixed three issues that caused noisy behavior during the 2026 All-Star break
(Feb 12–18). All fixes are additive — no existing behavior changes on regular game days.

---

## Issues Fixed

### Issue 1: `status.json` showed `overall_status: "degraded"` for 6 days

**Root cause (two-part):**

1. `_check_active_break()` in `status_exporter.py` queried `nba_raw.nbac_schedule`, which
   includes All-Star exhibition entries (Skills, 3-Point, Dunk, All-Star Game itself). These
   reduced the apparent gap between last regular game (Feb 12) and next regular game (Feb 20)
   to appear as 2 days (All-Star Game Feb 18 → Feb 20), below the 3-day threshold.
   Additionally, the query used `CURRENT_DATE()` (UTC) instead of ET today, introducing a
   possible 1-day timezone mismatch.

2. `_check_tonight_data_status()` was not break-aware — a stale `tonight/all-players.json`
   (from days without games) triggered a false `degraded` status even when `active_break`
   was set correctly.

**Fix (`data_processors/publishing/status_exporter.py`):**
- `_check_active_break()`: switched to `nba_reference.nba_schedule` filtered to
  `game_id LIKE '002%' OR game_id LIKE '004%'` (regular season + playoffs only), and uses
  a parameterized ET `@today` date instead of `CURRENT_DATE()`.
- `_check_tonight_data_status()`: now accepts `active_break` parameter; returns
  `status: healthy` immediately during breaks (same pattern as `_check_live_data_status`).
- `generate_json()`: passes `active_break` to `_check_tonight_data_status(active_break)`.

---

### Issue 2: Phase 4 processors emitted noisy `ValueError` logs on break days

**Root cause:** `MLFeatureStoreProcessor.extract_raw_data()` and
`PlayerDailyCacheProcessor.validate_extracted_data()` raise `ValueError("No players found...")`
/ `ValueError("No upcoming player context data extracted")` when no games exist. These trigger
Sentry captures, Pub/Sub retries, and repeated error Slack alerts.

**Fix:**
- `data_processors/precompute/base/precompute_base.py`:
  - Added `_has_games_on_date(analysis_date)` helper — queries `nba_reference.nba_schedule`
    with regular-season filter; fails open (returns `True`) on BQ errors.
  - Added `skipped_no_games` handling after the `skipped_early_season` check — reuses the
    same `_complete_early_season_skip()` clean-exit path.
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`:
  - Before raising `ValueError` for 0 players, checks `_has_games_on_date()`. On a confirmed
    no-game day, sets `processing_decision = 'skipped_no_games'` and returns cleanly.
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`:
  - Same pattern in `validate_extracted_data()` — graceful skip before the `ValueError`.

---

### Issue 3: BettingPros scraper retried 5+ times on a no-game day

**Root cause:** `bp_player_props.py` has no awareness of whether games are scheduled before
fetching event IDs. On Feb 18 it retried 3 times (15s + 30s + 60s backoff), sent a Slack
error alert, then Pub/Sub redelivered — producing ~5+ total attempts.

**Fix (`scrapers/bettingpros/bp_player_props.py`):**
- Added `_no_games_scheduled(date)` helper — single BQ query against `nba_reference.nba_schedule`
  with regular-season filter; fails open (returns `False`) on errors.
- `_fetch_event_ids_from_date()`: pre-checks schedule before retry loop. On confirmed no-game
  day, sets `opts["_no_games_expected"] = True` and returns immediately (no retries, no Slack).
- `set_additional_opts()`: early-returns if `_no_games_expected`.
- `set_url()`: sets `self.url = ""` and returns if `_no_games_expected`.
- `download_and_decode()`: sets `_no_data_success = True` and returns empty data if
  `_no_games_expected`. The `_no_data_success` flag causes `validation_mixin` to accept 0 rows
  as a successful run.

---

### Issue 4: `tonight_all_players_exporter.py` season stat fields

**Status:** Already committed prior to this session — no action needed. The 4 new season stat
fields (`fg_pct`, `three_pct`, `plus_minus`, `fta`) were already present in the codebase.

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/publishing/status_exporter.py` | Break detection query + break-aware tonight check |
| `data_processors/precompute/base/precompute_base.py` | `_has_games_on_date()` + `skipped_no_games` |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Graceful skip |
| `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` | Graceful skip |
| `scrapers/bettingpros/bp_player_props.py` | No-game day pre-check + early exit |

---

## Design Principles Applied

- **Fail open:** All schedule pre-checks return `True`/`False` (games exist / no games) on BQ
  error — never suppressing a real game-day error.
- **Additive only:** No existing behavior changes on regular game days. Checks only trigger
  when the primary condition already fails (0 players, empty context data).
- **Reuse existing patterns:** `skipped_no_games` reuses `_complete_early_season_skip()` which
  is already tested and used in production.
- **Regular-season filter:** `game_id LIKE '002%' OR game_id LIKE '004%'` correctly excludes
  All-Star exhibitions, preseason (001), and All-Star game itself.

---

## What to Watch For (Regular Season Resumes Feb 20)

1. **status.json** should show `active_break: null` on Feb 20 and `overall_status: healthy`
   once predictions exist. Verify with:
   ```bash
   gcloud storage cat gs://nba-props-platform-api/v1/status.json | python -m json.tool | grep -E 'active_break|overall_status'
   ```

2. **Phase 4 processors** should run cleanly with 0 `ValueError` logs. Check:
   ```bash
   gcloud run services logs read nba-phase4-precompute-processors --region=us-west2 --limit=50
   ```

3. **BettingPros scraper** should not send Slack alerts on break days and should complete
   in <5 seconds on no-game days (just the BQ pre-check).

4. **Retrain reminder** is due — model is `catboost_v9_train1102_0205` trained 2026-02-05,
   now 13 days old (OVERDUE tier). Run `./bin/retrain.sh --dry-run` to preview.

---

## Next Session Priorities

1. Verify fixes on Feb 20 first game day
2. Weekly retrain (model 13 days old — OVERDUE)
3. Monitor shadow model performance post-All-Star break
