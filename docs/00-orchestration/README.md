# NBA Pipeline Orchestration

Central documentation for the daily data pipeline orchestration system.

## Quick Links

| Document | Description |
|----------|-------------|
| [Services](services.md) | All services, their roles, and status |
| [Monitoring](monitoring.md) | Dashboards, alerts, and observability |
| [Troubleshooting](troubleshooting.md) | Common issues and fixes |
| [Architecture](../01-architecture/quick-reference.md) | System design (in 01-architecture/) |
| [Orchestrators](../01-architecture/orchestration/orchestrators.md) | Pub/Sub orchestrators (in 01-architecture/) |
| [Deployment](../04-deployment/deployment-verification-checklist.md) | Deployment verification |

## Pipeline Overview

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Phase 1   │───▶│   Phase 2   │───▶│   Phase 3   │───▶│   Phase 4   │
│  Scrapers   │    │    Raw      │    │  Analytics  │    │  Precompute │
│             │    │ Processors  │    │             │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                │
┌─────────────┐    ┌─────────────┐                              │
│   Phase 6   │◀───│   Phase 5   │◀─────────────────────────────┘
│   Export    │    │ Predictions │
│             │    │             │
└─────────────┘    └─────────────┘
```

## Key Concepts

### Workflows
Workflows define WHEN scrapers run based on game schedules. See [config/workflows.yaml](../../config/workflows.yaml).

### Phases
Each phase transforms data and triggers the next via Pub/Sub:
- **Phase 1**: Scrape external APIs → GCS
- **Phase 2**: GCS → BigQuery (raw tables)
- **Phase 3**: Raw → Analytics tables
- **Phase 4**: Analytics → Precomputed features
- **Phase 5**: Features → Predictions
- **Phase 6**: Predictions → Export/API

### Rate Limiting
Notifications are rate-limited to prevent email floods. See [../03-configuration/notification-rate-limiting.md](../03-configuration/notification-rate-limiting.md).

## Daily Operations

### Game Day Checklist
1. ✅ Schedule data fresh (check `nba_raw.nbac_schedule`)
2. ✅ Scrapers running on schedule (Cloud Scheduler)
3. ✅ Phase 2 processing Pub/Sub messages
4. ✅ No error spikes in Cloud Logging

### Early Game Days (Christmas, MLK Day)
Special workflows trigger at 3 PM, 6 PM, 9 PM ET for games starting before 7 PM.

## Incident Response

When things go wrong:
1. Check [troubleshooting.md](troubleshooting.md) for common issues
2. Review Cloud Logging for errors
3. Check Pub/Sub dead-letter queues
4. Document in [postmortems/](postmortems/) if significant

## Recent Incidents

| Date | Incident | Impact | Postmortem |
|------|----------|--------|------------|
| 2025-12-24 | Email flood (600+) | Inbox flooded, data stale | [Link](postmortems/2025-12-24-email-flood.md) |
