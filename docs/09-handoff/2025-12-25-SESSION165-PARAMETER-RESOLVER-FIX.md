# Session 165: Parameter Resolver Date Bug Fix

**Date:** December 25, 2025
**Status:** Complete
**Focus:** Fix critical date targeting bug causing 4-day data staleness

---

## Executive Summary

Fixed a critical bug in `orchestration/parameter_resolver.py` where post-game workflows (like `post_game_window_3`) were fetching TODAY's games instead of YESTERDAY's games. This caused gamebook data to go 4 days stale (since Dec 21), blocking the entire analytics pipeline.

---

## The Bug

### Root Cause
`ParameterResolver.build_workflow_context()` always used the current date:

```python
# BEFORE (buggy)
current_time = datetime.now(self.ET)
execution_date = current_time.date().strftime('%Y-%m-%d')
games_today = self.schedule_service.get_games_for_date(execution_date)  # Always TODAY!
```

### Impact
- `post_game_window_3` runs at 4 AM to collect gamebooks for YESTERDAY's finished games
- But it was looking for games on TODAY (no games at 4 AM)
- Gamebook scraper got empty games list → "No games today for gamebook PDF scraper"
- Result: **4 days of missing gamebook data (Dec 22-25)**

### Evidence from Logs
```
Dec 23 at 09:07 UTC: game_code: 20251223/WASCHA  ← TODAY's game (wrong!)
                     Should have been: 20251222/XXXYYY  ← YESTERDAY's game
Dec 24: "No games today for gamebook PDF scraper"  ← No games on Dec 24
```

---

## The Fix

### Changes Made

#### 1. Added Workflow Target Date Configuration
New constant in `orchestration/parameter_resolver.py`:
```python
YESTERDAY_TARGET_WORKFLOWS = [
    'post_game_window_1',    # 10 PM ET
    'post_game_window_2',    # 1 AM ET
    'post_game_window_3',    # 4 AM ET
    'late_games',            # Late night collection
]
```

#### 2. Added `_determine_target_date()` Method
Smart date selection based on workflow type:
```python
def _determine_target_date(self, workflow_name, current_time, explicit_target_date=None):
    if explicit_target_date:
        return explicit_target_date  # Backfill support

    if workflow_name in YESTERDAY_TARGET_WORKFLOWS:
        return yesterday  # Post-game workflows target yesterday

    return today  # Default
```

#### 3. Updated `build_workflow_context()`
Now accepts `target_date` parameter and uses `_determine_target_date()`:
```python
def build_workflow_context(self, workflow_name, target_games=None, target_date=None):
    resolved_target_date = self._determine_target_date(...)
    games_for_target_date = self.schedule_service.get_games_for_date(resolved_target_date)

    context = {
        'execution_date': execution_date,  # When the workflow runs
        'target_date': resolved_target_date,  # Which games to fetch
        'games_today': games_for_target_date,  # Games for target date
        ...
    }
```

#### 4. Updated `WorkflowExecutor`
Added `target_date` parameter for backfill support:
```python
def execute_workflow(self, workflow_name, scrapers, decision_id=None,
                     target_games=None, target_date=None):
```

---

## Files Changed

| File | Change |
|------|--------|
| `orchestration/parameter_resolver.py` | Added `YESTERDAY_TARGET_WORKFLOWS`, `_determine_target_date()`, updated `build_workflow_context()` |
| `orchestration/workflow_executor.py` | Added `target_date` parameter to `execute_workflow()` |
| `tests/orchestration/unit/test_parameter_resolver.py` | New test file with 9 tests |
| `bin/monitoring/check_data_freshness.sh` | New monitoring script |

---

## Prevention Measures

### 1. Unit Tests
Created `tests/orchestration/unit/test_parameter_resolver.py` with tests for:
- Post-game workflows target yesterday
- Regular workflows target today
- Explicit dates override patterns
- Context contains correct target_date

Run with:
```bash
pytest tests/orchestration/unit/test_parameter_resolver.py -v
```

### 2. Data Freshness Monitoring
Created `bin/monitoring/check_data_freshness.sh`:
- Checks all key tables for staleness
- Warns at 2 days stale, critical at 4 days
- Should be run daily via cron/Cloud Scheduler

```bash
./bin/monitoring/check_data_freshness.sh
```

### 3. Clear Documentation
Added prominent comments in `parameter_resolver.py`:
```python
# CRITICAL: If you add a new post-game workflow, add it here!
# Failure to do so will cause the workflow to look for TODAY's games
# instead of YESTERDAY's finished games.
YESTERDAY_TARGET_WORKFLOWS = [...]
```

### 4. Logging
Added clear logging when target date differs from execution date:
```
INFO: Workflow 'post_game_window_3' targets YESTERDAY's games. Target date: 2025-12-24 (today is 2025-12-25)
```

---

## Recommended Actions

### Immediate
1. Deploy fix to Cloud Run
2. Run gamebook backfill for Dec 22-23

### This Week
1. Set up daily `check_data_freshness.sh` as Cloud Scheduler job
2. Add Slack/email alerts for critical staleness

### Long Term
1. Consider adding pre-deploy validation that checks workflow config vs resolver
2. Add integration test that runs post_game_window_3 and verifies correct date

---

## Backfill Commands

Run gamebook backfill for missing dates:
```bash
# Dec 22 gamebooks
PYTHONPATH=. .venv/bin/python -c "
from scrapers.nbacom.nbac_gamebook_pdf import GetNbaComGamebookPdf
from shared.utils.schedule import NBAScheduleService

schedule = NBAScheduleService()
games = schedule.get_games_for_date('2025-12-22')
print(f'Found {len(games)} games for Dec 22')

for game in games:
    game_code = f'{game.game_date.replace(\"-\", \"\")}/{game.away_team}{game.home_team}'
    print(f'Processing: {game_code}')
    scraper = GetNbaComGamebookPdf()
    scraper.run({'game_code': game_code, 'group': 'prod'})
"

# Repeat for Dec 23
```

---

## Key Lesson

**Workflow execution date ≠ Target game date**

When a workflow runs at 4 AM to collect "yesterday's finished games":
- `execution_date` = today (when the job runs)
- `target_date` = yesterday (which games to fetch)

The parameter resolver must be aware of this distinction.

---

## Commits

| Commit | Description |
|--------|-------------|
| (pending) | fix: Parameter resolver now targets correct date for post-game workflows |

---

**Session Duration:** ~1 hour
**Pipeline Status:** Fix ready for deployment, backfill needed
