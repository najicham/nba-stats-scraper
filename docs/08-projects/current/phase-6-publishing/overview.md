# Phase 6: Website Publishing

**Status:** COMPLETE
**Last Updated:** 2025-12-10

## What is this?

Phase 6 exports prediction data from BigQuery to Google Cloud Storage as JSON files for website consumption. The React/Next.js frontend fetches these static JSON files directly from GCS (no API server needed).

## Architecture

```
BigQuery Tables          Exporters                    GCS Bucket                    Website
─────────────────────    ───────────────────────      ─────────────────────────     ────────────────
prediction_accuracy  →   ResultsExporter          →   results/{date}.json       →   Results Page
                         BestBetsExporter         →   best-bets/{date}.json     →   Best Bets Page
                         PredictionsExporter      →   predictions/{date}.json   →   Today's Picks
                         PlayerProfileExporter    →   players/{lookup}.json     →   Player Pages
system_daily_performance SystemPerformanceExporter→   systems/performance.json  →   Dashboard
```

## Public API Endpoints

| Endpoint | Purpose | Cache |
|----------|---------|-------|
| `/v1/results/latest.json` | Yesterday's results | 5 min |
| `/v1/results/{date}.json` | Historical results | 24 hr |
| `/v1/best-bets/latest.json` | Yesterday's best bets | 5 min |
| `/v1/predictions/today.json` | Today's predictions | 5 min |
| `/v1/systems/performance.json` | System accuracy metrics | 1 hr |
| `/v1/players/index.json` | Player list with stats | 1 hr |
| `/v1/players/{lookup}.json` | Individual player profile | 1 hr |

**Base URL:** `https://storage.googleapis.com/nba-props-platform-api`

## Current Data

| Resource | Count | Date Range |
|----------|-------|------------|
| Results files | 62 | 2021-11-06 to 2022-01-07 |
| Best bets files | 62 | 2021-11-06 to 2022-01-07 |
| Predictions files | 62 | 2021-11-06 to 2022-01-07 |
| Player profiles | 473 | All players with 5+ games |
| System performance | 1 | Rolling windows |

## Quick Start

```bash
# Export all data for a date
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --date 2021-11-10

# Backfill all historical dates
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --backfill-all

# Export player profiles
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --players --min-games 5

# Export specific types only
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --date 2021-11-10 --only results,best-bets
```

## Files

```
data_processors/publishing/
├── __init__.py
├── base_exporter.py              # Common GCS upload, BigQuery query methods
├── results_exporter.py           # Daily prediction results
├── best_bets_exporter.py         # High-confidence picks
├── predictions_exporter.py       # Forward-looking predictions
├── system_performance_exporter.py # Rolling accuracy metrics
└── player_profile_exporter.py    # Per-player accuracy profiles

backfill_jobs/publishing/
├── __init__.py
└── daily_export.py               # CLI for exports and backfills

schemas/bigquery/nba_predictions/
└── system_daily_performance.sql  # Aggregation table schema
```

## Related Documents

- **OPERATIONS.md** - Detailed operational guide
- **DESIGN.md** - Original design specification
- **IMPLEMENTATION-GUIDE.md** - Implementation reference (historical)

## Dependencies

- Phase 5B (Grading) - `prediction_accuracy` table
- GCS bucket: `gs://nba-props-platform-api`
- BigQuery table: `nba_predictions.system_daily_performance`
