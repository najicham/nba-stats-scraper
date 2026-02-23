# Bug Report — Live Grading Pipeline Not Updating + Tonight Actuals Still Missing

**Date:** 2026-02-22 (observed ~11 PM ET)
**Source:** Frontend debugging — Tonight page showing "Waiting on Results" for finished games
**Severity:** User-facing — live scores and final results never appear
**Related:** Doc 10 (WAITING-ON-RESULTS-BUG.md) — same symptom, thought to be fixed

---

## Problem Summary

Two data issues on 2026-02-22 (11-game slate):

1. **`live-grading/latest.json` is completely stale** — all 52 predictions stuck at `game_status: "scheduled"` and `status: "pending"` even though 3 games are final and 3 are in progress. No `actual` values populated for any player.

2. **`tonight/all-players.json` has correct game statuses but no actuals** — the file was regenerated at `2026-02-23T03:51:32 UTC` (~10:51 PM ET) and correctly shows 3 games as `final`, 3 as `in_progress`, 5 as `scheduled`. However, `actual_points` is `null` for every single player, including those in finished games.

3. **Only 52 of 385 players have lines** — 4 of 11 games have zero players with lines (CLE@OKC, DAL@IND, PHI@MIN, POR@PHX). This may be expected if lines weren't published for those games, but worth confirming.

## Raw Data Evidence

### `tonight/all-players.json` (generated 2026-02-23T03:51:32 UTC)

| Game | Status | Players | Has Line | Has Prediction | Has Actual |
|------|--------|---------|----------|----------------|------------|
| CLE @ OKC | final | 36 | 0 | 0 | 0 |
| BKN @ ATL | final | 37 | 13 | 0 | 0 |
| DEN @ GSW | final | 32 | 8 | 0 | 0 |
| TOR @ MIL | final | 34 | 8 | 0 | 0 |
| DAL @ IND | in_progress | 35 | 0 | 0 | 0 |
| CHA @ WAS | in_progress | 38 | 4 | 0 | 0 |
| BOS @ LAL | in_progress | 33 | 7 | 0 | 0 |
| PHI @ MIN | scheduled | 34 | 0 | 0 | 0 |
| NYK @ CHI | scheduled | 36 | 7 | 0 | 0 |
| POR @ PHX | scheduled | 36 | 0 | 0 | 0 |
| ORL @ LAC | scheduled | 34 | 5 | 0 | 0 |

Key observations:
- `game_status` is correct (matches real-world game states)
- `actual_points: null` for ALL players, including 3 finished games
- `predicted_points` is also missing from the top-level player objects (predictions are nested under `prediction.predicted` instead)
- `result: null` for all players

### `live-grading/latest.json` (updated 2026-02-23T03:51:28 UTC)

```json
{
  "summary": {
    "total_predictions": 52,
    "graded": 0,
    "pending": 52,
    "games_in_progress": 0,
    "games_final": 0
  }
}
```

- ALL 52 predictions show `game_status: "scheduled"` — none updated to `in_progress` or `final`
- ALL show `status: "pending"`, `actual: null`, `score_source: null`
- The file WAS regenerated recently (03:51 UTC) but with completely stale game status data

Sample prediction from a FINISHED game (TOR @ MIL):
```json
{
  "player_lookup": "immanuelquickley",
  "game_status": "scheduled",     // WRONG — game is final
  "status": "pending",            // WRONG — should be graded
  "actual": null,                 // MISSING — game is over
  "minutes": null,
  "score_source": null
}
```

## Root Cause Hypothesis

The live-grading pipeline appears to not be fetching/updating live box score data at all. The file is being regenerated (timestamp is fresh) but the content is never enriched with live scores or game statuses. This suggests either:

1. **The live score data source is not being queried** — the pipeline regenerates the file from predictions alone without checking NBA API / box scores
2. **The live export Cloud Function is running but the score-fetching step is failing silently** — the function executes and writes a file, but the upstream score data is empty/errored
3. **Permissions or API key issue** — if live scores come from an external NBA API, the credentials may have expired

For the tonight JSON: the previous fix (doc 10) added a re-export step to `post_grading_export`, but that only runs after grading completes (6-8 AM ET). The live export should be populating actuals during and shortly after games, but it's clearly not doing so.

## Questions for Backend

1. **Is the `live_export` Cloud Function running?** Check Cloud Function logs for tonight (2026-02-22). Is it being triggered on its schedule? Are there any errors?

2. **Where does `live_export` get live box scores from?** Is it querying an NBA API, scraping, or reading from BigQuery? Whatever the source, it's returning empty data.

3. **Why does `live-grading/latest.json` show `game_status: "scheduled"` for finished games?** The tonight JSON correctly shows `final` — so some pipeline knows the games are over. But the live-grading pipeline doesn't.

4. **Are the 4 games with zero lines expected?** CLE@OKC, DAL@IND, PHI@MIN, POR@PHX all have 0 players with `has_line: true`. Were prop lines simply not published for these games, or is there a scraping gap?

5. **Is `predicted_points` intentionally missing from the top-level player object?** The tonight JSON has predictions nested under `prediction.predicted` but `predicted_points` at the top level appears to not exist. The frontend type expects `predicted_points` at the top level. Is this a schema change?

## Expected Behavior

During game hours:
- `live-grading/latest.json` should update every ~30s with current `game_status`, `actual` points (live or final), and `minutes`
- `tonight/all-players.json` should be periodically refreshed with `actual_points` from live box scores

After games finish:
- Both files should reflect `game_status: "final"` with populated `actual_points` / `actual`
- The post-grading re-export (doc 10 fix) should catch any gaps the next morning

## Frontend Impact

Users see:
- "Waiting on Results" indefinitely on finished games
- No live score updates during in-progress games
- No WIN/LOSS result indicators after games end

The frontend code is correct — it displays "Waiting on Results" when `game_status === "final"` and `actual_points === null`. The data just never arrives.

---

## Update — 2026-02-23 ~12:15 AM ET: Fix Did Not Stick

Doc 12 (`LIVE-GRADING-BUG-RESOLUTION.md`) reported that the `BDL_API_KEY` was added to the `live-export` Cloud Run service and that 51/52 predictions were graded as of ~11:15 PM ET.

**However, as of 12:15 AM ET the data has reverted to fully stale:**

```
live-grading/latest.json (updated 2026-02-23T05:15:13 UTC = 12:15 AM ET):
  game_status distribution: {'scheduled': 152}  — ALL scheduled, none final
  score_source distribution: {None: 152}         — no BDL data
  status distribution: {'pending': 152}           — nothing graded
  actual: null for all 152 predictions
```

Meanwhile `tonight/all-players.json` correctly shows all 11 games as `final` (from the schedule scraper), confirming games are over. The live-grading service is writing fresh files (timestamp is current) but with completely empty score data — identical to the original bug.

**The `BDL_API_KEY` env var was likely lost again.** Possible causes:
1. The Cloud Run service was redeployed after the manual fix, wiping the env var again
2. The fix was applied to the wrong revision and a new revision rolled out without it
3. The deploy script fix (`deploy_live_export.sh`) wasn't used for the most recent deploy

**Action needed:**
1. Verify `BDL_API_KEY` is currently set on the **active revision** of the `live-export` Cloud Run service: `gcloud run services describe live-export --format='value(spec.template.spec.containers[0].env)'`
2. If missing, re-add it and **verify it persists across a test redeploy** using the updated deploy script
3. Consider moving `BDL_API_KEY` to a Secret Manager volume mount instead of an env var — volume mounts survive `--set-env-vars` wipes

The frontend is fully wired and ready — `useLiveUpdates` polls every 30s, `mergeWithLiveData` correctly enriches players with live actuals. The moment the backend actually delivers data, everything will work.
