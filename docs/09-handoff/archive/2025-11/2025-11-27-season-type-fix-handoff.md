# Player Boxscore Season Type Fix & Backfill Handoff

**Date:** 2025-11-27
**Session:** Season Type Detection Fix + Player Boxscore Backfill
**Status:** ✅ Phase 2 Complete, ⏸️ Phase 3 Needs Planning

---

## Summary

Fixed the player boxscore scraper to correctly detect season types (Regular Season, Playoffs, PlayIn, All Star) using the `NBAScheduleService`. Successfully backfilled all 845 useful game dates. Phase 3 analytics backfill was attempted but needs more careful planning.

---

## What Was Accomplished

### 1. Schedule Service Enhancement ✅

Added `get_season_type_for_date()` method to detect NBA.com API season type from schedule data.

**Files Modified:**
- `shared/utils/schedule/database_reader.py` - Added `get_nba_api_season_type()`
- `shared/utils/schedule/service.py` - Added `get_season_type_for_date()`

**Mapping:**
| Schedule Flag | NBA.com API `season_type` |
|--------------|---------------------------|
| `is_all_star = true` | `"All Star"` |
| `is_playoffs = true` AND `playoff_round = 'play_in'` | `"PlayIn"` |
| `is_playoffs = true` | `"Playoffs"` |
| `is_regular_season = true` | `"Regular Season"` |
| Otherwise | `"Pre Season"` |

### 2. Player Boxscore Scraper Fix ✅

Updated scraper to use schedule service for season type detection and skip All-Star games.

**File:** `scrapers/nbacom/nbac_player_boxscore.py`

**Changes:**
- Added `NBAScheduleService` import
- Added `_get_schedule_service()` class method (lazy initialization)
- Modified `_detect_season_type()` to query schedule database
- Added All-Star skip logic (raises `DownloadDataException`)

**Key Code:**
```python
# Skip All-Star games - they use non-NBA teams
if self.opts.get("season_type") == "All Star":
    raise DownloadDataException(
        f"Skipping All-Star game on {raw_date} - exhibition games not useful for predictions"
    )
```

### 3. Player Boxscore Processor Fix ✅

Updated processor to check game type and validate team codes appropriately.

**File:** `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`

**Changes:**
- Added `NBAScheduleService` import
- Added `VALID_NBA_TEAMS` constant (30 NBA team codes)
- Added `_extract_game_date()` helper method
- Added `_validate_team_code()` method with game-type-aware alerting
- Added All-Star game skip at start of `transform_data()`

**Key Logic:**
- If All-Star game: Skip silently (no alert)
- If non-All-Star with invalid team: Alert (real data quality issue)

### 4. Player Boxscore Backfill Complete ✅

**Final Coverage:**
- GCS: 858 date folders
- BigQuery: 845 dates
- All-Star Skipped: 8 dates (intentional)
- **Coverage: 100%**

**Dates Successfully Backfilled:**
- Play-In Tournament (10 dates): All season types correctly detected as "PlayIn"
- Playoffs (5 dates): Correctly detected as "Playoffs"
- Timeout retries (12 dates): All succeeded on retry

---

## What Was NOT Completed

### Phase 3 Analytics Backfill ⏸️

**Attempted:** Ran `player_game_summary_analytics_backfill.py` for full date range

**Problem:** The analytics processor has strict dependency checks:
- Requires: `nbac_gamebook_player_stats`, `bdl_player_boxscores`
- Each date without dependencies triggers an error alert
- Started from 2021-10-01 (before NBA season started 2021-10-19)
- Result: Flooded Slack/email with ~20+ error alerts before being killed

**Current State of Analytics Tables:**
```
player_game_summary: 647 rows (2024-11-22 to 2024-11-25 only)
```

**Data Availability for Dependencies:**
```
bdl_player_boxscores: 2021-10-19 to 2025-06-22 (169,725 records)
nbac_gamebook_player_stats: Exists, date range TBD
```

---

## Next Steps for New Chat

### 1. Phase 3 Analytics Backfill (Careful Approach)

**Before running:**
1. Determine valid date range with all dependencies present
2. Disable email/Slack alerts during backfill OR modify processor to not alert on historical data
3. Run for date ranges that have complete dependency data

**Suggested approach:**
```bash
# First, check what date range has both dependencies
bq query --use_legacy_sql=false "
SELECT
  DATE(game_date) as game_date,
  COUNT(*) as gamebook_rows
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= '2021-10-01'
GROUP BY 1
ORDER BY 1
LIMIT 10
"

# Then run backfill for valid range only
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22
```

**Important:** The processor has `ENABLE_HISTORICAL_DATE_CHECK = True` which skips dates >90 days old. For backfill, temporarily set to `False` in:
`data_processors/analytics/player_game_summary/player_game_summary_processor.py` line 101

### 2. Schedule Service Audit (Separate Task)

Created prompt doc for auditing all scrapers/processors for schedule service usage:
`docs/10-prompts/schedule-service-audit.md`

This covers checking all NBA.com scrapers and processors for proper:
- Season type handling
- All-Star game skipping
- Team code validation

### 3. Other Backfills to Consider

Check coverage tracker for other data sources:
`docs/09-handoff/data-coverage-tracker.md`

---

## Files Modified This Session

### New Files:
- `docs/10-prompts/schedule-service-audit.md` - Audit prompt for schedule service usage

### Modified Files:
- `shared/utils/schedule/database_reader.py` - Added `get_nba_api_season_type()`
- `shared/utils/schedule/service.py` - Added `get_season_type_for_date()`
- `scrapers/nbacom/nbac_player_boxscore.py` - Schedule service + All-Star skip
- `data_processors/raw/nbacom/nbac_player_boxscore_processor.py` - Game type check + team validation
- `docs/09-handoff/data-coverage-tracker.md` - Updated coverage status

---

## Deployments Made

### Scrapers (nba-phase1-scrapers)
- Revision: `00015-bgv`
- Changes: Season type detection, All-Star skip

### Processors (nba-phase2-raw-processors)
- Changes: Game type check, team validation
- Health check: Passed

---

## Key Learnings

### 1. All-Star Games Are Special
- Use non-NBA team codes (DRT = Team Durant, LBN = Team LeBron)
- Game IDs start with `003` (vs `002` for regular season)
- SEASON_ID prefix is `3` (vs `2` for regular season)
- Not useful for player prop predictions (exhibition)

### 2. Play-In Tournament Needs "PlayIn" Season Type
- NBA.com API requires exact `season_type=PlayIn`
- Dates: Usually April 11-19
- Schedule has `playoff_round = 'play_in'`

### 3. Analytics Backfill Is Complex
- Multiple dependency checks per date
- Alerts on every failure (noisy for historical backfills)
- Need to disable alerts or use correct date ranges

### 4. Pub/Sub Retries Can Cause Email Floods
- Deleted files still have queued Pub/Sub messages
- Each retry of failed message sends another alert
- Consider dead letter queue or message expiry

---

## Commands Reference

### Check Player Boxscore Coverage
```bash
# GCS
gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/ | wc -l

# BigQuery
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT DATE(game_date)) as dates
FROM nba_raw.nbac_player_boxscores
WHERE game_date >= '2021-10-01'
"
```

### Test Season Type Detection
```python
from shared.utils.schedule import NBAScheduleService
schedule = NBAScheduleService()
print(schedule.get_season_type_for_date('2024-02-18'))  # "All Star"
print(schedule.get_season_type_for_date('2024-04-16'))  # "PlayIn"
print(schedule.get_season_type_for_date('2024-04-20'))  # "Playoffs"
```

### Run Scraper Test
```bash
curl -X POST "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_player_boxscore", "gamedate": "20240416", "export_groups": "test"}'
```

---

## Contact/Context

- Previous handoff: `docs/09-handoff/2025-11-27-playoff-scraper-fix-handoff.md`
- Coverage tracker: `docs/09-handoff/data-coverage-tracker.md`
- Schedule service audit: `docs/10-prompts/schedule-service-audit.md`
