# API Specification

**Created:** December 17, 2024
**Purpose:** REST API endpoint contracts for frontend integration

---

## Overview

This document specifies the REST API endpoints needed to serve the Props Web frontend. The API will be built as a separate service (recommended: `props-api` repo) using FastAPI.

---

## Base URL

- **Production:** `https://api.propsplatform.com/v1`
- **Staging:** `https://api-staging.propsplatform.com/v1`
- **Local:** `http://localhost:8000/v1`

---

## Authentication

For MVP, no authentication required. Future premium features will use:

```
Authorization: Bearer <jwt_token>
```

---

## Common Response Format

All responses follow this structure:

```json
{
  "data": { ... },
  "meta": {
    "generated_at": "2024-12-17T12:00:00Z",
    "cache_until": "2024-12-17T12:05:00Z",
    "version": "1.0"
  }
}
```

Error responses:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Player not found: invalid-player-lookup",
    "details": {}
  }
}
```

---

## Player Endpoints

### GET /v1/player/{player_lookup}/game-report/{date}

Returns detailed analysis for a specific player and game date.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `player_lookup` | string | Normalized player identifier (e.g., "stephen-curry") |
| `date` | string | Game date in YYYY-MM-DD format |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_prediction` | boolean | true | Include prediction data |
| `include_angles` | boolean | true | Include prediction angles |

**Response:** See frontend spec `data-requirements.md` lines 117-380

**Example Request:**
```
GET /v1/player/stephen-curry/game-report/2024-12-17
```

**Example Response:**
```json
{
  "data": {
    "player_lookup": "stephen-curry",
    "player_full_name": "Stephen Curry",
    "team_abbr": "GSW",
    "game_date": "2024-12-17",
    "game_status": "scheduled",

    "game_info": {
      "opponent": "POR",
      "opponent_full": "Portland Trail Blazers",
      "home": true,
      "game_time": "7:30 PM ET",
      "days_rest": 3,
      "is_b2b": false,
      "final_score": null
    },

    "player_profile": {
      "archetype": "veteran_star",
      "archetype_label": "Veteran Star",
      "shot_profile": "perimeter",
      "years_in_league": 15,
      "usage_rate": 0.28,
      "rest_sensitivity": "high",
      "home_sensitivity": "high"
    },

    "player_stats": {
      "season_ppg": 27.4,
      "ppg_rank": 12,
      "games_played": 26
    },

    "opponent_context": {
      "team_abbr": "POR",
      "pace": 101.2,
      "pace_rank": 8,
      "is_opponent_b2b": false,
      "defense_rank": 24,
      "defense_vs_player_profile": {
        "shot_profile": "perimeter",
        "fg_pct_allowed": 0.382,
        "vs_league_avg": 2.1,
        "defense_rank": 26
      }
    },

    "prop_lines": {
      "points": {
        "current_line": 26.5,
        "opening_line": 27.5,
        "line_movement": -1.0,
        "season_avg_line": 26.8,
        "available": true
      }
    },

    "moving_averages": {
      "points": {
        "l5_avg": 29.2,
        "l10_avg": 28.4,
        "l20_avg": 27.8,
        "season_avg": 27.4,
        "trend": "up"
      },
      "lines": {
        "l5_avg_line": 26.8,
        "l10_avg_line": 26.5,
        "trend": "up"
      },
      "margin_vs_line": {
        "l5_avg": 2.4,
        "l10_avg": 1.9,
        "l20_avg": 1.5
      }
    },

    "prediction": {
      "predicted_points": 29.2,
      "recommendation": "OVER",
      "confidence": 0.72,
      "edge": 2.7
    },

    "prediction_angles": {
      "supporting": [
        {
          "angle_id": "home_advantage",
          "text": "playing at home where he averages 2.3 more points",
          "impact": 2.3
        },
        {
          "angle_id": "rest",
          "text": "coming off 3 days of rest",
          "impact": 1.8
        }
      ],
      "against": []
    },

    "recent_games": [
      {
        "date": "2024-12-13",
        "opponent": "LAL",
        "home": true,
        "points": 31,
        "line": 26.5,
        "result": "OVER",
        "margin": 4.5,
        "days_rest": 2,
        "team_result": "W"
      }
    ],

    "head_to_head": {
      "opponent": "POR",
      "games": [],
      "summary": {
        "record": "4-1",
        "avg_points": 29.6,
        "avg_margin": 3.1,
        "over_rate": 0.80
      }
    },

    "our_track_record": {
      "player_specific": {
        "predictions": 24,
        "hits": 18,
        "hit_rate": 0.75
      }
    }
  },
  "meta": {
    "generated_at": "2024-12-17T12:00:00Z",
    "cache_until": "2024-12-17T12:05:00Z"
  }
}
```

**Caching:**
| Game Status | Cache Duration |
|-------------|----------------|
| Future games | 5 minutes |
| Today (pre-game) | 1 minute |
| In progress | No cache |
| Final (past) | 24 hours |

---

### GET /v1/player/{player_lookup}/season/{season}

Returns season aggregates and analysis for a player.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `player_lookup` | string | Normalized player identifier |
| `season` | string | Season in YYYY-YY format (e.g., "2024-25") |

**Response:** See frontend spec `data-requirements.md` lines 707-901

**Example Request:**
```
GET /v1/player/stephen-curry/season/2024-25
```

**Caching:** 6 hours

---

### GET /v1/player/{player_lookup}/games

Returns paginated game log for a player.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `player_lookup` | string | Normalized player identifier |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `season` | string | current | Filter by season |
| `limit` | int | 20 | Games per page (max 100) |
| `offset` | int | 0 | Pagination offset |
| `opponent` | string | null | Filter by opponent team |

**Response:**
```json
{
  "data": {
    "player_lookup": "stephen-curry",
    "games": [
      {
        "date": "2024-12-13",
        "opponent": "LAL",
        "home": true,
        "points": 31,
        "line": 26.5,
        "result": "OVER",
        "margin": 4.5,
        "rebounds": 5,
        "assists": 7,
        "minutes": 34
      }
    ],
    "pagination": {
      "total": 26,
      "limit": 20,
      "offset": 0,
      "has_more": true
    }
  }
}
```

---

## Trends Endpoints

### GET /v1/trends/whos-hot

Returns hot and cold players based on heat score.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | "14d" | Time window: 7d, 14d, 30d, season |
| `limit` | int | 10 | Players per list (max 25) |
| `playing_tonight` | boolean | null | Filter to players with games today |

**Response:**
```json
{
  "data": {
    "as_of_date": "2024-12-17",
    "period": "14d",
    "hot_players": [
      {
        "player_lookup": "stephen-curry",
        "player_full_name": "Stephen Curry",
        "team_abbr": "GSW",
        "position": "PG",
        "heat_score": 8.7,
        "hit_rate": 0.70,
        "hit_rate_games": 10,
        "current_streak": 5,
        "streak_direction": "over",
        "avg_margin": 4.8,
        "playing_tonight": true,
        "tonight": {
          "opponent": "POR",
          "game_time": "7:30 PM",
          "home": true,
          "prop_line": 26.5
        }
      }
    ],
    "cold_players": [
      // Similar structure
    ]
  }
}
```

**Caching:** 1 hour (refreshed at 6:30 AM ET)

---

### GET /v1/trends/bounce-back

Returns bounce-back candidates.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `signal_strength` | string | null | Filter: "strong", "moderate" |
| `playing_tonight` | boolean | null | Filter to players with games today |
| `limit` | int | 20 | Max candidates |

**Response:**
```json
{
  "data": {
    "as_of_date": "2024-12-17",
    "candidates": [
      {
        "player_lookup": "trae-young",
        "player_full_name": "Trae Young",
        "team_abbr": "ATL",
        "prop_type": "points",
        "last_game": {
          "result": 14,
          "line": 26.5,
          "margin": -12.5,
          "opponent": "MIA",
          "context": "foul trouble"
        },
        "streak": {
          "consecutive_misses": 3,
          "avg_miss_margin": -8.2
        },
        "baseline": {
          "season_hit_rate": 0.68,
          "season_avg": 27.2
        },
        "tonight": {
          "opponent": "CHA",
          "opp_defense_rank": 29,
          "current_line": 26.5,
          "game_time": "7:30 PM",
          "home": true
        },
        "signal_strength": "strong"
      }
    ]
  }
}
```

---

### GET /v1/trends/what-matters

Returns archetype-based situational patterns.

**Response:**
```json
{
  "data": {
    "as_of_date": "2024-12-17",
    "factors": [
      {
        "factor_id": "rest",
        "factor_label": "Rest Impact",
        "factor_icon": "couch",
        "insight": "Veteran stars benefit most from rest",
        "archetypes": [
          {
            "archetype": "veteran_star",
            "archetype_label": "Veteran Stars (10+ seasons)",
            "example_players": ["LeBron", "Curry", "KD"],
            "player_count": 12,
            "with_factor_avg": 28.4,
            "without_factor_avg": 24.2,
            "impact": 4.2,
            "over_rate": 0.62,
            "sample_size": 189,
            "significance": "very_significant"
          }
        ]
      }
    ]
  }
}
```

**Caching:** 24 hours (refreshed weekly on Monday)

---

### GET /v1/trends/team-tendencies

Returns team-level tendencies.

**Response:**
```json
{
  "data": {
    "as_of_date": "2024-12-17",
    "pace_kings": [
      {
        "team_abbr": "IND",
        "team_name": "Indiana Pacers",
        "pace": 105.2,
        "pace_rank": 1,
        "opponent_ppg_boost": 4.8,
        "over_rate": 0.58,
        "sample_games": 28
      }
    ],
    "pace_grinders": [],
    "defense_by_shot_profile": {
      "interior": {
        "toughest": [],
        "friendliest": []
      },
      "perimeter": {
        "toughest": [],
        "friendliest": []
      }
    },
    "home_advantage": [],
    "b2b_vulnerable": []
  }
}
```

---

### GET /v1/trends/quick-hits

Returns bite-sized stat nuggets.

**Response:**
```json
{
  "data": {
    "as_of_date": "2024-12-17",
    "hits": [
      {
        "id": "qh1",
        "category": "day_of_week",
        "main_stat": "58%",
        "description": "Friday night overs hit this season",
        "sample_size": 127,
        "is_positive": true
      }
    ]
  }
}
```

---

## Prediction Endpoints

### GET /v1/predictions/performance

Returns prediction accuracy statistics.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | "30d" | Time window: 7d, 14d, 30d, season |
| `prop_type` | string | null | Filter: points, rebounds, assists |
| `confidence_min` | float | null | Minimum confidence (0-1) |
| `archetype` | string | null | Filter by player archetype |
| `player_lookup` | string | null | Specific player |

**Response:**
```json
{
  "data": {
    "period": "30d",
    "filters_applied": {
      "confidence_min": 0.70
    },
    "summary": {
      "total_predictions": 194,
      "hits": 142,
      "misses": 52,
      "hit_rate": 0.732,
      "avg_confidence": 0.76,
      "avg_margin": 2.8
    },
    "by_confidence_tier": [
      {
        "tier": "high",
        "confidence_range": [0.70, 1.0],
        "predictions": 194,
        "hits": 142,
        "hit_rate": 0.732
      }
    ],
    "by_archetype": [],
    "by_situation": [],
    "daily_trend": []
  }
}
```

---

### GET /v1/predictions/player/{player_lookup}

Returns prediction track record for a specific player.

**Response:**
```json
{
  "data": {
    "player_lookup": "stephen-curry",
    "player_full_name": "Stephen Curry",
    "total_predictions": 24,
    "hits": 18,
    "hit_rate": 0.75,
    "by_recommendation": {
      "OVER": { "predictions": 18, "hits": 14, "hit_rate": 0.78 },
      "UNDER": { "predictions": 6, "hits": 4, "hit_rate": 0.67 }
    },
    "recent_predictions": [
      {
        "game_date": "2024-12-13",
        "predicted_points": 28.5,
        "actual_points": 31,
        "recommendation": "OVER",
        "hit": true,
        "confidence": 0.72
      }
    ]
  }
}
```

---

## Search Endpoint

### GET /v1/search/players

Search for players by name.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | yes | Search query (min 2 chars) |
| `limit` | int | no | Max results (default 10) |

**Response:**
```json
{
  "data": {
    "query": "curry",
    "results": [
      {
        "player_lookup": "stephen-curry",
        "player_full_name": "Stephen Curry",
        "team_abbr": "GSW",
        "position": "PG"
      },
      {
        "player_lookup": "seth-curry",
        "player_full_name": "Seth Curry",
        "team_abbr": "CHA",
        "position": "SG"
      }
    ]
  }
}
```

---

## Health Endpoints

### GET /v1/health

Basic health check.

```json
{
  "status": "healthy",
  "timestamp": "2024-12-17T12:00:00Z"
}
```

### GET /v1/health/detailed

Detailed health with dependencies.

```json
{
  "status": "healthy",
  "timestamp": "2024-12-17T12:00:00Z",
  "dependencies": {
    "bigquery": { "status": "healthy", "latency_ms": 45 },
    "cache": { "status": "healthy", "hit_rate": 0.85 }
  },
  "data_freshness": {
    "player_game_summary": "2024-12-17T06:00:00Z",
    "player_archetypes": "2024-12-17T06:00:00Z",
    "predictions": "2024-12-17T12:00:00Z"
  }
}
```

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `NOT_FOUND` | 404 | Resource not found |
| `INVALID_DATE` | 400 | Invalid date format |
| `INVALID_PLAYER` | 400 | Invalid player lookup |
| `INVALID_SEASON` | 400 | Invalid season format |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |

---

## Rate Limiting

| Tier | Requests/min | Burst |
|------|--------------|-------|
| Free | 60 | 100 |
| Pro | 300 | 500 |
| Elite | 1000 | 2000 |

Rate limit headers:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1702814400
```

---

## Implementation Notes

### BigQuery Query Patterns

For optimal performance:

1. **Always include partition filter** (game_date)
2. **Use clustered columns** in WHERE clauses
3. **Limit result sets** - paginate large responses
4. **Cache aggressively** - historical data doesn't change

### Recommended Tech Stack

- **Framework:** FastAPI (async support, auto-docs)
- **Database Client:** google-cloud-bigquery async
- **Caching:** Redis with fallback to in-memory
- **Deployment:** Cloud Run (auto-scaling)
- **Monitoring:** Cloud Monitoring + custom metrics

### Response Time Targets

| Endpoint Type | Cached | Uncached |
|---------------|--------|----------|
| Single player | < 100ms | < 500ms |
| Aggregations | < 200ms | < 1s |
| Search | < 50ms | < 200ms |
| Trends | < 100ms | < 500ms |
