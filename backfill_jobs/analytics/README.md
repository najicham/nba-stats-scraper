# File: analytics_backfill/README.md

# Analytics Backfill Jobs

This directory contains Cloud Run backfill jobs for processing analytics data from raw BigQuery tables into analytics tables.

## Directory Structure

```
analytics_backfill/
├── player_game_summary/
│   ├── player_game_summary_backfill_job.py
│   └── job-config.env
├── team_offense_game_log/
│   ├── team_offense_backfill_job.py
│   └── job-config.env
├── team_defense_game_log/
│   ├── team_defense_backfill_job.py
│   └── job-config.env
└── README.md
```

## Available Analytics Processors

### Player Game Summary
Combines player performance data with prop betting context and analytics.
- **Source Tables**: `nbac_gamebook_player_stats`, `bdl_player_boxscores`, `odds_api_player_points_props`
- **Target Table**: `nba_analytics.player_game_summary`
- **Key Analytics**: Blowout analysis, prop outcomes, cross-source validation

### Team Offense Game Log
Aggregates team offensive performance and advanced metrics.
- **Source Tables**: `bdl_player_boxscores` (aggregated by team)
- **Target Table**: `nba_analytics.team_offense_game_log`
- **Key Analytics**: Effective FG%, True Shooting%, offensive rating

### Team Defense Game Log
Aggregates team defensive performance and opponent stats allowed.
- **Source Tables**: `bdl_player_boxscores` (aggregated by opposing team)
- **Target Table**: `nba_analytics.team_defense_game_log`
- **Key Analytics**: Defensive efficiency, opponent shooting allowed, rebound rates

## Deployment

Deploy jobs using the standard deployment script:

```bash
# Deploy specific analytics backfill job
./bin/deployment/deploy_analytics_backfill_job.sh player_game_summary
./bin/deployment/deploy_analytics_backfill_job.sh team_offense_game_log
./bin/deployment/deploy_analytics_backfill_job.sh team_defense_game_log
```

## Usage Examples

### Test with Dry Run
```bash
gcloud run jobs execute player-game-summary-analytics-backfill \
  --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2
```

### Process Single Date
```bash
gcloud run jobs execute player-game-summary-analytics-backfill \
  --args=--start-date=2024-01-15,--end-date=2024-01-15 --region=us-west2
```

### Process Date Range
```bash
gcloud run jobs execute team-offense-analytics-backfill \
  --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
```

### Process Full Season
```bash
gcloud run jobs execute team-defense-analytics-backfill \
  --args=--start-date=2023-10-01,--end-date=2024-06-30 --region=us-west2
```

## Monitoring

### View Job Executions
```bash
gcloud run jobs executions list --job=player-game-summary-analytics-backfill \
  --region=us-west2 --limit=5
```

### View Logs
```bash
gcloud beta run jobs executions logs read [execution-id] --region=us-west2
```

### Monitor Processing Runs
```sql
-- Check recent analytics processor runs
SELECT 
  processor_name,
  run_date,
  success,
  records_processed,
  duration_seconds,
  date_range_start,
  date_range_end
FROM `nba-props-platform.nba_processing.analytics_processor_runs`
WHERE DATE(run_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY run_date DESC;
```

### Check Data Quality Issues
```sql
-- View unresolved data quality issues
SELECT 
  processor_name,
  issue_type,
  severity,
  identifier,
  issue_description,
  created_at
FROM `nba-props-platform.nba_processing.analytics_data_issues`
WHERE resolved = FALSE
ORDER BY created_at DESC;
```

## Processing Strategy

All analytics processors use **MERGE_UPDATE** strategy:
1. Delete existing data for the date range being processed
2. Insert new analytics records
3. Log processing run and any quality issues

## Resource Requirements

- **Memory**: 8Gi (for large BigQuery result sets)
- **CPU**: 4 cores (for parallel processing)
- **Timeout**: 2 hours (for full season processing)

## Dependencies

Analytics processors depend on raw data being available:
- **Player Game Summary**: Requires gamebook data, box scores, and props data
- **Team Offense**: Requires player box scores for aggregation
- **Team Defense**: Requires player box scores for defensive aggregation

## Data Quality

Analytics processors include built-in data quality tracking:
- Cross-source validation (e.g., NBA.com vs Ball Don't Lie points)
- Missing data detection
- Statistical anomaly flagging
- Processing run logging

All quality issues are logged to `nba_processing.analytics_data_issues` for analyst review.

## Troubleshooting

### Common Issues

**"No data extracted"**: Check that raw data exists for the date range
**"BigQuery insert errors"**: Verify table schemas match processor output
**"Memory limits exceeded"**: Reduce chunk size or increase memory allocation

### Debug Steps

1. Check raw data availability in source tables
2. Run with `--dry-run` to verify date ranges
3. Process small date ranges first (single day)
4. Monitor BigQuery job logs for detailed errors
5. Check analytics processing logs in `nba_processing.analytics_processor_runs`

## Performance

Expected processing times:
- **Single day**: 30-60 seconds
- **One week**: 2-5 minutes  
- **Full season**: 30-60 minutes
- **Multi-season backfill**: 2-4 hours

Processing happens in 7-day chunks by default to balance performance and memory usage.
