# Frontend API Changes — Session 214 (GCS Live Updates)

**Date:** 2026-02-11
**Base URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/`

All changes are **additive** — new fields are added, no existing fields removed or renamed. Pre-game values are null, so existing rendering code won't break.

---

## 1. `picks/{date}.json` — New fields on each pick

Each pick object inside `model_groups[].subsets[].picks[]` now includes:

```jsonc
{
  "player_lookup": "lebron-james",
  "player": "LeBron James",
  "team": "LAL",
  "opponent": "BOS",
  "prediction": 26.1,
  "line": 24.5,
  "direction": "OVER",
  "created_at": "2026-02-11T12:00:00Z",

  // NEW FIELDS (Session 214):
  "actual": 28,          // int — player's actual points scored. null pre-game.
  "result": "hit"        // string — "hit" | "miss" | "push" | null
                         //   "hit"  = prediction correct (OVER and scored > line, or UNDER and scored < line)
                         //   "miss" = prediction wrong
                         //   "push" = actual == line (tie)
                         //   null   = game not played yet, or direction is not OVER/UNDER
}
```

**Timing:** Fields populate after Phase 3 analytics runs (~30 min after game ends), then refreshed by post-game re-export trigger.

**Frontend suggestion:** Show a results badge (green check/red X) when `result` is non-null. Show `actual` as "Scored: 28" next to the line.

---

## 2. `best-bets/latest.json` — No new fields, existing fields now populate

The `actual`, `result`, and `error` fields were already in the schema but were always null for current-date picks. They now populate post-game:

```jsonc
{
  "rank": 1,
  "tier": "premium",
  "player_lookup": "player-name",
  "recommendation": "UNDER",
  "line": 12.5,
  "predicted": 7.2,

  // These fields were always present but null for today. Now populate post-game:
  "result": "WIN",       // "WIN" | "LOSS" | "PUSH" | "PENDING"
  "actual": 10,          // int or null
  "error": 2.8           // float — absolute error, or null
}
```

**Note:** `result` uses uppercase ("WIN"/"LOSS"/"PUSH"/"PENDING") in best-bets, vs lowercase ("hit"/"miss"/"push"/null) in picks. This is the existing convention.

---

## 3. `live-grading/latest.json` — Improved status for PASS/NO_LINE predictions

Previously, predictions with `recommendation: "PASS"` or `"NO_LINE"` got:
```json
{ "status": "graded", "margin_vs_line": null }
```

Now they get proper grading:
```json
{ "status": "correct", "margin_vs_line": 3.5 }
```

**Status values** (unchanged set, now applies to all predictions with a line):
- `"correct"` — final game, prediction was right
- `"incorrect"` — final game, prediction was wrong
- `"trending_correct"` — in-progress, currently winning
- `"trending_incorrect"` — in-progress, currently losing
- `"in_progress"` — in-progress, too close to call
- `"graded"` — final game, but no line available to grade against
- `"pending"` — game hasn't started

**Frontend suggestion:** If you were filtering out `status: "graded"` predictions from win/loss counts, you can now include them — they'll have proper correct/incorrect status.

---

## 4. `tonight/all-players.json` — Scores during in-progress games

Previously, `home_score` and `away_score` were null until game was final. Now they populate during in-progress games:

```jsonc
{
  "games": [
    {
      "game_id": "20260211_LAL_BOS",
      "home_team": "BOS",
      "away_team": "LAL",
      "game_status": "in_progress",  // was always here
      "home_score": 54,              // NEW: populated during in-progress (was null)
      "away_score": 48,              // NEW: populated during in-progress (was null)
      "players": [...]
    }
  ]
}
```

**Refresh rate:** This file now refreshes every 2-3 minutes during game windows (was a static pre-game snapshot).

**Frontend suggestion:** Show live score in the game header when `game_status` is `"in_progress"`. The 2-3 min refresh cadence matches the live-grading updates.

---

## 5. `subsets/season.json` — Today's picks now included

Previously excluded today due to an off-by-one in the date range query. Today's picks now appear in the season file alongside historical data.

No field changes — just data completeness fix.

---

## Refresh Timeline

| Phase | What Updates | When |
|-------|-------------|------|
| Pre-game | All files generated with predictions, null actuals | Phase 5→6 (~6-8 AM ET) |
| During games | `tonight/all-players.json`, `live-grading/latest.json` | Every 2-3 min |
| Post-game | `picks/{date}.json`, `best-bets/latest.json`, `subsets/season.json`, `tonight/all-players.json` | ~30 min after last game ends |

---

## Migration Notes

- **No breaking changes** — all new fields are additive with null defaults
- **Client-side workarounds using live-grading for actuals can be removed** once these changes are verified in production
- **Cache busting:** `tonight/all-players.json` has `max-age=300` (5 min). During games, the 2-3 min refresh means the CDN will have fresh data within ~5 min. If faster updates are needed, append `?t={timestamp}` to bypass cache.
