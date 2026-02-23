# Frontend Prompt — Live Grading Bug Resolution

**Date:** 2026-02-22 (late night)
**Context:** Follow-up to Doc 11 (LIVE-GRADING-STALE-DATA-BUG.md)
**Purpose:** Hand this to the frontend Claude Code session so it knows the backend status.

---

## Prompt

The live grading / tonight data bug you reported in Doc 11 has been investigated and resolved on the backend. Here's what happened and what you should expect going forward.

### Root Cause

The `live-export` Cloud Run service was missing the `BDL_API_KEY` environment variable. The BDL (Ball Don't Lie) API is the sole real-time data source for live box scores. Without the key:

- Every API call returned **401 Unauthorized**
- The service ran every 3 minutes on schedule and wrote files to GCS, but with **empty/stale data**
- The freshness monitor detected the staleness but couldn't alert anyone (missing `pandas` dependency + no Slack webhook configured)

The key existed in GCP Secret Manager but was never wired to the Cloud Run service as an env var. A previous deployment using `--set-env-vars` (which wipes all existing vars) likely removed it.

### What Was Fixed

1. **`BDL_API_KEY` env var added** to the `live-export` Cloud Run service — live scores now flowing
2. **Deploy script updated** (`bin/deploy/deploy_live_export.sh`) — now pulls `BDL_API_KEY` from Secret Manager automatically on deploy
3. **Env var verification script updated** (`bin/monitoring/verify-env-vars-preserved.sh`) — `live-export` service now has `BDL_API_KEY` as a required env var, so drift detection will catch this in the future

### Current Data State (as of ~11:15 PM ET, Feb 22)

#### `live-grading/latest.json` — FIXED
- **51 of 52 predictions graded** (was 0/52 before fix)
- `game_status` now correctly shows `final` for finished games
- `actual` values populated from BDL live API (`score_source: "bdl_live"`)
- `status` shows `correct`/`incorrect` (not stuck on `pending`)
- Win rate: 54.3% (25 correct, 21 incorrect)

#### `tonight/all-players.json` — Partially fixed
- `game_status` is correct (`final`/`in_progress`/`scheduled`) — this was always correct since it comes from the schedule scraper
- `actual_points` is still `null` for all players — this is **expected** because the tonight exporter sources actuals from BigQuery (`player_game_summary`), not BDL. Phase 3 analytics hasn't processed today's finished games yet
- **Actuals will populate automatically** when the post-grading export runs tomorrow morning (~6-8 AM ET). This is the fix from Doc 10 working as designed

#### Pipeline health
- **Predictions exist:** 152 active catboost_v9 predictions for Feb 22
- **Best bets exist:** 4 picks generated
- **Lines scraped:** 174 players with BettingPros lines (539K records)
- **No backfill needed** — the prediction pipeline ran normally

### Answers to Doc 11 Questions

1. **Is the `live_export` Cloud Function running?** Yes, it ran every 3 minutes on schedule. The function itself was healthy — it was the BDL API call inside it that failed silently (401).

2. **Where does `live_export` get live box scores from?** Ball Don't Lie (BDL) API (`https://api.balldontlie.io/v1/box_scores/live`). It also has a BigQuery fallback (`player_game_summary`) for final games, but that table isn't populated until Phase 3 analytics runs (typically next morning).

3. **Why does `live-grading/latest.json` show `game_status: "scheduled"` for finished games?** Because the live-grading exporter gets game status from BDL API data (which returned empty due to 401), while the tonight exporter gets game status from `nbac_schedule` in BigQuery (which was correct). Now that BDL is working, both show correct statuses.

4. **Are the 4 games with zero lines expected?** Yes. CLE@OKC, DAL@IND, PHI@MIN, POR@PHX had zero players that passed the zero-tolerance quality gate AND had matching prop lines. BettingPros scraping was healthy (174 players total). This is the feature quality filter working as intended.

5. **Is `predicted_points` intentionally missing from the top-level player object?** Yes — predictions are nested under `prediction.predicted` in the tonight JSON schema. The frontend should use `player.prediction.predicted` not `player.predicted_points`. This is the intended schema.

### What the Frontend Should Do

1. **Verify live-grading rendering** — refresh the Tonight page during tomorrow's games (Feb 23). `live-grading/latest.json` should now show real-time `actual` values, correct `game_status`, and `correct`/`incorrect` grading during games.

2. **Handle the actuals gap gracefully** — between game end and post-grading export (~6-8 AM ET), `tonight/all-players.json` will have correct `game_status: "final"` but `actual_points: null`. The frontend already handles this correctly ("Waiting on Results"). The data will arrive in the morning.

3. **Consider using `live-grading/latest.json` as the source for actuals during game hours** — this file updates every 30 seconds with BDL live data and has `actual` values for in-progress and final games. The tonight JSON only gets actuals from BigQuery (delayed). If you want real-time actuals on the Tonight page, you could merge data from both endpoints.

4. **No schema changes needed** — the JSON structures are working as documented. The `prediction.predicted` nesting is intentional.
