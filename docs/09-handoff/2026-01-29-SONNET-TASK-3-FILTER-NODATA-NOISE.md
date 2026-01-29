# Sonnet Task 3: Filter "No Data" Error Noise

## Task Summary
Modify the pipeline monitoring to filter out "No data extracted" errors that are expected (no games scheduled), reducing alert noise by ~90%.

## Context
- "No data extracted" is the #1 error type (54+ per day)
- Most are LEGITIMATE - no games were scheduled for that date
- This masks real issues and creates alert fatigue
- We need to check the game schedule before flagging as an error

## Current State

Check current error distribution:
```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN error_message LIKE '%No data extracted%' THEN 'no_data_extracted'
    ELSE 'other_error'
  END as error_type,
  COUNT(*) as cnt
FROM nba_orchestration.pipeline_event_log
WHERE event_type = 'error'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1"
```

## Implementation Steps

### 1. Understand the Schedule Table
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC"
```

### 2. Modify phase_success_monitor.py

Read the current file:
```bash
cat bin/monitoring/phase_success_monitor.py
```

Add a function to check if a date has scheduled games:

```python
def get_game_dates_with_games(hours: int = 24) -> set:
    """Get dates that actually had games scheduled."""
    from google.cloud import bigquery
    client = bigquery.Client()

    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
      AND game_date <= CURRENT_DATE()
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", (hours // 24) + 1)
        ]
    )

    result = client.query(query, job_config=job_config).result()
    return {row.game_date for row in result}
```

Then modify the error counting to filter:

```python
def is_expected_no_data_error(error_row, game_dates_with_games: set) -> bool:
    """Check if a 'no data' error is expected (no games that day)."""
    if 'No data extracted' not in str(error_row.get('error_message', '')):
        return False

    # Extract date from the error context
    game_date = error_row.get('game_date')
    if game_date and game_date not in game_dates_with_games:
        return True  # Expected - no games scheduled

    return False  # Unexpected - should have had games
```

### 3. Add Categorization to Error Output

Modify the error reporting to show:
```
--------------------------------------------------
ERRORS BY CATEGORY
--------------------------------------------------
Real Errors (need attention): 12
  - PlayerGameSummaryProcessor: 5
  - MLFeatureStoreProcessor: 3
  - Other: 4

Expected No-Data (filtered): 54
  - Days with no games: 2026-01-29 (no games)
```

### 4. Alternative: Add to Error Query Directly

Modify the BigQuery query in the monitor to exclude expected no-data:

```sql
SELECT processor_name, error_message, COUNT(*) as error_count
FROM nba_orchestration.pipeline_event_log pel
WHERE event_type = 'error'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
  -- Filter out expected no-data errors
  AND NOT (
    error_message LIKE '%No data extracted%'
    AND NOT EXISTS (
      SELECT 1
      FROM nba_raw.nbac_schedule s
      WHERE s.game_date = DATE(pel.game_date)
    )
  )
GROUP BY 1, 2
ORDER BY error_count DESC
```

### 5. Update the Validation Skill

Check if `/validate-daily` skill needs updating:
```bash
cat .claude/skills/validate-daily/SKILL.md | head -100
```

Add similar filtering logic there.

## Testing

### Test with a Known No-Game Day
```bash
# Find a day with no games
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date >= '2026-01-01'
GROUP BY 1
HAVING COUNT(*) = 0
ORDER BY 1 DESC
LIMIT 5"
```

### Verify Filtering Works
After modification, run:
```bash
python bin/monitoring/phase_success_monitor.py --hours 24
```

Should show:
- Real errors: ~10-15 (actual issues)
- Filtered no-data: ~50+ (expected, hidden)

## Success Criteria
- [ ] Monitor distinguishes between real errors and expected no-data
- [ ] Error count drops from 54+ to ~10-15 real errors
- [ ] No-game days are clearly identified
- [ ] Alert threshold only considers real errors

## Files to Modify
- `bin/monitoring/phase_success_monitor.py` - main changes
- `.claude/skills/validate-daily/SKILL.md` - if skill needs update

## Time Estimate
30-45 minutes
