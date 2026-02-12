# Frontend API Reference — GCS JSON Endpoints

**Last Updated:** 2026-02-12
**Base URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/`

---

## Overview

The backend serves static JSON files from Google Cloud Storage. Files are generated/refreshed at specific points in the pipeline lifecycle. All data flows through a 6-phase pipeline that runs daily starting ~6 AM ET.

### Game-Day Timeline

| Time (ET) | What Happens | Files Updated |
|-----------|-------------|---------------|
| ~6-8 AM | Predictions generated (Phase 5→6) | `picks/{date}.json`, `best-bets/latest.json`, `tonight/all-players.json`, `subsets/season.json` |
| ~7 PM - 1 AM | Games in progress | `tonight/all-players.json`, `live-grading/latest.json`, `live/latest.json` (every 3 min) |
| ~30 min after last game | Post-game re-export | `picks/{date}.json`, `best-bets/latest.json`, `subsets/season.json`, `tonight/all-players.json` |
| ~6 AM next day | Morning pipeline processes results | All files refreshed with final actuals |

### Date Logic

The live-export system uses **Pacific Time with a 1 AM cutover**:
- Between midnight and 1 AM PT → still tracks the previous day's games
- After 1 AM PT → switches to the new day

This ensures late west-coast games (which can end past midnight ET) are still treated as "tonight."

### Cache TTLs

| File | Cache-Control | Notes |
|------|--------------|-------|
| `tonight/all-players.json` | `max-age=300` (5 min) | Refreshed every 3 min during games |
| `live-grading/latest.json` | `max-age=30` (30 sec) | Near-real-time during games |
| `live/latest.json` | `max-age=30` (30 sec) | Live scores |
| `picks/{date}.json` | `max-age=300` (5 min) | Refreshed on re-export |
| `best-bets/{date}.json` | `max-age=86400` (1 day) | Historical dates |
| `best-bets/latest.json` | `max-age=300` (5 min) | Current day |
| `subsets/season.json` | `max-age=3600` (1 hour) | Full season data |

To bust cache during games, append `?t={timestamp}`.

---

## Endpoints

### 1. `tonight/all-players.json` — Homepage Player Cards

The primary initial page load endpoint (~150-800 KB). Contains all players in tonight's games with prediction, fatigue, injury, and stats data.

**Also available as:** `tonight/{date}.json` (date-specific, long cache)

**Refresh:** Static pre-game snapshot, then every 3 minutes during game windows.

```jsonc
{
  "game_date": "2026-02-11",
  "generated_at": "2026-02-11T07:00:00Z",
  "total_players": 481,
  "total_with_lines": 192,
  "games": [
    {
      "game_id": "20260211_LAL_DEN",
      "home_team": "DEN",
      "away_team": "LAL",
      "game_time": "7:30 PM ET",           // Lock time for betting
      "game_status": "scheduled",           // "scheduled" | "in_progress" | "final"
      "home_score": null,                   // int during in_progress/final, null pre-game
      "away_score": null,                   // int during in_progress/final, null pre-game
      "player_count": 35,
      "players": [
        {
          // Identity
          "player_lookup": "lebron-james",  // Stable ID for linking
          "name": "LeBron James",
          "team": "LAL",
          "is_home": false,

          // Status
          "has_line": true,                 // Has a sportsbook prop line
          "injury_status": "available",     // "available" | "questionable" | "doubtful" | "out"
          "injury_reason": null,            // e.g., "Right Ankle Soreness"
          "limited_data": false,            // true if < 10 games played

          // Fatigue
          "fatigue_level": "normal",        // "fresh" | "normal" | "tired"
          "fatigue_score": 82.5,            // 0-100, higher = more rested
          "days_rest": 2,

          // Season Stats
          "season_ppg": 25.3,
          "season_mpg": 35.2,
          "minutes_avg": 35.2,              // Same as season_mpg
          "last_5_ppg": 28.1,
          "games_played": 45,

          // Recent Form
          "recent_form": "Hot",             // "Hot" | "Cold" | "Neutral" | null

          // Last 10 Games (for sparkline charts)
          "last_10_points": [28, 22, null, 31, 19, 25, 30, 27, 24, 33],  // null = DNP
          "last_10_lines": [24.5, 24.5, null, 25.0, 24.5, 24.5, 25.0, 24.5, 24.5, 25.0],
          "last_10_results": ["O", "U", "DNP", "O", "U", "O", "O", "O", "U", "O"],  // vs line
          "last_10_record": "6-3",          // O-U record (excludes DNP)
          "last_10_vs_avg": ["O", "U", "DNP", "O", "U", "O", "O", "O", "U", "O"],  // vs season avg
          "last_10_avg_record": "6-3",

          // Props (only when has_line = true)
          "props": [{
            "stat_type": "points",
            "line": 24.5,
            "over_odds": -110,              // American odds, null if unavailable
            "under_odds": -110
          }],

          // Prediction (only when has_line = true)
          "prediction": {
            "predicted": 27.5,
            "confidence": 0.72,
            "recommendation": "OVER",       // "OVER" | "UNDER" | "PASS" | "NO_LINE"
            "factors": [                    // Up to 4 directional factors
              "Strong model conviction (5.3 point edge)",
              "Trending over: 6-3 last 10",
              "Well-rested, favors performance"
            ]
          }
        }
      ]
    }
  ]
}
```

**Player sort order:** Players with lines first (by confidence desc), then without (by PPG desc). OUT players last.

---

### 2. `picks/{date}.json` — Daily Subset Picks

All subset groups' picks for a date. Includes daily signal and W-L records per subset. Multi-model structure (v2).

```jsonc
{
  "date": "2026-02-11",
  "generated_at": "2026-02-11T07:00:00Z",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix",               // Codename for the model
      "model_name": "Phoenix",             // Display name
      "model_type": "primary",             // "primary" | "challenger" | "quantile"
      "description": "Our primary prediction engine",
      "signal": "favorable",               // "favorable" | "neutral" | "challenging"
      "subsets": [
        {
          "id": "1",
          "name": "Top Pick",              // Public-facing subset name
          "record": {                       // W-L records, null for new models
            "season": { "wins": 42, "losses": 18, "pct": 70.0 },
            "month":  { "wins": 8,  "losses": 3,  "pct": 72.7 },
            "week":   { "wins": 3,  "losses": 1,  "pct": 75.0 }
          },
          "picks": [
            {
              "player_lookup": "jarrettallen",
              "player": "Jarrett Allen",
              "team": "CLE",
              "opponent": "WAS",
              "prediction": 26.2,           // Model's predicted points
              "line": 16.5,                 // Sportsbook line
              "direction": "OVER",          // "OVER" | "UNDER"
              "created_at": "2026-02-11T21:10:35Z",
              "actual": 28,                 // int — actual points scored. null pre-game.
              "result": "hit"               // "hit" | "miss" | "push" | null
            }
          ]
        }
      ]
    }
  ]
}
```

**`result` values:**
- `"hit"` — prediction correct (OVER and scored > line, or UNDER and scored < line)
- `"miss"` — prediction wrong
- `"push"` — actual == line (tie)
- `null` — game not played yet, or direction is not OVER/UNDER

**`signal` values:**
- `"favorable"` — market conditions favor the model (GREEN internally)
- `"neutral"` — normal conditions (YELLOW)
- `"challenging"` — difficult market conditions (RED)

**`record`:** Can be `null` for new/challenger models — display a "New" badge.

---

### 3. `best-bets/latest.json` — Top Tiered Picks

Top prediction picks using tiered selection (premium/strong/value) based on edge size.

**Also available as:** `best-bets/{date}.json` (date-specific)

```jsonc
{
  "game_date": "2026-02-11",
  "generated_at": "2026-02-11T07:00:00Z",
  "methodology": "Tiered selection: edge/confidence thresholds",
  "total_picks": 22,
  "tier_summary": {
    "premium": 3,                           // 5+ point edge (83-88% target hit rate)
    "strong": 8,                            // 3-5 point edge (74-79%)
    "value": 11,                            // <3 point edge (63-69%)
    "standard": 0
  },
  "picks": [
    {
      "rank": 1,
      "tier": "premium",                   // "premium" | "strong" | "value" | "standard"
      "player_lookup": "jarrettallen",
      "player_full_name": "Jarrett Allen",
      "game_id": "20260211_WAS_CLE",
      "team": "CLE",
      "opponent": "WAS",
      "recommendation": "OVER",            // "OVER" | "UNDER"
      "line": 16.5,
      "predicted": 26.2,
      "edge": 9.7,                         // abs(predicted - line)
      "confidence": 0.85,
      "composite_score": 1.234,            // Ranking score (higher = better)
      "player_historical_accuracy": 0.72,  // Past accuracy for this player, null if < 5 games
      "player_sample_size": 15,
      "fatigue_score": 88.0,               // 0-100
      "fatigue_level": "normal",           // "fresh" | "normal" | "tired" | null
      "rationale": [                        // Human-readable reasons for the pick
        "Premium pick: highest confidence tier (target 92%+ hit rate)",
        "Strong edge (9.7 points)",
        "Good track record (72% accuracy, 15 games)"
      ],
      "result": "WIN",                     // "WIN" | "LOSS" | "PUSH" | "PENDING"
      "actual": 28,                        // int or null
      "error": 1.8                         // float — absolute error, or null
    }
  ]
}
```

**Note:** `result` uses uppercase here (`"WIN"`/`"LOSS"`/`"PUSH"`/`"PENDING"`) vs lowercase in picks (`"hit"`/`"miss"`/`"push"`/`null`).

---

### 4. `live-grading/latest.json` — Real-Time Prediction Accuracy

Live grading of all predictions against actual scores during games. Updates every 30 seconds during game windows.

**Also available as:** `live-grading/{date}.json`

```jsonc
{
  "updated_at": "2026-02-11T21:30:00Z",
  "game_date": "2026-02-11",
  "summary": {
    "total_predictions": 196,
    "graded": 180,                          // Have actual data
    "pending": 16,                          // Waiting for game to start
    "correct": 45,                          // Final games, prediction right
    "incorrect": 22,                        // Final games, prediction wrong
    "trending_correct": 30,                 // In-progress, currently winning
    "trending_incorrect": 15,               // In-progress, currently losing
    "win_rate": 0.672,                      // correct / (correct + incorrect), null if 0
    "avg_error": 4.2,                       // Mean absolute error
    "games_in_progress": 5,
    "games_final": 9
  },
  "predictions": [
    {
      "player_lookup": "lebron-james",
      "player_name": "LeBron James",
      "team": "LAL",
      "home_team": "DEN",
      "away_team": "LAL",
      "game_status": "in_progress",         // "scheduled" | "in_progress" | "final"
      "period": 3,                          // Current quarter (1-4, 5+ for OT)
      "time_remaining": "5:30",
      "predicted": 27.5,
      "line": 24.5,
      "recommendation": "OVER",            // "OVER" | "UNDER" | "PASS" | "NO_LINE"
      "confidence": 0.72,
      "has_line": true,
      "line_source": "ODDS_API",           // Where the line came from
      "actual": 20,                         // Current points (live), null pre-game
      "minutes": "28:30",                   // Minutes played so far
      "error": 7.5,                         // predicted - actual
      "margin_vs_line": -4.5,              // actual - line (negative = under the line)
      "status": "in_progress"               // See status values below
    }
  ]
}
```

**`status` values (sorted in this display order):**
1. `"correct"` — final game, prediction was right
2. `"incorrect"` — final game, prediction was wrong
3. `"trending_correct"` — in-progress, currently on the right side
4. `"trending_incorrect"` — in-progress, currently on the wrong side
5. `"in_progress"` — in-progress, too close to call (within 5 points)
6. `"graded"` — final game, no line to grade against (rare)
7. `"pending"` — game hasn't started

**Predictions sort:** By status (above order), then by confidence descending within each status group.

**PASS/NO_LINE predictions:** These still have a `line` value and get graded using inferred direction (predicted > line → treated as OVER). They receive proper `correct`/`incorrect` status and `margin_vs_line`.

---

### 5. `subsets/season.json` — Full Season History

Full-season picks with results for all models. Used for the subset picks page with date tabs.

```jsonc
{
  "generated_at": "2026-02-11T07:00:00Z",
  "version": 2,
  "season": "2025-26",
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "model_type": "primary",
      "record": {                           // Aggregate W-L, null for new models
        "season": { "wins": 42, "losses": 18, "pct": 70.0 },
        "month":  { "wins": 8,  "losses": 3,  "pct": 72.7 },
        "week":   { "wins": 3,  "losses": 1,  "pct": 75.0 }
      },
      "dates": [                            // Reverse chronological
        {
          "date": "2026-02-11",
          "signal": "favorable",
          "picks": [
            {
              "player": "Jarrett Allen",
              "team": "CLE",
              "opponent": "WAS",
              "prediction": 26.2,
              "line": 16.5,
              "direction": "OVER",
              "created_at": "2026-02-11T21:10:35Z",
              "actual": 28,                 // int or null
              "result": "hit"               // "hit" | "miss" | "push" | null
            }
          ]
        }
      ]
    }
  ]
}
```

**Includes today's picks** (previously excluded due to a date range bug, now fixed).

---

### 6. `live/latest.json` — Raw Live Scores

Live game scores from BallDontLie API. Refreshed every 30 seconds during games.

**Also available as:** `live/{date}.json`

```jsonc
{
  "updated_at": "2026-02-11T21:30:00Z",
  "game_date": "2026-02-11",
  "games": [
    {
      "game_id": "20260211_LAL_DEN",
      "home_team": "DEN",
      "away_team": "LAL",
      "status": "in_progress",
      "period": 3,
      "time": "5:30",
      "home_score": 78,
      "away_score": 72,
      "players": {
        "lebron-james": {
          "points": 20,
          "minutes": "28:30",
          "team": "LAL"
        }
      }
    }
  ],
  "summary": {
    "total_games": 14,
    "in_progress": 5,
    "final": 9,
    "scheduled": 0
  }
}
```

---

### 7. `status.json` — Pipeline Health

Overall system status for frontend health indicators.

```jsonc
{
  "generated_at": "2026-02-11T21:30:00Z",
  "status": "healthy",                     // "healthy" | "degraded" | "down"
  "issues": [],
  "components": { ... }
}
```

---

## Data Lifecycle: A Pick's Journey

```
Pre-game (6-8 AM ET):
  prediction = 26.2, line = 16.5, direction = OVER
  actual = null, result = null

During game (7 PM - midnight):
  [tonight/all-players.json updates every 3 min with game_status and scores]
  [live-grading/latest.json shows trending status and live points]

Post-game (~30 min after last game):
  [Post-game trigger fires → re-exports picks, best-bets, season, tonight]
  actual = 28, result = "hit"

Next morning (6 AM):
  [Full pipeline reprocesses → all files refreshed with final validated data]
```

---

## Key Patterns for Frontend

### Determining if a game has results
```javascript
// For picks/season files:
if (pick.actual !== null) {
  // Game completed — show result badge
  showResult(pick.result); // "hit" | "miss" | "push"
} else {
  // Pre-game or in-progress — show prediction only
}

// For best-bets:
if (pick.result !== "PENDING") {
  showResult(pick.result); // "WIN" | "LOSS" | "PUSH"
}
```

### Determining game state (tonight file)
```javascript
switch (game.game_status) {
  case "scheduled":
    // Show game time, countdown to lock
    break;
  case "in_progress":
    // Show live score (home_score, away_score)
    // Scores refresh every 3 min
    break;
  case "final":
    // Show final score
    break;
}
```

### Live grading status colors
```javascript
const statusColors = {
  correct: "green",
  incorrect: "red",
  trending_correct: "light-green",
  trending_incorrect: "light-red",
  in_progress: "yellow",
  graded: "gray",
  pending: "gray",
};
```

### Handling null records (new models)
```javascript
if (modelGroup.record === null) {
  // New model — show "New" badge instead of W-L record
}
```

---

## Common Pitfalls

1. **`result` casing differs by endpoint** — picks/season use lowercase (`"hit"`/`"miss"`), best-bets use uppercase (`"WIN"`/`"LOSS"`). This is intentional.

2. **`actual` can be 0** — A player can score 0 points. Check `actual !== null` not `actual` for truthiness.

3. **Scores null despite final status** — `home_score`/`away_score` in tonight can be null even when `game_status` is `"final"` if the schedule scraper hasn't refreshed yet. Handle gracefully (show "Final" without score).

4. **`prediction` object only exists for players with lines** — Check `has_line` before accessing `player.prediction`.

5. **`record` can be null** — New/challenger models have no grading history yet.

6. **Tonight file is large** — ~150-800 KB depending on game count. Consider whether you need to fetch it frequently or can cache aggressively.
