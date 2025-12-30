# Admin Dashboard API Reference

## Authentication

All endpoints (except `/health`) require authentication via API key.

**Methods:**
1. Query parameter: `?key=YOUR_API_KEY`
2. Header: `X-API-Key: YOUR_API_KEY`

**Unauthorized Response:**
```json
{"error": "Unauthorized"}
```

---

## Health Check

### GET /health
### GET /

Health check endpoint (no auth required).

**Response:**
```json
{
  "status": "healthy",
  "service": "admin-dashboard",
  "timestamp": "2025-12-29T23:00:00.000000Z"
}
```

---

## Status Endpoints

### GET /api/status

Get pipeline status for today and tomorrow.

**Response:**
```json
{
  "timestamp": "2025-12-29T19:00:00-05:00",
  "today": {
    "date": "2025-12-29",
    "status": {
      "game_date": "2025-12-29",
      "games_scheduled": 11,
      "phase3_context": 352,
      "phase4_features": 352,
      "predictions": 1700,
      "players_with_predictions": 68,
      "pipeline_status": "COMPLETE"
    },
    "games": [
      {
        "game_id": "0022500447",
        "home_team": "Hornets",
        "away_team": "Bucks",
        "home_abbr": "CHA",
        "away_abbr": "MIL",
        "context_count": 31,
        "feature_count": 31,
        "prediction_count": 100,
        "pipeline_status": "COMPLETE"
      }
    ]
  },
  "tomorrow": {
    "date": "2025-12-30",
    "status": {...},
    "games": [...]
  }
}
```

### GET /api/games/:date

Get detailed game status for a specific date.

**Parameters:**
- `date` (path): Date in YYYY-MM-DD format

**Response:**
```json
{
  "date": "2025-12-29",
  "games": [
    {
      "game_id": "0022500447",
      "home_team": "Hornets",
      "away_team": "Bucks",
      "home_abbr": "CHA",
      "away_abbr": "MIL",
      "game_status_text": "Scheduled",
      "context_count": 31,
      "feature_count": 31,
      "prediction_count": 100,
      "pipeline_status": "COMPLETE"
    }
  ]
}
```

**Pipeline Status Values:**
- `COMPLETE` - All phases done, predictions generated
- `PHASE_5_PENDING` - Features ready, awaiting predictions
- `PHASE_4_PENDING` - Context ready, awaiting features
- `PHASE_3_PENDING` - No context generated yet

---

## Error Endpoints

### GET /api/errors

Get recent errors from Cloud Logging.

**Query Parameters:**
- `limit` (optional): Max errors to return (default: 20)
- `hours` (optional): Look back hours (default: 6)

**Response:**
```json
{
  "errors": [
    {
      "timestamp": "2025-12-29T23:16:39.338157Z",
      "service": "nba-phase1-scrapers",
      "severity": "ERROR",
      "message": "ConnectionError: HTTPSConnectionPool...",
      "insert_id": "abc123"
    }
  ]
}
```

---

## Orchestration Endpoints

### GET /api/orchestration/:date

Get Firestore orchestration state for a date.

**Parameters:**
- `date` (path): Date in YYYY-MM-DD format

**Response:**
```json
{
  "date": "2025-12-29",
  "phase3": {
    "date": "2025-12-29",
    "collection": "phase3_completion",
    "exists": true,
    "processors": {
      "upcoming_player_game_context": {
        "completed_at": "2025-12-29T06:07:12.076000+00:00",
        "name": "upcoming_player_game_context"
      }
    },
    "completed_count": 1,
    "triggered": false,
    "triggered_at": null
  },
  "phase4": {
    "exists": true,
    "processors": {...},
    "triggered": false
  }
}
```

### GET /api/schedulers

Get Cloud Scheduler execution history.

**Response:**
```json
{
  "schedulers": [
    {
      "timestamp": "2025-12-29T23:27:41.403649315Z",
      "job_id": "same-day-predictions-tomorrow",
      "status": "success",
      "message": ""
    }
  ]
}
```

---

## History Endpoints

### GET /api/history

Get 7-day pipeline history.

**Response:**
```json
{
  "history": [
    {
      "game_date": "2025-12-29",
      "games_scheduled": 11,
      "phase3_context": 352,
      "phase4_features": 352,
      "predictions": 1700,
      "players_with_predictions": 68,
      "pipeline_status": "COMPLETE"
    },
    {
      "game_date": "2025-12-28",
      "games_scheduled": 8,
      "phase3_context": 280,
      "phase4_features": 280,
      "predictions": 1400,
      "players_with_predictions": 56,
      "pipeline_status": "COMPLETE"
    }
  ]
}
```

---

## Action Endpoints

### POST /api/actions/force-predictions

Force prediction generation for a specific date.

**Request Body:**
```json
{
  "date": "2025-12-30"
}
```

**Response:**
```json
{
  "status": "triggered",
  "date": "2025-12-30",
  "message": "Force predictions job triggered"
}
```

### POST /api/actions/retry-phase

Retry a specific phase for a date.

**Request Body:**
```json
{
  "date": "2025-12-30",
  "phase": "phase3"
}
```

**Valid Phases:** `phase3`, `phase4`, `phase5`

**Response:**
```json
{
  "status": "triggered",
  "date": "2025-12-30",
  "phase": "phase3",
  "message": "Phase phase3 retry triggered"
}
```

---

## HTMX Partial Endpoints

These endpoints return HTML fragments for HTMX updates.

### GET /partials/status-cards

Returns status cards HTML for today/tomorrow.

### GET /partials/games-table/:date

Returns games table HTML for a specific date.

### GET /partials/error-feed

Returns error feed HTML.

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "error": "Error description"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad request (missing parameters)
- `401` - Unauthorized (invalid/missing API key)
- `500` - Server error
