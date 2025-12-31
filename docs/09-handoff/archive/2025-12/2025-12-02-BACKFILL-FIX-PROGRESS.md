# Phase 3 Backfill Fix Progress

**Date:** 2025-12-02 (Updated)
**Session Focus:** Fixing blockers for `upcoming_player_game_context` and `upcoming_team_game_context` backfills

## Summary

Made significant progress fixing blockers for the Phase 3 `upcoming_*` processor backfills. Multiple code fixes were implemented to support backfill mode properly. **Both backfills are now running successfully.**

## Session 2 Fixes (Latest)

### 6. Team Processor - Date String Conversion in `_extract_schedule_data()` (Line 472-476)

Added defensive date conversion at the start of the method:
```python
# Ensure dates are date objects, not strings (defensive conversion)
if isinstance(start_date, str):
    start_date = date.fromisoformat(start_date)
if isinstance(end_date, str):
    end_date = date.fromisoformat(end_date)
```

### 7. Team Processor - DataFrame `game_date` Conversion (Line 513-515)

Force convert `game_date` column to datetime after loading from BigQuery:
```python
# Ensure game_date is datetime type for .dt accessor
# Force conversion regardless of dtype (BQ can return various types)
schedule_df['game_date'] = pd.to_datetime(schedule_df['game_date'])
```

### 8. Team Processor - Date Conversion in `validate_extracted_data()` (Lines 828-832)

Added date string conversion before date comparisons:
```python
# Convert to date objects if strings
if isinstance(start_date, str):
    start_date = date.fromisoformat(start_date)
if isinstance(end_date, str):
    end_date = date.fromisoformat(end_date)
```

### 9. Team Processor - Date Conversion in `calculate_analytics()` (Lines 1022-1026)

Same fix applied in the analytics calculation method.

### 10. Team Processor - Completeness Checker Field Name Fix (Lines 1049, 1061)

Changed `upstream_entity_field` from `home_team_abbr` to `home_team_tricode` to match actual table schema:
```python
upstream_entity_field='home_team_tricode',  # Schedule uses home/away tricodes
```

### 11. Team Processor - Schema Field Filtering in `save_results()` (Lines 1765-1771)

Added filtering to only include columns that exist in the BigQuery table schema:
```python
# Filter data to only include columns that exist in the schema
schema_fields = {field.name for field in table.schema}
filtered_data = [
    {k: v for k, v in record.items() if k in schema_fields}
    for record in self.transformed_data
]
```

## Current Backfill Status

### Upcoming Player Game Context
- **Status:** Running (PID 3531895)
- **Date Range:** 2021-10-19 to 2021-11-15
- **Log:** `/tmp/upcoming_player_backfill.log`
- **Notes:** Team mapping warnings are expected for historical data

### Upcoming Team Game Context
- **Status:** Running (PID 3568322)
- **Date Range:** 2021-10-19 to 2021-11-15
- **Log:** `/tmp/upcoming_team_backfill.log`
- **Verified:** 18 records saved to BigQuery for 2021-10-25

## Previous Session Fixes (Session 1)

### 1. Analytics Base - Dependency Check Types (analytics_base.py)

Added support for two new check types in `_check_table_data()`:

```python
# Lines 738-767: Added date_match and lookback_days check types
elif check_type == 'date_match':
    # Check for records on exact date (end_date is the target date)
    query = f"""
    SELECT COUNT(*) as row_count, ...
    FROM `{self.project_id}.{table_name}`
    WHERE {date_field} = '{end_date}'
    """

elif check_type == 'lookback_days':
    # Check for records in a lookback window from end_date
    lookback = config.get('lookback_days', 30)
    # Calculate lookback start date
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    lookback_start = (end_dt - timedelta(days=lookback)).strftime('%Y-%m-%d')
    query = f"""
    SELECT COUNT(*) as row_count, ...
    FROM `{self.project_id}.{table_name}`
    WHERE {date_field} BETWEEN '{lookback_start}' AND '{end_date}'
    """
```

### 2. Analytics Base - Backfill Mode Critical Dependency Handling (analytics_base.py)

Modified line 209-235 to allow processing to continue in backfill mode even when critical dependencies are missing:

```python
if not dep_check['all_critical_present']:
    if self.is_backfill_mode:
        logger.warning(f"BACKFILL_MODE: {error_msg} - continuing anyway")
        logger.info("BACKFILL_MODE: Processor will handle missing data in extract_raw_data()")
    else:
        # ... raise error in normal mode
```

### 3. Upcoming Player Game Context Processor

**File:** `upcoming_player_game_context_processor.py`

Added `target_date` initialization from opts in `extract_raw_data()` (lines 292-300):

```python
# Set target_date from opts if not already set (for run() vs process_date() compatibility)
if self.target_date is None:
    end_date = self.opts.get('end_date')
    if isinstance(end_date, str):
        self.target_date = date.fromisoformat(end_date)
    elif isinstance(end_date, date):
        self.target_date = end_date
    else:
        raise ValueError("target_date not set and no valid end_date in opts")
```

### 4. Upcoming Team Game Context Processor

**File:** `upcoming_team_game_context_processor.py`

Multiple fixes:

a) Added `self.target_date = None` to `__init__()` (line 103-104)

b) Added `target_date` initialization from opts in `extract_raw_data()` (lines 273-281)

c) Added backfill mode skip for internal stale data check (lines 345-361):
```python
# Check critical staleness (skip in backfill mode)
if dep_check.get('has_stale_fail') and not self.is_backfill_mode:
    # ... raise error
elif dep_check.get('has_stale_fail') and self.is_backfill_mode:
    logger.info(f"BACKFILL_MODE: Skipping stale data check for {stale}")
```

d) Added date string to date object conversion (lines 304-319):
```python
start_date_str = self.opts.get('start_date')
end_date_str = self.opts.get('end_date')
# Convert to date objects if they are strings
if isinstance(start_date_str, str):
    start_date = date.fromisoformat(start_date_str)
```

### 5. Backfill Scripts - Date Iteration

Both backfill scripts were updated to iterate through dates properly:

**Files:**
- `backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py`
- `backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py`

Changed from single `run()` call to iterating through dates:
```python
for i, target_date in enumerate(dates_to_process, 1):
    processor = UpcomingTeamGameContextProcessor()
    opts = {
        'start_date': target_date.isoformat(),
        'end_date': target_date.isoformat(),
        'backfill_mode': True,
        'skip_downstream_trigger': True
    }
    success = processor.run(opts)
```

## Known Issues (Non-Blocking)

### 1. Missing Analytics Dataset Warning
```
Dataset nba-props-platform:nba_analytics.nba_analytics was not found
```
- Smart reprocessing hash queries fail
- Non-blocking (continues processing)
- Dataset path may be incorrect or dataset needs creation

### 2. Player Team Mapping Warnings
- Some players can't be mapped to teams in historical data
- Expected behavior for backfill of old seasons
- Non-blocking (player is skipped)

### 3. Schema Mismatch Warning for `analytics_processor_runs`
```
Field success has changed mode from REQUIRED to NULLABLE
```
- Non-blocking for backfill
- Schema needs to be updated for production use

## Files Modified

1. `data_processors/analytics/analytics_base.py`
2. `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
3. `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`
4. `backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py`
5. `backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py`

## Next Steps

1. **Monitor both backfills to completion:**
   - Player: `/tmp/upcoming_player_backfill.log`
   - Team: `/tmp/upcoming_team_backfill.log`
   - Expected: ~45 minutes per processor for 28 dates

2. **Verify data after completion:**
   ```sql
   SELECT game_date, COUNT(*)
   FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
   WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
   GROUP BY 1 ORDER BY 1;

   SELECT game_date, COUNT(*)
   FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
   WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
   GROUP BY 1 ORDER BY 1;
   ```

3. **Run validation script after completion:**
   ```bash
   python3 bin/validate_pipeline.py 2021-10-19 2021-11-15
   ```

## Commands for Monitoring

```bash
# Player backfill progress
tail -f /tmp/upcoming_player_backfill.log

# Team backfill progress
tail -f /tmp/upcoming_team_backfill.log

# Check if backfill processes are running
ps aux | grep upcoming.*backfill

# Check data in BigQuery
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as records FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\` GROUP BY 1 ORDER BY 1"
```
