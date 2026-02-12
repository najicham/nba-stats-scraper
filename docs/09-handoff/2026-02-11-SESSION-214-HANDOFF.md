# Session 214 Handoff - Fix GCS JSON Files That Never Update After Games

**Date:** 2026-02-11
**Session:** 214
**Status:** ✅ Complete

## Summary

Fixed 7 issues where GCS JSON files were generated as pre-game snapshots during Phase 5→6 publishing and never refreshed with game results. The frontend already has rendering code for all fields — once data is populated, everything displays correctly.

## Changes (6 files, 7 fixes)

### Fix 1: Live grading status and margin_vs_line (highest impact)
**File:** `data_processors/publishing/live_grading_exporter.py`

**Problem:** In `_grade_predictions()`, grading was gated on `recommendation in ('OVER', 'UNDER')`. Predictions with PASS/NO_LINE recommendations that had a valid `line_value` fell through — getting `status: 'graded'` and `margin_vs_line: null`. Affected 141/196 final predictions.

**Fix:**
- `margin_vs_line` computed whenever `actual` and `line` are both available (regardless of recommendation)
- Infer `effective_direction` for PASS/NO_LINE: `predicted > line → OVER`, else `UNDER`
- Use `effective_direction` for correct/incorrect status (same logic as OVER/UNDER path)
- Only fall back to `status: 'graded'` when there's truly no line

### Fix 2: Tonight scores for in-progress games
**File:** `data_processors/publishing/tonight_all_players_exporter.py`

**Problem:** `_query_games()` gated scores behind `game_status = 3` (Final only).

**Fix:** `game_status = 3` → `game_status >= 2` — shows scores for in-progress (2) and final (3) games.

### Fix 3: Tonight refresh on live-export tick
**File:** `orchestration/cloud_functions/live_export/main.py`

**Problem:** `tonight/all-players.json` generated once pre-game, never refreshed.

**Fix:** Added `TonightAllPlayersExporter.export()` call after live grading in `run_live_export()`. Runs on each 2-3 min tick. Queries are partition-filtered and lightweight.

### Fix 4: Actual/result in picks/{date}.json
**File:** `data_processors/publishing/all_subsets_picks_exporter.py`

**Problem:** Neither materialized nor on-the-fly path included actual points or result.

**Fix:**
- Added LEFT JOIN `player_game_summary` in `_query_materialized_picks()`
- Added `pgs.points as actual_points` to `_query_all_predictions()` SELECT
- Added `actual`/`result` (hit/miss/push/null) computation in both `_build_json_from_materialized()` and `_build_json_on_the_fly()`

### Fix 5: Actuals in best-bets/latest.json for current date
**File:** `data_processors/publishing/best_bets_exporter.py`

**Problem:** Predictions-table branch hardcoded `NULL as actual_points` and `NULL as prediction_correct`.

**Fix:** Added LEFT JOIN `player_game_summary` and computed `actual_points`, `prediction_correct`, `absolute_error`, `signed_error` from real data. Pre-game: all NULL (no regression). Post-game: real values.

### Fix 6: season.json excluding today's picks
**File:** `data_processors/publishing/season_subset_picks_exporter.py`

**Problem:** `end_date = today.isoformat()` with `game_date < @end_date` excluded today.

**Fix:** Changed to `end_date = (today + timedelta(days=1)).isoformat()` — includes today.

### Fix 7: Post-game re-export trigger
**File:** `orchestration/cloud_functions/live_export/main.py`

**Problem:** After all games go final, picks/best-bets/season files still had null actuals until 5 AM scheduler.

**Fix:** After live exports, checks if all games are final via `nbac_schedule`. If so:
1. Checks GCS marker (`v1/live/post-game-{date}.done`) to avoid duplicates
2. Publishes to `nba-phase6-export-trigger` with `export_types: [best-bets, subset-picks, season-subsets, tonight]`
3. Writes marker file

All wrapped in try/except — non-critical, won't fail live export on error.

## New API Fields (Frontend Reference)

### picks/{date}.json — each pick object
```json
{
  "actual": 28,        // int or null (pre-game)
  "result": "hit"      // "hit" | "miss" | "push" | null
}
```

### best-bets/latest.json — each pick object
No new fields — `actual`, `result`, `error` were already in the schema but populated with null for current-date picks. Now populated post-game.

### live-grading/latest.json — predictions with PASS/NO_LINE
Previously: `status: "graded"`, `margin_vs_line: null`
Now: `status: "correct"/"incorrect"`, `margin_vs_line: -4.5` (computed)

### tonight/all-players.json
- `home_score`/`away_score` now populated during in-progress games (were null until final)
- File now refreshes every 2-3 min during games (was static pre-game snapshot)

### subsets/season.json
- Today's picks now included (were excluded due to off-by-one)

## Deployment

All changes auto-deploy via Cloud Build on push to main:
- `data_processors/publishing/` → affects Phase 6 export infrastructure
- `orchestration/cloud_functions/live_export/` → deploys as Cloud Function

## Verification

```bash
# After games complete, verify JSON has actuals:
gsutil cat gs://nba-props-platform-api/v1/picks/2026-02-11.json | python -m json.tool | head -50
gsutil cat gs://nba-props-platform-api/v1/best-bets/latest.json | python -m json.tool | head -30
gsutil cat gs://nba-props-platform-api/v1/live-grading/latest.json | python -m json.tool | head -30
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json | python -m json.tool | grep -A2 score

# Check post-game marker was written:
gsutil ls gs://nba-props-platform-api/v1/live/post-game-2026-02-11.done

# Check Cloud Build deployed successfully:
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

## Key Design Decisions

1. **Inferred direction for PASS/NO_LINE** — These predictions still have a `line_value` and `predicted_points`, so we can meaningfully grade them. Using `predicted > line` to infer OVER/UNDER matches how the model would have recommended if the line source were real.

2. **Tonight refresh on every tick** — The queries are all partition-filtered (~5-15s). This is simpler than tracking game state changes, and the 2-3 min cadence is already acceptable for live data.

3. **GCS marker for post-game dedup** — Simple, stateless, no database needed. Marker cleanup is unnecessary (tiny files, one per game day).

4. **Non-critical wrapping** — All new functionality is wrapped in try/except so failures don't break existing live export behavior.

## Related Documentation

- `docs/08-projects/current/session-214-gcs-live-updates/FRONTEND-API-CHANGES.md` — Frontend field reference

---

**Session completed:** 2026-02-11
**Next session:** Monitor tonight's games to verify live updates work end-to-end. Check post-game marker is created and Phase 6 re-export triggers successfully.
