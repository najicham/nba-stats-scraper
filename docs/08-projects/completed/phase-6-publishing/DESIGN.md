# Phase 6: Website Publishing - Design Document

**Status:** Design Phase
**Created:** 2025-12-10
**Purpose:** Prepare and export prediction data for frontend website consumption

---

## 1. Executive Summary

Phase 6 transforms internal BigQuery data into formats consumable by the React/Next.js website. This includes:

- **JSON files in GCS** for bulk data (predictions, historical results)
- **Firestore documents** for real-time/interactive data

Unlike Phase 5C (ML feedback), Phase 6 data is READ-ONLY by the frontend - it doesn't flow back into the prediction pipeline.

---

## 2. Data Flow

```
Phase 5A: Predictions → player_prop_predictions
Phase 5B: Grading → prediction_accuracy
Phase 5C: ML Feedback → (internal tables)
    ↓
Phase 6: Publishing ← YOU ARE HERE
    ├── GCS JSON files (static, CDN-cached)
    └── Firestore collections (real-time)
    ↓
Website: React/Next.js frontend
```

---

## 3. What the Website Needs

### 3.1 Daily Predictions Page

**URL:** `/predictions/today` or `/predictions/2025-01-15`

**Data Needed:**
- All players playing that day
- Their predictions from ensemble system
- Confidence scores
- Recommended action (OVER/UNDER/PASS)
- Betting line
- Supporting context (recent form, matchup, etc.)

**Grouping:** By game (so user can browse game-by-game)

### 3.2 System Performance Dashboard

**URL:** `/systems` or `/accuracy`

**Data Needed:**
- Each system's accuracy metrics
- Rolling accuracy (7-day, 30-day, season)
- Win rate trends over time
- Comparison charts

### 3.3 Player Profile Pages

**URL:** `/players/lebron-james`

**Data Needed:**
- Player info (name, team, position)
- How well we predict this player
- Recent predictions and results
- Historical accuracy

### 3.4 Best Bets Page

**URL:** `/best-bets`

**Data Needed:**
- Top N highest confidence picks for today
- Ranked by composite score (confidence + edge + historical accuracy)
- Filters: by confidence tier, by edge size

### 3.5 Historical Results

**URL:** `/results/2025-01-14`

**Data Needed:**
- Yesterday's predictions vs actuals
- Which picks hit, which missed
- System performance for the day

---

## 4. Delivery Methods

### 4.1 GCS Static JSON (Primary)

**Best For:**
- Bulk data that changes once daily
- Data that can be cached aggressively
- Reducing backend query load

**Implementation:**
```
gs://nba-props-platform-api/v1/
├── predictions/
│   ├── today.json           # Current day's predictions
│   ├── 2025-01-15.json      # Historical predictions
│   └── ...
├── results/
│   ├── latest.json          # Most recent graded results
│   ├── 2025-01-14.json      # Historical results
│   └── ...
├── systems/
│   ├── performance.json     # All systems rolling accuracy
│   └── daily/
│       └── 2025-01-15.json  # Per-day system performance
├── best-bets/
│   ├── today.json           # Today's top picks
│   └── ...
└── players/
    ├── index.json           # Player list with summary stats
    └── lebron_james/
        └── profile.json     # Full player profile
```

**Serving:**
- Cloud Storage with Cloud CDN in front
- Cache-Control headers based on data freshness
- CORS configured for frontend domain

### 4.2 Firestore (Secondary)

**Best For:**
- Real-time updates during games
- Interactive queries (filtering, pagination)
- User-specific data (favorites, watchlist)

**Collections:**
```
/predictions/{game_date}/games/{game_id}
/predictions/{game_date}/players/{player_lookup}
/systems/{system_id}/performance
/players/{player_lookup}/summary
/best_bets/{game_date}/picks/{rank}
```

**When to Use Firestore:**
- If user needs to filter/sort client-side
- If data updates during active games
- If user has personalized views

---

## 5. JSON Schemas

### 5.1 Daily Predictions (`predictions/today.json`)

```json
{
  "game_date": "2025-01-15",
  "generated_at": "2025-01-15T09:00:00Z",
  "total_games": 8,
  "total_predictions": 156,
  "games": [
    {
      "game_id": "0022400123",
      "game_time": "2025-01-15T19:00:00Z",
      "home_team": {
        "id": "1610612747",
        "abbreviation": "LAL",
        "name": "Los Angeles Lakers"
      },
      "away_team": {
        "id": "1610612744",
        "abbreviation": "GSW",
        "name": "Golden State Warriors"
      },
      "predictions": [
        {
          "player_lookup": "lebron_james",
          "display_name": "LeBron James",
          "team": "LAL",
          "position": "F",
          "is_home": true,
          "prediction": {
            "points": 27.5,
            "confidence": 0.78,
            "recommendation": "OVER",
            "line": 25.5,
            "edge": 2.0
          },
          "context": {
            "points_last_5": 28.2,
            "points_season": 25.8,
            "minutes_avg": 35.2,
            "opponent_def_rating": 112.5
          },
          "systems": {
            "moving_average": 26.8,
            "zone_matchup": 28.1,
            "similarity": 27.2,
            "xgboost": 27.9,
            "ensemble": 27.5
          },
          "historical_accuracy": {
            "player_mae_last_10": 4.2,
            "player_win_rate_last_10": 0.70
          }
        }
        // ... more players
      ]
    }
    // ... more games
  ]
}
```

### 5.2 System Performance (`systems/performance.json`)

```json
{
  "as_of_date": "2025-01-15",
  "generated_at": "2025-01-15T02:00:00Z",
  "systems": [
    {
      "system_id": "ensemble_v1",
      "display_name": "Ensemble",
      "description": "Weighted combination of all systems",
      "is_primary": true,
      "windows": {
        "last_7_days": {
          "predictions": 245,
          "mae": 4.32,
          "win_rate": 0.892,
          "over_win_rate": 0.76,
          "under_win_rate": 0.94
        },
        "last_30_days": {
          "predictions": 1050,
          "mae": 4.51,
          "win_rate": 0.878,
          "over_win_rate": 0.74,
          "under_win_rate": 0.93
        },
        "season": {
          "predictions": 9798,
          "mae": 4.51,
          "win_rate": 0.924,
          "over_win_rate": 0.751,
          "under_win_rate": 0.937
        }
      },
      "trend": "stable",  // "improving", "declining", "stable"
      "ranking": 1
    }
    // ... more systems
  ],
  "comparison": {
    "best_mae": "ensemble_v1",
    "best_win_rate": "moving_average_baseline_v1",
    "most_consistent": "ensemble_v1"
  }
}
```

### 5.3 Best Bets (`best-bets/today.json`)

```json
{
  "game_date": "2025-01-15",
  "generated_at": "2025-01-15T09:00:00Z",
  "methodology": "Ranked by composite score: confidence * edge * historical_accuracy",
  "picks": [
    {
      "rank": 1,
      "player_lookup": "stephen_curry",
      "display_name": "Stephen Curry",
      "team": "GSW",
      "game_id": "0022400123",
      "opponent": "LAL",
      "recommendation": "OVER",
      "line": 26.5,
      "prediction": 29.8,
      "edge": 3.3,
      "confidence": 0.82,
      "composite_score": 0.91,
      "rationale": [
        "High system agreement (variance: 1.2)",
        "Strong recent form (31.5 ppg last 5)",
        "Favorable matchup vs LAL defense (115.2 def rating)"
      ],
      "risk_factors": [
        "Back-to-back game"
      ]
    }
    // ... more picks (top 10-20)
  ]
}
```

### 5.4 Daily Results (`results/2025-01-14.json`)

```json
{
  "game_date": "2025-01-14",
  "generated_at": "2025-01-15T02:00:00Z",
  "summary": {
    "total_predictions": 148,
    "total_recommendations": 95,
    "correct": 87,
    "incorrect": 8,
    "win_rate": 0.916,
    "avg_mae": 4.28
  },
  "by_system": [
    {
      "system_id": "ensemble_v1",
      "predictions": 148,
      "recommendations": 95,
      "correct": 87,
      "win_rate": 0.916,
      "mae": 4.28
    }
    // ... more systems
  ],
  "results": [
    {
      "player_lookup": "lebron_james",
      "display_name": "LeBron James",
      "game_id": "0022400122",
      "predicted": 27.5,
      "actual": 31,
      "line": 25.5,
      "recommendation": "OVER",
      "result": "WIN",
      "error": 3.5
    }
    // ... more results
  ],
  "highlights": {
    "biggest_hit": {
      "player": "Luka Doncic",
      "predicted": 35.2,
      "actual": 36,
      "error": 0.8
    },
    "biggest_miss": {
      "player": "Some Player",
      "predicted": 18.5,
      "actual": 8,
      "error": 10.5,
      "reason": "Early foul trouble, only 22 minutes"
    }
  }
}
```

### 5.5 Player Profile (`players/lebron_james/profile.json`)

```json
{
  "player_lookup": "lebron_james",
  "display_name": "LeBron James",
  "team": "LAL",
  "position": "F",
  "jersey_number": 23,
  "last_updated": "2025-01-15T02:00:00Z",
  "prediction_accuracy": {
    "sample_size": 45,
    "our_mae": 4.8,
    "our_win_rate": 0.72,
    "our_bias": -2.1,
    "notes": "We tend to under-predict LeBron by ~2 points"
  },
  "recent_predictions": [
    {
      "game_date": "2025-01-14",
      "opponent": "GSW",
      "predicted": 27.5,
      "actual": 31,
      "line": 25.5,
      "recommendation": "OVER",
      "result": "WIN"
    }
    // ... last 10 games
  ],
  "season_stats": {
    "ppg": 25.8,
    "minutes": 35.2,
    "games_played": 42
  }
}
```

---

## 6. BigQuery Aggregation Tables

Before exporting to JSON, we need intermediate tables for efficient querying.

### 6.1 `system_daily_performance`

**Purpose:** Pre-aggregate daily system metrics for performance dashboard.

```sql
-- Keys: (game_date, system_id)
-- Metrics: mae, win_rate, over/under breakdown, rolling windows
-- Refresh: Daily after Phase 5B grading
```

### 6.2 `player_accuracy_summary`

**Purpose:** Pre-aggregate per-player accuracy for player profiles.

```sql
-- Keys: (player_lookup, system_id)
-- Metrics: sample_size, mae, win_rate, bias
-- Refresh: Daily
```

### 6.3 `daily_predictions_export`

**Purpose:** Denormalized view ready for JSON export.

```sql
-- Joins predictions with player info, game info, lines
-- One row per player-prediction
-- Refresh: Daily before games (after Phase 5A)
```

---

## 7. Processing Pipeline

### 7.1 Daily Schedule

```
06:00 AM - Phase 5A predictions complete
    ↓
07:00 AM - Phase 6 export job runs
    ├── Query daily_predictions_export
    ├── Transform to JSON
    ├── Upload to GCS: predictions/today.json
    └── (Optional) Update Firestore

02:00 AM (next day) - Phase 5B grading complete
    ↓
03:00 AM - Phase 6 results export
    ├── Query prediction_accuracy for yesterday
    ├── Aggregate system_daily_performance
    ├── Transform to JSON
    ├── Upload to GCS: results/{date}.json
    ├── Upload to GCS: systems/performance.json
    └── (Optional) Update Firestore
```

### 7.2 Processors

```
data_processors/publishing/
├── __init__.py
├── daily_predictions_exporter.py    # Predictions JSON
├── daily_results_exporter.py        # Results JSON
├── system_performance_exporter.py   # System metrics JSON
├── best_bets_exporter.py            # Best bets JSON
├── player_profile_exporter.py       # Player profiles JSON
└── firestore_syncer.py              # Firestore sync (if needed)
```

---

## 8. GCS Bucket Setup

### 8.1 Bucket Configuration

```
Bucket: nba-props-platform-api
Location: us-central1 (or multi-region)
Storage Class: Standard
Public Access: Uniform (with Cloud CDN)
```

### 8.2 CORS Configuration

```json
[
  {
    "origin": ["https://nbaprops.com", "http://localhost:3000"],
    "method": ["GET"],
    "responseHeader": ["Content-Type", "Cache-Control"],
    "maxAgeSeconds": 3600
  }
]
```

### 8.3 Cache Headers

| File Pattern | Cache-Control |
|--------------|---------------|
| `predictions/today.json` | `public, max-age=300` (5 min) |
| `predictions/{date}.json` | `public, max-age=86400` (1 day) |
| `results/latest.json` | `public, max-age=300` (5 min) |
| `results/{date}.json` | `public, max-age=86400` (1 day) |
| `systems/performance.json` | `public, max-age=3600` (1 hour) |
| `players/*/profile.json` | `public, max-age=3600` (1 hour) |

---

## 9. Firestore Structure (If Needed)

### 9.1 Collections

```
predictions/
  {game_date}/
    metadata: { total_games, total_predictions, generated_at }
    games/
      {game_id}/
        home_team, away_team, game_time
        players/
          {player_lookup}/
            prediction, confidence, recommendation, line, ...

systems/
  {system_id}/
    display_name, description
    performance/
      {window_type}/
        mae, win_rate, predictions, ...

players/
  {player_lookup}/
    display_name, team, position
    accuracy: { mae, win_rate, bias, sample_size }
    recent_predictions: [...]
```

### 9.2 When to Use Firestore vs GCS

| Use Case | GCS JSON | Firestore |
|----------|----------|-----------|
| Load all predictions for a day | ✅ | ❌ (too many reads) |
| Filter predictions by team | ❌ | ✅ |
| Real-time score updates | ❌ | ✅ |
| Historical charts | ✅ | ❌ |
| User favorites list | ❌ | ✅ |

---

## 10. Implementation Priority

### Phase 6.1 (MVP)
1. **`predictions/today.json`** - Core product feature
2. **`systems/performance.json`** - Trust/transparency
3. **`results/latest.json`** - Show our track record

### Phase 6.2 (Enhanced)
4. **`best-bets/today.json`** - High-value feature
5. **Historical predictions** - `predictions/{date}.json`
6. **Historical results** - `results/{date}.json`

### Phase 6.3 (Full)
7. **Player profiles** - `players/{lookup}/profile.json`
8. **Firestore sync** - Real-time features
9. **Player index** - Browse all players

---

## 11. Success Metrics

| Metric | Target |
|--------|--------|
| JSON generation time | < 30 seconds |
| File size (predictions/today) | < 500 KB |
| Cache hit rate | > 90% |
| API latency (CDN) | < 100ms p95 |

---

## 12. Open Questions

1. **Historical depth?** How many days of historical predictions/results to keep as JSON?
2. **Player profiles scope?** All players or only players with N+ predictions?
3. **Firestore necessity?** Can we launch with GCS-only and add Firestore later?
4. **Best bets criteria?** What composite score formula? Top 10 or top 20?
5. **Authentication?** Is any data behind auth, or all public?

---

## 13. Files to Create

```
data_processors/publishing/
├── __init__.py
├── predictions_exporter.py
├── results_exporter.py
├── system_performance_exporter.py
├── best_bets_exporter.py
├── player_profile_exporter.py
└── gcs_uploader.py

backfill_jobs/publishing/
├── __init__.py
└── publishing_backfill.py

schemas/bigquery/nba_predictions/
├── system_daily_performance.sql
├── player_accuracy_summary.sql
└── daily_predictions_export.sql

shared/publishing/
├── __init__.py
├── json_transformer.py
└── gcs_client.py
```

---

## 14. Next Steps

1. [ ] Review this design
2. [ ] Answer open questions
3. [ ] Create GCS bucket and configure
4. [ ] Create aggregation tables in BigQuery
5. [ ] Implement exporters
6. [ ] Set up Cloud Scheduler for daily exports
7. [ ] Test with frontend

---

**Document End**
