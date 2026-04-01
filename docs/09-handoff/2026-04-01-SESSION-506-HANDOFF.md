# Session 506 Handoff — 2026-04-01 (Wednesday)

**Context:** Session 505 retrained the fleet and restored fleet diversity. Session 506 ran
a full post-session audit (8 agents: 5 Opus + 3 Sonnet), fixed all identified issues, and
deployed updated code. System is GREEN heading into April 1's 10-game slate.

---

## Current System State

### NBA Fleet — FRESH (retrained Session 505, 2026-03-31)

| Model | State | Enabled | Training Window |
|-------|-------|---------|-----------------|
| `lgbm_v12_noveg_train0126_0323` | active | YES | Jan 26 – Mar 23 |
| `catboost_v12_noveg_train0126_0323` | active | YES | Jan 26 – Mar 23 |

Fleet diversity: 1 LGBM + 1 CatBoost. `combo_3way`, `book_disagreement`, `combo_he_ms` will fire.

### Season Record (as of 2026-03-31, authoritative BQ count)
- **Season: 108-76 (58.7% HR)** — updated from stale 89-61 figure
- **March: 19-27 (41.3%)** — drought period
- **Edge 5+: 82-44 (65.1%)**

---

## What Happened This Session

### 1. 5-Agent Morning Audit

Covered all open items from Session 505 handoff:
- New models healthy: 147 preds each, avg edge 1.35-1.49 (normal calibration)
- 0 best bets for March 31 — confirmed correct (Phase 6 ran before model registration,
  and by re-trigger time 5/7 games were already in progress)
- TIGHT cap bug confirmed (effective recovery window was 22 days, not 7)
- MLB `bp_pitcher_props` root cause found: scraper never wired into MLB pipeline

### 2. All 5 Open Items Resolved

| Item | Action |
|------|--------|
| TIGHT cap bug | Fixed: `date.today()` replaces `train_end` in `cap_to_last_loose_market_date()` |
| `usage_surge_over` | Reverted to shadow (COLD at 33.3%, N=15) |
| MLB `bp_pitcher_props` | Wired up (registry + TODAY fix + GCP schedulers) |
| `reconcile` + `validate-freshness` | Deployed, drift cleared |
| March 31 best bets | 0 picks confirmed correct — no action taken |

### 3. 8-Agent Post-Commit Review (5 Opus + 3 Sonnet)

Comprehensive audit found 3 blocking bugs in the initial MLB wiring:

**Bug 1 (blocking):** `bp_mlb_player_props` added to `scrapers/mlb/registry.py` (unused at
runtime) instead of `scrapers/registry.py` `MLB_SCRAPER_REGISTRY` (the file the Flask service
actually loads). Would have returned 400 "Unknown scraper" for every scheduler call.

**Bug 2 (blocking):** `BettingProsMLBPlayerProps.set_additional_opts()` did not call
`super().set_additional_opts()`, so "TODAY" was never resolved to an actual date. Would have
written all GCS files to path `bettingpros-mlb/pitcher-strikeouts/TODAY/` (literal string).

**Bug 3 (blocking):** `bin/schedulers/setup_mlb_schedulers.sh` used bare `$1` with `set -u`,
crashing with "unbound variable" when run with no arguments.

All 3 fixed in commit `9b797124`. The Docker build in progress at fix time will include
the corrected code since `COPY scrapers/` runs after pip install.

### 4. Other Audit Findings (LGTM)

- TIGHT cap fix: LGTM — `date` properly imported, no other similar bug patterns found.
  Note: effective shift was 15 days (not 14 as documented), so old recovery window was 22 days.
  Design gap: TIGHT days between `train_end` and today are invisible to the lookback query
  (not a bug, but worth knowing).
- `usage_surge_over` revert: LGTM — all 8 references across codebase verified. Shadow mode
  invariants all satisfied.
- All builds SUCCESS post-push, zero deployment drift.
- Season record updated to authoritative 108-76 (58.7%) / edge 5+: 82-44 (65.1%).

---

## Open Items (Priority Order)

### 1. Verify MLB Scraper Deploy (CHECK FIRST)

`mlb-phase1-scrapers` was being deployed at end of session. Verify it completed:

```bash
gcloud run services describe mlb-phase1-scrapers --region=us-west2 \
  --project=nba-props-platform --format="value(status.url,status.latestReadyRevisionName)"

# Test the scraper is registered:
curl "$(gcloud run services describe mlb-phase1-scrapers --region=us-west2 \
  --project=nba-props-platform --format='value(status.url)')/list-scrapers" \
  | python3 -m json.tool | grep bp_mlb_player_props
```

If deploy didn't complete or scraper is missing, redeploy:
```bash
./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh
```

The GCP schedulers fire at **10:45 AM ET (14:45 UTC)** and **12:45 PM ET (16:45 UTC)** tomorrow.
If the service doesn't have `bp_mlb_player_props` by then, they'll 400.

### 2. Monitor New Models (FIRST 2 DAYS — ongoing)

April 1 is the first full day for `lgbm_0126_0323` and `catboost_0126_0323`. Expect 3-8 picks
(mostly UNDER) based on current edge distribution (avg 1.35-1.49, few edge 5+ picks today).

```bash
# Check picks generated
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-04-01' GROUP BY 1,2 ORDER BY 2"

# Check graded accuracy (after games complete)
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END)*100,1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-04-01' AND system_id LIKE '%0126_0323%'
  AND prediction_correct IS NOT NULL
GROUP BY 1,2 ORDER BY 2"
```

### 3. `under_low_rsc` Filter — Watch Closely

CF HR = 54.2%, N=24. Auto-demotion triggers at N ≥ 30 AND CF HR ≥ 55% for 7 consecutive days.
Most recent readings: 37.5-40% (correctly blocking losers). But with new UNDER picks from fresh
models, N will grow quickly. Monitor daily.

### 4. `home_under` Signal — Underperforming

41.4% HR over 29 picks (7d) vs typical 66-69%. This is the primary `real_sc=1` driver for UNDER
picks. If it stays COLD, UNDER pick volume will stay low. Check signal_health_daily daily.

### 5. `friday_over_block` — Watch April 3

CF HR = 87.5% (N=8) on March 27. Too small to demote (need N≥30), but watch next Friday.

```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT filter_name, game_date, ROUND(cf_hr*100,1) as cf_hr_pct, n_graded
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date = '2026-04-03' AND filter_name = 'friday_over_block'"
```

### 6. `scrapers/mlb/registry.py` Drift

The file `scrapers/mlb/registry.py` is NOT used at runtime (Flask loads `scrapers/registry.py`).
It's a stale standalone file that will continue to drift silently. Consider removing it or adding
a comment that the runtime registry is `scrapers/registry.py`.

---

## Session 506 Commits

| Commit | Description |
|--------|-------------|
| `3ca7dcb7` | fix: correct TIGHT cap recovery window in weekly_retrain CF |
| `0a8cc4fe` | fix: revert usage_surge_over to shadow (COLD at 33.3% HR, N=15) |
| `3c5ea91b` | feat: wire bp_mlb_player_props into MLB daily pipeline |
| `9b797124` | fix: correct 3 blocking bugs in bp_mlb_player_props wiring |

All deployed. `weekly-retrain` CF live at 01:39 UTC April 1, ahead of Monday April 6 firing.

---

## System Health: GREEN (with one pending verification)

- NBA pipeline: healthy, 10 games April 1, fresh models
- Market: NORMAL (vegas_mae 5.22), no TIGHT suppression
- Signals: `combo_3way`/`combo_he_ms` NORMAL at 75% HR, fleet diversity restored
- MLB: pipeline live, `bp_pitcher_props` schedulers set for 10:45 AM + 12:45 PM ET
- Pending: verify `mlb-phase1-scrapers` deploy completed with `bp_mlb_player_props` in registry

---

## Quick Start for Next Session

```bash
# 1. Verify MLB scraper deploy
curl "$(gcloud run services describe mlb-phase1-scrapers --region=us-west2 \
  --project=nba-props-platform --format='value(status.url)')/list-scrapers" \
  | python3 -m json.tool | grep bp_mlb_player_props

# 2. Check April 1 picks
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 1 GROUP BY 1,2 ORDER BY 1,2"

# 3. Morning steering
/daily-steering
```
