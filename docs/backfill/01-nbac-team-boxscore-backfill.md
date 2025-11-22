# NBA.com Team Boxscore Backfill

**Created:** 2025-11-21 17:06:34 PST
**Last Updated:** 2025-11-21 17:06:34 PST

Quick reference for backfilling NBA.com team boxscore data from GCS to BigQuery.

## Prerequisites

- Scraper deployed and running: `nbac_team_boxscore`
- Processor deployed: `NbacTeamBoxscoreProcessor`
- Cloud Run Job deployed: `nbac-team-boxscore-processor-backfill`

## Running Locally (Recommended for Testing)

Best for development - shows detailed logs in real-time.

```bash
# Dry run - see what would be processed
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py \
  --dry-run --start-date=2024-11-20 --end-date=2024-11-20

# Process single day
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py \
  --start-date=2024-11-20 --end-date=2024-11-20

# Process date range
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py \
  --start-date=2024-11-01 --end-date=2024-11-30

# Limit number of files
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py \
  --limit=10
```

## Running on Cloud Run (Production)

```bash
# Dry run
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--dry-run,--limit=10 \
  --region=us-west2

# Process single day
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-11-20,--end-date=2024-11-20 \
  --region=us-west2

# Process current season to date
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-10-22,--end-date=$(date +%Y-%m-%d) \
  --region=us-west2

# Process full month
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-11-01,--end-date=2024-11-30 \
  --region=us-west2
```

## Monitoring

### View Cloud Run Execution Logs

```bash
# List recent executions
gcloud run jobs executions list \
  --job=nbac-team-boxscore-processor-backfill \
  --region=us-west2 \
  --limit=10

# View logs for latest execution
gcloud beta run jobs executions logs read $(gcloud run jobs executions list \
  --job=nbac-team-boxscore-processor-backfill \
  --region=us-west2 \
  --limit=1 \
  --format='value(name)') \
  --region=us-west2
```

### Check BigQuery Data

```sql
-- Count total teams
SELECT COUNT(*) as total_teams
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`;

-- Recent games
SELECT game_date, game_id, team_abbr, is_home, points, assists
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC, game_id;

-- Data quality check (should be 2 teams per game)
SELECT
  game_date,
  COUNT(*) as total_teams,
  COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

## Smart Idempotency

The backfill automatically skips unchanged data:

- **First run:** Inserts new data
- **Subsequent runs:** Skips writes for unchanged games (cost savings)
- **Expected skip rate:** 30-90% depending on how recently data was processed

Example output:
```
BACKFILL SUMMARY:
  Success: 3 games
  Skipped (smart idempotency): 7 games
  Errors: 0 games
  Total Teams Processed: 6
  Skip Rate: 70.0% (cost savings!)
```

## Troubleshooting

### No files found

Check GCS for available dates:
```bash
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/
```

### Verify data landed

```bash
gsutil ls -r gs://nba-scraped-data/nba-com/team-boxscore/20241120/ | grep "\.json$"
```

## Files

- **Backfill script:** `backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py`
- **Job config:** `backfill_jobs/raw/nbac_team_boxscore/job-config.env`
- **Deploy script:** `backfill_jobs/raw/nbac_team_boxscore/deploy.sh`
- **Processor:** `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
- **Schema:** `schemas/bigquery/raw/nbac_team_boxscore_tables.sql`

## See Also

- [Backfill Deployment Guide](../guides/03-backfill-deployment-guide.md)
- [Processor README](../../backfill_jobs/raw/nbac_team_boxscore/README.md)
