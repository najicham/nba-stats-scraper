# System Architecture Overview

High-level overview of the NBA Props Platform architecture.

**Last Updated:** $(date +%Y-%m-%d)

## Overview

The NBA Props Platform is a data pipeline that:
1. Scrapes NBA data and betting odds from multiple sources
2. Processes and normalizes the data
3. Generates analytics and predictions
4. Serves data for prop bet recommendations

## Architecture Diagram

```
┌─────────────────┐
│ Cloud Scheduler │  ← Triggers workflows on schedule
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Workflows     │  ← Orchestrates scraping & processing
└────────┬────────┘
         │
         ├──────────────────────┬──────────────────────┐
         ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  nba-scrapers   │    │ nba-processors  │    │ nba-analytics-   │
│  (Cloud Run)    │    │  (Cloud Run)    │    │ processors       │
└────────┬────────┘    └────────┬────────┘    └────────┬─────────┘
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│   GCS Buckets   │───→│    BigQuery     │←───│   BigQuery       │
│   (Raw JSON)    │    │   (Processed)   │    │   (Analytics)    │
└─────────────────┘    └─────────────────┘    └──────────────────┘
```

## Components

### Cloud Scheduler
Triggers workflows on schedule (e.g., every 2 hours, daily at 8am)

### Workflows
Orchestrates multiple scrapers/processors in sequence

### Cloud Run Services
- **nba-scrapers**: Fetches data from external APIs
- **nba-processors**: Processes raw data into BigQuery
- **nba-analytics-processors**: Generates analytics

### Storage
- **GCS**: Raw JSON files from scrapers
- **BigQuery**: Structured data for querying

## Data Flow

1. **Scraping**: External API → nba-scrapers → GCS (raw JSON)
2. **Processing**: GCS (raw) → nba-processors → BigQuery (structured)
3. **Analytics**: BigQuery (raw) → nba-analytics-processors → BigQuery (analytics)

## Key Workflows

- **real-time-business**: Updates odds/props every 2 hours
- **morning-operations**: Daily setup and recovery
- **post-game-collection**: Collects game data after games

## Monitoring

Use `nba-monitor status yesterday` to check system health.

See [../operations/README.md](../operations/README.md) for monitoring tools.

## Related

- [system-architecture.md](system-architecture.md) - Detailed technical architecture
- [Wiki: Architecture](https://your-wiki-url/architecture) - User-friendly overview
