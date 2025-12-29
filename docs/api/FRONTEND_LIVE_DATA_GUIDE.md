# Frontend Guide: Live Data Integration

**Last Updated:** 2025-12-28
**Status:** Production
**Contact:** Backend Team

---

## Overview

This guide explains how to integrate with the live data pipeline, including the new **status.json** endpoint for monitoring data freshness.

---

## API Endpoints

### 1. Status Endpoint (NEW)
```
GET https://storage.googleapis.com/nba-props-platform-api/v1/status.json
```

**Purpose:** Check the health of all backend services before displaying data to users.

**Response:**
```json
{
  "updated_at": "2025-12-29T00:42:32Z",
  "overall_status": "healthy",
  "services": {
    "live_data": {
      "status": "healthy",
      "message": "Data is fresh",
      "last_update": "2025-12-29T00:42:03Z",
      "age_minutes": 0.5,
      "is_stale": false,
      "games_active": true,
      "next_update_expected": "2025-12-29T00:45:03Z"
    },
    "tonight_data": {
      "status": "healthy",
      "message": "Data is fresh",
      "last_update": "2025-12-28T23:37:05Z",
      "age_minutes": 42.5,
      "is_stale": false
    },
    "grading": {
      "status": "healthy",
      "message": "Grading data available",
      "last_update": "2025-12-29T00:42:32Z"
    },
    "predictions": {
      "status": "healthy",
      "message": "650 predictions available for 2025-12-28",
      "predictions_count": 650,
      "target_date": "2025-12-28"
    }
  },
  "known_issues": [],
  "maintenance_windows": []
}
```

**Recommended Polling:** Every 30-60 seconds during game hours

---

### 2. Live Scores
```
GET https://storage.googleapis.com/nba-props-platform-api/v1/live/latest.json
```

**Update Frequency:** Every 3 minutes during games (4 PM - 1 AM ET)

**Use For:** Real-time game scores, player stats during games

---

### 3. Live Grading
```
GET https://storage.googleapis.com/nba-props-platform-api/v1/live-grading/latest.json
```

**Update Frequency:** Every 3 minutes during games

**Use For:** Challenge grading, showing if picks are winning/losing

---

### 4. Tonight's Players
```
GET https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json
```

**Update Frequency:** After predictions are generated (~2 PM ET) and hourly

**Use For:** Homepage player cards, predictions display

---

## How to Use Status.json

### Basic Health Check

```typescript
interface ServiceStatus {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  message: string;
  last_update?: string;
  age_minutes?: number;
  is_stale?: boolean;
}

interface StatusResponse {
  updated_at: string;
  overall_status: 'healthy' | 'degraded' | 'unhealthy';
  services: {
    live_data: ServiceStatus & {
      games_active: boolean;
      next_update_expected?: string;
    };
    tonight_data: ServiceStatus;
    grading: ServiceStatus;
    predictions: ServiceStatus & {
      predictions_count: number;
      target_date: string;
    };
  };
  known_issues: Array<{
    severity: string;
    message: string;
    detected_at: string;
  }>;
  maintenance_windows: any[];
}

async function checkBackendHealth(): Promise<StatusResponse> {
  const response = await fetch(
    'https://storage.googleapis.com/nba-props-platform-api/v1/status.json'
  );
  return response.json();
}
```

### Recommended UI Patterns

#### 1. Show Loading State When Data is Stale

```typescript
function LiveScoresComponent() {
  const [status, setStatus] = useState<StatusResponse | null>(null);

  // Poll status every 30 seconds
  useEffect(() => {
    const interval = setInterval(async () => {
      const s = await checkBackendHealth();
      setStatus(s);
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  if (status?.services.live_data.is_stale) {
    return (
      <div className="loading-overlay">
        <Spinner />
        <p>Updating live scores...</p>
        <small>Last update: {formatTime(status.services.live_data.last_update)}</small>
      </div>
    );
  }

  return <LiveScoresDisplay />;
}
```

#### 2. Show Banner for Known Issues

```typescript
function KnownIssuesBanner({ status }: { status: StatusResponse }) {
  if (status.known_issues.length === 0) return null;

  return (
    <div className="alert alert-warning">
      {status.known_issues.map((issue, i) => (
        <p key={i}>{issue.message}</p>
      ))}
    </div>
  );
}
```

#### 3. Disable Grading When Unavailable

```typescript
function ChallengeGrading({ status }: { status: StatusResponse }) {
  if (status.services.grading.status !== 'healthy') {
    return (
      <div className="grading-unavailable">
        <p>Grading temporarily unavailable</p>
        <small>{status.services.grading.message}</small>
      </div>
    );
  }

  return <GradingDisplay />;
}
```

#### 4. Show "No Games" State

```typescript
function LiveDataSection({ status }: { status: StatusResponse }) {
  if (!status.services.live_data.games_active) {
    return (
      <div className="no-games">
        <p>No games currently in progress</p>
        <small>Live data will update when games start</small>
      </div>
    );
  }

  return <LiveScores />;
}
```

---

## Status Values Reference

### overall_status
| Value | Meaning | Action |
|-------|---------|--------|
| `healthy` | All services working normally | Display data normally |
| `degraded` | Some services have issues | Show warning, data may be stale |
| `unhealthy` | Critical issues | Show error state |

### Service-Level status
| Value | Meaning |
|-------|---------|
| `healthy` | Service working normally |
| `degraded` | Service has minor issues (e.g., stale data) |
| `unhealthy` | Service is down or has major issues |
| `unknown` | Unable to determine status |

### is_stale (live_data only)
- `true` = Data is older than 10 minutes AND games are active
- `false` = Data is fresh OR no games are active

### games_active (live_data only)
- `true` = NBA games are currently in progress (4 PM - 1 AM ET typically)
- `false` = No games in progress

---

## What Changed (2025-12-28)

### Problem Solved
Live data was showing yesterday's games because:
1. Scheduler didn't start until 7 PM but games started at 6 PM
2. Late-night runs mislabeled yesterday's games as today
3. No way for frontend to detect stale data

### Fixes Applied

1. **Scheduler Expanded**
   - Now runs 4 PM - 1 AM ET (was 7 PM - 1 AM)
   - Covers all game start times including weekends/holidays

2. **Date Filtering Added**
   - Live data now only includes games matching the target date
   - Prevents date mismatch bugs

3. **Status Endpoint Added**
   - Frontend can now detect stale data
   - Shows health of all services
   - Lists any known issues

4. **Self-Healing Monitor Added**
   - Runs every 5 minutes during games
   - Auto-fixes stale data
   - Alerts backend team on persistent issues

---

## Troubleshooting

### "Data looks stale but status says healthy"
- Check `age_minutes` - if < 10, data is considered fresh
- During off-hours, data won't update (this is expected)

### "No predictions showing"
- Check `status.services.predictions.predictions_count`
- If 0, predictions may not have been generated yet (usually ready by 2 PM ET)

### "Grading not working"
- Check `status.services.grading.status`
- Verify `status.services.live_data.games_active` is true

### "Live scores show wrong games"
- This should be fixed now with date filtering
- Check `game_date` in live/latest.json matches today
- Report to backend if mismatch occurs

---

## Related Endpoints

| Endpoint | Purpose | Update Frequency |
|----------|---------|------------------|
| `/v1/status.json` | Health check | Every 3 min during games |
| `/v1/live/latest.json` | Live game scores | Every 3 min during games |
| `/v1/live-grading/latest.json` | Prediction grading | Every 3 min during games |
| `/v1/tonight/all-players.json` | Tonight's predictions | Hourly |
| `/v1/live/{date}.json` | Historical live data | Once (at game end) |
| `/v1/live-grading/{date}.json` | Historical grading | Once (at game end) |

---

## Questions?

Create an issue or reach out to the backend team.
