# NBA Odds API Game Lines Backfill Job

Collects historical NBA game lines betting data for 4 seasons (2021-22 through 2024-25).

## Overview

This backfill job:
- Reads NBA schedule files from GCS to identify exact game dates
- Collects game lines data for ~1,200 game dates across 4 seasons
- Uses conservative rate limiting (1 second between API calls)
- Implements resume logic to skip already processed dates
- Stores data in `gs://nba-scraped-data/odds-api/game-lines-history/`

## Quick Start

```bash
# 1. Deploy
chmod +x backfill/odds_api_lines/deploy.sh
./backfill/odds_api_lines/deploy.sh

# 2. Test with dry run
gcloud run jobs execute nba-odds-api-lines-backfill \
  --args=--dry-run,--limit=5 --region=us-west2

# 3. Run small test
gcloud run jobs execute nba-odds-api-lines-backfill \
  --args=--limit=10 --region=us-west2

# 4. Full backfill (~4 hours)
gcloud run jobs execute nba-odds-api-lines-backfill --region=us-west2
```

## File Structure

```
backfill/odds_api_lines/
├── odds_api_lines_backfill_job.py    # Main backfill script
├── job-config.env                    # Job configuration
├── deploy.sh                         # Deployment script
└── README.md                         # This file
```

## Configuration

- **Memory**: 4Gi (for schedule processing and caching)
- **CPU**: 2 (dual CPU for faster processing)
- **Timeout**: 4 hours (full 4-season collection)
- **Strategy**: Conservative (4h before typical game time)

## Data Collection

### Game Lines vs Props
- **Game Lines**: Spread, totals, moneyline for each game
- **Simpler**: One API call per date (vs per game for props)
- **Earlier Availability**: Lines available much sooner than props
- **Date Range**: 2021-10-01 onwards (vs 2023-05-03 for props)

### Expected Runtime

| Scope | Dates | API Calls | Duration |
|-------|-------|-----------|----------|
| Single season | ~300 | ~600 | ~1 hour |
| All 4 seasons | ~1,200 | ~2,400 | ~4 hours |

## Arguments

```bash
# Available command line arguments:
--seasons=2021,2022,2023,2024    # Seasons to process (default: all 4)
--dry-run                        # Show what would be processed (no API calls)
--limit=10                       # Limit number of dates (for testing)
--strategy=conservative          # Timestamp strategy (conservative/pregame/final)
--bucket=nba-scraped-data        # GCS bucket name
```

## Monitoring

```bash
# List executions
gcloud run jobs executions list --job=nba-odds-api-lines-backfill --region=us-west2

# View logs
gcloud beta run jobs executions logs read EXECUTION_ID --region=us-west2

# Check output data
gsutil ls gs://nba-scraped-data/odds-api/game-lines-history/ | head -20
```

## Resume Logic

The job automatically skips dates that already have data:
```
[42/1200] Skipping 2022-03-15 (already exists)
```

To force reprocessing, delete existing data:
```bash
gsutil rm -r gs://nba-scraped-data/odds-api/game-lines-history/2022-03-15/
```

## Troubleshooting

### Common Issues

**"No schedule files found"**
- Verify schedule data exists: `gsutil ls gs://nba-scraped-data/nba-com/schedule/`

**"Rate limit exceeded"**
- Job includes conservative 1-second delays
- For faster processing, use `--strategy=pregame`

**"Service URL not found"**
- Check scraper service is deployed: `gcloud run services list --region=us-west2`

## Next Steps

1. Validate data quality and coverage
2. Create processors to transform data to BigQuery
3. Build analytics for historical lines analysis
4. Set up real-time daily lines collection pipeline