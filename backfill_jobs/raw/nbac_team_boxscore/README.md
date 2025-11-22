# NBA.com Team Boxscore Backfill Job

Backfill processor for NBA.com team boxscore data from GCS to BigQuery.

## Overview

- **Source:** NBA.com Team Box Score API
- **Input:** GCS files at `gs://nba-scraped-data/nba-com/team-boxscore/`
- **Output:** BigQuery table `nba_raw.nbac_team_boxscore`
- **Processing:** Each game → 2 rows (1 per team: home + away)
- **Features:** Smart idempotency (skips unchanged data for cost savings)

## Quick Start

### 1. Deploy

```bash
cd /path/to/nba-stats-scraper
./backfill_jobs/raw/nbac_team_boxscore/deploy.sh
```

### 2. Test with Dry Run

```bash
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--dry-run,--limit=10 \
  --region=us-west2
```

### 3. Run Small Test

```bash
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--limit=5 \
  --region=us-west2
```

## Usage

### Date Range Processing

```bash
# Single day
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-11-20,--end-date=2024-11-20 \
  --region=us-west2

# Week range
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-11-01,--end-date=2024-11-07 \
  --region=us-west2

# Month range
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-11-01,--end-date=2024-11-30 \
  --region=us-west2

# Full season to date
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-10-22,--end-date=2024-11-30 \
  --region=us-west2
```

### With Limits

```bash
# Process only 10 games
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--limit=10 \
  --region=us-west2

# Dry run with limit
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--dry-run,--limit=20 \
  --region=us-west2
```

## Smart Idempotency

This processor uses **smart idempotency** to optimize costs:

- ✅ **Computes hash** from meaningful team stats fields
- ✅ **Queries BigQuery** for existing hash using primary keys
- ✅ **Skips write** if data unchanged (saves BigQuery costs)
- ✅ **Logs skip rate** for monitoring

**Expected skip rate:** 30-50% when reprocessing recent data

**Example output:**
```
Processing 10/10: gs://nba-scraped-data/nba-com/team-boxscore/20241120/0022400259/file.json
✓ Skipped (unchanged): 2 rows

BACKFILL SUMMARY:
  Success: 3 games
  Skipped (smart idempotency): 7 games
  Errors: 0 games
  Total Teams Processed: 6
  Skip Rate: 70.0% (cost savings!)
```

## Monitoring

### List Recent Executions

```bash
gcloud run jobs executions list \
  --job=nbac-team-boxscore-processor-backfill \
  --region=us-west2 \
  --limit=10
```

### View Logs

```bash
# Get execution ID from list above, then:
gcloud beta run jobs executions logs read [EXECUTION-ID] \
  --region=us-west2
```

### Check BigQuery Data

```sql
-- Count total teams
SELECT COUNT(*) as total_teams
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`;

-- Recent games
SELECT
  game_date,
  game_id,
  team_abbr,
  is_home,
  points,
  assists,
  total_rebounds
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC, game_id, is_home;

-- Data quality check
SELECT
  game_date,
  COUNT(*) as total_teams,
  COUNT(DISTINCT game_id) as games,
  SUM(CASE WHEN is_home THEN 1 ELSE 0 END) as home_teams,
  SUM(CASE WHEN NOT is_home THEN 1 ELSE 0 END) as away_teams
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

## Configuration

### Job Resources

- **Memory:** 2Gi (lightweight processing)
- **CPU:** 1 vCPU
- **Timeout:** 3600s (1 hour)

### GCS Path Pattern

```
gs://nba-scraped-data/nba-com/team-boxscore/YYYYMMDD/game_id/*.json
```

Example:
```
gs://nba-scraped-data/nba-com/team-boxscore/20241120/0022400259/20251121_231924.json
```

## Troubleshooting

### No files found

```bash
# Check GCS paths manually
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/20241120/
```

### View detailed logs

```bash
# Enable debug logging
gcloud beta run jobs executions logs read [EXECUTION-ID] \
  --region=us-west2 \
  --tail
```

### BigQuery errors

```bash
# Verify schema
bq show --schema nba-props-platform:nba_raw.nbac_team_boxscore

# Check recent data
bq query --use_legacy_sql=false \
  "SELECT * FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
   WHERE game_date = DATE('2024-11-20') LIMIT 10"
```

## Files

- `nbac_team_boxscore_backfill_job.py` - Main backfill script
- `job-config.env` - Cloud Run job configuration
- `deploy.sh` - Deployment script
- `README.md` - This file

## See Also

- [Backfill Deployment Guide](../../../docs/guides/03-backfill-deployment-guide.md)
- [Processor Development Guide](../../../docs/guides/01-processor-development-guide.md)
- [NBA.com Team Boxscore Processor](../../../data_processors/raw/nbacom/nbac_team_boxscore_processor.py)
- [BigQuery Schema](../../../schemas/bigquery/raw/nbac_team_boxscore_tables.sql)
