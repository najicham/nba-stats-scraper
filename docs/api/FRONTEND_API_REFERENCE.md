# Frontend API Reference

**Version:** 1.1
**Last Updated:** 2025-12-28
**Base URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/`

---

## Overview

All data is served as static JSON files from Google Cloud Storage. Files are publicly accessible and have appropriate cache headers set.

### URL Pattern
```
https://storage.googleapis.com/nba-props-platform-api/v1/{endpoint}/{file}.json
```

---

## Endpoints

| Endpoint | Description | Update Frequency |
|----------|-------------|------------------|
| `/status.json` | **NEW** Health check for all services | Every 3 min during games |
| `/tonight/` | Tonight's predictions and player data | Daily ~2 PM ET |
| `/live/` | Real-time game scores during games | Every 3 min during games |
| `/live-grading/` | Real-time prediction grading | Every 3 min during games |
| `/results/` | Historical prediction results | Daily 5 AM ET |
| `/trends/` | Hot/cold trends, analytics | Hourly during day |
| `/best-bets/` | Top picks for the day | Daily with predictions |
| `/players/` | Individual player profiles | Weekly |

> **Important:** See [FRONTEND_LIVE_DATA_GUIDE.md](./FRONTEND_LIVE_DATA_GUIDE.md) for details on using the status endpoint to detect stale data.

---

## 1. Tonight's Predictions

### Endpoint
```
GET /tonight/all-players.json
```

### Description
Complete list of all players with predictions for tonight's games. This is the main endpoint for the daily picks page.

### Cache
- **Cache-Control:** `public, max-age=300` (5 minutes)
- **Updates:** Daily around 6 PM ET when predictions are ready

### Response Schema
```json
{
  "game_date": "2025-12-27",
  "generated_at": "2025-12-27T23:16:21.938706+00:00",
  "total_players": 832,
  "total_with_lines": 275,
  "games": [
    {
      "game_id": "0022500432",
      "home_team": "SAC",
      "away_team": "DAL",
      "game_time": "5:00 PM ET",
      "game_status": "scheduled",
      "player_count": 22,
      "players": [
        {
          "player_lookup": "cooperflagg",
          "name": "Cooper Flagg",
          "team": "DAL",
          "is_home": false,
          "has_line": true,
          "fatigue_level": "normal",
          "fatigue_score": null,
          "injury_status": "questionable",
          "injury_reason": "Injury/Illness - Back; Contusion",
          "season_ppg": 13.9,
          "season_mpg": 26.0,
          "last_5_ppg": 21.8,
          "games_played": 27,
          "limited_data": false,
          "props": [
            {
              "stat_type": "points",
              "line": 23.5,
              "over_odds": 102,
              "under_odds": null
            }
          ],
          "prediction": {
            "predicted": 13.8,
            "confidence": 0.57,
            "recommendation": "PASS"
          },
          "last_10_results": ["O", "O", "U", "-", "-", "-", "-", "-", "-", "-"],
          "last_10_record": "2-1",
          "last_10_vs_avg": ["O", "U", "U", "O", "O", "O", "U", "O", "U", "O"],
          "last_10_avg_record": "5-5"
        }
      ]
    }
  ]
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `player_lookup` | string | Unique player identifier (lowercase, no spaces) |
| `name` | string | Display name |
| `team` | string | 3-letter team code |
| `is_home` | boolean | True if playing at home |
| `has_line` | boolean | True if betting line available |
| `fatigue_level` | string | `"normal"`, `"tired"`, `"rested"` |
| `injury_status` | string | `null`, `"questionable"`, `"probable"`, `"doubtful"`, `"out"` |
| `injury_reason` | string | Injury description if applicable |
| `season_ppg` | float | Season points per game average |
| `season_mpg` | float | Season minutes per game average |
| `last_5_ppg` | float | Last 5 games PPG |
| `games_played` | int | Total games played this season |
| `limited_data` | boolean | True if <10 games played (predictions less reliable) |
| `last_10_points` | int[] | Points scored in last 10 games (most recent first). Available for ALL players. |
| `last_10_results` | string[] | O/U vs real sportsbook line per game. `"O"`, `"U"`, or `"-"` (no line). Only for players with `has_line`. ~35% coverage per game. |
| `last_10_record` | string | Win-loss record vs real sportsbook lines (e.g., `"3-2"`). Only for players with `has_line`. |
| `last_10_vs_avg` | string[] | O/U vs player's season average per game. `"O"`, `"U"`, or `"P"` (push). Available for ALL players. 100% coverage. |
| `last_10_avg_record` | string | Win-loss record vs season average (e.g., `"6-4"`). Available for ALL players. |

#### Props Object
| Field | Type | Description |
|-------|------|-------------|
| `stat_type` | string | Currently only `"points"` |
| `line` | float | Vegas betting line |
| `over_odds` | int | American odds for over (e.g., -110, +102) |
| `under_odds` | int | American odds for under |

#### Prediction Object
| Field | Type | Description |
|-------|------|-------------|
| `predicted` | float | Our predicted points |
| `confidence` | float | Confidence score 0.0-1.0 |
| `recommendation` | string | `"OVER"`, `"UNDER"`, `"PASS"`, `"NO_LINE"` |

---

## 2. Live Scores

### Endpoint
```
GET /live/latest.json
GET /live/{date}.json
```

### Description
Real-time game scores and player stats during live games. Updates every 3 minutes from 7 PM - 2 AM ET on game days.

### Cache
- **Cache-Control:** `public, max-age=30` (30 seconds)
- **Updates:** Every 3 minutes during game windows

### Response Schema
```json
{
  "updated_at": "2025-12-28T02:12:02.561663+00:00",
  "game_date": "2025-12-27",
  "poll_id": "20251228T021201Z",
  "games_in_progress": 4,
  "games_final": 5,
  "total_games": 9,
  "games": [
    {
      "game_id": "18447247",
      "status": "in_progress",
      "period": 4,
      "time_remaining": "Q4 5:39",
      "home_team": "ORL",
      "away_team": "DEN",
      "home_score": 111,
      "away_score": 105,
      "player_count": 34,
      "players": [
        {
          "player_lookup": "anthonyblack",
          "name": "Anthony Black",
          "team": "ORL",
          "points": 34,
          "rebounds": 6,
          "assists": 5,
          "steals": 1,
          "blocks": 0,
          "turnovers": 1,
          "minutes": "25",
          "fg_made": 12,
          "fg_attempted": 21,
          "fg3_made": 7,
          "fg3_attempted": 10,
          "ft_made": 3,
          "ft_attempted": 5
        }
      ]
    }
  ]
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"scheduled"`, `"in_progress"`, `"final"` |
| `period` | int | Current period (1-4, 5+ for OT) |
| `time_remaining` | string | Clock display (e.g., "Q4 5:39", "Final") |
| `player_count` | int | Total players in this game's data |

#### Player Stats (Live)
| Field | Type | Description |
|-------|------|-------------|
| `points` | int | Current points scored |
| `rebounds` | int | Total rebounds |
| `assists` | int | Total assists |
| `steals` | int | Total steals |
| `blocks` | int | Total blocks |
| `turnovers` | int | Total turnovers |
| `minutes` | string | Minutes played (e.g., "25", "32:45") |
| `fg_made` / `fg_attempted` | int | Field goals made/attempted |
| `fg3_made` / `fg3_attempted` | int | Three pointers made/attempted |
| `ft_made` / `ft_attempted` | int | Free throws made/attempted |

---

## 3. Live Grading

### Endpoint
```
GET /live-grading/latest.json
GET /live-grading/{date}.json
```

### Description
Real-time grading of predictions against live scores. Shows which predictions are winning/losing as games progress.

### Cache
- **Cache-Control:** `public, max-age=30` (30 seconds)
- **Updates:** Every 3 minutes during game windows

### Response Schema
```json
{
  "updated_at": "2025-12-28T02:12:03.744694+00:00",
  "game_date": "2025-12-27",
  "summary": {
    "total_predictions": 61,
    "graded": 61,
    "pending": 0,
    "correct": 10,
    "incorrect": 5,
    "trending_correct": 0,
    "trending_incorrect": 0,
    "win_rate": 0.667,
    "avg_error": 5.6,
    "games_in_progress": 0,
    "games_final": 9
  },
  "predictions": [
    {
      "player_lookup": "jeremiahfears",
      "player_name": "Jeremiah Fears",
      "team": "NOP",
      "home_team": "NOP",
      "away_team": "PHX",
      "game_status": "final",
      "predicted": 12.0,
      "line": 13.5,
      "recommendation": "OVER",
      "confidence": 0.86,
      "has_line": true,
      "line_source": "ESTIMATED_AVG",
      "actual": 18,
      "minutes": "34",
      "error": -6.0,
      "margin_vs_line": 4.5,
      "status": "correct"
    }
  ]
}
```

### Summary Object
| Field | Type | Description |
|-------|------|-------------|
| `total_predictions` | int | Total predictions made |
| `graded` | int | Predictions with final results |
| `pending` | int | Waiting for game data |
| `correct` | int | Predictions that hit (final games) |
| `incorrect` | int | Predictions that missed (final games) |
| `trending_correct` | int | Currently winning (in-progress games) |
| `trending_incorrect` | int | Currently losing (in-progress games) |
| `win_rate` | float | Correct / (Correct + Incorrect) |
| `avg_error` | float | Average absolute error in points |

### Prediction Grading Object
| Field | Type | Description |
|-------|------|-------------|
| `predicted` | float | Our predicted points |
| `line` | float | Vegas betting line |
| `recommendation` | string | `"OVER"`, `"UNDER"`, `"PASS"` |
| `actual` | int | Actual points scored (null if pending) |
| `minutes` | string | Minutes played |
| `error` | float | predicted - actual |
| `margin_vs_line` | float | actual - line |
| `status` | string | See status values below |

### Status Values
| Status | Description |
|--------|-------------|
| `pending` | Game hasn't started |
| `in_progress` | Game in progress, no clear trend |
| `trending_correct` | In progress, currently winning |
| `trending_incorrect` | In progress, currently losing |
| `correct` | Final - prediction hit |
| `incorrect` | Final - prediction missed |
| `graded` | Final - NO_LINE/PASS prediction (graded but no win/loss) |

---

## 4. Historical Results

### Endpoint
```
GET /results/latest.json
GET /results/{date}.json
```

### Description
Final graded results for completed dates. Used for historical performance tracking.

### Cache
- **Cache-Control:** `public, max-age=3600` (1 hour)
- **Updates:** Daily at 5 AM ET

### Response Schema
```json
{
  "game_date": "2025-12-26",
  "generated_at": "2025-12-27T10:00:06.382758+00:00",
  "summary": {
    "total_predictions": 45,
    "recommendations": 32,
    "correct": 18,
    "incorrect": 14,
    "pass_count": 13,
    "win_rate": 0.563,
    "avg_mae": 4.2,
    "avg_bias": -0.8,
    "within_3_points": 22,
    "within_3_pct": 0.49,
    "within_5_points": 31,
    "within_5_pct": 0.69
  },
  "breakdowns": {
    "by_player_tier": {
      "elite": { "total": 8, "wins": 5, "losses": 3, "win_rate": 0.625 },
      "starter": { "total": 15, "wins": 9, "losses": 6, "win_rate": 0.6 },
      "role_player": { "total": 9, "wins": 4, "losses": 5, "win_rate": 0.44 }
    },
    "by_confidence": {
      "high": { "total": 12, "wins": 8, "losses": 4, "win_rate": 0.667 },
      "medium": { "total": 14, "wins": 7, "losses": 7, "win_rate": 0.5 },
      "low": { "total": 6, "wins": 3, "losses": 3, "win_rate": 0.5 }
    }
  }
}
```

---

## 5. Update Schedule

### Schedulers (All times ET)

| Time | Job | What Updates |
|------|-----|--------------|
| 5:00 AM | `phase6-daily-results` | `/results/` |
| 6:00 AM - 11:00 PM | `phase6-hourly-trends` | `/trends/` |
| 1:00 PM | `phase6-tonight-picks` | `/tonight/`, `/best-bets/` |
| 7:00 PM - 2:00 AM | `live-export` | `/live/`, `/live-grading/` (every 3 min) |

### Live Data Window
Live scoring runs **every 3 minutes** during game windows:
- Evening: 7:00 PM - 11:59 PM ET
- Late night: 12:00 AM - 1:59 AM ET

---

## 6. Player Lookup Key

The `player_lookup` field is the primary key for joining data across endpoints. It's generated as:
- Lowercase
- No spaces or punctuation
- Alphanumeric only

**Examples:**
| Player Name | player_lookup |
|-------------|---------------|
| LeBron James | `lebronjames` |
| De'Aaron Fox | `dearonfox` |
| P.J. Washington | `pjwashington` |
| Nikola Jokić | `nikolajokic` |

---

## 7. Error Handling

### Empty States
When no data is available, endpoints return structured empty responses:

```json
{
  "game_date": "2025-12-27",
  "generated_at": "...",
  "total_games": 0,
  "games": []
}
```

### HTTP Status Codes
| Code | Meaning |
|------|---------|
| 200 | Success |
| 404 | File not found (date may not exist) |
| 403 | Access denied (should not happen for public bucket) |

---

## 8. Example Usage

### JavaScript Fetch
```javascript
// Get tonight's predictions
const tonight = await fetch(
  'https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json'
).then(r => r.json());

// Get live scores (poll every 30 seconds during games)
const live = await fetch(
  'https://storage.googleapis.com/nba-props-platform-api/v1/live/latest.json'
).then(r => r.json());

// Get live grading
const grading = await fetch(
  'https://storage.googleapis.com/nba-props-platform-api/v1/live-grading/latest.json'
).then(r => r.json());
```

### Joining Tonight + Live Grading
```javascript
// Match predictions to grading results
const gradingMap = new Map(
  grading.predictions.map(p => [p.player_lookup, p])
);

tonight.games.forEach(game => {
  game.players.forEach(player => {
    const liveResult = gradingMap.get(player.player_lookup);
    if (liveResult) {
      player.actual = liveResult.actual;
      player.status = liveResult.status;
    }
  });
});
```

---

## 9. File Inventory

### Current Files Available

| Path | Description |
|------|-------------|
| `/tonight/all-players.json` | Tonight's full player list with predictions |
| `/live/latest.json` | Most recent live scores |
| `/live/{YYYY-MM-DD}.json` | Live scores for specific date |
| `/live-grading/latest.json` | Most recent live grading |
| `/live-grading/{YYYY-MM-DD}.json` | Live grading for specific date |
| `/results/latest.json` | Most recent completed results |
| `/results/{YYYY-MM-DD}.json` | Results for specific date |
| `/trends/whos-hot-v2.json` | Hot/cold player trends |
| `/trends/tonight-plays.json` | Tonight's top plays |
| `/best-bets/latest.json` | Today's best bets |

---

## Questions?

Contact the backend team for:
- New fields or data requirements
- Custom aggregations
- Higher update frequencies
- Historical data access
