# Sonnet Fix Task: Team Stats Dependency Check

## Objective
Prevent NULL usage_rate by ensuring team_offense_game_summary data exists before player_game_summary calculates usage_rate.

## Problem
`player_game_summary` processor runs before `team_offense_game_summary` completes. When player processor joins to team stats, they don't exist yet → NULL usage_rate for 71% of players.

## Root Cause
Both processors are triggered by same Pub/Sub message (`bdl_player_boxscores` completion) and run in parallel with no ordering.

## Solution Design

### Option A: Add Team Stats Availability Check (RECOMMENDED)
Modify `PlayerGameSummaryProcessor.extract_raw_data()` to check if team stats exist before including team stats fields.

**File to modify**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Changes**:

1. Add method to check team stats availability:
```python
def _check_team_stats_available(self, start_date: str, end_date: str) -> Tuple[bool, int]:
    """
    Check if team_offense_game_summary has data for the target dates.

    Returns:
        (is_available, record_count)
    """
    query = f"""
    SELECT COUNT(DISTINCT CONCAT(game_id, '_', team_abbr)) as team_game_count
    FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    result = self.bq_client.query(query).result()
    count = next(result).team_game_count

    # Expect ~14 team-games per day (7 games × 2 teams)
    # Allow some flexibility for partial days
    expected_min = 10
    is_available = count >= expected_min

    if not is_available:
        logger.warning(
            f"Team stats not ready: {count} records found (expected >= {expected_min}). "
            f"Usage rate will be NULL for this run."
        )

    return is_available, count
```

2. Call this check at start of `extract_raw_data()`:
```python
def extract_raw_data(self) -> None:
    start_date = self.opts['start_date']
    end_date = self.opts['end_date']

    # Check team stats availability
    team_stats_available, team_stats_count = self._check_team_stats_available(start_date, end_date)
    self._team_stats_available = team_stats_available

    if not team_stats_available:
        # Log and track for monitoring
        self.track_source_coverage_event(
            event_type=SourceCoverageEventType.DEPENDENCY_STALE,
            severity=SourceCoverageSeverity.WARNING,
            source='team_offense_game_summary',
            message=f"Team stats not available, usage_rate will be NULL",
            details={'team_stats_count': team_stats_count}
        )

    # Rest of extract logic...
```

3. Modify usage_rate calculation in `_process_single_player_game()` to skip if team stats unavailable:
```python
# In _process_single_player_game(), around line 1274:
# Only calculate usage_rate if team stats were available
usage_rate = None
if self._team_stats_available and (
    pd.notna(row.get('team_fg_attempts')) and
    # ... rest of conditions
):
    # ... existing usage_rate calculation
```

4. Add quality flag to track this condition:
```python
# In the record dict:
'data_quality_flag': 'complete' if (usage_rate is not None and self._team_stats_available) else 'partial_no_team_stats',
'team_stats_available_at_processing': self._team_stats_available,
```

### Option B: Re-process When Team Stats Arrive
Add a trigger in `TeamOffenseGameSummaryProcessor` to re-trigger player processing after it completes.

**Not recommended** - creates circular dependencies and extra processing.

## Testing

1. Run player_game_summary for a date where team stats don't exist:
```bash
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
    --start-date 2026-01-26 --end-date 2026-01-26 --debug
```

2. Verify logs show "Team stats not ready" warning
3. Verify records have `data_quality_flag = 'partial_no_team_stats'`
4. Run team_offense_game_summary, then re-run player_game_summary
5. Verify usage_rate is now populated

## Validation Query
```sql
SELECT
  game_date,
  data_quality_flag,
  COUNTIF(usage_rate IS NOT NULL) as has_usage,
  COUNTIF(usage_rate IS NULL) as null_usage,
  COUNT(*) as total
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2026-01-26'
GROUP BY game_date, data_quality_flag
```

## Expected Outcome
- No more silent NULL usage_rate from timing issues
- Clear tracking of WHY usage_rate is NULL
- Monitoring can alert on `partial_no_team_stats` quality flag
