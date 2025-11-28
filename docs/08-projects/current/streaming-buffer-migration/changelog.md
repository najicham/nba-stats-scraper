# Streaming Buffer Migration Changelog

---

## 2025-11-27 - All High Priority Processors Fixed

**Session:** Fixed all P0, P1, and Phase 5 processors (15 total)

**P0 Critical Processors (2):**
- [x] `nbac_player_boxscore_processor.py` - Changed `insert_rows_json()` to `load_table_from_json()`
- [x] `nbac_team_boxscore_processor.py` - Changed `insert_rows_json()` to `load_table_from_json()`

**P1 High Priority Processors (11):**
- [x] `bdl_boxscores_processor.py`
- [x] `espn_boxscore_processor.py`
- [x] `nbac_play_by_play_processor.py`
- [x] `nbac_gamebook_processor.py`
- [x] `bigdataball_pbp_processor.py`
- [x] `nbac_schedule_processor.py`
- [x] `bdl_standings_processor.py`
- [x] `bdl_active_players_processor.py`
- [x] `br_roster_processor.py`
- [x] `upcoming_player_game_context_processor.py`
- [x] `upcoming_team_game_context_processor.py`

**Phase 5 Predictions (2):**
- [x] `predictions/worker/worker.py` - write_predictions_to_bigquery()
- [x] `predictions/worker/execution_logger.py` - _log_execution()

**Phase 3 & 4 Verification:**
- [x] All analytics processors use `AnalyticsProcessorBase.save_analytics()` → already uses batch loading
- [x] All precompute processors use `PrecomputeProcessorBase.save_precompute()` → already uses batch loading
- Base classes use `load_table_from_file()` for main data (lines 1098 and 726 respectively)

**Additional fix:**
- Fixed `HASH_FIELDS` in player boxscore processor (`rebounds` → `total_rebounds`)

**Testing:**
- [x] Local test passed - processed 47 rows using batch load, no DML errors
- [ ] Deployed to Cloud Run (pending)
- [ ] Retry failed backfill (303 dates)

**Remaining (Low Priority - Logging only):**
- `analytics_base.py` - issue/run logging (single records)
- `precompute_base.py` - issue/run logging (single records)
- `nbac_gamebook_processor.py` - resolution logging (lines 276, 495)
- APPEND_ALWAYS processors (injuries, player_movement) - no DELETE conflict

---

## 2025-11-26 Evening - CRITICAL FAILURE: Player Boxscore Backfill

**Session:** Player boxscore backfill with 12 workers

**What happened:**
- Ran player boxscore backfill: 853 dates, 12 workers, 52.5 minutes
- **Result: 35.5% FAILURE RATE**
  - ✅ 543 dates succeeded (63.7%)
  - ❌ 303 dates failed (35.5%)
  - ⏭️ 7 dates skipped
- **Hundreds of error emails** received

**Error message:**
```
BigQuery load errors: ['400 Resources exceeded during query execution:
Too many DML statements outstanding against table
nba-props-platform:nba_raw.nbac_player_boxscores, limit is 20.']
```

**Root cause:**
- `NbacPlayerBoxscoreProcessor` uses `insert_rows_json()` (streaming inserts)
- 12 backfill workers + auto-processor = >20 concurrent DML operations
- BigQuery hard limit: 20 DML statements per table
- Streaming inserts count as DML, batch loading does not

**Impact:**
- 🔴 **BLOCKS Phase 3+ analytics** (needs complete player boxscore data)
- 🔴 Cannot proceed with remaining backfills
- 🔴 310 dates need reprocessing (231 from GCS + 79 new scrapes needed)
- 🔴 Hundreds of error emails generated

**Current data state:**
- GCS (Phase 1): 622/853 dates have raw data files (72.9%)
- BigQuery (Phase 2): 543/853 dates loaded (63.7%)
- Missing: 310 dates total
  - 231 dates never made it to GCS (HTTP 500 / timeouts from NBA.com)
  - 79 dates in GCS but failed BigQuery loading

**Artifacts:**
- Failed dates: `backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_20251126_162719.json`
- Backfill log: `player_boxscore_backfill_v2.log`
- Backfill script (fixed): `nbac_player_boxscore_scraper_backfill_v2.py`

**Decision:**
- **IMMEDIATE:** Fix `nbac_player_boxscore_processor.py` (P0 - CRITICAL)
- **THEN:** Retry 303 failed dates
- **THEN:** Fix base classes and other processors
- **DEFER:** Additional backfills until streaming buffer is fixed

---

## 2025-11-26 Morning - Project Created

**Session:** Team boxscore backfill revealed streaming buffer issue

**What happened:**
- During team boxscore backfill (~5,299 games), received 101+ email alerts
- Error: `UPDATE or DELETE statement over table would affect rows in the streaming buffer`
- Root cause: `nbac_team_boxscore_processor.py` uses `insert_rows_json()` (streaming)

**Analysis:**
- Found ~20 processors using streaming inserts
- Only ~11 processors using batch loading (correct pattern)
- Reference doc exists: `docs/05-development/guides/bigquery-best-practices.md`

**Created:**
- `overview.md` - Problem description and solution
- `checklist.md` - All processors to migrate with priorities
- `changelog.md` - This file

**Next steps (UPDATED BASED ON EVENING FAILURE):**
- [x] Attempted player boxscore backfill → **FAILED**
- [ ] Fix `nbac_player_boxscore_processor.py` (NOW P0 - CRITICAL)
- [ ] Retry 303 failed dates
- [ ] Fix base classes
- [ ] Fix remaining processors

**Related project:** Source Coverage System (design complete, implementation pending)
- Source Coverage also needs batch loading pattern
- Recommend fixing streaming buffer first as prerequisite
- See: `docs/09-handoff/2025-11-26-source-coverage-design.md`

---

## Template for Future Entries

```
## YYYY-MM-DD - [Brief Description]

**Processors migrated:**
- [ ] processor_name.py

**Testing:**
- [ ] Local test passed
- [ ] Deployed to Cloud Run
- [ ] Monitored for 24 hours - no streaming buffer errors

**Notes:**
- Any issues encountered
```
