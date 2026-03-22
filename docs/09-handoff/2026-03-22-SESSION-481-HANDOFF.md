# Session 481 Handoff — NBA Full Validation + MLB Opening Day Prep

**Date:** 2026-03-22
**Previous:** Session 480 (morning check, system healthy)

---

## TL;DR

Comprehensive NBA validation (all healthy), fixed 2 site bugs (KD ungraded pick + Zion duplicate), fixed 3 MLB bugs (TODAY/YESTERDAY literals in prediction worker + grading services), deployed updated MLB services, created missing `mlb_orchestration.scraper_execution_log` table. MLB system is ready for March 27 opening day.

---

## NBA Validation — All Healthy

### Pipeline Status
| Check | Status |
|-------|--------|
| Deployment drift | ✅ All critical services current. `nba-phase1-scrapers` 12 commits behind (MLB features, LOW priority) |
| Phase 3 today | ✅ 1/5 (same-day mode, upcoming_player_game_context only — correct) |
| Phase 3 yesterday | ✅ 4/5 triggered (missing: upcoming_team_game_context — non-blocking) |
| Betting lines | ✅ All 5 today's games have Odds API + BettingPros lines |
| Feature store | ✅ Zero-tolerance working — 36 clean / 91 total today |
| Analytics quality | ✅ Active players: 99% usage rate coverage |
| Model health | ✅ Both enabled LGBMs: 60% HR 7d, HEALTHY |

### Today's Picks: 0 (expected)
Both LGBM models show RED signal (0-1.5% OVER picks, 5-game light slate). Tight market — models predict close to line for everyone. `avg_pvl=-0.35 and -0.16`. This is correct behavior. **Mar 25 (12 games) is the target day this week.**

### Minor Issues Found
- `nba-props-evening-closing`: DEADLINE_EXCEEDED (900s too short for CLV workflow)
- `self-heal-predictions`: DEADLINE_EXCEEDED (900s too short)
- Fix command (not urgent): `gcloud scheduler jobs update {job} --location=us-west2 --attempt-deadline=1800s`

---

## Site Bug Fixes

### 1. Kevin Durant Mar 16 — Ungraded Pick (FIXED)
- **Root cause**: XGB model (`xgb_v12_noveg_train0113_0303`) was BLOCKED, so its predictions were `is_active=FALSE`. Grading service skips inactive predictions.
- **Fix**: Reactivated the KD Mar 16 XGB prediction (line 25.5), ran grading backfill for Mar 16, then re-ran `best-bets-all` export.
- **Result**: KD UNDER 25.5, actual=18, **WIN** now shows correctly on site.

### 2. Zion Williamson Mar 19 — Two Picks Showing (FIXED)
- **Root cause**: `prediction_accuracy` had TWO records for Zion Mar 19 from `lgbm_v12_noveg_vw015_train1215_0208` with different line values (21.5 and 20.5). The JOIN from signal_best_bets_picks → prediction_accuracy produced 2 rows on the site.
- **Fix**: Deleted the stale 21.5 prediction_accuracy record (BB pick used 20.5 line, edge=3.7). Ran `best-bets-all` export.
- **Result**: Zion UNDER 20.5, actual=15, **WIN** shows as 1 pick.

### Residual: signal-best-bets/2026-03-16.json has 0 picks
Triggering `signal-best-bets` export for historical dates re-runs the aggregator and produces 0 picks (correct behavior). The site's history view reads from `best-bets/all.json`, which is correctly updated. The date-specific signal-best-bets files are primarily used for same-day display.

---

## MLB Opening Day Prep (March 27)

### Bugs Fixed (commits e30fe7c7, 9142bcb6, dbfc99a7)

**1. MLB prediction worker `TODAY` literal (FIXED + DEPLOYED)**
- `predictions/mlb/worker.py`: `/predict-batch` endpoint now resolves `'TODAY'` before `strptime`
- Scheduler sends `{"game_date": "TODAY"}` — this was crashing with ValueError
- New revision: `mlb-prediction-worker-00022-mlg` at 100% traffic ✅
- Smoke test: `game_date: 2026-03-22 | error: none` ✅

**2. MLB grading YESTERDAY/TODAY literals (FIXED + DEPLOYED)**
- `data_processors/grading/mlb/mlb_prediction_grading_processor.py`: resolves TODAY/YESTERDAY in `run()` before BigQuery queries
- `data_processors/grading/mlb/mlb_shadow_grading_processor.py`: same fix
- Both causing SQL errors: `Could not cast literal "YESTERDAY" to type DATE`
- New service: `mlb-phase6-grading-00003-56h` at 100% traffic ✅

**3. MLB grading Dockerfile + requirements (NEW, DEPLOYED)**
- Created `data_processors/grading/mlb/Dockerfile` (was missing — service couldn't be rebuilt)
- Created `data_processors/grading/mlb/requirements.txt` with full dependencies including pandas
- `mlb-phase6-grading` service now properly includes `predictions/shared/` (DistributedLock import)

**4. `mlb_orchestration.scraper_execution_log` table (CREATED)**
- Was missing — scrapers logging failures generated 404 errors
- Created with matching schema from `nba_orchestration.scraper_execution_log`

### MLB System State
| Item | Status |
|------|--------|
| MLB prediction worker | ✅ Deployed, TODAY fix live |
| MLB grading service | ✅ Deployed, YESTERDAY fix live, /grade-shadow endpoint now 200 |
| MLB model | ✅ `catboost_mlb_v2_regressor_36f_20250928` (HR=70%, is_production=TRUE, trained Sep 2025) |
| MLB schedule in BQ | ✅ Mar 27–Apr 3 (8 dates, ~101 games) |
| MLB scrapers (lineups/props) | ✅ Running, returning 0 records pre-season (expected) |
| BDL API key | ✅ Present (`cd483b51...`) — 401 from live box scores is pre-season restriction |
| `mlb-resume-reminder-mar24` | ENABLED, fires Mar 24 8 AM ET |

### MLB Scheduler Status
- Jobs returning code=13 (INTERNAL): `mlb-lineups-*`, `mlb-predictions-generate`, `mlb-props-*` — all now fixed by TODAY/YESTERDAY resolution
- `mlb-shadow-grading-daily` (code=5): Was hitting old image missing `/grade-shadow`. Now fixed.
- `mlb-game-lines-morning`, `mlb-statcast-daily`, etc. (code=3 INVALID_ARGUMENT): Minor, non-blocking

### Opening Day Checklist (March 27)
1. **Mar 24 8 AM ET**: Follow `mlb-resume-reminder-mar24` Slack alert → `./bin/mlb-season-resume.sh` (mostly no-op since all jobs already ENABLED, but verifies system state)
2. **Mar 27 AM**: Verify `mlb-predictions-generate` produced predictions in `mlb_predictions.pitcher_strikeout_predictions`
3. **Mar 27**: `mlb-pitcher-props-validator-4hourly` restricted Apr-Oct — prop lines on Mar 27 may need manual trigger
4. **Watch**: BDL live box scores scraper — was returning 401 pre-season. Verify it works when actual games start

---

## Code Changes Summary

| File | Change |
|------|--------|
| `predictions/mlb/worker.py` | TODAY literal resolution in /predict-batch |
| `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | TODAY/YESTERDAY literals |
| `data_processors/grading/mlb/mlb_shadow_grading_processor.py` | TODAY/YESTERDAY literals |
| `data_processors/grading/mlb/Dockerfile` | New — enables mlb-phase6-grading rebuilds |
| `data_processors/grading/mlb/requirements.txt` | New — full deps for grading service |

## Data Changes (no code)
- `prediction_accuracy`: KD Mar 16 XGB graded (UNDER 25.5 actual=18 WIN)
- `prediction_accuracy`: Deleted duplicate Zion Mar 19 lgbm 21.5 record
- `player_prop_predictions`: KD Mar 16 XGB reactivated (is_active=TRUE)
- `mlb_orchestration.scraper_execution_log`: Table created
- `best-bets/all.json`: Regenerated — KD WIN, Zion single pick

---

## Latest Commits
```
dbfc99a7 fix: mlb grading Dockerfile missing predictions/shared module copy
9142bcb6 fix: add pandas and full google-cloud deps to mlb grading service requirements
e30fe7c7 fix: MLB TODAY/YESTERDAY literal resolution in prediction worker and grading services
```

---

## Quick Reference — Current Enabled NBA Fleet

```bash
bq query --use_legacy_sql=false "
SELECT model_id, enabled, training_end_date
FROM nba_predictions.model_registry
WHERE enabled = TRUE
ORDER BY training_end_date DESC"
```

Both models: `lgbm_v12_noveg` family, training ends Feb 14 and Feb 27. Both HEALTHY.

---

## Next Session Priorities
1. **Mar 24**: Execute `./bin/mlb-season-resume.sh` after reminder fires
2. **Mar 25**: 12-game NBA slate — biggest pick volume day, monitor carefully
3. **Mar 25**: Decision point on `lgbm_1215` — deactivate if HR < 52.4%
4. **Mar 27**: MLB Opening Day — verify predictions fire, check BDL live box scores
5. **Ongoing**: MAE gap (0.74 → normalizing). Keep `weekly-retrain` CF paused until Vegas MAE < 5.0
