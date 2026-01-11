# Schedule Processor Fix Handoff

**Date:** 2026-01-11
**Priority:** HIGH
**Estimated Effort:** 1-2 hours

---

## Problem Summary

The `nbac_schedule_processor` is using WRITE_APPEND instead of proper MERGE, causing:
1. **Duplicate rows** in `nba_raw.nbac_schedule` table
2. **Conflicting statuses** - old rows show "Scheduled", new rows show "Final"
3. **Downstream failures** - queries may pick wrong status, causing cascading issues

### Evidence

```sql
-- Shows duplicate rows with different statuses for same game
SELECT game_id, game_status, game_status_text, COUNT(*) as row_count
FROM nba_raw.nbac_schedule
WHERE game_date = '2026-01-10'
GROUP BY game_id, game_status, game_status_text
ORDER BY game_id, game_status
```

Results show games have BOTH status=1 (Scheduled) AND status=3 (Final) rows.

### Impact

- `nbac_team_boxscore` scraper fails for 60+ games (sees "Scheduled" status)
- Predictions not generated for games showing wrong status
- Coverage checks show incorrect data

---

## What Needs to Be Done

### Task 1: Create a View for Latest Schedule Status

Create `nba_raw.v_nbac_schedule_latest` that returns only the most recent status per game:

```sql
CREATE OR REPLACE VIEW `nba_raw.v_nbac_schedule_latest` AS
SELECT * EXCEPT(rn)
FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY game_id
      ORDER BY game_date_est DESC, game_status DESC
    ) as rn
  FROM `nba_raw.nbac_schedule`
)
WHERE rn = 1
```

### Task 2: Fix Schedule Processor to Use MERGE

**File:** `data_processors/raw/nbacom/nbac_schedule_processor.py`

The processor says MERGE_UPDATE (line 27, 47) but uses WRITE_APPEND (line 652). Fix options:

**Option A:** Implement proper MERGE with DML
```python
# Use MERGE statement instead of load job
MERGE `nba_raw.nbac_schedule` T
USING staging_table S
ON T.game_id = S.game_id AND T.game_date = S.game_date
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
```

**Option B:** Use WRITE_TRUNCATE with date partition
- Only replace data for the specific game_date partition
- Simpler but requires careful partition handling

### Task 3: Update Downstream Queries

After creating the view, update any queries that reference `nba_raw.nbac_schedule` to use `nba_raw.v_nbac_schedule_latest` where they need current status.

Check these files:
- `scrapers/nbacom/nbac_team_boxscore.py` - may check schedule status
- `orchestration/master_controller.py` - uses schedule for game-aware decisions
- `orchestration/workflow_executor.py` - may filter by game status

---

## Documentation to Read

Use agents to read and understand these directories:

### 1. Architecture & Orchestration
```
/home/naji/code/nba-stats-scraper/docs/01-architecture/
```
- Understand the 6-phase pipeline
- How processors work
- BigQuery write strategies

### 2. Current Projects
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/pipeline-reliability-improvements/
```
- Recent fixes and patterns used
- Known issues being addressed

### 3. Operations
```
/home/naji/code/nba-stats-scraper/docs/02-operations/
```
- `daily-validation-checklist.md` - has correct table names and commands
- Update this doc if you change anything

### 4. Handoff Docs
```
/home/naji/code/nba-stats-scraper/docs/09-handoff/
```
- `2026-01-11-SESSION-8-HANDOFF.md` - tonight's session summary
- Keep handoff docs updated with your changes

---

## Files to Study

Use the Explore agent to understand these files:

### Schedule Processor
```bash
# Main file to fix
/home/naji/code/nba-stats-scraper/data_processors/raw/nbacom/nbac_schedule_processor.py

# Look for:
# - Line 27: Says MERGE_UPDATE
# - Line 47: Sets processing_strategy
# - Line 600: Checks processing_strategy
# - Line 652: Uses WRITE_APPEND (the bug!)
```

### Schedule Scraper
```bash
# Understand what data is scraped
/home/naji/code/nba-stats-scraper/scrapers/nbacom/nbac_schedule_api.py
```

### Other Processors Using MERGE
```bash
# Look at these for examples of proper MERGE implementation
/home/naji/code/nba-stats-scraper/data_processors/analytics/upcoming_player_game_context/
/home/naji/code/nba-stats-scraper/data_processors/analytics/player_game_summary/
```

### Orchestration (uses schedule)
```bash
/home/naji/code/nba-stats-scraper/orchestration/master_controller.py
/home/naji/code/nba-stats-scraper/orchestration/workflow_executor.py
```

---

## Validation Commands

After making changes, verify with:

```bash
# Check schedule status breakdown
bq query --use_legacy_sql=false "
SELECT game_date, game_status, game_status_text, COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
GROUP BY game_date, game_status, game_status_text
ORDER BY game_date DESC, game_status"

# Compare to NBA.com live
curl -s 'https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json' | \
  jq '[.scoreboard.games[] | {id: .gameId, status: .gameStatusText}]'

# Test the view (after creating it)
bq query --use_legacy_sql=false "
SELECT game_id, game_status_text
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date = CURRENT_DATE()
ORDER BY game_id"
```

---

## Agent Commands to Run

Start by having agents explore these areas:

```
1. "Read all files in docs/01-architecture/ and summarize the pipeline architecture"

2. "Find all processors that use MERGE_UPDATE strategy and show me how they implement it"

3. "Read the schedule processor at data_processors/raw/nbacom/nbac_schedule_processor.py and identify where WRITE_APPEND is used instead of MERGE"

4. "Find all files that query nba_raw.nbac_schedule and list them"

5. "Read docs/08-projects/current/pipeline-reliability-improvements/ for context on recent fixes"
```

---

## Success Criteria

1. ✅ View `nba_raw.v_nbac_schedule_latest` exists and returns 1 row per game
2. ✅ Schedule processor uses proper MERGE (no duplicate rows on next run)
3. ✅ Documentation updated in `docs/02-operations/daily-validation-checklist.md`
4. ✅ Handoff doc created summarizing changes

---

## Notes

- The schedule table is partitioned by `game_date`
- Hash fields include: `game_id, game_date, game_date_est, home_team_tricode, away_team_tricode, game_status`
- Schedule scraper runs during `morning_operations` and `schedule_dependency` workflows
- Currently no post-game schedule refresh (separate issue to address)

---

**End of Handoff**
