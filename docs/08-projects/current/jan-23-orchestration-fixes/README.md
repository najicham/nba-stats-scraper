# January 23, 2026 - Daily Orchestration Fixes

## Overview

This project documents critical fixes implemented on January 23, 2026 to address multiple issues discovered during daily orchestration validation.

**Date:** January 23, 2026
**Status:** Completed
**Priority:** HIGH/CRITICAL

## Issues Discovered

### 1. Scraper Parameter Resolution Failures (HIGH)

**Symptoms:**
- `espn_team_roster_api`: Missing [team_abbr] - 6 failures
- `oddsa_events`: Missing [sport] - 5 failures
- `oddsa_current_game_lines`: Missing [event_id] - 2 failures
- `nbac_team_boxscore`: Missing [game_date] - 3 failures

**Root Causes:**
1. `YESTERDAY_TARGET_WORKFLOWS` list was missing `post_game_window_2b` and `morning_recovery`
2. `oddsa_events` scraper had no resolver registered

**Files Modified:**
- `orchestration/parameter_resolver.py`

### 2. Feature Store 60-Day Lookback Bug (CRITICAL)

**Symptoms:**
- 80% of players failing spot check validation
- `games_found` and `games_expected` incorrect for players with games > 60 days old
- `contributing_game_dates` missing older dates

**Root Cause:**
The `_batch_extract_last_10_games()` function used a 60-day lookback window for BOTH:
- Retrieving the last 10 games (correct)
- Counting `total_games_available` (INCORRECT - limited count to 60-day window)

**Fix:**
Used CTE to separate:
- Last-10 retrieval (60-day window for efficiency)
- Total games count (no date limit for accuracy)

**File Modified:**
- `data_processors/precompute/ml_feature_store/feature_extractor.py`

### 3. Stale Schedule Data (MEDIUM)

**Symptoms:**
- 3 games from 2026-01-22 showing "In Progress" when they should be "Final"
- 1 game from 2026-01-08 still showing as "Scheduled"
- `fix_stale_schedule.py` script was broken

**Root Causes:**
1. Script referenced non-existent column `start_time_et` (actual: `time_slot`)
2. Script referenced `home_team_abbr` (actual: `home_team_tricode`)
3. UPDATE query missing required partition filter on `game_date`
4. Also found inconsistency: `game_status=3` but `game_status_text="In Progress"`

**Files Modified:**
- `bin/monitoring/fix_stale_schedule.py`

## Changes Made

### 1. orchestration/parameter_resolver.py

**Lines 44-49:** Added missing workflows to `YESTERDAY_TARGET_WORKFLOWS`:
```python
YESTERDAY_TARGET_WORKFLOWS = [
    'post_game_window_1',
    'post_game_window_2',
    'post_game_window_2b',   # ADDED
    'post_game_window_3',
    'morning_recovery',      # ADDED
    'late_games',
]
```

**Lines 83-94:** Added `oddsa_events` resolver:
```python
self.complex_resolvers = {
    ...
    'oddsa_events': self._resolve_odds_events,  # ADDED
    ...
}
```

**Lines 642-658:** New resolver method:
```python
def _resolve_odds_events(self, context: Dict[str, Any]) -> Dict[str, Any]:
    """Resolver for Odds API events scraper."""
    return {
        'sport': 'basketball_nba',
        'game_date': context['execution_date']
    }
```

### 2. data_processors/precompute/ml_feature_store/feature_extractor.py

**Lines 414-467:** Rewrote `_batch_extract_last_10_games()` to use CTE:

**Before (buggy):**
```sql
SELECT ...
    COUNT(*) OVER (PARTITION BY player_lookup) as total_games_available
FROM player_game_summary
WHERE game_date < '{game_date}'
  AND game_date >= '{lookback_date}'  -- BUG: Limits total count!
```

**After (fixed):**
```sql
WITH total_games_per_player AS (
    -- Count ALL historical games (no date limit)
    SELECT player_lookup, COUNT(*) as total_games_available
    FROM player_game_summary
    WHERE game_date < '{game_date}'
    GROUP BY player_lookup
),
last_10_games AS (
    -- Use 60-day window for efficient retrieval
    SELECT ...
    FROM player_game_summary
    WHERE game_date < '{game_date}'
      AND game_date >= '{lookback_date}'
)
SELECT l.*, t.total_games_available
FROM last_10_games l
JOIN total_games_per_player t ON l.player_lookup = t.player_lookup
WHERE l.rn <= 10
```

### 3. bin/monitoring/fix_stale_schedule.py

- Fixed column references: `start_time_et` → `time_slot`, `home_team_abbr` → `home_team_tricode`
- Added partition filter to UPDATE query
- Updated both `game_status` AND `game_status_text` for consistency
- Grouped updates by date for partition-safe operations

## Validation

### Pre-Fix State
```
Players checked: 10
Total checks: 60
  Passed: 44
  Failed: 16  (80% failure rate on historical completeness)
```

### Post-Fix State
- Stale schedule data: Fixed (8 games total)
- Feature store: Fix applies to future runs (requires backfill for historical data)
- Parameter resolution: Scrapers should now receive correct parameters

## Completed Actions

### Feature Store Code Fix (DEPLOYED)

The 60-day lookback bug has been fixed in `feature_extractor.py`. The fix:
- Uses CTE to separate last-10 retrieval (60-day window) from total games count (no limit)
- Will apply to all NEW feature store records going forward
- Existing historical records retain old values (would require DELETE + re-run to fix)

**Note:** Existing records for 2026-01-01 to 2026-01-22 were not updated because the backfill
skips dates that already have data. To fully fix historical data, a manual cleanup would be needed:

```bash
# Option 1: Delete and re-run (during maintenance window)
bq query 'DELETE FROM nba_predictions.ml_feature_store_v2 WHERE game_date BETWEEN "2026-01-01" AND "2026-01-22"'
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2026-01-01 --end-date 2026-01-22 --parallel
```

### Stale Schedule Automation (DEPLOYED)

Created Cloud Scheduler job `fix-stale-schedule`:
- **Schedule:** Every 4 hours (0 */4 * * *)
- **Endpoint:** POST /fix-stale-schedule
- **Service:** nba-scrapers
- **Region:** us-west2

Setup script: `bin/schedulers/setup_stale_schedule_job.sh`

New endpoint added to `scrapers/main_scraper_service.py`:
- Route: `POST /fix-stale-schedule`
- Automatically marks old in-progress games as Final
- Updates both `game_status` and `game_status_text` for consistency

## Related Documentation

- [Daily Validation Checklist](/docs/02-operations/daily-validation-checklist.md)
- [Orchestration Overview](/docs/03-phases/phase1-orchestration/overview.md)
- [Feature Store Documentation](/docs/03-phases/phase4-precompute/ml-feature-store.md)

## Testing

### Verify Parameter Resolution
```bash
# Test workflow context building
python -c "
from orchestration.parameter_resolver import ParameterResolver
pr = ParameterResolver()
print('YESTERDAY_TARGET_WORKFLOWS:', pr.YESTERDAY_TARGET_WORKFLOWS if hasattr(pr, 'YESTERDAY_TARGET_WORKFLOWS') else 'N/A')
print('oddsa_events resolver:', 'oddsa_events' in pr.complex_resolvers)
"
```

### Verify Spot Check
```bash
python bin/spot_check_features.py --count 10
```

### Verify Schedule Fix
```bash
python bin/monitoring/fix_stale_schedule.py --dry-run
```
