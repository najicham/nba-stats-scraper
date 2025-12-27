# Phase 6 Data Model

**Created:** 2025-12-02
**Status:** Draft

---

## Source Data (Phase 5 BigQuery)

### player_prop_predictions Table

```sql
-- Key fields for Phase 6
SELECT
  player_lookup,          -- "stephen_curry"
  game_date,              -- 2024-01-15
  game_id,                -- "20240115_GSW_LAL"
  system_id,              -- "ensemble", "moving_average", etc.
  predicted_points,       -- 29.0
  confidence_score,       -- 72.5
  recommendation,         -- "OVER", "UNDER", "PASS"
  current_points_line,    -- 25.5
  line_margin,            -- 3.5
  is_active,              -- true
  created_at              -- timestamp
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = true
```

---

## Firestore Schema

### Collection: `/predictions`

```
/predictions
  /{game_date}                    # Document ID: "2024-01-15"
    - metadata: {
        last_updated: Timestamp,
        games_count: 5,
        players_count: 45,
        predictions_count: 225
      }
    - games: [                    # Array of game info
        {
          game_id: "20240115_GSW_LAL",
          home_team: "LAL",
          away_team: "GSW",
          game_time: Timestamp,
          status: "scheduled"
        }
      ]
```

### Collection: `/predictions/{date}/players`

```
/predictions/{date}/players
  /{player_lookup}                # Document ID: "stephen_curry"
    - player_name: "Stephen Curry"
    - team_abbr: "GSW"
    - opponent_abbr: "LAL"
    - is_home: false
    - game_id: "20240115_GSW_LAL"
    - game_time: Timestamp
    - current_line: 25.5
    - ensemble: {                 # Primary prediction
        predicted_points: 29.0,
        confidence: 72.5,
        recommendation: "OVER",
        margin: 3.5
      }
    - models: {                   # Individual model predictions
        moving_average: {
          predicted_points: 27.5,
          confidence: 65.0,
          recommendation: "OVER"
        },
        zone_matchup: {
          predicted_points: 30.0,
          confidence: 70.0,
          recommendation: "OVER"
        },
        similarity: {
          predicted_points: 28.5,
          confidence: 68.0,
          recommendation: "OVER"
        },
        xgboost: {
          predicted_points: 29.5,
          confidence: 75.0,
          recommendation: "OVER"
        }
      }
    - updated_at: Timestamp
```

### Collection: `/metadata`

```
/metadata
  /status                         # Current system status
    - last_published: Timestamp
    - current_date: "2024-01-15"
    - is_game_day: true
    - next_game_time: Timestamp
    - health: "ok"
```

---

## API Response Format

### GET /api/predictions/{date}

```json
{
  "date": "2024-01-15",
  "updated_at": "2024-01-15T10:30:00Z",
  "games_count": 5,
  "predictions": [
    {
      "player_lookup": "stephen_curry",
      "player_name": "Stephen Curry",
      "team": "GSW",
      "opponent": "LAL",
      "game_time": "2024-01-15T22:30:00Z",
      "current_line": 25.5,
      "prediction": {
        "points": 29.0,
        "confidence": 72.5,
        "recommendation": "OVER",
        "margin": 3.5
      },
      "models": {
        "moving_average": { "points": 27.5, "confidence": 65.0 },
        "zone_matchup": { "points": 30.0, "confidence": 70.0 },
        "similarity": { "points": 28.5, "confidence": 68.0 },
        "xgboost": { "points": 29.5, "confidence": 75.0 },
        "ensemble": { "points": 29.0, "confidence": 72.5 }
      }
    }
  ]
}
```

### GET /api/predictions/{date}/{player}

```json
{
  "player_lookup": "stephen_curry",
  "player_name": "Stephen Curry",
  "team": "GSW",
  "game_date": "2024-01-15",
  "opponent": "LAL",
  "is_home": false,
  "game_time": "2024-01-15T22:30:00Z",
  "current_line": 25.5,
  "prediction": {
    "points": 29.0,
    "confidence": 72.5,
    "recommendation": "OVER",
    "margin": 3.5,
    "explanation": "Strong recent performance (L5 avg: 28.3), favorable matchup vs LAL perimeter D"
  },
  "models": {
    "moving_average": {
      "points": 27.5,
      "confidence": 65.0,
      "recommendation": "OVER",
      "inputs": {
        "l5_avg": 28.3,
        "l10_avg": 27.1,
        "season_avg": 26.5
      }
    }
    // ... other models
  },
  "history": {
    "last_5_actuals": [32, 25, 28, 30, 27],
    "vs_line_record": "3-2"
  }
}
```

---

## Data Transformation

### BigQuery → Firestore

```python
def transform_prediction(bq_row):
    """Transform BigQuery row to Firestore document."""
    return {
        'player_lookup': bq_row['player_lookup'],
        'player_name': format_name(bq_row['player_lookup']),
        'team_abbr': bq_row['team_abbr'],
        'opponent_abbr': bq_row['opponent_abbr'],
        'game_id': bq_row['game_id'],
        'current_line': bq_row['current_points_line'],
        'ensemble': {
            'predicted_points': bq_row['predicted_points'],
            'confidence': bq_row['confidence_score'],
            'recommendation': bq_row['recommendation'],
            'margin': bq_row['line_margin']
        },
        'updated_at': firestore.SERVER_TIMESTAMP
    }
```

### Aggregating Multiple Systems

```python
def aggregate_predictions(rows):
    """Group by player, aggregate all system predictions."""
    by_player = {}
    for row in rows:
        player = row['player_lookup']
        if player not in by_player:
            by_player[player] = {
                'player_lookup': player,
                'models': {}
            }

        system = row['system_id']
        by_player[player]['models'][system] = {
            'predicted_points': row['predicted_points'],
            'confidence': row['confidence_score'],
            'recommendation': row['recommendation']
        }

        # Use ensemble as primary
        if system == 'ensemble':
            by_player[player]['ensemble'] = by_player[player]['models'][system]

    return list(by_player.values())
```

---

## Indexes Required

### Firestore Composite Indexes

```
Collection: predictions/{date}/players
Index 1: team_abbr ASC, confidence DESC
Index 2: recommendation ASC, confidence DESC
```

---

## Data Retention

| Collection | Retention | Notes |
|------------|-----------|-------|
| predictions (current) | 7 days | Active predictions |
| predictions (archive) | 1 season | For accuracy tracking |
| metadata | Permanent | Small size |

---

## Migration Considerations

When we have real Phase 5 data:

1. Validate data completeness (players per game)
2. Verify confidence scores are realistic
3. Check recommendation distribution (not all PASS)
4. Test with single game before full rollout
