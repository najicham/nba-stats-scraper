# Session 162: Christmas Day Schedule Fix & Early Game Workflows

**Date:** December 23-24, 2025
**Status:** Complete
**Focus:** Fix Christmas Day game times, add early game collection workflows

---

## Executive Summary

Fixed multiple issues preventing correct game times from appearing in the schedule, and added automated workflows for early game days (Christmas, MLK Day).

### Key Accomplishments
1. Added `game_aware_early` decision type for same-day early game collection
2. Fixed NBA API timezone handling (Z suffix = Eastern, not UTC)
3. Fixed schedule processor method signature bugs
4. Christmas Day schedule now shows correct game times

---

## Commits

| Commit Hash | Description |
|-------------|-------------|
| `2d637ca` | feat: Add early game collection workflows for Christmas Day |
| `4851081` | fix: Use gameDateTimeEst for accurate game times in schedule |
| `cf4a200` | fix: Handle NBA API timezone quirk (Z suffix = Eastern, not UTC) |
| `d81e11c` | fix: Schedule processor method signatures and return values |

---

## Issues Found & Fixed

### Issue 1: Wrong Game Times in Schedule

**Symptom:** All Christmas Day games showed 7:00 PM ET instead of actual times (noon, 2:30 PM, etc.)

**Root Cause Chain:**
1. Processor used `gameDateEst` (date only, midnight) instead of `gameDateTimeEst` (date + time)
2. NBA API returns `gameDateTimeEst: 2025-12-25T12:00:00Z` with misleading 'Z' suffix
3. Code treated 'Z' as UTC, but it's actually Eastern time (confirmed by `gameStatusText: "12:00 pm ET"`)

**Fix:**
- Use `gameDateTimeEst` field
- Parse with pytz as Eastern time, not UTC

### Issue 2: gcs_path NULL in Pub/Sub

**Symptom:** Phase 2 received scraper completion events but `gcs_path` was always NULL

**Root Cause:** Scrapers service hadn't been deployed since July 2025. The `gcs_output_path` capture code was added later but never deployed.

**Fix:** Redeployed scrapers service (`nba-phase1-scrapers`)

### Issue 3: Schedule Processor Method Mismatches

**Symptom:** `transform_data() takes 1 positional argument but 3 were given`

**Root Causes:**
1. `transform_data()` defined with no args, but called with `(raw_data, file_path)`
2. No return statement - function declared `-> list` but returned nothing
3. Called `load_data(rows)` (load FROM GCS) instead of `save_data()` (save TO BigQuery)

**Fix:** Corrected method signatures and added return statement

---

## Architecture: Early Game Workflows

### New Decision Type: `game_aware_early`

For days with early games (before 7 PM ET), the new workflows:
1. Detect games starting before configurable cutoff (default 7 PM)
2. Wait 3 hours after game start before collection
3. Check BigQuery for already-collected games
4. Skip automatically on regular game days

### New Workflows

| Workflow | Time (ET) | Purpose |
|----------|-----------|---------|
| `early_game_window_1` | 3 PM | First collection for noon games |
| `early_game_window_2` | 6 PM | Second collection + PBP |
| `early_game_window_3` | 9 PM | Final collection + all enhanced data |

### How It Works

```
Game starts at noon ET
    |
    +-- Wait 3 hours
    |
    v
3 PM: early_game_window_1 runs
    |
    +-- Check BigQuery: game collected?
    |
    +-- No: Run scrapers (bdl_box_scores, nbac_team_boxscore, nbac_player_boxscore)
    |
    v
6 PM: early_game_window_2 runs (adds bigdataball_pbp)
    |
    v
9 PM: early_game_window_3 runs (adds nbac_play_by_play, nbac_gamebook_pdf)
```

---

## Christmas Day Schedule (Verified)

| Game Time | Matchup |
|-----------|---------|
| 12:00 PM ET | CLE @ NYK |
| 2:30 PM ET | SAS @ OKC |
| 5:00 PM ET | DAL @ GSW |
| 8:00 PM ET | HOU @ LAL |
| 10:30 PM ET | MIN @ DEN |

---

## Files Modified

| File Path | Change |
|-----------|--------|
| `orchestration/master_controller.py` | Added `game_aware_early` decision type + evaluator |
| `config/workflows.yaml` | Added 3 early game workflows |
| `data_processors/raw/nbacom/nbac_schedule_processor.py` | Fixed timezone, method signatures, return values |

---

## Lessons Learned & Process Improvements

### What Went Wrong

1. **Stale Deployments**: Scrapers service was 5 months behind. No visibility into what code version was running.

2. **Silent Failures**: `gcs_path = NULL` didn't trigger any alerts. Scraper reported "success" even though Phase 2 couldn't process.

3. **Log Visibility**: GCS exporter logs not appearing in Cloud Logging (possible log level filtering).

4. **Inconsistent Code Patterns**: Schedule processor mixed different coding styles - some methods used `self.raw_data`, others took parameters.

### Recommended Improvements

#### 1. Deployment Version Tracking
```bash
# Add commit SHA to Cloud Run metadata
gcloud run deploy $SERVICE --set-labels commit-sha=$(git rev-parse --short HEAD)
```

#### 2. Integration Health Checks
Add pipeline integration test that:
- Writes a test file to GCS
- Triggers Phase 2 via Pub/Sub
- Verifies data appears in BigQuery
- Run weekly or after deployments

#### 3. Monitoring Alerts
```sql
-- Alert when successful scrapers have NULL gcs_path
SELECT scraper_name, COUNT(*) as count
FROM nba_orchestration.scraper_execution_log
WHERE status = 'success' AND gcs_path IS NULL
  AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
HAVING count > 3
```

#### 4. Code Consistency Refactor
The schedule processor should be refactored to:
- Use consistent base class patterns
- Follow the same method signatures as other processors
- Have integration tests that catch signature mismatches

---

## Verification Commands

### Check Christmas Day Schedule
```bash
bq query --use_legacy_sql=false "
SELECT FORMAT_TIMESTAMP('%H:%M ET', game_date_est, 'America/New_York') as time,
       away_team_tricode || ' @ ' || home_team_tricode as matchup
FROM nba_raw.nbac_schedule
WHERE game_date = '2025-12-25'
ORDER BY game_date_est"
```

### Test Early Game Workflow Evaluation
```bash
PYTHONPATH=. .venv/bin/python -c "
from orchestration.master_controller import MasterWorkflowController
from datetime import datetime
import pytz

controller = MasterWorkflowController()
now = datetime.now(pytz.timezone('America/New_York'))
decisions = controller.evaluate_all_workflows(now)

for d in decisions:
    if 'early_game' in d.workflow_name:
        print(f'{d.workflow_name}: {d.action.value} - {d.reason}')
"
```

### Check Service Deployment Version
```bash
gcloud run services describe nba-phase1-scrapers --region us-west2 \
  --format="value(status.latestReadyRevision)"
```

---

## Todo for Next Session

### High Priority
1. **Verify Dec 23 data flow** - Check after games finish that data appears in all phases
2. **Monitor Christmas Day** - First noon game at 12:00 PM ET, first collection at 3:00 PM ET

### Medium Priority
3. **Add deployment version labels** - Track what commit is running on each service
4. **Add gcs_path NULL monitoring** - Alert when successful scrapers don't publish paths

### Low Priority
5. **Refactor schedule processor** - Make it consistent with other processors
6. **Clean up nba-phase3-trigger topic** - Still unused from Session 161

---

**Session Duration:** ~3 hours
**Pipeline Status:** Fully operational with correct Christmas Day schedule
