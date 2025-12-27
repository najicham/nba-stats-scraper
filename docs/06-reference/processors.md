# NBA Processors Reference

**Created:** 2025-11-21 17:12:03 PST
**Last Updated:** 2025-12-27

Quick reference for NBA data processors transforming GCS data to BigQuery.

**Total Active:** 26 processors

## Processing Strategies

- **APPEND_ALWAYS:** Keep all historical versions (odds, injury reports)
- **MERGE_UPDATE:** Update existing, add new (rosters, game data)
- **INSERT_NEW_ONLY:** Insert only new records (transactions)
- **OVERWRITE:** Replace all data (rare)

## Odds API (2 processors)

### Player Props ⭐

**Status:** ⚠️ Historical ✅ / Current 📋 Update Needed

```
Table: nba_raw.odds_api_player_points_props
Partition: game_date
Strategy: APPEND_ALWAYS
GCS: /odds-api/player-props-history/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
```

**Coverage:** May 2023 - June 2025 (53,871 records, 2,429 games)
**Processor:** OddsApiPropsProcessor
**Deployment:** odds-api-props-backfill (us-west2)

### Game Lines ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.odds_api_game_lines
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
GCS: /odds-api/game-lines-history/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
```

**Coverage:** Oct 2021 - June 2025 (39,256 records, 4,930 games)
**Markets:** spreads, totals
**Processor:** OddsGameLinesProcessor
**Deployment:** odds-game-lines-processor-backfill (us-west2)

## NBA.com (9 processors)

### Schedule ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.nbac_schedule
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
GCS: /nba-com/schedule/{season}/{timestamp}.json
```

**Coverage:** 6,706 games (2021-2026, 5 seasons)
**Features:** 18 analytical fields (primetime, broadcaster, scheduling context)
**Processor:** NbacScheduleProcessor
**Deployment:** nbac-schedule-processor-backfill (us-west2)

### Team Boxscore

**Status:** ⏳ Ready for Deployment

```
Table: nba_raw.nbac_team_boxscore
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
Primary Key: (game_id, team_abbr)
GCS: /nba-com/team-boxscore/{game_date}/{game_id}/{timestamp}.json
```

**Expected:** ~10,800 records (5,400 games × 2 teams)
**Processor:** NbacTeamBoxscoreProcessor
**Deployment:** nbac-team-boxscore-processor-backfill (us-west2)
**Replaces:** Scoreboard V2 (deprecated Oct 2025)

### Gamebooks ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.nbac_gamebook_player_stats
Partition: game_date
Strategy: MERGE_UPDATE
GCS: /nba-com/gamebooks-data/{date}/{game-code}/{timestamp}.json
```

**Coverage:** 118,000 records, 26,412 inactive players
**Resolution:** 98.92% accuracy
**Processor:** NbacGamebookProcessor
**Deployment:** nbac-gamebook-backfill (us-west2, 8Gi RAM, 4 CPU)

### Player List ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.nbac_player_list_current
Primary Key: player_lookup
Strategy: MERGE_UPDATE (current state only)
GCS: /nba-com/player-list/{date}/{timestamp}.json
```

**Coverage:** ~600 active players
**Processor:** NbacPlayerListProcessor

### Injury Report ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.nbac_injury_report
Partition: report_date
Strategy: APPEND_ALWAYS (hourly snapshots)
GCS: /nba-com/injury-report-data/{date}/{hour}/{timestamp}.json
```

**Coverage:** ~500-600k records (4 years, 24 reports/day)
**Processor:** NbacInjuryReportProcessor
**Deployment:** nbac-injury-report-backfill (us-west2)

### Player Movement

**Status:** ✅ Production Ready

```
Table: nba_raw.nbac_player_movement
Partition: season_year (range bucket)
Strategy: INSERT_NEW_ONLY
GCS: /nba-com/player-movement/{date}/{timestamp}.json
```

**Coverage:** 4,457 records (2021+)
**Types:** Signing (47%), Waive (31%), Trade (20%)
**Processor:** NbacPlayerMovementProcessor
**Deployment:** nbac-player-movement-processor-backfill (us-west2)

### Play By Play

**Status:** ✅ Production Ready

```
Table: nba_raw.nbac_play_by_play
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
Primary Key: (game_id, event_sequence)
GCS: /nba-com/play-by-play/{date}/game-{gameId}/{timestamp}.json
```

**Coverage:** 1,043 events (2 games, limited collection)
**Potential:** ~5,400+ games available
**Processor:** NbacPlayByPlayProcessor
**Deployment:** nbac-play-by-play-processor-backfill (us-west2, 8Gi RAM)

### Player Boxscore

**Status:** ⏳ Awaiting Data

```
Table: nba_raw.nbac_player_boxscores
Partition: game_date
Strategy: MERGE_UPDATE
Primary Key: (game_id, nba_player_id)
GCS: /nba-com/player-boxscores/{date}/{timestamp}.json
```

**Expected:** ~165,000 records (matches BDL coverage)
**Processor:** NbacPlayerBoxscoreProcessor
**Deployment:** nbac-player-boxscore-processor-backfill (us-west2)

### Referee Assignments

**Status:** ✅ Production Ready

```
Tables:
  - nba_raw.nbac_referee_game_assignments
  - nba_raw.nbac_referee_replay_center
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
GCS: /nba-com/referee-assignments/{date}/{timestamp}.json
```

**Coverage:** 4,957 games, 710 replay center records
**Processor:** NbacRefereeProcessor
**Deployment:** nbac-referee-processor-backfill (us-west2)

## Ball Don't Lie (5 processors)

### Box Scores ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.bdl_player_boxscores
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
Primary Key: (player_lookup, game_id)
GCS: /ball-dont-lie/boxscores/{date}/{timestamp}.json
```

**Coverage:** 165,070 records (4 seasons, ~5,400 games)
**Processor:** BdlBoxscoresProcessor
**Deployment:** bdl-boxscores-processor-backfill (us-west2)

### Active Players ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.bdl_active_players_current
Primary Key: player_lookup
Strategy: MERGE_UPDATE (current state only)
GCS: /ball-dont-lie/active-players/{date}/{timestamp}.json
```

**Coverage:** 569 active players
**Validation:** Cross-checks with NBA.com (61.9% validated)
**Processor:** BdlActivePlayersProcessor
**Deployment:** bdl-active-players-processor-backfill (us-west2)

### Injuries

**Status:** ✅ Production Ready

```
Table: nba_raw.bdl_injuries
Partition: scrape_date
Strategy: APPEND_ALWAYS (daily snapshots)
Primary Key: (scrape_date, bdl_player_id)
GCS: /ball-dont-lie/injuries/{date}/{timestamp}.json
```

**Coverage:** 345 records (29/30 teams)
**Quality:** 100% high-confidence records
**Processor:** BdlInjuriesProcessor
**Deployment:** bdl-injuries-processor-backfill (us-west2)

### Standings

**Status:** ✅ Production Ready

```
Table: nba_raw.bdl_standings
Partition: date_recorded
Strategy: MERGE_UPDATE
Primary Key: (season_year, date_recorded, team_abbr)
GCS: /ball-dont-lie/standings/{season}/{date}/{timestamp}.json
```

**Coverage:** 30 teams per snapshot (daily)
**Processor:** BdlStandingsProcessor
**Deployment:** bdl-standings-processor-backfill (us-west2)

### Live Box Scores ⭐ (NEW)

**Status:** ✅ Production Ready (Session 174)

```
Table: nba_raw.bdl_live_boxscores
Partition: game_date (REQUIRED)
Cluster: game_id, player_lookup, poll_timestamp
Strategy: APPEND_ALWAYS (time-series data)
GCS: /ball-dont-lie/live-boxscores/{date}/{poll_id}.json
```

**Purpose:** Real-time player stats for challenge grading
**Frequency:** Every 3 minutes during games (7 PM - 2 AM ET)
**Key Fields:**
- `poll_timestamp` - When snapshot was taken
- `poll_id` - e.g., "20251227T213000Z"
- `period`, `time_remaining` - Game progress
- `player_lookup` - Consistent with tonight endpoint
- Full box score stats (points, rebounds, assists, etc.)

**Processor:** BdlLiveBoxscoresProcessor
**Deployment:** nba-phase2-raw-processors (via Pub/Sub)

## BettingPros (1 processor)

### Player Props ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.bettingpros_player_points_props
Partition: game_date (REQUIRED)
Strategy: APPEND_ALWAYS
Primary Key: (game_date, offer_id, bet_side, book_id)
GCS: /bettingpros/player-props/points/{date}/{timestamp}.json
```

**Coverage:** 1,087,315 records (855 files, 4 seasons)
**Confidence:** Freshness-based (0.1-0.95)
**Processor:** BettingPropsProcessor
**Deployment:** bettingpros-player-props-processor-backfill (us-west2)

## BigDataBall (1 processor)

### Enhanced Play-by-Play ⭐

**Status:** ✅ Production Ready

```
Table: nba_raw.bigdataball_play_by_play
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
Primary Key: (game_id, event_sequence)
GCS: /big-data-ball/{season}/{date}/game_{id}/{file}.csv
```

**Coverage:** 566,034 events (1,211 games, 2024-25 season)
**Features:** Shot coordinates, 5-man lineups, advanced timing
**Processor:** BigDataBallPbpProcessor
**Deployment:** bigdataball-pbp-processor-backfill (us-west2, 2hr timeout)

## ESPN (3 processors - backup only)

### Scoreboard

**Status:** ✅ Production Ready

```
Table: nba_raw.espn_scoreboard
Partition: game_date
Strategy: MERGE_UPDATE
GCS: /espn/scoreboard/{date}/{timestamp}.json
```

**Coverage:** Limited (backup source)
**Schedule:** 5 AM PT final check only
**Processor:** EspnScoreboardProcessor
**Deployment:** espn-scoreboard-processor-backfill (us-west2)

### Boxscores

**Status:** ✅ Production Ready

```
Table: nba_raw.espn_boxscores
Partition: game_date (REQUIRED)
Strategy: MERGE_UPDATE
Primary Key: (espn_player_id, espn_game_id)
GCS: /espn/boxscores/{date}/game-{id}/{timestamp}.json
```

**Coverage:** Sparse (backup collection)
**Processor:** EspnBoxscoreProcessor
**Deployment:** espn-boxscore-processor-backfill (us-west2)

### Team Roster

**Status:** ✅ Production Ready

```
Table: nba_raw.espn_team_rosters
Partition: roster_date
Strategy: MERGE_UPDATE
Primary Key: (roster_date, scrape_hour, team_abbr, espn_player_id)
GCS: /espn/rosters/{date}/team_{team_abbr}/{timestamp}.json
```

**Coverage:** Limited (backup source)
**Processor:** EspnTeamRosterProcessor
**Deployment:** espn-team-roster-processor-backfill (us-west2)

## Basketball Reference (1 processor)

### Season Rosters

**Status:** ✅ Production Ready

```
Table: nba_raw.br_rosters_current
Partition: season_year (range bucket)
Strategy: MERGE_UPDATE
Primary Key: (season_year, team_abbrev, player_full_name)
GCS: /basketball-ref/season-rosters/{season}/{team}.json
```

**Coverage:** 120 roster files (30 teams × 4 seasons: 2022-2025)
**Purpose:** Name mapping for gamebook PDFs
**Processor:** BasketballRefRosterProcessor

## Deprecated

### NBA.com Scoreboard V2 ❌

**Status:** Deprecated October 2025
**Reason:** NBA.com endpoint stopped working
**Replacement:** NBA.com Team Boxscore
**Previous Table:** nba_raw.nbac_scoreboard_v2

## Critical Query Requirements

**Partitioned Tables - MUST include partition filter:**

```sql
-- ❌ WILL FAIL
SELECT * FROM nba_raw.nbac_schedule

-- ✅ REQUIRED
SELECT * FROM nba_raw.nbac_schedule
WHERE game_date >= "2021-01-01"
```

**Affected tables:**
- odds_api_game_lines
- nbac_schedule
- nbac_team_boxscore
- nbac_play_by_play
- nbac_referee_game_assignments
- bdl_player_boxscores
- bdl_live_boxscores
- bettingpros_player_points_props
- bigdataball_play_by_play
- espn_boxscores

## Backfill Commands

```bash
# Example: Team Boxscore
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py \
  --start-date=2024-11-01 --end-date=2024-11-30

# Cloud Run
gcloud run jobs execute nbac-team-boxscore-processor-backfill \
  --args=--start-date=2024-11-01,--end-date=2024-11-30 \
  --region=us-west2
```

## Files

**Repository:**
- Processors: `data_processors/raw/{source}/{processor_name}.py`
- Backfill Jobs: `backfill_jobs/raw/{processor_name}/`
- Schemas: `schemas/bigquery/raw/{table_name}_tables.sql`

**Cloud Run:**
- Jobs: `{processor-name}-backfill` (us-west2)
- Service: `raw-data-processor` (Pub/Sub integration)

## See Also

- [Scraper Reference](01-scrapers-reference.md)
- [Backfill Guides](../backfill/)
- [Processor Base Class](../../data_processors/processor_base.py)
