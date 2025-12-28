# Backend Bug Report - December 28, 2025

**Reported by:** Frontend Team
**Severity:** Critical - App is broken
**Endpoint:** `/tonight/all-players.json`

---

## Summary

The `/tonight/all-players.json` endpoint has multiple critical data issues that are breaking the frontend app. Games are not displaying correctly and player data is corrupted.

---

## Bug 1: Duplicate Players (Critical)

### Description
Each player appears **multiple times** (typically 5x) with identical data in the same game.

### Evidence
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | \
  jq '.games[0].players | group_by(.player_lookup) | .[] | select(length > 1) | {name: .[0].name, count: length}'
```

**Output:**
```json
{"name": "Brandon Ingram", "count": 5}
{"name": "Gradey Dick", "count": 5}
{"name": "Immanuel Quickley", "count": 5}
{"name": "Scottie Barnes", "count": 5}
... (7 players with 5 duplicates each)
```

### Impact by Game
| Game | Total Players | Unique Players | Duplicates |
|------|---------------|----------------|------------|
| GSW @ TOR | 44 | 16 | 28 |
| PHI @ OKC | 57 | 33 | 24 |
| MEM @ WAS | 49 | 29 | 20 |
| BOS @ POR | 35 | 15 | 20 |
| DET @ LAC | 0 | 0 | 0 |
| SAC @ LAL | 26 | 14 | 12 |

### Expected Behavior
Each player should appear exactly once per game.

---

## Bug 2: Missing Teams in Games (Critical)

### Description
Some games only contain players from ONE team, not both.

### Evidence
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | \
  jq '[.games[] | {matchup: "\(.away_team) @ \(.home_team)", teams_present: ([.players[].team] | unique)}]'
```

**Output:**
| Game | Expected Teams | Actual Teams in Data |
|------|----------------|---------------------|
| GSW @ TOR | GSW, TOR | TOR only |
| PHI @ OKC | PHI, OKC | PHI, OKC ✓ |
| MEM @ WAS | MEM, WAS | MEM, WAS ✓ |
| BOS @ POR | BOS, POR | BOS only |
| DET @ LAC | DET, LAC | (empty) |
| SAC @ LAL | SAC, LAL | LAL only |

### Expected Behavior
Both teams' players should be present in each game.

---

## Bug 3: Empty Game (DET @ LAC)

### Description
The DET @ LAC game has zero players.

### Evidence
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | \
  jq '.games[4] | {matchup: "\(.away_team) @ \(.home_team)", player_count: (.players | length)}'
```

**Output:**
```json
{"matchup": "DET @ LAC", "player_count": 0}
```

### Expected Behavior
Should have ~20-30 players with lines for this game.

---

## Bug 4: `last_10_points` Field Missing

### Description
The API does not include `last_10_points` (array of actual point values from last 10 games). The frontend expects this field to display point totals in the Last 10 grid.

### Current API Response
```json
{
  "last_10_results": ["U", "O", "U", "-", "-", "-", "-", "-", "-", "-"],
  "last_10_record": "1-2"
}
```

### Expected API Response
```json
{
  "last_10_results": ["U", "O", "U", "-", "-", "-", "-", "-", "-", "-"],
  "last_10_record": "1-2",
  "last_10_points": [18, 25, 15, null, null, null, null, null, null, null]
}
```

### Frontend Impact
Without `last_10_points`, the UI shows thin bars instead of numbered boxes with actual point values. This makes it harder for users to evaluate player performance.

---

## Bug 5: Excessive DNPs in Last 10

### Description
Many players show 7-8 DNPs (Did Not Play) in their last 10 games, which seems incorrect for regular starters.

### Evidence
```json
{
  "name": "Scottie Barnes",
  "last_10_results": ["U", "O", "U", "-", "-", "-", "-", "-", "-", "-"],
  "last_10_record": "1-2"
}
```

Scottie Barnes has played 30+ games this season but shows only 3 games in last 10?

### Possible Cause
- Last 10 might be tracking games vs a specific line rather than all games played
- Or there's a data collection issue

### Expected Behavior
For active starters, last 10 should show mostly O/U results, with DNPs only for actual missed games (injury, rest, etc.).

---

## Reproduction

```bash
# Full diagnostic
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | jq '{
  game_date,
  games: [.games[] | {
    matchup: "\(.away_team) @ \(.home_team)",
    total_players: (.players | length),
    unique_players: ([.players[].player_lookup] | unique | length),
    teams_present: ([.players[].team] | unique)
  }]
}'
```

---

## Priority

1. **Bug 1 (Duplicates)** - Critical, causes cards to render multiple times
2. **Bug 2 (Missing Teams)** - Critical, half the players missing from games
3. **Bug 3 (Empty Game)** - High, entire game not displaying
4. **Bug 4 (last_10_points)** - Medium, UI degraded but functional
5. **Bug 5 (DNPs)** - Low, may be expected behavior

---

## Frontend Workaround Status

- Added null-safe check for `props?.find()` to prevent crash
- Duplicates and missing data cannot be worked around on frontend

---

## Contact

Please reach out if you need more details or want to pair on debugging.
