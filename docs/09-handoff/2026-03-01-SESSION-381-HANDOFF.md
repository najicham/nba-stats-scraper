# Session 381 Handoff — Live Scoring Pipeline Repair

**Date:** 2026-03-01
**Focus:** Fix tonight endpoint missing scores, game status transitions, and live data pipeline gaps

## What Was Done

### 1. Deployments
- **prediction-coordinator** deployed (commit e40e6d8f) — UTC fix from Session 380 + signal monitoring
- **nba-scrapers** deployed (commit 83e12b30) — boxscore NoneType fix + all Session 380 changes
- **NOTE:** `nba-phase1-scrapers` is a DIFFERENT Cloud Run service from `nba-scrapers`. Schedulers point to `nba-scrapers` (BUILD_COMMIT: 83e12b30). `nba-phase1-scrapers` is stale at a97da8ef — it may be orphaned/unused.

### 2. Bugs Fixed (Committed + Deployed)

**a. Team boxscore NoneType crash (commit 83e12b30)**
- File: `scrapers/nbacom/nbac_team_boxscore.py`
- Bug: NBA API returns `"statistics": null` for unstarted games. Validation checked key existence (`"statistics" not in team`) but not value. `stats.get("minutes")` crashed on None.
- Fix: Changed to `"statistics" not in team or team["statistics"] is None`

**b. date.today() UTC bug in coordinator (commit e40e6d8f — from last session)**
- File: `predictions/coordinator/coordinator.py` (lines 901, 3984, 4196, 4214)
- All 4 instances replaced with `datetime.now(ZoneInfo('America/New_York')).date()`

**c. Schedule refresh added to game-hour workflows (commit 2a573751 — parallel session)**
- File: `config/workflows.yaml`
- Added `nbac_schedule_api` to `early_game_window_1`, `_2`, and `_3`
- This ensures game_status transitions (1→2→3) happen during game hours (3 PM, 6 PM, 9 PM ET)

### 3. Manual Data Recovery
- Triggered `nbac_schedule_api` scraper → game statuses + scores now updating
- Re-triggered Phase 6 tonight export → scores visible in tonight endpoint
- Player boxscore data: 139 records in `nba_raw.nbac_player_boxscores` for Mar 1 (7 games)
- Team boxscore data: 14 records in `nba_raw.nbac_team_boxscore` for Mar 1

### 4. Tonight Endpoint Status (as of ~6:40 PM PT)
```
SAS@NYK  status=final        home=114  away=89   actual_points=0
CLE@BKN  status=final        home=102  away=106  actual_points=0
MIL@CHI  status=final        home=120  away=97   actual_points=0
MIN@DEN  status=final        home=108  away=117  actual_points=0
MEM@IND  status=in_progress  home=None away=None  actual_points=0
DET@ORL  status=in_progress  home=None away=None  actual_points=0
POR@ATL  status=in_progress  home=None away=None  actual_points=0
OKC@DAL  status=scheduled    (not started)
PHI@BOS  status=scheduled    (not started)
NOP@LAC  status=scheduled    (not started)
SAC@LAL  status=scheduled    (not started)
```

## What's NOT Working Yet

### 1. actual_points Still Missing (HIGH PRIORITY)
**Root cause:** `player_game_summary` has 0 records for Mar 1.

**Why:** Two blocking checks in PlayerGameSummaryProcessor:
1. **`ENABLE_GAMES_FINISHED_CHECK = True`** (early_exit_mixin.py line 81): Requires ALL games on the date to be finished. With 11 games, only 4 are final → skips processing. Bypassed by `backfill_mode=true`.
2. **Team stats threshold** (player_game_summary_processor.py ~line 824): Requires 80% of expected teams to have stats. TeamOffenseGameSummaryProcessor only has 4 teams (2 early final games). The 2 newer final games (CLE@BKN, MIN@DEN) don't have team stats yet because the boxscore scraper ran before they went final.

**To fix:**
```bash
# 1. Re-run boxscore scrapers to pick up all 4+ final games
curl -s -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflow" \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "early_game_window_3"}' \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# 2. Then re-run Phase 3 in backfill mode
curl -s -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"start_date": "2026-03-01", "end_date": "2026-03-01", "processors": ["TeamOffenseGameSummaryProcessor", "PlayerGameSummaryProcessor"], "backfill_mode": true, "skip_downstream_trigger": false}'

# 3. Then re-trigger tonight export
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["tonight", "tonight-players"], "target_date": "2026-03-01", "update_latest": true}'
```

### 2. In-Progress Game Scores Missing
- The `nbac_schedule` table only gets scores for FINAL games (from the Schedule API)
- In-progress scores require the Scoreboard V2 API or team boxscore scraper
- BDL live API is disabled — the live-export function can't get live scores
- **Architecture gap:** No frequent (every 1-3 min) scraper updating in-progress scores during game hours

### 3. Live Grading JSON Shows 0 Games
- `live-grading/latest.json` has 0 games
- The live export Cloud Function runs every 3 min (4-11 PM PT) but relies on BDL API for live player data
- BDL is disabled → live grading has no player-level data to work with

### 4. nba-phase1-scrapers vs nba-scrapers Confusion
- Two separate Cloud Run services with similar names
- `nba-scrapers`: Active, schedulers point here, BUILD_COMMIT 83e12b30
- `nba-phase1-scrapers`: Stale (a97da8ef from Feb 19), may be orphaned
- The drift check monitors `nba-phase1-scrapers` but schedulers use `nba-scrapers`
- **Action needed:** Investigate whether `nba-phase1-scrapers` can be decommissioned, or update the drift check to monitor `nba-scrapers`

## Architecture Gaps Identified

### Gap 1: No Real-Time Score Updates During Games
- Schedule API only provides final scores
- No scoreboard V2 scraper in any workflow
- BDL disabled, so no live data source
- **Recommendation:** Add `nbac_scoreboard_v2` to a frequent scheduler (every 5 min, 7 PM - 2 AM ET) for live scores

### Gap 2: player_game_summary Waits for ALL Games
- `ENABLE_GAMES_FINISHED_CHECK` blocks until all games on a date are final
- This means no actual_points until ~2 AM ET (late West Coast games)
- **Recommendation:** Change to process when >50% of games are final, or process incrementally per game

### Gap 3: Team Stats Completeness Threshold
- 80% threshold prevents processing when only some games have data
- On big slates (11+ games), early final games can't be processed
- **Recommendation:** Lower threshold or process per-game instead of per-date

## Daily Steering Summary (Mar 1)

- **Fleet status:** 22/32 models BLOCKED. Champion catboost_v12 at 50.6% 7d HR.
- **Best bets:** 5-7 (41.7%) last 7d, 30-22 (57.7%) last 30d
- **LightGBM models:** HEALTHY at 71.4% (N=7) — best models
- **Market regime:** Edges healthy (compression 1.257), conversion poor
- **OVER/UNDER split:** UNDER 63.6% vs OVER 45.5% (18pp divergence)
- **11 games today** — big slate

## Files Changed
- `scrapers/nbacom/nbac_team_boxscore.py` — NoneType null check
- `predictions/coordinator/coordinator.py` — UTC fix (4 locations)
- `config/workflows.yaml` — nbac_schedule_api in early_game_windows (parallel session)

## Next Session Priorities
1. **Immediate:** Re-run boxscore + Phase 3 + tonight export once more games are final
2. **Architecture:** Add live score updates (scoreboard V2 scraper on frequent schedule)
3. **Architecture:** Fix player_game_summary to process incrementally (not wait for all games)
4. **Cleanup:** Investigate nba-phase1-scrapers vs nba-scrapers service duplication
5. **Model health:** Fleet in rough patch — consider retrain with fresh data
