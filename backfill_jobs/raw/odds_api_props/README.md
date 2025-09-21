# File: processor_backfill/odds_api_props/README.md
#
# Odds API Props Processor Backfill

## Overview
This processor loads historical NBA player props data from The Odds API into BigQuery. The data spans from May 2023 through the 2024-25 season, containing point prop lines and odds from multiple bookmakers.

## Data Volume Estimates
- **Date Range**: May 2023 - April 2025 (~730 days)
- **Games per day**: 5-15 during season, 0 during off-season
- **Files per game**: ~20-50 (multiple snapshots)
- **Total files**: ~100,000-200,000 files
- **Processing time**: ~10-20 hours for full backfill

## Quick Start

### 1. Test Locally
```bash
# Test with a single file
python scripts/test_odds_api_props_processor.py \
  --gcs-file "gs://nba-scraped-data/odds-api/player-props-history/2023-10-24/fd55db2fa9ee5be1f108be5151e2ecb0-LALDEN/20250812_035909-snap-2130.json"

# Test and load to BigQuery
python scripts/test_odds_api_props_processor.py \
  --gcs-file "gs://nba-scraped-data/odds-api/player-props-history/2023-10-24/fd55db2fa9ee5be1f108be5151e2ecb0-LALDEN/20250812_035909-snap-2130.json" \
  --load
```

### 2. Run Local Backfill (Small Date Range)
```bash
# Process a single day
python processor_backfill/odds_api_props/odds_api_props_backfill_job.py \
  --dates 2023-10-24

# Process a week
python processor_backfill/odds_api_props/odds_api_props_backfill_job.py \
  --start-date 2023-10-24 \
  --end-date 2023-10-30

# Dry run to see what would be processed
python processor_backfill/odds_api_props/odds_api_props_backfill_job.py \
  --start-date 2023-10-24 \
  --end-date 2023-10-30 \
  --dry-run
```

### 3. Deploy to Cloud Run
```bash
# Deploy using the generic deployment script
cd ~/code/nba-stats-scraper
./bin/deployment/deploy_processor_backfill_job.sh odds_api_props

# Or use the wrapper
./processor_backfill/odds_api_props/deploy.sh

# Execute the job for full backfill
gcloud run jobs execute odds-api-props-backfill \
  --region=us-central1

# Execute for specific dates
gcloud run jobs execute odds-api-props-backfill \
  --region=us-central1 \
  --args="--dates,2023-10-24,2023-10-25,2023-10-26"

# Execute for a specific month
gcloud run jobs execute odds-api-props-backfill \
  --region=us-central1 \
  --args="--start-date,2024-01-01,--end-date,2024-01-31"
```

### 4. Monitor Progress
```bash
# Monitor running job using the monitoring script
./bin/processor_backfill/odds_api_props_backfill_monitor.sh

# Or watch logs in real-time
gcloud run jobs executions logs <execution-name> --region=us-central1 --tail

# Check BigQuery table
bq query --use_legacy_sql=false "
SELECT 
  DATE(game_date) as date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_name) as players,
  COUNT(*) as total_records
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
GROUP BY date
ORDER BY date DESC
LIMIT 10"

# Check processing status
bq query --use_legacy_sql=false "
SELECT 
  DATE(processing_timestamp) as process_date,
  COUNT(*) as records_loaded,
  COUNT(DISTINCT game_date) as days_processed,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
GROUP BY process_date
ORDER BY process_date DESC"
```

## Backfill Strategy

### Recommended Approach
1. **Test Phase**: Process 1 day locally to verify
2. **Pilot Phase**: Process 1 month via Cloud Run
3. **Full Backfill**: Run complete historical load

### Chunking Strategy for Large Backfill
```bash
# Process by season quarters
# 2023 Playoffs (May-June 2023)
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2023-05-01,--end-date,2023-06-30"

# 2023-24 Season Start (Oct-Dec 2023)
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2023-10-01,--end-date,2023-12-31"

# 2023-24 Season Mid (Jan-Mar 2024)
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2024-01-01,--end-date,2024-03-31"

# 2023-24 Season End + Playoffs (Apr-Jun 2024)
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2024-04-01,--end-date,2024-06-30"

# 2024 Off-season (Jul-Sep 2024)
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2024-07-01,--end-date,2024-09-30"

# 2024-25 Season (Oct 2024 - Apr 2025)
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2024-10-01,--end-date,2025-04-30"
```

## Configuration

### Environment Variables
```bash
export GCP_PROJECT_ID="nba-props-platform"
export BUCKET_NAME="nba-scraped-data"
export MAX_WORKERS=4        # Parallel file processors
export BATCH_SIZE=100        # Files per batch
export SAVE_RESULTS=1        # Save detailed results to file
```

### Cloud Run Job Settings
- **Memory**: 4Gi (handles large batches)
- **CPU**: 2 cores
- **Timeout**: 3600 seconds (1 hour)
- **Max Retries**: 3
- **Parallelism**: 10 (for multiple date ranges)

## Data Quality Checks

### Verify Line Movement Tracking
```sql
-- Check line movements for a specific game
SELECT 
  player_name,
  bookmaker,
  points_line,
  over_price,
  under_price,
  minutes_before_tipoff,
  snapshot_timestamp
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_id = '20231024_LAL_DEN'
  AND player_name = 'LeBron James'
ORDER BY snapshot_timestamp;
```

### Check Data Completeness
```sql
-- Games with prop data by month
SELECT 
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(DISTINCT game_id) as games_with_props,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(*) as total_prop_records
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
GROUP BY month
ORDER BY month;
```

### Identify Missing Data
```sql
-- Days with no data (potential gaps)
WITH date_range AS (
  SELECT DATE_ADD('2023-05-01', INTERVAL day_num DAY) as check_date
  FROM UNNEST(GENERATE_ARRAY(0, 730)) as day_num
),
actual_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
)
SELECT check_date
FROM date_range
LEFT JOIN actual_dates ON date_range.check_date = actual_dates.game_date
WHERE actual_dates.game_date IS NULL
  AND check_date <= CURRENT_DATE()
ORDER BY check_date;
```

## Troubleshooting

### Common Issues

1. **Memory Errors**
   - Reduce BATCH_SIZE environment variable
   - Increase Cloud Run memory allocation

2. **Timeout Errors**
   - Process smaller date ranges
   - Increase task timeout in Cloud Run

3. **Missing Files**
   - Normal for off-season dates
   - Check GCS bucket for actual file availability

4. **BigQuery Insert Errors**
   - Check schema matches
   - Verify BigQuery table exists
   - Check for quota limits

### Debug Mode
```bash
# Run with detailed logging
LOG_LEVEL=DEBUG python processor_backfill/odds_api_props/backfill_job.py \
  --dates 2023-10-24 \
  --max-workers 1 \
  --batch-size 10
```

## Maintenance

### Daily Processing (After Backfill)
Once historical backfill is complete, set up daily processing:
```bash
# Schedule daily job for yesterday's data
gcloud scheduler jobs create http odds-api-props-daily \
  --location=us-central1 \
  --schedule="0 6 * * *" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/odds-api-props-backfill:run" \
  --http-method=POST \
  --oauth-service-account-email=scheduler@nba-props-platform.iam.gserviceaccount.com
```

### Reprocessing
To reprocess specific dates (e.g., after schema changes):
```bash
# Delete existing data for date range
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date BETWEEN '2023-10-24' AND '2023-10-30'"

# Reprocess
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2023-10-24,--end-date,2023-10-30"
```

## Performance Metrics

Expected processing rates:
- **Local**: ~10-20 files/minute
- **Cloud Run (4 workers)**: ~100-200 files/minute
- **Full backfill**: 10-20 hours

## Contact
For issues or questions about the backfill process, check the logs in Cloud Logging or the processing statistics in BigQuery.