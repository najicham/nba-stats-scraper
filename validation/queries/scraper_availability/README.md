# Scraper Availability Validation Queries

**Created:** January 22, 2026

Queries for validating scraper data availability and latency.

## Queries

| Query | Purpose |
|-------|---------|
| `daily_scraper_health.sql` | Check all scrapers' coverage and latency for yesterday |

## Prerequisites

These queries require the `scraper_data_arrival` table and views to be deployed:
```bash
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/scraper_data_arrival.sql
```

## Usage

### CLI Check (Recommended)
```bash
# Check all enabled scrapers
python bin/scraper_completeness_check.py --all

# Check specific scraper
python bin/scraper_completeness_check.py bdl_box_scores
```

### BigQuery Console
Run `daily_scraper_health.sql` Query 1 to get summary.

## Expected Thresholds

| Scraper | Min Coverage | Max P90 Latency | Notes |
|---------|--------------|-----------------|-------|
| nbac_gamebook | 100% | 4 hours | Critical source |
| bdl_box_scores | 90% | 12 hours | Has fallback to NBAC |
| oddsa_player_props | 80% | 6 hours | Pre-game data |

## Related Documentation
- `/docs/08-projects/current/jan-21-critical-fixes/BDL-LATE-DATA-SOLUTION.md`
- `/docs/09-handoff/2026-01-22-SCRAPER-RETRY-SYSTEM-HANDOFF.md`
