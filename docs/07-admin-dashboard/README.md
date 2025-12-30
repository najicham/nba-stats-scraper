# NBA Admin Dashboard

The Admin Dashboard is a Flask-based web application for monitoring the NBA Props pipeline orchestration. It provides real-time visibility into pipeline status, errors, and allows manual intervention when needed.

## Overview

**URL:** `https://nba-admin-dashboard-756957797294.us-west2.run.app/dashboard`

**Authentication:** API key required (passed as `?key=YOUR_KEY` or `X-API-Key` header)

**Tech Stack:**
- Flask + Jinja2 (server-side rendering)
- Tailwind CSS (styling via CDN)
- HTMX (partial page updates without full reload)
- Alpine.js (client-side interactivity)
- Tabulator.js (advanced tables)

## Features

### 1. Pipeline Status Cards
Shows at-a-glance status for Today and Tomorrow:
- Games scheduled
- Predictions count
- Phase 3 context records
- Phase 4 ML features
- Overall pipeline status (COMPLETE, PENDING, etc.)

### 2. Games Table
Per-game breakdown showing:
- Home/Away teams
- Context count (Phase 3)
- Feature count (Phase 4)
- Prediction count (Phase 5)
- Individual game status

Games with missing data are highlighted in red.

### 3. Error Feed
Recent errors from Cloud Logging:
- Service name
- Severity level
- Error message
- Timestamp

### 4. Scheduler History
Timeline of Cloud Scheduler job executions:
- Job name
- Execution time
- Status (success/error/triggered)

### 5. 7-Day History
Historical view of pipeline status:
- Date
- Games scheduled
- Context/Features/Predictions counts
- Overall status

### 6. Action Buttons
Manual intervention capabilities:
- Force Phase 3 retry
- Force Phase 4 retry
- Force predictions generation

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Cloud Run: nba-admin-dashboard               │
│                   (Auth: API Key in query/header)               │
├─────────────────────────────────────────────────────────────────┤
│  Flask App (main.py)                                            │
│  ├── /dashboard         → Main dashboard page                   │
│  ├── /api/status        → JSON: Today/Tomorrow status           │
│  ├── /api/games/:date   → JSON: Per-game details                │
│  ├── /api/errors        → JSON: Recent errors                   │
│  ├── /api/schedulers    → JSON: Scheduler history               │
│  ├── /api/history       → JSON: 7-day history                   │
│  ├── /partials/*        → HTMX partial updates                  │
│  └── /api/actions/*     → POST: Manual triggers                 │
└─────────────────────────────────────────────────────────────────┘
           │                    │                    │
           ▼                    ▼                    ▼
    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
    │   BigQuery   │    │Cloud Logging │    │  Firestore   │
    │              │    │              │    │              │
    │ daily_phase  │    │ Recent       │    │ phase3_      │
    │ _status view │    │ errors       │    │ completion   │
    └──────────────┘    └──────────────┘    └──────────────┘
```

## Data Sources

### BigQuery
- `nba_orchestration.daily_phase_status` - Aggregated pipeline status
- `nba_analytics.upcoming_player_game_context` - Phase 3 output
- `nba_predictions.ml_feature_store_v2` - Phase 4 output
- `nba_predictions.player_prop_predictions` - Phase 5 output

### Firestore
- `phase3_completion/{date}` - Phase 3 processor tracking
- `phase4_completion/{date}` - Phase 4 processor tracking

### Cloud Logging
- `resource.type="cloud_run_revision"` - Service logs
- `resource.type="cloud_scheduler_job"` - Scheduler logs

## Local Development

```bash
# From repo root
cd services/admin_dashboard
./run_local.sh
```

Access at: `http://localhost:8080/dashboard`

## Deployment

```bash
# From repo root
./services/admin_dashboard/deploy.sh
```

The script will:
1. Build Docker image
2. Push to GCR
3. Deploy to Cloud Run
4. Generate API key (if not set)
5. Print access URL

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCP_PROJECT_ID` | GCP project | `nba-props-platform` |
| `ADMIN_DASHBOARD_API_KEY` | API key for auth | Required |
| `PORT` | Server port | `8080` |
| `FLASK_ENV` | `development` or `production` | `production` |

## File Structure

```
services/admin_dashboard/
├── main.py                     # Flask app entry point
├── services/
│   ├── bigquery_service.py     # BigQuery queries
│   ├── firestore_service.py    # Firestore queries
│   └── logging_service.py      # Cloud Logging queries
├── templates/
│   ├── base.html               # Base layout
│   ├── dashboard.html          # Main dashboard
│   ├── auth_required.html      # Login page
│   └── components/
│       ├── status_cards.html   # Status cards partial
│       ├── games_table.html    # Games table partial
│       └── error_feed.html     # Errors partial
├── Dockerfile                  # Container build
├── deploy.sh                   # Deployment script
└── run_local.sh                # Local dev script
```

## Auto-Refresh

The dashboard automatically refreshes:
- Status cards: Every 30 seconds
- Current time display: Every second

Manual refresh buttons are available for each section.

## Related Documentation

- [API Reference](./API.md) - Detailed API documentation
- [Deployment Guide](./DEPLOYMENT.md) - Deployment instructions
- [Daily Operations](../02-operations/daily-operations-runbook.md) - Using dashboard for monitoring
