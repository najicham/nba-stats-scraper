# NBA Referee Assignments Backfill Job

Collects historical NBA referee assignments from official.nba.com for specified seasons using date-based iteration.

## Overview

This backfill job:
- Extracts game dates from NBA schedule files stored in GCS
- Downloads referee assignments for each date via Cloud Run scraper service
- Handles off-season dates gracefully (no games is normal)
- Stores data in `gs://nba-scraped-data/nba-com/referee-assignments/`
- Includes resume logic to skip already processed dates

## Quick Start

```bash
# 1. Deploy
chmod +x backfill/nbac_referee_assignments/deploy.sh
./backfill/nbac_referee_assignments/deploy.sh

# 2. Test with dry run
gcloud run jobs execute nba-referee-assignments-backfill --args=--dry-run,--limit=5 --region=us-west2

# 3. Run small test
gcloud run jobs execute nba-referee-assignments-backfill --args=--limit=10 --region=us-west2

# 4. Full backfill
gcloud run jobs execute nba-referee-assignments-backfill --region=us-west2
```

## Configuration

- **Memory**: 2Gi (lightweight API processing)
- **CPU**: 1 (sufficient for date-based iteration)
- **Timeout**: 4 hours (covers ~1400 dates across 4 seasons)

## Expected Runtime

| Scope | Dates | API Calls | Duration |
|-------|-------|-----------|----------|
| Test (10 dates) | 10 | 10 | 1 minute |
| Single season | ~350 | 350 | 45 minutes |
| Full (4 seasons) | ~1400 | 1400 | 3-4 hours |

## Data Structure

The scraper collects referee assignments with this structure:

```json
{
  "metadata": {
    "date": "2023-01-15",
    "season": "2022-23",
    "fetchedUtc": "2025-01-15T10:30:00Z",
    "gameCount": {
      "nba": 8,
      "gLeague": 2,
      "wnba": 0,
      "total": 10
    },
    "replayCenterOfficials": 3
  },
  "refereeAssignments": {
    "nba": {
      "Table": {
        "rows": [
          {
            "game_id": "0022200123",
            "home_team": "LAL",
            "away_team": "BOS",
            "official1": "Scott Foster",
            "official2": "Tony Brothers",
            "official3": "Kane Fitzgerald"
          }
        ]
      }
    }
  }
}
```

## Command Line Options

```bash
# Specific seasons
--seasons=2023,2024

# Date range filtering
--start-date=2023-01-01 --end-date=2023-12-31

# Testing options
--dry-run --limit=50

# Different bucket
--bucket=custom-bucket-name
```

## Monitoring

```bash
# List executions
gcloud run jobs executions list --job=nba-referee-assignments-backfill --region=us-west2

# View logs
gcloud beta run jobs executions logs read EXECUTION_ID --region=us-west2

# Check output data
gsutil ls gs://nba-scraped-data/nba-com/referee-assignments/ | head -20
```

## Data Validation

The job includes built-in validation:
- Checks for required NBA data structure
- Validates referee assignment fields
- Confirms date consistency
- Handles "no games" dates appropriately

## Common Patterns

### Regular Season Data
- Most dates have 8-15 NBA games
- Each game has 3 officials plus replay center staff
- Data available from October through April

### Off-Season Handling
- Summer months (June-September) typically have no games
- All-Star break has reduced game counts
- Playoff dates have fewer but more important games

### Resume Logic
- Automatically skips dates that already have data in GCS
- Safe to restart job from any point
- Uses GCS path structure to detect existing files

## Troubleshooting

### Common Issues

**"No schedule files found"**
- Ensure NBA schedule data exists in GCS
- Check season year format (2023 for 2023-24 season)
- Verify GCS bucket access permissions

**"No games found for date"**
- Normal for off-season dates
- Job continues processing other dates
- Check logs for "no games" vs error messages

**"Rate limit exceeded"**
- Increase RATE_LIMIT_DELAY in script
- Current setting: 2 seconds per request
- Conservative for daily referee data

### Performance Optimization

**Memory Usage**
- Current 2Gi allocation is sufficient
- Date-based processing is memory efficient
- No large file processing required

**Processing Speed**
- Limited by API rate limits, not compute
- 2-second delay between requests
- Focus on reliability over speed

## Integration Notes

### Data Pipeline Integration
- Prepares data for processor backfill jobs
- Uses established GCS path conventions
- Compatible with existing monitoring scripts

### Downstream Processing
- Data ready for BigQuery transformation
- Referee-game mapping for analysis
- Official assignment pattern studies

## Next Steps

1. Validate data quality and coverage across all seasons
2. Create processor to transform data to BigQuery tables
3. Set up real-time collection pipeline for current season
4. Develop analytics for referee assignment patterns
5. Cross-reference with game outcome data

This backfill provides the foundation for comprehensive NBA referee assignment analysis and integrates seamlessly with your existing data collection infrastructure.