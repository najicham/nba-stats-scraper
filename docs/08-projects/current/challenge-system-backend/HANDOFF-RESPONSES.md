# Backend Responses to Frontend Handoff Questions

**Created:** 2025-12-27
**In Response To:** `/home/naji/code/props-web/docs/06-projects/current/challenge-system/BACKEND-HANDOFF.md`

---

## Critical Questions (Answered)

### 1. player_lookup Format

**Answer:** Lowercase, no separators

**Examples:**
- `lebronjames` (not `lebron-james` or `lebron_james`)
- `traeyoung`
- `stephencurry`

**Consistency:** Guaranteed identical across:
- `/tonight/all-players.json`
- `/live/latest.json`
- `/live-grading/latest.json`

**Source:** Both tonight and live endpoints derive `player_lookup` from the same BigQuery tables (`nba_reference.nba_players_registry` and `bdl_player_boxscores`).

---

### 2. Live Endpoint for Players Whose Games Haven't Started

**Answer:** The `/live/latest.json` endpoint only returns data from the BallDontLie `/box_scores/live` API, which only includes games that are **currently in progress**.

**Behavior:**
- Before games start: Player NOT included in response
- During game: Player included with current stats
- After game ends: Player included with final stats (until next poll cycle)

**Workaround for frontend:**
1. Use `/tonight/all-players.json` as the source of truth for "who's playing tonight"
2. Cross-reference with `/live/latest.json` for live stats
3. If player not found in live, they haven't started yet

---

### 3. DNP (Did Not Play) Handling

**Answer:** Players who did not play appear with:
```json
{
  "player_lookup": "kevindurante",
  "points": 0,
  "rebounds": 0,
  "assists": 0,
  "minutes": "0:00"
}
```

**There is no explicit DNP flag.** Check for `minutes: "0:00"` or `minutes: null`.

**Grading impact:**
- `points: 0` means UNDER hits for any positive line
- No special handling needed

---

### 4. Postponed Games

**Answer:** The BallDontLie API does not return postponed games in the live endpoint.

**Current behavior:**
- Postponed game won't appear in `/live/latest.json`
- Schedule shows `game_status: "scheduled"` (no change to "postponed")

**Recommendation:** Frontend should handle the case where a game never appears in live data. If a game was in tonight's schedule but never shows up in live after expected start time, treat as potentially postponed.

**Future enhancement:** We can add a `postponed` status if the NBA schedule API provides this data.

---

### 5. time_remaining Format

**Answer:** Currently returns just the time: `"5:42"` or `"12:00"` or `"Final"`

**Current format:** `MM:SS` (no quarter prefix)

The quarter info is available separately in the `period` field:
```json
{
  "period": 3,
  "time_remaining": "5:42"
}
```

**Frontend can combine:** `Q${period} ${time_remaining}` → `"Q3 5:42"`

---

### 6. Update Frequency

**Confirmed schedules:**

| Endpoint | Frequency | Schedule |
|----------|-----------|----------|
| `/tonight/all-players.json` | Daily | Phase 6 export (~noon ET) |
| `/live/latest.json` | Every 3 min | 7 PM - 1 AM ET |
| `/live-grading/latest.json` | Every 3 min | 7 PM - 1 AM ET |
| `/results/{date}.json` | Daily | Phase 6 export (~5 AM ET next day) |

---

### 7. Historical Dates

**Answer:** Yes, historical live data works:
- `/live/2025-12-25.json` - Live data from Dec 25
- `/live-grading/2025-12-25.json` - Grading from Dec 25

**Note:** Only dates that had live polling will have data.

---

### 8. Error Responses (No Games)

**Answer:** Empty games array returned:
```json
{
  "updated_at": "2025-12-27T18:00:00Z",
  "game_date": "2025-12-27",
  "total_games": 0,
  "games_in_progress": 0,
  "games_final": 0,
  "games": []
}
```

---

## Schema Alignment Summary

### Tonight Endpoint (`/tonight/all-players.json`)

**Deployed schema:**
```json
{
  "game_date": "2025-12-27",
  "generated_at": "2025-12-27T18:00:00Z",
  "games": [{
    "game_id": "0022500432",
    "game_time": " 7:30 PM ET",
    "game_status": "scheduled",
    "home_team": "LAL",
    "away_team": "HOU",
    "players": [{
      "player_lookup": "lebronjames",
      "name": "LeBron James",
      "team": "LAL",
      "props": [{
        "stat_type": "points",
        "line": 24.5,
        "over_odds": -110,
        "under_odds": -110
      }],
      "prediction": {
        "predicted": 27.5,
        "confidence": 0.72,
        "recommendation": "OVER"
      }
    }]
  }]
}
```

**Differences from handoff doc:**
- `generated_at` instead of `updated_at` (minor)
- `prediction.predicted` instead of `prediction.predicted_value`
- No `position` field (can add if needed)

---

### Live Endpoint (`/live/latest.json`)

**Schema matches handoff requirements:**
```json
{
  "updated_at": "2025-12-27T21:30:00Z",
  "game_date": "2025-12-27",
  "games_in_progress": 2,
  "games_final": 1,
  "games": [{
    "game_id": "18447237",
    "status": "in_progress",
    "period": 3,
    "time_remaining": "5:42",
    "home_team": "LAL",
    "away_team": "HOU",
    "home_score": 58,
    "away_score": 79,
    "players": [{
      "player_lookup": "lebronjames",
      "name": "LeBron James",
      "team": "LAL",
      "points": 18,
      "rebounds": 4,
      "assists": 5,
      "minutes": "28:30"
    }]
  }]
}
```

**Note on game_id:** Live uses BallDontLie internal IDs (e.g., `"18447237"`), while tonight uses NBA IDs (e.g., `"0022500432"`). Both are strings - match by `player_lookup`, not `game_id`.

---

### Live Grading Endpoint (`/live-grading/latest.json`)

**Schema matches handoff requirements** (mostly):
```json
{
  "updated_at": "2025-12-27T21:30:00Z",
  "game_date": "2025-12-27",
  "summary": {
    "total_predictions": 45,
    "graded": 30,
    "correct": 22,
    "incorrect": 8,
    "win_rate": 0.733
  },
  "predictions": [{
    "player_lookup": "lebronjames",
    "player_name": "LeBron James",
    "team": "LAL",
    "game_id": "0022500432",
    "game_status": "in_progress",
    "predicted": 27.5,
    "line": 24.5,
    "recommendation": "OVER",
    "confidence": 0.72,
    "actual": 18,
    "minutes": "28:30",
    "status": "trending_correct"
  }]
}
```

---

## Endpoints Status

| Endpoint | Status | Last Verified |
|----------|--------|---------------|
| `/tonight/all-players.json` | ✅ Live | Deploying updates |
| `/live/latest.json` | ✅ Live | Working |
| `/live-grading/latest.json` | ✅ Live | Working |
| `/results/{date}.json` | ⚠️ Check | Need to verify |

---

## Testing Commands

```bash
# Verify player_lookup consistency
LOOKUP=$(curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" \
  | jq -r '.games[0].players[0].player_lookup')
echo "Tonight: $LOOKUP"

curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/live/latest.json" \
  | jq ".games[].players[] | select(.player_lookup == \"$LOOKUP\") | {player_lookup, points}"

# Verify new schema
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" \
  | jq '.games[0].players[0] | {player_lookup, name, team, props, prediction}'
```

---

## Contact

Backend changes deployed. Frontend can begin testing.

Questions? Check the implementation in:
- Tonight exporter: `data_processors/publishing/tonight_all_players_exporter.py`
- Live exporter: `data_processors/publishing/live_scores_exporter.py`
