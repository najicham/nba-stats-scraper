# Tonight All Players API Documentation

**For Frontend Team Review**
**Status:** ✅ Fixed and Deployed (2026-02-11)
**Endpoint:** `https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json`

---

## Overview

The `/tonight/all-players.json` endpoint provides comprehensive player data for all games scheduled today. This is the **primary data source for the website homepage** and provides ~150KB of player cards with predictions, stats, injury status, and betting lines.

---

## Issue Fixed (2026-02-11)

### What Was Broken
- **File existed but had 0 players** in every game
- Generated valid JSON with games array, but `players: []` for each game
- Total players always 0, despite games being scheduled

### Root Cause
- **game_id format mismatch** between schedule table (NBA format: `0022500771`) and player context table (date format: `20260210_IND_NYK`)
- Players grouped by one format, games keyed by another → lookup always failed
- Secondary: Used deprecated `catboost_v8` instead of production `catboost_v9`

### What's Fixed Now
- ✅ game_ids now use consistent date-based format
- ✅ Players correctly associated with games
- ✅ Using production model (catboost_v9) for predictions
- ✅ Auto-deploys on code changes (new Cloud Build trigger)

---

## Endpoint Details

### URL
```
https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json
```

### HTTP Method
`GET`

### CORS Support
✅ Enabled for:
- `https://playerprops.io`
- `https://nbaprops.com`
- `http://localhost:3000`
- `http://localhost:5173`

### Cache Headers
```
Cache-Control: public, max-age=300
```
**Note:** 5-minute cache. Lines can change frequently before game time.

### Update Schedule
- **Pre-game:** Generated when predictions are ready (~6:30 AM ET)
- **Updates:** Can be regenerated anytime via manual trigger
- **Stale threshold:** File older than 8 hours is considered degraded

---

## Response Format

### Top-Level Structure
```json
{
  "game_date": "2026-02-10",
  "generated_at": "2026-02-11T05:35:25.788356+00:00",
  "total_players": 80,
  "total_with_lines": 20,
  "games": [...]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `game_date` | string | ISO date (YYYY-MM-DD) |
| `generated_at` | string | ISO 8601 timestamp with timezone |
| `total_players` | integer | Total players across all games (both teams, all games) |
| `total_with_lines` | integer | Players who have betting lines available |
| `games` | array | Array of game objects (see below) |

---

## Game Object Structure

```json
{
  "game_id": "20260210_IND_NYK",
  "home_team": "NYK",
  "away_team": "IND",
  "game_time": " 7:30 PM ET",
  "game_status": "scheduled",
  "player_count": 27,
  "players": [...]
}
```

### Game Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `game_id` | string | Format: `YYYYMMDD_AWAY_HOME` | Unique game identifier |
| `home_team` | string | 3-letter tricode | Home team abbreviation |
| `away_team` | string | 3-letter tricode | Away team abbreviation |
| `game_time` | string | " H:MM PM ET" | Game start time (Eastern) |
| `game_status` | string | `scheduled`, `in_progress`, `final` | Current game status |
| `player_count` | integer | 0-30 typical | Number of players in this game |
| `players` | array | Player objects | Array of player data (see below) |

**Note:** `game_id` format is date-based. Use this for API calls, not the NBA's internal game_id.

---

## Player Object Structure

### Player with Betting Line
```json
{
  "player_lookup": "karlanthonytowns",
  "name": "Karl-Anthony Towns",
  "team": "NYK",
  "is_home": true,
  "has_line": true,

  "fatigue_level": "fresh",
  "fatigue_score": 100.0,
  "days_rest": 4,

  "injury_status": "available",
  "injury_reason": "Injury/Illness - Right Eye; Laceration",

  "season_ppg": 19.6,
  "season_mpg": 31.2,
  "last_5_ppg": 16.3,
  "games_played": 51,
  "limited_data": false,

  "last_10_points": [11, 24, 19, 11, 14, 8, 17, 10, 14],

  "props": [{
    "stat_type": "points",
    "line": 20.5,
    "over_odds": null,
    "under_odds": -111
  }],

  "prediction": {
    "predicted": 20.0,
    "confidence": 92.0,
    "recommendation": "PASS"
  },

  "last_10_results": ["-", "-", "-", "-", "-", "-", "-", "-", "-"],
  "last_10_record": null
}
```

### Player without Betting Line
```json
{
  "player_lookup": "jerichosimsnyc",
  "name": "Jericho Sims",
  "team": "NYK",
  "is_home": true,
  "has_line": false,

  "fatigue_level": "normal",
  "fatigue_score": 85.0,
  "days_rest": 4,

  "injury_status": "available",
  "injury_reason": null,

  "season_ppg": 2.1,
  "season_mpg": 9.4,
  "last_5_ppg": 1.8,
  "games_played": 42,
  "limited_data": false,

  "last_10_points": [0, 2, 4, 0, 2, 6, 0, 2]
}
```

---

## Player Field Definitions

### Core Identity
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `player_lookup` | string | ✅ | Unique player identifier (lowercase, no spaces) |
| `name` | string | ✅ | Full player name |
| `team` | string | ✅ | 3-letter team tricode |
| `is_home` | boolean | ✅ | true if playing at home |
| `has_line` | boolean | ✅ | true if betting line available |

### Fatigue & Rest
| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `fatigue_level` | string | `fresh`, `normal`, `tired` | Fatigue assessment |
| `fatigue_score` | float/null | 0-100 | Numeric fatigue score (100 = most fresh) |
| `days_rest` | integer/null | 0-7+ | Days since last game |

**Fatigue Level Thresholds:**
- `fresh`: fatigue_score >= 95
- `normal`: 75 <= fatigue_score < 95
- `tired`: fatigue_score < 75

### Injury Status
| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `injury_status` | string | `available`, `out`, `questionable`, `doubtful` | Current injury status |
| `injury_reason` | string/null | Free text | Injury description if applicable |

### Season Stats
| Field | Type | Description |
|-------|------|-------------|
| `season_ppg` | float/null | Season points per game average |
| `season_mpg` | float/null | Season minutes per game average |
| `last_5_ppg` | float/null | Points per game over last 5 games |
| `games_played` | integer | Games played this season |
| `limited_data` | boolean | true if games_played < 10 |

### Recent Performance
| Field | Type | Description |
|-------|------|-------------|
| `last_10_points` | array\<int\> | Points scored in last 10 games (most recent first) |
| `last_10_results` | array\<string\> | Over/Under results: `"O"`, `"U"`, `"-"` (only if has_line) |
| `last_10_record` | string/null | Format: `"7-3"` (overs-unders) (only if has_line) |

**Note:** `last_10_results` and `last_10_record` only present when `has_line: true`

### Betting Props (if has_line = true)
| Field | Type | Description |
|-------|------|-------------|
| `props` | array | Array of prop objects (typically 1 item for points) |

**Prop Object:**
```json
{
  "stat_type": "points",
  "line": 20.5,
  "over_odds": null,
  "under_odds": -111
}
```

| Prop Field | Type | Description |
|------------|------|-------------|
| `stat_type` | string | Always `"points"` (currently) |
| `line` | float | Points line (e.g., 20.5) |
| `over_odds` | integer/null | American odds for Over (e.g., +110) |
| `under_odds` | integer/null | American odds for Under (e.g., -111) |

**Note:** Odds fields may be `null` until odds data is populated.

### Prediction (if has_line = true)
| Field | Type | Description |
|-------|------|-------------|
| `prediction` | object/null | ML model prediction (only if has_line) |

**Prediction Object:**
```json
{
  "predicted": 20.0,
  "confidence": 92.0,
  "recommendation": "PASS"
}
```

| Prediction Field | Type | Values | Description |
|------------------|------|--------|-------------|
| `predicted` | float | 0-60+ | Predicted points for the game |
| `confidence` | float | 0-100 | Model confidence score |
| `recommendation` | string | `OVER`, `UNDER`, `PASS`, `NO_LINE` | Betting recommendation |

**Recommendation Logic:**
- `OVER`: predicted > line + edge threshold
- `UNDER`: predicted < line - edge threshold
- `PASS`: Edge too small, no actionable signal
- `NO_LINE`: No betting line available (shouldn't see this if has_line=true)

---

## Player Sorting Order

Players within each game are sorted by:
1. **has_line** (players with lines first)
2. **injury_status** (OUT players last)
3. **confidence** (high confidence first, for players with lines)
4. **season_ppg** (high scorers first, for players without lines)

This ensures the most relevant/actionable players appear first in each game.

---

## Example Response (Abbreviated)

```json
{
  "game_date": "2026-02-10",
  "generated_at": "2026-02-11T05:35:25.788356+00:00",
  "total_players": 80,
  "total_with_lines": 20,
  "games": [
    {
      "game_id": "20260210_IND_NYK",
      "home_team": "NYK",
      "away_team": "IND",
      "game_time": " 7:30 PM ET",
      "game_status": "scheduled",
      "player_count": 27,
      "players": [
        {
          "player_lookup": "karlanthonytowns",
          "name": "Karl-Anthony Towns",
          "team": "NYK",
          "is_home": true,
          "has_line": true,
          "fatigue_level": "fresh",
          "fatigue_score": 100.0,
          "days_rest": 4,
          "injury_status": "available",
          "injury_reason": "Injury/Illness - Right Eye; Laceration",
          "season_ppg": 19.6,
          "season_mpg": 31.2,
          "last_5_ppg": 16.3,
          "games_played": 51,
          "limited_data": false,
          "last_10_points": [11, 24, 19, 11, 14, 8, 17, 10, 14],
          "props": [{
            "stat_type": "points",
            "line": 20.5,
            "over_odds": null,
            "under_odds": -111
          }],
          "prediction": {
            "predicted": 20.0,
            "confidence": 92.0,
            "recommendation": "PASS"
          },
          "last_10_results": ["-", "-", "-", "-", "-", "-", "-", "-", "-"],
          "last_10_record": null
        }
        // ... more players
      ]
    }
    // ... more games
  ]
}
```

---

## Usage Notes

### Fetching the Data
```javascript
const response = await fetch(
  'https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json',
  {
    headers: {
      'Accept': 'application/json'
    }
  }
);
const data = await response.json();
```

### Handling Null Values
Many fields can be `null`:
- `fatigue_score`, `fatigue_level`, `days_rest` (for players with limited data)
- `injury_reason` (when no injury)
- `season_ppg`, `season_mpg`, `last_5_ppg` (for players with no history)
- `over_odds`, `under_odds` (when odds not yet available)
- `last_10_record` (when no clear record)
- `prediction` (only present when has_line is true)

**Always check for null before using values.**

### Filtering Players with Lines
```javascript
const playersWithLines = data.games.flatMap(game =>
  game.players.filter(p => p.has_line)
);
```

### Checking Data Freshness
```javascript
const generatedAt = new Date(data.generated_at);
const now = new Date();
const ageMinutes = (now - generatedAt) / 1000 / 60;

if (ageMinutes > 480) { // 8 hours
  console.warn('Data may be stale');
}
```

### Handling Missing Games
```javascript
if (data.games.length === 0) {
  // No games scheduled today (off-day)
  displayNoGamesMessage();
}
```

---

## Error Scenarios

### File Not Found (404)
- **Cause:** Export hasn't run yet for today
- **When:** Early morning before 6:30 AM ET
- **Action:** Show "Data not yet available" message

### Empty Games Array
- **Cause:** No NBA games scheduled today
- **When:** All-Star break, off-days
- **Action:** Show "No games scheduled" message

### total_players = 0 (Fixed!)
- **Previously:** This was a bug (game_id mismatch)
- **Now:** Should never happen
- **Action:** If you see this, report as bug

### Stale Data
- **Cause:** Export pipeline stalled
- **Detection:** `generated_at` > 8 hours old
- **Action:** Show warning banner

---

## Performance Tips

### File Size
- **Typical:** 60-70 KB (compressed)
- **Range:** 50-150 KB depending on number of games
- **Recommendation:** Can be fetched on page load

### Caching Strategy
```javascript
// Cache for 5 minutes (matches GCS cache-control)
const CACHE_TTL = 5 * 60 * 1000;

async function fetchTonightData() {
  const cached = localStorage.getItem('tonight_data');
  if (cached) {
    const { data, timestamp } = JSON.parse(cached);
    if (Date.now() - timestamp < CACHE_TTL) {
      return data;
    }
  }

  const response = await fetch(/* ... */);
  const data = await response.json();

  localStorage.setItem('tonight_data', JSON.stringify({
    data,
    timestamp: Date.now()
  }));

  return data;
}
```

---

## Related Endpoints

| Endpoint | Purpose | When to Use |
|----------|---------|-------------|
| `/tonight/all-players.json` | All players for tonight | Homepage, game previews |
| `/tonight/player/{player_lookup}.json` | Individual player detail | Player profile pages |
| `/picks/{date}.json` | Best picks for a date | Picks/recommendations page |
| `/signals/{date}.json` | Daily prediction signal | Dashboard, alerts |

---

## Change Log

### 2026-02-11 - Fixed & Auto-Deploy Added
- ✅ Fixed game_id format mismatch (0 players → 80 players)
- ✅ Updated to use production model (catboost_v9)
- ✅ Added auto-deploy trigger for publishing code changes
- ✅ Fixed pre-existing Cloud Function syntax error

### Previous Issues (Now Resolved)
- **Session 193:** Materializer pre-game bug (0 picks) → Fixed with upcoming_player_game_context fallback
- **Feb 2026:** Tonight export had 0 players → Fixed with game_id format correction

---

## Support & Questions

**Backend Team:** See `data_processors/publishing/tonight_all_players_exporter.py`
**Session Documentation:** `docs/09-handoff/2026-02-11-SESSION-195-*.md`
**API Guide:** `docs/08-projects/current/website-export-api/FRONTEND-API-GUIDE.md`

**Questions?** Check the session handoff docs or reach out to the platform team.

---

## Testing

### Manual Export Test
```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --date 2026-02-10 \
  --only tonight
```

### Verify Output
```bash
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json \
  | python3 -m json.tool \
  | head -100
```

### Check Metrics
```python
import json
data = json.loads(response.text)
print(f"Total players: {data['total_players']}")
print(f"With lines: {data['total_with_lines']}")
print(f"Games: {len(data['games'])}")
```

---

**Last Updated:** 2026-02-11
**Status:** ✅ Production-ready
**Version:** 1.0
