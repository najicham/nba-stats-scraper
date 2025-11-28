# Handoff: Source Coverage System Design & Team Boxscore Backfill

**Date:** 2025-11-26
**Session Duration:** ~4 hours
**Status:** Design complete, implementation pending

---

## Executive Summary

This session accomplished two major things:

1. **Completed team boxscore backfill** - 5,293 of 5,299 games (99.9%)
2. **Designed source coverage system** - Comprehensive system for handling missing external data

The source coverage design was done via a separate AI chat and resulted in 5 detailed documents ready for implementation.

---

## Part 1: Team Boxscore Backfill

### What Was Done

| Metric | Value |
|--------|-------|
| Total games in CSV | 5,299 |
| Successfully scraped | 5,293 (99.9%) |
| Missing (no NBA.com data) | 6 Play-In games |
| Duration | ~6.5 hours overnight |
| GCS folders created | 850 dates |

### Script Enhanced

**File:** `backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py`

**Changes made:**
- Added `--workers` flag for concurrent execution (tested with 12 workers)
- Added `--timeout` flag (default 300s)
- Added automatic retry with resume logic (skips already-scraped games)
- Added `failed_games_*.json` output for tracking failures
- Changed default service URL to correct endpoint: `https://nba-phase1-scrapers-756957797294.us-west2.run.app`

**Important:** The handoff doc at `docs/09-handoff/2025-11-25-scraper-backfill-plan.md` had the WRONG service URL. The correct URL is `nba-phase1-scrapers-756957797294.us-west2.run.app` (not `nba-scrapers-f7p3g7f6ya-wl.a.run.app`).

### 6 Missing Play-In Games

These games return empty data from NBA.com's `boxscoretraditionalv2` API:

| Game ID | Date | Type |
|---------|------|------|
| 0052400101 | 2025-04-15 | Play-In Tournament |
| 0052400121 | 2025-04-15 | Play-In Tournament |
| 0052400111 | 2025-04-16 | Play-In Tournament |
| 0052400131 | 2025-04-16 | Play-In Tournament |
| 0052400201 | 2025-04-18 | Play-In Tournament |
| 0052400211 | 2025-04-18 | Play-In Tournament |

**Root cause:** NBA.com API doesn't have boxscore data for these specific games. The website may use a different endpoint. Older Play-In games (2022-2024) scraped successfully.

**To resolve:** Need to scrape from ESPN or BDL as alternative sources, or find a different NBA.com endpoint.

---

## Part 2: Streaming Buffer Issue

### The Problem

During the backfill, ~101 email alerts were received like:

```
Processor: NbacTeamBoxscoreProcessor
Error: UPDATE or DELETE statement over table would affect rows in the streaming buffer
```

### Root Cause

Processors use `insert_rows_json()` (streaming inserts) instead of `load_table_from_json()` (batch loading). BigQuery's streaming buffer holds recent inserts for ~90 minutes and doesn't allow UPDATE/DELETE on those rows.

### Project Created

**Location:** `docs/08-projects/current/streaming-buffer-migration/`

**Files:**
- `overview.md` - Problem description and solution
- `checklist.md` - List of ~20 processors to migrate
- `changelog.md` - Progress tracking

**Status:** Not Started

**Reference:** `docs/05-development/guides/bigquery-best-practices.md` explains the pattern to use.

---

## Part 3: Source Coverage System Design

### Background

The missing Play-In games raised a broader question: How should the system handle missing data from external sources?

### Design Process

1. Created prompt documents in `docs/10-prompts/`:
   - `data-completeness-strategy.md` - The problem statement
   - `data-pipeline-overview.md` - Condensed system reference (317 lines)

2. User took these to a separate AI chat session
3. That session produced 5 comprehensive design documents

### Design Documents - SAVED

**Location:** `docs/architecture/source-coverage/`

| Document | Content |
|----------|---------|
| `00-index.md` | Quick navigation, quick start guide |
| `01-core-design.md` | Architecture, philosophy, decisions, roadmap |
| `02-schema-reference.md` | Complete DDL, table schemas, migrations |
| `03-implementation-guide.md` | Python code for mixins, processors |
| `04-testing-operations.md` | Tests, runbooks, troubleshooting |
| `05-review-enhancements.md` | Additional code from Opus review |

**Key features incorporated:**
- Season-aware quality thresholds (prevents false bronzes early season)
- Adaptation notes for existing infrastructure (`notify_error`, `quality_issues`, etc.)
- BigQuery best practices (no indexes, use clustering)
- Prerequisite callout for streaming buffer migration

### Key Design Decisions

| Decision | Choice |
|----------|--------|
| Architecture | Event-based log + quality columns on tables |
| Schema | Single `source_coverage_log` table + view for game-level |
| Integration | Mixin pattern (`QualityMixin`, `FallbackSourceMixin`) |
| Audit | Daily batch job to catch silent failures |
| Alerts | Critical = immediate Slack; Others = daily digest |
| Cost | ~$5-7/month additional |

---

## Part 4: Files Created/Modified This Session

### New Files

| File | Purpose |
|------|---------|
| `docs/08-projects/current/streaming-buffer-migration/overview.md` | Project overview |
| `docs/08-projects/current/streaming-buffer-migration/checklist.md` | Migration checklist |
| `docs/08-projects/current/streaming-buffer-migration/changelog.md` | Progress log |
| `docs/10-prompts/README.md` | Directory for design prompts |
| `docs/10-prompts/data-completeness-strategy.md` | Source coverage design prompt |
| `docs/10-prompts/data-pipeline-overview.md` | Condensed pipeline reference |
| `backfill_jobs/scrapers/nbac_team_boxscore/failed_games_*.json` | Failure logs from backfill |

### Modified Files

| File | Changes |
|------|---------|
| `backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py` | Added concurrent workers, timeout, better logging |
| `docs/08-projects/README.md` | Added streaming buffer migration project |

### Log Files (Can Delete)

```
team_boxscore_backfill.log
team_boxscore_retry.log
team_boxscore_final_retry.log
```

---

## Part 5: Immediate Next Steps

### Option A: Save Source Coverage Docs (15 min)

1. Create `docs/architecture/source-coverage/` directory
2. Save the 5 design documents with numbered prefixes
3. Add adaptation notes section to each

### Option B: Start Source Coverage Implementation (Week 1)

1. Create `source_coverage_log` BigQuery table
2. Add quality columns to `player_game_summary`
3. Implement basic `QualityMixin`
4. Test on 10 games

### Option C: Fix Streaming Buffer Issue First

1. Review `docs/05-development/guides/bigquery-best-practices.md`
2. Update base classes to use `load_table_from_json()`
3. Test and deploy
4. Then implement source coverage (which uses the same pattern)

### Option D: Resolve 6 Play-In Games

1. Try scraping from ESPN or BDL
2. Or find alternative NBA.com endpoint
3. Mark as known gaps if no data available

---

## Part 6: Key Commands

### Check Team Boxscore Coverage

```bash
# Count GCS folders
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/ | wc -l
# Expected: 850

# Check specific Play-In dates
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/20250415/
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/20250416/
```

### Run Phase 2 Processor Manually

After streaming buffer clears (~90 min after backfill), you can run:

```bash
# Process team boxscore data to BigQuery
python -m data_processors.raw.nbacom.nbac_team_boxscore_processor
```

### Check for Streaming Buffer Issues

```sql
-- In BigQuery
SELECT COUNT(*)
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR);
```

---

## Part 7: Architecture Context

### Existing Infrastructure

| Component | Location | Notes |
|-----------|----------|-------|
| Notification system | `shared/utils/notification_system.py` | Has `notify_error`, `notify_warning`, `notify_info` |
| Analytics base class | `data_processors/analytics/analytics_base.py` | Has `quality_issues`, `source_metadata` |
| Raw processor base | `data_processors/raw/processor_base.py` | Has `bq_client`, `run_id` |
| BigQuery best practices | `docs/05-development/guides/bigquery-best-practices.md` | Explains batch vs streaming |

### Two Scraper Services

| Service | URL | Has nbac_team_boxscore? |
|---------|-----|-------------------------|
| nba-phase1-scrapers | https://nba-phase1-scrapers-756957797294.us-west2.run.app | YES |
| nba-scrapers (old) | https://nba-scrapers-f7p3g7f6ya-wl.a.run.app | NO |

Always use `nba-phase1-scrapers` for team boxscore backfills.

---

## Part 8: Questions for Next Session

1. **Should we save the source coverage docs first or start implementing?**

2. **Should streaming buffer migration be done before source coverage?** (They're related - source coverage will also need batch loading)

3. **What to do about the 6 Play-In games?** Accept as known gap, or try alternative sources?

4. **Run Phase 2 processor now?** Streaming buffer should have cleared by now (90+ min since backfill completed)

---

## Summary

| Item | Status |
|------|--------|
| Team boxscore backfill | ✅ 99.9% complete (6 Play-In games documented) |
| Data gap documentation | ✅ Created `known-data-gaps.md` + `data-coverage-tracker.md` |
| Streaming buffer migration | Project created, not started |
| Source coverage design | Complete, docs SAVED to `docs/architecture/source-coverage/` |
| Source coverage implementation | Not started |
| Phase 2 processing | Pending (streaming buffer issue) |

**Updated priority (2025-11-26 evening):**
1. ~~Save source coverage docs~~ DONE - `docs/architecture/source-coverage/`
2. ~~Document 6 Play-In game gap~~ DONE - `docs/09-handoff/known-data-gaps.md`
3. ✅ **NEXT:** Complete player boxscore backfill (~14 min)
4. ✅ **NEXT:** Complete BDL standings backfill (~6 sec)
5. Fix streaming buffer issue (enables Phase 2 processing AND source coverage)
6. Implement source coverage system
7. 6 Play-In games will be auto-detected by source coverage audit job
