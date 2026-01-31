# Unified Admin Dashboard

A comprehensive monitoring and operations dashboard that consolidates all system health, pipeline monitoring, ML performance, and data quality into a single interface.

## Overview

This dashboard replaces the fragmented monitoring systems (pipeline dashboard, scraper dashboard, admin dashboard) with one unified solution using modern web technologies.

## Architecture

- **Backend:** FastAPI (Python 3.11)
- **Frontend:** React + TypeScript + Tailwind CSS
- **Data Sources:** Firestore (real-time state), BigQuery (historical analytics)
- **Deployment:** Cloud Run

## Features

### Phase 1 (Current - MVP)
- ✅ Home/Command Center page
  - System health score (0-100)
  - Critical alerts
  - Today's summary (predictions, coverage, accuracy)
  - Pipeline flow visualization
  - Quick actions

### Phase 2 (Planned)
- Pipeline Health page
- Prediction Quality page
- Data Quality page
- Scrapers & Phase 1 page

### Phase 3 (Planned)
- Alerts & Incidents page
- Cost & Efficiency page
- System Health page

## Local Development

### Backend

```bash
cd services/unified_dashboard/backend

# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn main:app --reload --port 8080

# Test endpoint
curl http://localhost:8080/api/home
```

### Frontend

```bash
cd services/unified_dashboard/frontend

# Install dependencies
npm install

# Run dev server
npm run dev

# Build for production
npm run build
```

Frontend will be available at http://localhost:3000 and will proxy API requests to backend at http://localhost:8080.

## Deployment

Deploy to Cloud Run using the deployment script:

```bash
# From repo root
./bin/deploy-service.sh unified-dashboard
```

Or manually:

```bash
# From repo root
gcloud run deploy unified-dashboard \
  --source . \
  --dockerfile services/unified_dashboard/Dockerfile \
  --region us-west2 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars PORT=8080
```

## API Endpoints

### GET /api/home
Get complete home page data including health score, alerts, summary, and pipeline flow.

**Response:**
```json
{
  "timestamp": "2026-01-31T12:00:00Z",
  "health": {
    "overall_score": 89,
    "status": "healthy",
    "breakdown": {
      "pipeline": {"score": 95, "weight": 0.30, "status": "healthy"},
      "data_quality": {"score": 87, "weight": 0.25, "status": "warning"},
      "ml_performance": {"score": 72, "weight": 0.25, "status": "warning"},
      "services": {"score": 98, "weight": 0.15, "status": "healthy"},
      "cost": {"score": 100, "weight": 0.05, "status": "healthy"}
    }
  },
  "alerts": [...],
  "summary": {...},
  "pipeline_flow": {...}
}
```

### GET /api/home/health
Get just the health score (lightweight endpoint).

## Data Sources

### Firestore Collections
- `processor_heartbeats` - Real-time processor status
- `phase2_completion` - Phase 2 completion state
- `phase3_completion` - Phase 3 completion state
- `circuit_breaker_state` - Circuit breaker states

### BigQuery Tables
- `nba_predictions.player_prop_predictions` - Predictions
- `nba_predictions.prediction_accuracy` - Grading results
- `nba_reference.processor_run_history` - Processor execution history
- `nba_orchestration.shot_zone_quality_trend` - Shot zone quality metrics

## Health Score Calculation

The overall system health score (0-100) is calculated as a weighted average:

```
health_score = (
    pipeline_success_rate * 0.30 +      # 30%: Pipeline execution
    data_quality_score * 0.25 +         # 25%: Data completeness
    prediction_accuracy * 0.25 +        # 25%: Model performance
    service_uptime * 0.15 +             # 15%: Infrastructure
    cost_efficiency * 0.05              #  5%: Cost control
)
```

**Status thresholds:**
- ✅ **Healthy:** ≥85
- 🟡 **Warning:** 65-84
- 🔴 **Critical:** <65

## Design System

Following the clean white theme from the scraper dashboard:

**Colors:**
- Background: `#f5f5f5` (light gray)
- Cards: `#ffffff` (white)
- Text: `#333333` (dark gray)
- Success: `#28a745` (green)
- Warning: `#ffc107` (yellow)
- Critical: `#d32f2f` (red)

**Typography:**
- Font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto
- Headings: Bold, 18-24px
- Body: Regular, 14px

**Components:**
- Card shadows: `0 2px 4px rgba(0,0,0,0.1)`
- Border radius: `8px`
- Spacing: 8px base unit

## Future Enhancements

- WebSocket real-time updates
- AI-powered pipeline trace
- Natural language queries
- Predictive health forecasting
- Mobile-first alerts
- Time-travel debugging

## Related Documentation

- Design handoff: `docs/09-handoff/2026-01-31-SESSION-56-UNIFIED-DASHBOARD-HANDOFF.md`
- Architecture: `docs/01-architecture/`
- Operations: `docs/02-operations/`
