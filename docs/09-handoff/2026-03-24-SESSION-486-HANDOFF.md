# Session 486 Handoff — 2026-03-24

**Latest commit:** `c7c1c1e8` — feat: add cap_to_last_loose_market_date() to weekly-retrain CF
**Branch:** main (auto-deployed)

---

## System State: HEALTHY

### NBA Fleet (5 enabled models)
| Model | Framework | Train Window | Eval HR edge 3+ | Notes |
|-------|-----------|-------------|-----------------|-------|
| `lgbm_v12_noveg_train1001_0316` | LGBM | Oct 1 – Mar 16 | **67.61%** (N=71) ✓ | NEW — enabled this session |
| `lgbm_v12_noveg_train0103_0227` | LGBM | Jan 3 – Feb 27 | — | HEALTHY |
| `lgbm_v12_noveg_train0103_0228` | LGBM | Jan 3 – Feb 28 | — | HEALTHY |
| `lgbm_v12_noveg_train1215_0214` | LGBM | Dec 15 – Feb 14 | — | WATCH (decay CF) |
| `catboost_v12_noveg_train0103_0228` | CatBoost | Jan 3 – Feb 28 | — | edge-collapsed (avg_abs_diff 1.06) |

**First real test for new model: Mar 25 predictions.** Watch avg_abs_diff on `lgbm_v12_noveg_train1001_0316` — expecting higher edge than current fleet due to Oct–Nov high-variance training data.

### Weekly Retrain CF
- **State: ENABLED** (was PAUSED since 2026-03-21)
- Next fire: **Monday Mar 30, 5 AM ET**
- Gate fix deployed: `cap_to_last_loose_market_date()` (Session 486)

---

## What Was Done This Session (486)

### 1. Multi-Agent Research (8 agents total)
Four research agents surveyed system state, then four review agents (3 Opus, 1 Sonnet) critiqued the original priority list. Key reversals:

**Original list was wrong on 5 of 8 items:**
- Item 1 (re-enable vw015): **KILLED** — 30d HR 48.6%, 21d HR 41.2%. Decay machine was right.
- Item 2 (grading gap): **FALSE ALARM** — 30/36 graded in `prediction_accuracy`. Canary checks wrong source.
- Item 3 (deploy nba-phase1-scrapers): **WRONG TARGET** — orphaned legacy service. Real target: `mlb-phase1-scrapers`.
- Items 4+5 (disable/check catboost_0113_0310): **ALREADY DONE** — already blocked/disabled.
- Item 6 (MLB resume script): **NO-OP** — all 35 jobs already enabled.

**Added to list (not in original):**
- Phase 5 completion logging shows zero entries (Sonnet reviewer) — likely phantom alert, but worth monitoring
- `mlb-phase1-scrapers` was 77 days stale (Opus 3 deep-dive) — 4 jobs would fail on Opening Day
- `pybaseball` never installed — `mlb_statcast_daily` has never worked in production (discovered during deploy)
- `weekly-retrain` CF gate fix is more urgent than listed — Monday fire would run with backwards logic

### 2. MLB Opening Day Fixes
Session 485 declared MLB "Opening Day ready." It was not. Four issues found and fixed:

**a) 4 broken scheduler jobs:**
- `mlb-overnight-results`: body `mlb_box_scores` → `mlb_box_scores_mlbapi` (BDL scraper name was retired)
- `mlb-live-boxscores`: body `mlb_live_box_scores` → `mlb_game_feed` (non-existent scraper)
- `mlb-umpire-assignments`: URI from `nba-scrapers` → `mlb-phase1-scrapers` (wrong service)
- `mlb-game-lines-morning`: URI from `nba-scrapers` → `mlb-phase1-scrapers` (wrong service)

**b) `mlb-phase1-scrapers` deployed** (commit `e1571da8`, was on `b855a1d` from Jan 7):
- Used `gcloud builds submit --config cloudbuild.yaml --substitutions _SERVICE=mlb-phase1-scrapers,_DOCKERFILE=scrapers/Dockerfile,...`
- `SHORT_SHA` must be passed explicitly in manual builds — built-in substitution not populated outside triggers

**c) `pybaseball==2.2.7` added to requirements** (commit `f2791647`):
- `mlb_statcast_daily` was raising `ImportError` on every invocation since Jan 7
- Added to `scrapers/requirements.txt` and `scrapers/requirements-lock.txt`
- Second manual deploy of `mlb-phase1-scrapers` done to pick up the new dep
- Confirmed working: `mlb_statcast_daily` returns success on Sept 2025 test date

**d) `deploy_mlb_scrapers.sh` Dockerfile path fixed:**
- `docker/scrapers.Dockerfile` → `scrapers/Dockerfile` (archived Jan 29)

### 3. NBA Retrain — `lgbm_v12_noveg_train1001_0316`

Two retrain attempts before success:

**Attempt 1 — 56-day window ending Mar 23:**
- Governance FAILED: HR edge 3+ = 56.38% (needs ≥60%)
- Edge 5+ was 66.7% (N=21), but N too thin and edge 3-5 too weak
- Decision: honor the gate, don't deploy

**Attempt 2 — 167-day window (Oct 1 – Mar 16), eval Mar 17-23:**
- Governance PASSED: HR edge 3+ = **67.61%** (N=71) ✓
- Vegas bias: +0.68 ✓, directional balance: OVER 69.6% / UNDER 60.0% ✓
- Why longer window works: Nov 2025 avg_abs_diff was 4.29 (high-variance). Model sees more scoring spread → learns to diverge from Vegas → better edge generation
- Training through TIGHT (Mar 11-14): only 4/167 days = 2.4% contamination. Acceptable dilution.
- Model enabled and worker cache refreshed

**Note on eval window arg:** `--train-end` in `quick_retrain.py` sets the eval END (not training end). Training data ends 7 days before. With explicit `--train-start`, use `--eval-start` / `--eval-end` separately to avoid 0-sample eval bug.

### 4. `weekly-retrain` CF Gate Fix (commit `c7c1c1e8`)

Added `cap_to_last_loose_market_date()` to `orchestration/cloud_functions/weekly_retrain/main.py`:

**Problem:** The scheduler was manually paused to prevent training during TIGHT markets, but this was backwards — LOOSE markets (MAE > 5.0) are the best time to train. The fix moves the gate into code, not the scheduler.

**Logic:**
- Query `league_macro_daily` for TIGHT days (vegas_mae_7d < 4.5) in last 30 days
- If the most recent TIGHT day was < 7 days before `train_end`, cap training to the day before TIGHT started
- After 7 days of LOOSE recovery, cap expires (TIGHT data is diluted in 56-day window)
- Skipped when `train_end` is explicitly overridden via query param

**On Mar 30 run:** TIGHT ended Mar 14 (16 days ago). 16 > 7 → cap does NOT apply. Training Jan 18 – Mar 15 normally.

Scheduler re-enabled: `gcloud scheduler jobs resume weekly-retrain-trigger --location=us-west2`.

---

## New Gotchas (Session 486)

**`mlb-phase1-scrapers` is NOT auto-deployed.** Push to main deploys `nba-scrapers` only. MLB scraper changes require manual `gcloud builds submit --config cloudbuild.yaml --substitutions _SERVICE=mlb-phase1-scrapers,_DOCKERFILE=scrapers/Dockerfile,...`. Must pass `SHORT_SHA=$(git rev-parse --short HEAD)` explicitly — built-in substitution is empty in manual builds.

**`nba-phase1-scrapers` is an orphaned legacy service.** Zero scheduler jobs target it. The drift check monitors it but it has no consumers. Can be deleted when convenient. Real scraper services: `nba-scrapers` (NBA, auto-deployed) and `mlb-phase1-scrapers` (MLB, manual).

**Grading canary alert is a false positive.** "ZERO graded predictions despite N final games" checks GCS live-grading JSON scope, not `prediction_accuracy`. The BQ table shows 83%+ graded correctly. The canary message "Likely cause: BDL_API_KEY missing" is stale — BDL is intentionally disabled. Low priority to fix but causes noise.

**Projection-level HR ≠ BB-level HR (reconfirmed).** `signal_health_daily` counts all predictions where a signal fired. A signal can show 64% HR there while having 12% actual BB-level HR. Always verify against `signal_best_bets_picks` before graduation decisions.

**`cap_to_last_loose_market_date()` `recovery_days` threshold is 7.** Chosen because: (a) 7 days of LOOSE data provides enough post-TIGHT signal to dilute 4 TIGHT days in the 56-day window, and (b) matches CLAUDE.md finding that Feb-trained models produce higher edge than March-trained. If market tightens again, the CF will auto-protect. Threshold is a parameter — adjustable without code change to the calling logic.

---

## MLB Opening Day Verification (Mar 27)

### Evening after predictions (6-8 PM ET):
```sql
SELECT game_date, COUNT(*) as n FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 15-20 predictions

SELECT game_date, COUNT(*) as picks FROM mlb_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 3-5 picks
```

### Morning after (Mar 28):
```sql
SELECT game_date, COUNT(*) as graded FROM mlb_predictions.prediction_accuracy
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 15-20 graded
```

### Statcast working verification:
```bash
curl -s -X POST https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper": "mlb_statcast_daily", "date": "2026-03-27"}'
# Expected: status: success
```

---

## Pending Items

- [ ] Monitor `lgbm_v12_noveg_train1001_0316` avg_abs_diff on Mar 25 — is pick drought recovering?
- [ ] MLB Opening Day verification → **Mar 27 evening + Mar 28 morning**
- [ ] MLB `mlb_league_macro.py` manual backfill after first games grade → **Mar 28**
- [ ] Decay CF will handle `lgbm_v12_noveg_train1215_0214` (WATCH) → **auto Mar 25**
- [ ] Playoffs: activate shadow mode → **Apr 14**
- [ ] `usage_surge_over` graduation watch — N=18 at 72.2% HR 30d; check again at N=30
- [ ] Fix canary false positive ("BDL_API_KEY" grading alert) — low priority

---

## Key Active Constraints

- `catboost_v12_noveg_train0103_0228`: keep in fleet for now (edge-collapsed but not hurting)
- `weekly-retrain` CF: **ENABLED**, fires Mon 5 AM ET, gate-protected by new code
- OVER edge floor: **5.0** (auto-rises to 6.0 when vegas_mae < 4.5)
- `projection_consensus_over`: **DO NOT GRADUATE** — BB-level HR only 12.5% (1-8), needs 6-8 more weeks

---

## Session 486 Commits (2 total)
```
c7c1c1e8 feat: add cap_to_last_loose_market_date() to weekly-retrain CF
f2791647 fix: add pybaseball to scraper requirements for mlb_statcast_daily
```
