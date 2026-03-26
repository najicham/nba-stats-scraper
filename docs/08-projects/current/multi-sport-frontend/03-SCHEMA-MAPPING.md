# Multi-Sport Frontend — Schema Mapping

*Created: Session 488 (2026-03-25)*

## NBA → MLB Field Mapping

The frontend uses `BestBetsPick` as the canonical pick shape. MLB picks need to be mapped to this shape before being written to `all.json`.

| Frontend Field | NBA Source | MLB Source | Notes |
|---------------|-----------|-----------|-------|
| `player` | `player_display_name` | `pitcher_name` | Full name, display only |
| `player_lookup` | `player_lookup` | `pitcher_id` (or `pitcher_lookup`) | Normalized key (lowercase, no spaces) |
| `team` | `team_abbr` | `team_abbr` | 3-letter team code |
| `opponent` | `opponent_team_abbr` | `opponent_team_abbr` | 3-letter code |
| `home` | `is_home` | `is_home` | True = home |
| `direction` | `recommendation` | `recommendation` | "OVER" or "UNDER" |
| `stat` | `"PTS"` (hardcoded) | `"K"` (hardcoded) | Frontend stat label key |
| `line` | `line_value` | `strikeouts_line` | The prop line |
| `edge` | `ABS(predicted - line)` | `edge` | In stat units |
| `angles` | `signal_tags[]` | `[]` (none yet) | Signal tags — empty for now |
| `game_time` | `game_time` | `game_time` | ISO 8601 UTC |
| `is_ultra` | `is_ultra` | not applicable | MLB won't have this |
| `actual` | `actual_points` | `actual_strikeouts` | Null until graded |
| `result` | `"WIN"/"LOSS"/"VOID"` | `"WIN"/"LOSS"` | From `is_correct` |
| `void_reason` | `"DNP"/"NO_PROP_LINE"` | not applicable | MLB won't void same way |
| `rank` | `rank` (by edge) | `rank` (by edge) | 1 = best pick |
| `sport` | `"nba"` | `"mlb"` | New optional field |

## MLB Pick Shape (what BQ contains)

```sql
-- mlb_predictions.pitcher_strikeouts
pitcher_lookup        STRING    -- "gerritcole"
pitcher_name          STRING    -- "Gerrit Cole"
team_abbr             STRING    -- "NYY"
opponent_team_abbr    STRING    -- "BOS"
is_home               BOOLEAN   -- true
game_date             DATE      -- 2026-03-27
game_time             TIMESTAMP -- 2026-03-27T18:05:00Z
strikeouts_line       FLOAT64   -- 6.5
predicted_strikeouts  FLOAT64   -- 8.5
recommendation        STRING    -- "OVER"
confidence            FLOAT64   -- 0.72 (0–1 scale)
edge                  FLOAT64   -- 2.0 (in K units)
model_version         STRING    -- "catboost_mlb_v2_regressor_36f_20250928"
is_correct            BOOLEAN   -- null until graded
actual_strikeouts     INT64     -- null until graded
graded_at             TIMESTAMP -- null until graded
```

## Mapped Output Shape (what `all.json` today[] contains)

```json
{
  "rank": 1,
  "player": "Gerrit Cole",
  "player_lookup": "gerritcole",
  "team": "NYY",
  "opponent": "BOS",
  "home": true,
  "direction": "OVER",
  "stat": "K",
  "line": 6.5,
  "edge": 2.0,
  "angles": [],
  "game_time": "2026-03-27T18:05:00Z",
  "is_ultra": false,
  "actual": null,
  "result": null,
  "sport": "mlb"
}
```

## Result Mapping

| BQ `is_correct` | BQ `actual_strikeouts` | Frontend `result` | Frontend `actual` |
|-----------------|----------------------|-------------------|-------------------|
| `null` | `null` | `null` | `null` |
| `true` | `9` | `"WIN"` | `9` |
| `false` | `5` | `"LOSS"` | `5` |

No VOID equivalent for MLB (DNP doesn't apply to pitchers — if scratched, prediction is deleted).

## Record Window Computation

Backend computes these from BQ, frontend just displays:

```python
# Season = from 2026-03-27 (Opening Day) forward
season_wins   = COUNT(*) WHERE is_correct = TRUE AND game_date >= '2026-03-27'
season_losses = COUNT(*) WHERE is_correct = FALSE AND game_date >= '2026-03-27'

# Month = current calendar month
# Week = last 7 days
# Last 10 = last 10 graded picks
```

## Frontend Stat Label

The only frontend code change for MLB is adding `K` to the stat label map:

```typescript
// src/components/best-bets/BetCard.tsx (and TodayPicksTable.tsx)
const statLabel = (stat: string): string => {
  const labels: Record<string, string> = {
    PTS: "pts",    // NBA points
    REB: "reb",    // NBA rebounds
    AST: "ast",    // NBA assists
    "3PM": "3pm",  // NBA 3-pointers
    K: "k",        // MLB strikeouts  ← new
  };
  return labels[stat] ?? stat.toLowerCase();
};
```

A pick renders as: `O 6.5 k` (OVER 6.5 strikeouts).

## API URL Mapping

| Sport | GCS Path | Notes |
|-------|----------|-------|
| NBA | `v1/best-bets/all.json` | Existing |
| NBA | `v1/best-bets/{date}.json` | Per-date (not used by main page) |
| MLB | `v1/mlb/best-bets/all.json` | New — to be created |
| MLB | `v1/mlb/best-bets/{date}.json` | Per-date — existing exporter |

Frontend proxy maps these via `/api/proxy/{path}`.

## Confidence Field Difference

MLB exporter stores confidence as 0–1 decimal (`0.72`).
NBA best bets store edge as the primary ranking signal.

The frontend Best Bets page doesn't display confidence — it shows `edge`. So this difference is irrelevant for the best-bets page. (The Tonight page PlayerCard does display confidence, but MLB has no Tonight page.)

## Future Stats (not in scope now)

If we expand MLB beyond strikeouts:

| MLB Stat | `stat` value | Label |
|----------|-------------|-------|
| Strikeouts | `"K"` | `"k"` |
| Hits allowed | `"H"` | `"h"` |
| Walks | `"BB"` | `"bb"` |
| Innings pitched | `"IP"` | `"ip"` |
| ERA | `"ERA"` | `"era"` |
