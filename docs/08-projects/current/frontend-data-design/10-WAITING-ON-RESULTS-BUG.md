# Bug Report — "Waiting on Results" on Finished Games

**Date:** 2026-02-22
**Source:** Frontend observation on the Tonight page
**Severity:** User-facing — players see stale data

---

## Problem

Multiple player cards on the Tonight page (`/`) show **"Waiting on Results"** for games that have already finished. This message displays when `game_status === "final"` but `actual_points === null` — meaning the game ended but the player's actual stat line was never written back to the data file.

## Where This Shows

**Frontend component:** `src/components/cards/PlayerCard.tsx`, `GameCountdown` function (line 1125-1129):

```typescript
// Game is final but no actual_points
if (isFinal || gameStatus === "final") {
  if (isDNP) {
    return <span>Did Not Play</span>;
  }
  return <span>Waiting on Results</span>;
}
```

**Data source:** `/api/proxy/tonight/{date}.json` — the per-player prediction objects have:
- `game_status: "final"` (correctly set — the game is over)
- `actual_points: null` (not populated — this is the bug)

## Questions for Backend

1. **Which pipeline writes `actual_points` to the tonight JSON files?** Is it the same grading pipeline that grades best-bets picks, or a separate process?

2. **Is this a timing issue or a permanent miss?** Are these games that just finished and will be populated on the next export cycle (~6 AM ET), or are they stuck permanently with `actual_points: null`?

3. **Does this affect only tonight's data or historical dates too?** If I navigate to yesterday's date on the Tonight page, are those `actual_points` populated correctly?

4. **Is this related to the DNP/void fix from Session 330?** The 6 ungraded picks were DNP players. Could the same pipeline gap be causing non-DNP players to also show null actuals?

5. **Is there a separate live-scoring data source?** The frontend has a `useLiveUpdates` hook that polls during game hours. If the live data has actual scores but the static JSON doesn't, we could potentially fall back to the live data for final games.

## Expected Behavior

When `game_status === "final"`:
- `actual_points` should be populated with the player's final stat line
- The player card should show the actual points and a WIN/LOSS/PUSH result indicator
- "Waiting on Results" should only appear briefly between game end and the next data refresh (minutes, not hours)

## Current Impact

Users checking the Tonight page after games finish see "Waiting on Results" indefinitely, which makes the site look broken or stale. This undermines the "fresh, fast, reliable" impression we want.

---

## Backend Response (Session 332)

**Root cause:** Timing gap in the export pipeline. The tonight JSON was last refreshed by the `live_export` Cloud Function during games (~7 PM–1 AM ET), but `player_game_summary` (the source for `actual_points`) isn't populated until Phase 3 runs after box scores are scraped. The post-grading export — which runs AFTER Phase 3 + grading complete — re-exported picks and season data but **did not** re-export tonight JSON. By the time it runs, actuals ARE available; we just weren't re-exporting.

**Fix:** Added tonight JSON re-export as step 6 of `post_grading_export` Cloud Function. Now when grading completes, `tonight/all-players.json` is refreshed with `actual_points` populated from `player_game_summary`.

### Answers to Frontend Questions

1. **Which pipeline writes `actual_points`?** The `TonightAllPlayersExporter` queries `player_game_summary` at export time — same underlying data source as grading. It's not a separate process; the exporter JOINs actuals in at query time. The gap was that no one re-ran the tonight export after actuals were available.

2. **Timing issue or permanent miss?** Timing issue. Actuals exist in BigQuery (via `player_game_summary`) but the tonight JSON wasn't being re-exported after they were populated. The fix adds a re-export step to the post-grading pipeline, so `actual_points` will be populated within minutes of grading completing (~6–8 AM ET the next morning).

3. **Historical dates affected?** No. Date-specific files (`tonight/YYYY-MM-DD.json`) are written with a 24h cache and were already correct by the next day's export cycle. The issue only affects `tonight/all-players.json` (the "latest" file) during the window between game completion and the next morning's export.

4. **Related to DNP/void fix?** No — separate issue. The DNP/void fix (Session 330) was about grading metadata (`player_status` field). This bug is purely about export timing — `actual_points` was available in BQ but not re-exported to the tonight JSON.

5. **Separate live-scoring source?** The `live_export` Cloud Function refreshes tonight JSON during games but stops at ~1 AM ET. After that, there were no more refreshes until the next day's Phase 6 export. The fix closes this gap by adding a re-export in the post-grading pipeline, which runs after grading completes (typically 6–8 AM ET).
