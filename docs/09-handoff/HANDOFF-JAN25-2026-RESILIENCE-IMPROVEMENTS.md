# Handoff: Resilience Improvements - January 25, 2026

**Created:** 2026-01-25 ~7:00 PM PST
**Purpose:** Continue orchestration resilience improvements
**Priority:** High - System improvements for long-term stability

---

## Context: What Was Done This Session

### Investigation Completed
Four parallel agents analyzed the system:
1. **Firestore 403 Permissions** - Intermittent errors, now resolved
2. **Schedule/Boxscore Pipeline** - Found dedup view not being used
3. **Auto-Healing Infrastructure** - Found 85% of pipeline unprotected
4. **Monitoring/Validation** - Found gaps in dashboarding and integration

### Key Finding: Deduplication View Not Used
The codebase has a deduplication view `nba_raw.v_nbac_schedule_latest` that prevents duplicate game status confusion, but 100+ locations were querying the raw table `nba_raw.nbac_schedule` directly.

**View Definition** (in `schemas/bigquery/raw/nbac_schedule_tables.sql:171-183`):
```sql
-- Returns only the most recent status per game by:
-- 1. Partitioning by game_id
-- 2. Ordering by game_status DESC (Final=3 > InProgress=2 > Scheduled=1)
-- 3. Breaking ties by processed_at DESC
-- Limited to 90 days past / 30 days future
```

### Code Changes Made (Task #1 - COMPLETED)

**Files updated to use `v_nbac_schedule_latest`:**

1. `shared/utils/schedule/database_reader.py`
   - Line 214: `get_nba_api_season_type()` - now uses view
   - Line 271: `get_season_start_date()` - added inline dedup for historical data

2. `shared/utils/completeness_checker.py`
   - 8 queries updated (lines 325, 398, 411, 468, 482, 1592, 1712, 1722)

3. `shared/validation/context/schedule_context.py`
   - Line 165: `_query_schedule()` - now uses view

4. `shared/processors/patterns/early_exit_mixin.py`
   - Lines 120, 167: game status checks - now use view

5. **Analytics Processors** (9 files):
   - `defense_zone_analytics_processor.py`
   - `player_game_summary_processor.py`
   - `team_defense_game_summary_processor.py`
   - `team_offense_game_summary_processor.py`
   - `upcoming_player_game_context_processor.py` (3 queries)
   - `async_upcoming_player_game_context_processor.py` (3 queries)
   - `upcoming_team_game_context_processor.py` (2 queries)
   - `travel_utils.py`

---

## Remaining Tasks

### Task #5: Sync Cloud Function Copies (CRITICAL - DO FIRST)
Cloud Functions have their own copies of shared utilities that need to be synced.

**Files to sync:**
- `shared/utils/schedule/database_reader.py`
- `shared/utils/completeness_checker.py`
- `shared/validation/context/schedule_context.py`
- `shared/processors/patterns/early_exit_mixin.py`

**Target Cloud Functions (7):**
- `orchestration/cloud_functions/phase2_to_phase3/shared/`
- `orchestration/cloud_functions/phase3_to_phase4/shared/`
- `orchestration/cloud_functions/phase4_to_phase5/shared/`
- `orchestration/cloud_functions/phase5_to_phase6/shared/`
- `orchestration/cloud_functions/auto_backfill_orchestrator/shared/`
- `orchestration/cloud_functions/daily_health_summary/shared/`
- `orchestration/cloud_functions/self_heal/shared/`

**How to sync:**
```bash
# Option 1: Manual rsync for each file
rsync -av shared/utils/completeness_checker.py \
  orchestration/cloud_functions/phase2_to_phase3/shared/utils/

# Option 2: Check if sync script covers these
python bin/maintenance/sync_shared_utils.py --all --dry-run
```

---

### Task #2: Implement `_evaluate_bdl_catchup()` Method (HIGH PRIORITY)

**Problem:** Three workflows are configured but NOT IMPLEMENTED:
- `bdl_catchup_midday` (10 AM ET)
- `bdl_catchup_afternoon` (2 PM ET)
- `bdl_catchup_evening` (6 PM ET)

They use `decision_type: "bdl_catchup"` but `master_controller.py` has no handler.
Currently logs warning and SKIPS silently.

**File to modify:** `orchestration/master_controller.py`

**Changes needed:**

1. Add routing case at line ~242 in `_evaluate_all_workflows_internal()`:
```python
elif decision_type == "bdl_catchup":
    decision = self._evaluate_bdl_catchup(workflow_name, workflow_config, current_time)
```

2. Add new method before line 933 (`_extract_scrapers_from_plan()`):
```python
def _evaluate_bdl_catchup(
    self,
    workflow_name: str,
    config: Dict,
    current_time: datetime
) -> WorkflowDecision:
    """
    Evaluate BDL catch-up workflow.

    Finds games from last N days that have NBAC data but missing BDL data,
    then retries collection during the scheduled window.
    """
    # 1. Check if in time window (fixed_time +/- tolerance)
    # 2. Get lookback_days from config (e.g., 3)
    # 3. Query for games with NBAC data but NO BDL data
    # 4. Filter for games with game_status = 3 (Final)
    # 5. Return RUN with target_games list if missing found
```

**Reference config in `config/workflows.yaml`:**
```yaml
bdl_catchup_midday:
  decision_type: "bdl_catchup"
  schedule:
    fixed_time: "10:00"
    tolerance_minutes: 30
    lookback_days: 3
```

---

### Task #3: Add Phase 2 Scraper Resilience (CRITICAL - LONGER TERM)

**Problem:** 85% of pipeline has NO auto-healing. Phase 2 scrapers (6 total) are the highest-risk gap.

**Current State:**
- Phase 3 & 4 processors have event logging via `analytics_base.py` and `precompute_base.py`
- Phase 2 scrapers have ZERO resilience

**Scrapers needing coverage:**
- `p2_bdl_box_scores`
- `p2_nbacom_schedule`
- `p2_nbacom_gamebook_pdf`
- `p2_bigdataball_pbp`
- `p2_odds_game_lines`
- `p2_br_season_roster`

**Solution approach:**
1. Create `ScraperBase` class with pipeline logging integration
2. Integrate `shared/utils/pipeline_logger.py` (already exists)
3. Add transient error classification for network failures
4. Implement 3-retry logic with exponential backoff

**Reference implementation:**
- `data_processors/analytics/analytics_base.py` - see how it integrates pipeline_logger
- `shared/utils/pipeline_logger.py` - the logging utility

---

### Task #4: Build Unified Monitoring Dashboard (MEDIUM PRIORITY)

**Problem:** No unified real-time dashboard exists. Users must query BigQuery manually.

**Existing infrastructure:**
- Daily health summary at 9 AM ET (Slack)
- Sentry error tracking
- Multiple validation scripts in `bin/validation/`

**What's needed:**
- Cloud Monitoring dashboard with phase completion status
- Error rate trending (24h, 7d, 30d)
- Data freshness timeline
- DLQ depth and auto-retry success rate

---

## Key Files to Study

| File | Purpose |
|------|---------|
| `orchestration/master_controller.py` | Main workflow decision logic |
| `config/workflows.yaml` | Workflow definitions and schedules |
| `shared/utils/pipeline_logger.py` | Event logging utility |
| `shared/utils/completeness_checker.py` | Data completeness validation |
| `schemas/bigquery/raw/nbac_schedule_tables.sql` | View definitions |
| `data_processors/analytics/analytics_base.py` | Reference for pipeline logging integration |

---

## System Health Verification

**Tomorrow morning (Jan 26), run this health check:**
```bash
bq query --use_legacy_sql=false "
SELECT
  'schedule' as check_type,
  COUNTIF(game_status = 3) as final_games,
  COUNT(*) as total_games
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date = '2026-01-24'
UNION ALL
SELECT 'boxscores', COUNT(DISTINCT game_id), 0
FROM nba_raw.bdl_player_boxscores WHERE game_date = '2026-01-24'
UNION ALL
SELECT 'analytics', COUNT(*), 0
FROM nba_analytics.player_game_summary WHERE game_date = '2026-01-24'
ORDER BY check_type"
```

**Expected results:**
- Schedule: 7 final / 7 total
- Boxscores: 7 games
- Analytics: ~245 records

**Check for Firestore errors:**
```bash
gcloud logging read 'textPayload:"403" AND textPayload:"Firestore"' \
  --project=nba-props-platform --limit=5 --freshness=12h
```
Should return empty.

---

## Current Task List

```
#5 [pending] Sync dedup view changes to Cloud Function copies
#2 [pending] Implement _evaluate_bdl_catchup() method in master_controller
#3 [pending] Add Phase 2 scraper resilience with pipeline logging
#4 [pending] Build unified Cloud Monitoring dashboard
#1 [completed] Use v_nbac_schedule_latest view in NBAScheduleService
```

---

## Investigation Reports (Agent Outputs)

Full investigation reports from the 4 parallel agents are available at:
- `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/a15cdf4.output` - Firestore 403
- `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/aee75c0.output` - Schedule/Boxscore pipeline
- `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/a42205e.output` - Auto-healing infrastructure
- `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/a09d0f2.output` - Monitoring/validation

---

## Quick Commands

```bash
# Check current task list
# Use /tasks in Claude Code

# Run sync script (dry run first)
python bin/maintenance/sync_shared_utils.py --all --dry-run

# Check schedule data freshness
bq query --use_legacy_sql=false "
SELECT game_date, game_status, COUNT(*)
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date >= '2026-01-24'
GROUP BY 1,2 ORDER BY 1,2"

# Check for any 403 errors
gcloud logging read 'textPayload:"403"' --project=nba-props-platform --limit=10 --freshness=6h
```

---

**End of Handoff Document**
