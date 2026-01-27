# Data Quality Monitoring Queries

SQL queries for detecting data quality issues in the NBA predictions pipeline.

## Overview

These queries are designed to detect the specific issues that occurred on 2026-01-26:
- Zero predictions generated
- Low usage_rate coverage
- Duplicate records
- Missing prop lines

Each query:
- Is self-contained and parameterized
- Returns alert level (OK, INFO, WARNING, CRITICAL)
- Includes diagnostic hints
- Suggests remediation actions
- Can be run manually or via Cloud Function

## Queries

### 1. zero_predictions.sql

**Purpose:** Detect when no predictions are generated for a game day

**Parameters:**
- `game_date` (DATE): Date to check

**Alert Levels:**
- CRITICAL: 0 predictions when games are scheduled
- WARNING: < 10 predictions when games are scheduled
- OK: Predictions generated normally

**Example Usage:**
```bash
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < zero_predictions.sql
```

**Expected Output:**
- `players_predicted`: Number of players with predictions
- `actionable_predictions`: Number of OVER/UNDER recommendations
- `no_line_count`: Players without betting lines
- `games_today`: Number of games scheduled
- `eligible_players`: Expected number of predictions
- `coverage_percent`: Actual / Expected coverage
- `alert_level`: OK, WARNING, or CRITICAL
- `alert_message`: Human-readable message
- `diagnostics`: Hints about root cause

---

### 2. low_usage_coverage.sql

**Purpose:** Detect when player_game_summary has low usage_rate coverage

**Parameters:**
- `game_date` (DATE): Date to check

**Alert Levels:**
- CRITICAL: < 50% coverage after all games complete
- WARNING: < 80% coverage after all games complete
- OK: ≥ 80% coverage

**Example Usage:**
```bash
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < low_usage_coverage.sql
```

**Expected Output:**
- `total_records`: Total records in player_game_summary
- `with_usage_rate`: Records with non-NULL usage_rate
- `null_usage_rate`: Records with NULL usage_rate
- `usage_rate_coverage_pct`: Percentage with usage_rate
- `games_count`: Number of games processed
- `completed_games`: Games with status = 'Final'
- `alert_level`: OK, WARNING, or CRITICAL
- `alert_message`: Human-readable message
- `diagnostics`: Timing information and hints

---

### 3. duplicate_detection.sql

**Purpose:** Detect duplicate records in player_game_summary

**Parameters:**
- `game_date` (DATE): Date to check

**Alert Levels:**
- OK: No duplicates
- INFO: ≤ 5 duplicate groups
- WARNING: ≤ 20 duplicate groups
- CRITICAL: > 20 duplicate groups

**Example Usage:**
```bash
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < duplicate_detection.sql
```

**Expected Output:**
- `duplicate_groups`: Number of (player, game) pairs with duplicates
- `total_duplicate_records`: Total duplicate records
- `excess_records`: Duplicate records beyond first occurrence
- `total_records`: Total records for the date
- `alert_level`: OK, INFO, WARNING, or CRITICAL
- `alert_message`: Human-readable message
- `duplicate_details`: Top 10 duplicate examples with timing
- `diagnostics`: Hints about root cause

---

### 4. prop_lines_missing.sql

**Purpose:** Detect when players are missing betting lines

**Parameters:**
- `game_date` (DATE): Date to check

**Alert Levels:**
- CRITICAL: 0% coverage or < 20% coverage
- WARNING: < 50% coverage
- INFO: < 80% coverage
- OK: ≥ 80% coverage

**Example Usage:**
```bash
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < prop_lines_missing.sql
```

**Expected Output:**
- `total_players`: Players in upcoming_player_game_context
- `players_with_lines`: Players with has_prop_line = TRUE
- `players_without_lines`: Players with has_prop_line = FALSE/NULL
- `prop_line_coverage_pct`: Percentage with prop lines
- `games_count`: Number of games
- `props_scraped_count`: Props scraped in last 24 hours
- `alert_level`: OK, INFO, WARNING, or CRITICAL
- `alert_message`: Human-readable message
- `diagnostics`: Phase 3 timing, props timing, recommended action

---

## Testing

### Test All Queries

```bash
# Run test script
./test_queries.sh

# Or test with specific date
./test_queries.sh 2026-01-25
```

### Test Individual Query

```bash
# Test with known issue date
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < zero_predictions.sql

# Test with today's date
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:$(date +%Y-%m-%d) \
  < zero_predictions.sql
```

### Performance Testing

```bash
# Check query execution time
time bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < zero_predictions.sql

# Check bytes processed
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  --dry_run \
  < zero_predictions.sql
```

## Query Design Principles

### 1. Self-Contained

Each query is complete and can be run independently. No dependencies on other queries or views.

### 2. Parameterized

All queries accept `@game_date` parameter for easy testing across dates.

### 3. Fast Execution

Queries are optimized to run in < 30 seconds:
- Use partition filters where possible
- Limit expensive operations (JOINs, aggregations)
- Pre-aggregate in CTEs

### 4. Actionable Output

Each query returns:
- Clear alert level
- Human-readable message
- Diagnostic hints
- Recommended remediation actions

### 5. Defensive

Queries handle edge cases:
- NULL values
- Missing data
- Division by zero
- Games not scheduled

## Query Optimization

### Current Performance

- **zero_predictions.sql:** ~5 seconds, ~80 MB scanned
- **low_usage_coverage.sql:** ~8 seconds, ~120 MB scanned
- **duplicate_detection.sql:** ~10 seconds, ~150 MB scanned
- **prop_lines_missing.sql:** ~12 seconds, ~100 MB scanned

**Total:** ~35 seconds, ~450 MB scanned per date

### Cost Analysis

- **Data Scanned:** 450 MB per day = 13.5 GB per month
- **Cost:** $0.005 per GB = $0.0675 per month = $0.81 per year
- **Negligible impact** on BigQuery budget

### Optimization Tips

If queries become slow:

1. **Add Partition Filters**
   ```sql
   WHERE game_date = @game_date  -- Already done
   AND _PARTITIONTIME = @game_date  -- If table is partitioned
   ```

2. **Use APPROX Functions**
   ```sql
   APPROX_COUNT_DISTINCT(player_lookup)  -- Instead of COUNT(DISTINCT ...)
   ```

3. **Materialize Common CTEs**
   ```sql
   -- Create a view for frequently used base queries
   CREATE VIEW nba_monitoring.daily_player_context AS ...
   ```

4. **Add Clustering**
   ```sql
   -- Cluster tables by game_date, player_lookup
   -- Improves query performance for these filters
   ```

## Integration with Cloud Function

These queries are used by the `data-quality-alerts` Cloud Function:

1. Function runs daily at 7 PM ET
2. Executes all 4 queries for current date
3. Parses results and determines alert levels
4. Sends alerts to Slack if issues detected

See: `orchestration/cloud_functions/data_quality_alerts/`

## Manual Usage

### Daily Health Check

Run all queries for today:
```bash
DATE=$(date +%Y-%m-%d)
for query in *.sql; do
  echo "Running $query..."
  bq query --use_legacy_sql=false \
    --parameter=game_date:DATE:$DATE \
    < $query
done
```

### Historical Analysis

Check last 7 days:
```bash
for i in {0..6}; do
  DATE=$(date -d "$i days ago" +%Y-%m-%d)
  echo "Checking $DATE..."
  bq query --use_legacy_sql=false \
    --parameter=game_date:DATE:$DATE \
    < zero_predictions.sql
done
```

### Create Scheduled Query

Run a query automatically:
```bash
# Create scheduled query in BigQuery
bq mk --transfer_config \
  --project_id=nba-props-platform \
  --data_source=scheduled_query \
  --display_name="Daily Zero Predictions Check" \
  --schedule="0 19 * * *" \
  --params='{
    "query":"'"$(cat zero_predictions.sql)"'",
    "destination_table_name_template":"alert_zero_predictions_{run_date}",
    "write_disposition":"WRITE_TRUNCATE",
    "partitioning_type":"DAY"
  }'
```

## Troubleshooting

### Query Returns No Results

**Possible causes:**
1. No games scheduled for that date
2. Tables not yet populated
3. Date format incorrect

**Fix:**
```bash
# Check if games exist
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.nbacom_schedule\` WHERE game_date = '2026-01-26'"
```

### Query Times Out

**Possible causes:**
1. Large date range
2. Missing partition filters
3. BigQuery quota exhausted

**Fix:**
```bash
# Check quota
gcloud alpha billing quotas list --consumer="projects/nba-props-platform" | grep bigquery

# Run with --maximum_bytes_billed to prevent runaway costs
bq query --maximum_bytes_billed=1000000000 ...  # 1 GB limit
```

### Incorrect Alert Level

**Possible causes:**
1. Thresholds too sensitive
2. Data timing issues (games just finished)
3. Expected behavior (e.g., no games today)

**Fix:**
1. Review alert thresholds in query
2. Add timing checks
3. Adjust for expected conditions

## Related Documentation

- [Monitoring Plan](../../../docs/08-projects/current/2026-01-27-data-quality-investigation/MONITORING-PLAN.md)
- [Cloud Function](../../orchestration/cloud_functions/data_quality_alerts/)
- [Root Cause Analysis](../../../docs/08-projects/current/2026-01-27-data-quality-investigation/2026-01-27-root-cause-analysis.md)

## Changelog

- **2026-01-27:** Initial version
  - Created 4 queries for data quality monitoring
  - Optimized for < 30s execution
  - Added diagnostic hints and remediation actions
  - Created test script

## Future Enhancements

- [ ] Add processing order violation detection query
- [ ] Add coordinator stuck detection query
- [ ] Create BigQuery scheduled queries for automatic monitoring
- [ ] Build dashboard for historical alert trends
- [ ] Add query for model confidence drift detection
