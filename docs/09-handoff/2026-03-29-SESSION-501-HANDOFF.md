# Session 501 Handoff — 2026-03-29 (late night)

**Date:** 2026-03-29
**Commits:** 2 commits — coordinator URL bug fix + MLB lineup scraper fix

---

## The Big Picture

Session 501 was a maintenance/debugging session. Found and fixed two production bugs:
1. **3-day NBA pick drought (March 26-28)** — caused by dead coordinator URL in `phase4-to-phase5-orchestrator`
2. **MLB lineup data missing for all of 2026** — caused by wrong field path in lineup scraper

---

## Critical Bug Fixed: 0 NBA Picks March 26-28

### Root Cause
`phase4-to-phase5-orchestrator` CF had a hardcoded dead URL:
```
https://prediction-coordinator-756957797294.us-west2.run.app  # DEAD
```
Correct URL:
```
https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app  # CORRECT
```

The CF received Phase 4 completion messages, returned 200 (ACKing them), but silently failed to call the coordinator. The `_triggered` Firestore flag was never set (Session 128 fix: only set on success), so each message retried — and kept failing with the wrong URL.

### Fix Applied
1. Set `PREDICTION_COORDINATOR_URL` env var on the deployed CF via `--update-env-vars`
2. Updated hardcoded default in code (`main.py`) for all 4 affected CFs:
   - `orchestration/cloud_functions/phase4_to_phase5/main.py`
   - `orchestration/cloud_functions/phase4_timeout_check/main.py`
   - `orchestration/cloud_functions/line_quality_self_heal/main.py`
   - `orchestration/cloud_functions/enrichment_trigger/main.py`
3. Committed and pushed (commit `fa0a4c7a`) → auto-deployed all 4 CFs

### Why It Survived Future Deploys
`cloudbuild-functions.yaml` uses `--update-env-vars` (not `--set-env-vars`) — the manually-set env var persists. The code default is also now correct as a second layer.

### Recovery
Manually triggered Phase 5 for March 28 after fixing the CF. Fleet was too degraded for picks (see below).

---

## MLB Lineup Scraper Fix

### Root Cause
`scrapers/mlb/mlbstatsapi/mlb_lineups.py` read `away_team_abbr` from:
```python
away_team.get("team", {}).get("abbreviation")  # liveData.boxscore.teams.away.team
```
The boxscore team object has `[id, name, link]` — no `abbreviation`. Correct path:
```python
game_teams.get("away", {}).get("abbreviation")  # gameData.teams.away
```
BQ table has `away_team_abbr`/`home_team_abbr` as REQUIRED → every write failed → `mlb_lineup_batters` empty for all of 2026.

### Fix Applied
- Fixed in `scrapers/mlb/mlbstatsapi/mlb_lineups.py` (commit `27c6b032`)
- `mlb-phase1-scrapers` redeployed via `./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`
- Backfill re-scraped March 24-28 → `mlb_lineup_batters` now populated:
  - March 25: 18 rows
  - March 26: 226 rows
  - March 27: 161 rows
  - March 28: 307 rows

---

## NBA Fleet Status (DEGRADED — Monday Retrain Critical)

| Model | State | 7d HR | N |
|-------|-------|-------|---|
| `lgbm_v12_noveg_train0121_0318` | WATCH | 56.5% | 23 |
| `lgbm_v12_noveg_train0103_0227` | DEGRADING | 53.0% | 83 |
| `catboost_v12_noveg_train0121_0318` | BLOCKED | 45.5% | 11 |
| `catboost_v12_noveg_train0118_0315` | BLOCKED | 46.2% | 13 |

**Monday March 30 5 AM ET:** `weekly-retrain-trigger` fires. TIGHT cap applies — train window = Jan 9–Mar 7.

After retrain completes:
```bash
./bin/model-registry.sh sync
./bin/refresh-model-cache.sh --verify
```

Watch `#nba-betting-signals` for Slack alerts. SLACK_WEBHOOK_URL confirmed on the CF.

---

## MLB Phase 4 Precompute Rebuild

Built and deployed `mlb-precompute-processors` with `k_rate_last_30` removal and `bdl_pitchers` → `mlb_pitcher_stats` fix (Task 4 from Session 500).

Build: `e6dfc18b` → revision `mlb-phase4-precompute-processors-00011-9ff`

---

## March 29 Predictions

Manually triggered Phase 5 for March 29 — returned `with_prop_line: 0` (lines not posted yet, ~10 PM ET). The pipeline will auto-run tomorrow morning when:
1. Odds scrapers post March 29 lines
2. Phase 4 refreshes ml_feature_store for March 29
3. `phase4-to-phase5-orchestrator` triggers coordinator (now with correct URL)

No manual action needed for March 29.

---

## Open Issues

### 1. NBA Monday Retrain (CRITICAL — March 30 5 AM ET)
Same as Session 500. Fleet is more degraded now (2 BLOCKED, 1 DEGRADING). Retrain is essential.

### 2. Stale 756957797294 URLs in bin/backfill scripts (LOW)
`backfill_jobs/`, `bin/scraper_catchup_controller.py`, `bin/monitoring/phase3_season_audit.py`, `monitoring/mlb/`, `validation/validators/mlb/` still reference old-format URLs. These are non-production one-off scripts but should be cleaned up eventually.

---

## Key File Locations

| Component | File |
|-----------|------|
| Phase 4→5 orchestrator | `orchestration/cloud_functions/phase4_to_phase5/main.py` |
| Phase 4 timeout check | `orchestration/cloud_functions/phase4_timeout_check/main.py` |
| Enrichment trigger | `orchestration/cloud_functions/enrichment_trigger/main.py` |
| Line quality self-heal | `orchestration/cloud_functions/line_quality_self_heal/main.py` |
| MLB lineup scraper | `scrapers/mlb/mlbstatsapi/mlb_lineups.py` |
