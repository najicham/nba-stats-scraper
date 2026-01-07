# Session 174 Handoff: Challenge System Backend Implementation

**Date:** 2025-12-27
**Duration:** Extended session
**Status:** Major implementation complete, some items pending

---

## Executive Summary

This session implemented the backend data infrastructure for the Challenge System frontend. Two major workstreams were completed:

1. **Tonight's Players API** - Schema aligned with frontend requirements
2. **Live Box Scores Pipeline** - New infrastructure for persisting in-game stats to BigQuery

---

## What Was Accomplished

### 1. Tonight's Players Exporter (`/tonight/all-players.json`)

**File:** `data_processors/publishing/tonight_all_players_exporter.py`

| Change | Before | After |
|--------|--------|-------|
| `game_time` | `null` | `" 5:00 PM ET"` |
| Player name field | `player_full_name` | `name` |
| Team field | `team_abbr` | `team` |
| Props structure | Flat fields | `props: [{stat_type, line, over_odds, under_odds}]` |
| Prediction data | Flat fields | `prediction: {predicted, confidence, recommendation}` |
| `game_id` format | `20251226_BOS_IND` | `0022500432` (NBA native) |
| Odds data | Not included | Joined from `bettingpros_player_points_props` |

**Key code changes:**
- Lines 91-108: Added `game_time` with `FORMAT_TIMESTAMP`
- Lines 195-206: Added `best_odds` CTE for over/under odds
- Lines 341-385: Restructured player output with `name`, `team`, `props`, `prediction`

### 2. Live Box Scores Pipeline (NEW)

Created complete infrastructure for persisting live in-game stats:

| Component | File/Location | Status |
|-----------|---------------|--------|
| BigQuery Table | `nba_raw.bdl_live_boxscores` | ✅ Created |
| GCS Path Template | `scrapers/utils/gcs_path_builder.py:44` | ✅ Added |
| Phase 2 Processor | `data_processors/raw/balldontlie/bdl_live_boxscores_processor.py` | ✅ Created |
| Processor Registry | `data_processors/raw/main_processor_service.py:85` | ✅ Registered |
| Scraper Registry | `scrapers/registry.py:97-100` | ✅ Registered |
| Scheduler Jobs | `bdl-live-boxscores-evening`, `bdl-live-boxscores-late` | ✅ Created |
| Setup Script | `bin/scrapers/setup_live_boxscores_scheduler.sh` | ✅ Created |

**BigQuery Table Schema:**
```sql
-- Key fields for time-series analysis
poll_timestamp TIMESTAMP     -- When snapshot was taken
poll_id STRING               -- e.g., "20251227T213000Z"
game_id STRING               -- BDL game ID
game_date DATE               -- Partition key
period INT64                 -- 1-4 or OT
time_remaining STRING        -- "5:42" or "Final"
player_lookup STRING         -- Consistent with tonight endpoint
points INT64                 -- Current points at poll time
-- Plus full box score stats...

-- Partitioned by game_date, clustered by game_id, player_lookup, poll_timestamp
```

### 3. Deployments Completed

| Service | Revision | Status |
|---------|----------|--------|
| nba-phase1-scrapers | 00049-wm9 | ✅ Deployed |
| nba-phase2-raw-processors | 00041-27s | ✅ Deployed |
| phase6-export | 00002-juz | ✅ Deployed |

### 4. Scheduler Jobs Created

```bash
# Evening games (7 PM - 11:59 PM ET)
bdl-live-boxscores-evening: */3 19-23 * * * (America/New_York)

# Late night games (12 AM - 1:59 AM ET)
bdl-live-boxscores-late: */3 0-1 * * * (America/New_York)
```

---

## Current System State

### Working Correctly

1. **Tonight's Players API** - Returns proper schema with `name`, `team`, `game_time`, NBA `game_id`
2. **Live Scores Exporter** - Runs every 3 min during games, updates `/live/latest.json`
3. **Live Grading Exporter** - Runs every 3 min, updates `/live-grading/latest.json`
4. **Live Box Scores Scheduler** - Jobs created and enabled
5. **`player_lookup` consistency** - Verified identical across all endpoints (format: `lebronjames`)

### Known Issues

#### Issue 1: Tonight Shows 0 Players for Some Games
**Symptom:** Games DAL@SAC and DEN@ORL show `player_count: 0`
**Cause:** These games are missing from `nba_analytics.upcoming_player_game_context` table
**Impact:** Medium - other games have players
**To investigate:**
```sql
SELECT game_id, COUNT(*) as players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE()
GROUP BY game_id
```

#### Issue 2: Predictions Have NULL Lines
**Symptom:** `props` and `prediction` are `null` for all players
**Cause:** `current_points_line` is NULL in `nba_predictions.player_prop_predictions`
**Impact:** High - no betting lines shown
**To investigate:**
```sql
SELECT
    COUNTIF(current_points_line IS NOT NULL) as with_line,
    COUNTIF(current_points_line IS NULL) as without_line
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'ensemble_v1'
```
**This is a Phase 5 predictions issue, not an exporter issue.**

#### Issue 3: Live Boxscores Not Tested
**Symptom:** No data in `nba_raw.bdl_live_boxscores` table yet
**Cause:** No games in progress during implementation
**When to test:** During game window (7 PM - 1 AM ET)
**To verify:**
```bash
# Trigger manually
gcloud scheduler jobs run bdl-live-boxscores-evening --location=us-west2

# Check logs
gcloud logging read 'resource.labels.service_name="nba-phase1-scrapers" AND "bdl_live"' --limit=10 --freshness=10m

# Check BigQuery
bq query "SELECT COUNT(*) FROM nba_raw.bdl_live_boxscores WHERE game_date = CURRENT_DATE()"
```

---

## Files to Study

### Critical Files (Must Read)

1. **Tonight Exporter** - `data_processors/publishing/tonight_all_players_exporter.py`
   - Understand the BigQuery queries and output structure
   - Key methods: `_query_games()`, `_query_players()`, `_build_games_data()`

2. **Live Box Scores Processor** - `data_processors/raw/balldontlie/bdl_live_boxscores_processor.py`
   - New file created this session
   - Append-only strategy for time-series data

3. **Frontend Requirements** - `/home/naji/code/props-web/docs/06-projects/current/challenge-system/BACKEND-DATA-REQUIREMENTS.md`
   - Original requirements from frontend team

4. **Handoff Questions** - `/home/naji/code/props-web/docs/06-projects/current/challenge-system/BACKEND-HANDOFF.md`
   - Detailed questions from frontend team

### Reference Files

5. **Schema Alignment Doc** - `docs/08-projects/current/challenge-system-backend/SCHEMA-ALIGNMENT.md`
   - Analysis of all schema issues

6. **Handoff Responses** - `docs/08-projects/current/challenge-system-backend/HANDOFF-RESPONSES.md`
   - Answers to all frontend questions

7. **Live Boxscores Design** - `docs/08-projects/current/challenge-system-backend/LIVE-BOXSCORES-DESIGN.md`
   - Architecture and schema design for live pipeline

---

## Key Decisions Made

### Decision 1: `player_lookup` Format
**Choice:** Lowercase, no separators (e.g., `lebronjames`)
**Rationale:** This is what's already in BigQuery. Consistent across all data sources.
**Alternative considered:** Hyphenated (`lebron-james`) - rejected, would require migration.

### Decision 2: Live Boxscores as Append-Only
**Choice:** Each poll creates new rows (no updates)
**Rationale:** Enables time-series analysis ("when did player hit 20 points?")
**Trade-off:** More storage, but enables historical queries

### Decision 3: Keep Separate game_id Formats
**Choice:** Tonight uses NBA IDs (`0022500432`), Live uses BDL IDs (`18447237`)
**Rationale:** Each comes from different data source. Frontend matches by `player_lookup`, not `game_id`.
**Risk:** Low - `player_lookup` is the join key

### Decision 4: Props Array Structure
**Choice:** `props: [{stat_type: "points", line: 24.5, over_odds: -110, under_odds: -110}]`
**Rationale:** Matches frontend expectation, extensible for future stat types (rebounds, assists)

---

## Verification Commands

### Check Tonight's API
```bash
# Full structure
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | jq '{
  game_date,
  total_players,
  first_game: .games[0] | {game_id, game_time, home_team, away_team, player_count}
}'

# Check a player's schema
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | \
  jq '.games[] | select(.player_count > 0) | .players[0]'
```

### Check Live API
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/live/latest.json" | jq '{
  updated_at,
  game_date,
  games_in_progress,
  games_final
}'
```

### Check Live Grading API
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/live-grading/latest.json" | jq '{
  summary,
  first_prediction: .predictions[0]
}'
```

### Check Live Boxscores Pipeline
```bash
# Check scheduler jobs
gcloud scheduler jobs list --location=us-west2 | grep bdl-live

# Trigger manually (during game window)
gcloud scheduler jobs run bdl-live-boxscores-evening --location=us-west2

# Check scraper logs
gcloud logging read 'resource.labels.service_name="nba-phase1-scrapers" AND "bdl_live"' --limit=10 --freshness=30m

# Check BigQuery data
bq query --use_legacy_sql=false "
SELECT poll_timestamp, game_id, COUNT(*) as players
FROM nba_raw.bdl_live_boxscores
WHERE game_date = CURRENT_DATE()
GROUP BY poll_timestamp, game_id
ORDER BY poll_timestamp DESC
LIMIT 10
"
```

---

## Next Steps (Priority Order)

### High Priority

1. **Investigate NULL prediction lines**
   - Why is `current_points_line` NULL in `player_prop_predictions`?
   - This is blocking props display on frontend
   - Likely a Phase 5 issue

2. **Test live boxscores during game window**
   - Trigger scheduler manually during games
   - Verify data flows: Scraper → GCS → Phase 2 → BigQuery
   - Confirm `player_lookup` consistency with live endpoint

3. **Investigate missing games in upcoming_player_game_context**
   - Why are DAL@SAC and DEN@ORL missing?
   - Check Phase 3/4 processing for these games

### Medium Priority

4. **Update frontend mock data**
   - Location: `/home/naji/code/props-web/public/mock/v1/`
   - Match the new schema structure

5. **Add `position` field to tonight's export**
   - Frontend requests it in handoff doc
   - Source: `nba_reference.nba_players_registry.position`

6. **Improve `time_remaining` format**
   - Frontend expects "Q3 6:35"
   - Currently returns "5:42" without quarter prefix
   - Could add: `f"Q{period} {time_remaining}"`

### Low Priority

7. **Fix leading space in game_time**
   - Currently " 7:00 PM ET" (with leading space)
   - Change `%l` to `%I` or strip the result

8. **Add historical date support**
   - Verify `/live/{date}.json` works for past dates
   - Document behavior

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CHALLENGE SYSTEM DATA FLOW                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  TONIGHT'S PLAYERS (for challenge creation)                         │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                         │
│                                                                      │
│  BigQuery Tables:                                                    │
│    nba_analytics.upcoming_player_game_context                        │
│    nba_predictions.player_prop_predictions                           │
│    nba_raw.bettingpros_player_points_props (for odds)               │
│         ↓                                                            │
│    TonightAllPlayersExporter (Phase 6)                              │
│         ↓                                                            │
│    GCS: /tonight/all-players.json (5-min cache)                     │
│                                                                      │
│  LIVE SCORES (for challenge grading)                                │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                                │
│                                                                      │
│  BallDontLie API                                                     │
│         ↓                                                            │
│  ┌─────────────────────┐    ┌─────────────────────┐                 │
│  │ LiveScoresExporter  │    │ BdlLiveBoxScoresScraper               │
│  │ (direct API call)   │    │ (scheduled scraper)  │                │
│  └─────────────────────┘    └─────────────────────┘                 │
│         ↓                            ↓                               │
│  GCS: /live/latest.json     GCS: ball-dont-lie/live-boxscores/     │
│  (30-sec cache)                      ↓                               │
│                              BdlLiveBoxscoresProcessor (Phase 2)    │
│                                      ↓                               │
│                              BigQuery: nba_raw.bdl_live_boxscores   │
│                              (append-only, for historical analysis)  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Contact Points

- **Frontend Requirements:** Check `/home/naji/code/props-web/docs/06-projects/current/challenge-system/`
- **Backend Docs:** Check `/home/naji/code/nba-stats-scraper/docs/08-projects/current/challenge-system-backend/`

---

## Git Commits This Session

```
452464d fix: Live boxscores scraper sort error and scheduler endpoint
a0099aa docs: Add handoff responses for frontend team
0d08dda feat: Register live box scores scraper and add scheduler setup
7e1e222 feat: Add live box scores pipeline for real-time game tracking
6c349db feat: Align tonight's players API with frontend requirements
```

---

## Quick Reference

### Trigger Tonight Export
```bash
gcloud pubsub topics publish nba-phase6-export-trigger --message='{"export_types": ["tonight"], "target_date": "today"}'
```

### Trigger Live Export (manual)
```bash
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/live-export" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Deploy Services
```bash
# Phase 1 Scrapers
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Phase 2 Processors
./bin/raw/deploy/deploy_processors_simple.sh

# Phase 6 Publishing
./bin/deploy/deploy_phase6_function.sh
```
