# New Chat Handoff — 2026-03-22 (Post Session 482)

**Date:** 2026-03-22 (Sunday)
**Latest commit:** `aed38023` — chore: add .venv/ and models/ to .gcloudignore

---

## System State: HEALTHY

### NBA Fleet (as of 2026-03-21)
| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | HEALTHY | 60.0% (N=20) | Primary — Feb 27 training end |
| `lgbm_v12_noveg_train1215_0214` | HEALTHY | 60.0% (N=15) | avg_edge 1.34 — watch edge collapse |

**Today (Mar 22):** 0 picks — correct. 5-game slate, both models RED signal.

### Shadow Models (monitoring only, not in best bets)
All enabled=FALSE in registry. These generate predictions for performance tracking but are not best bets eligible:
catboost_v12_noveg_train0118_0315, catboost_v12_train0118_0315, catboost_v9_train0118_0315,
catboost_v12_noveg_train0109_0305, catboost_v12_train0109_0305, lgbm_v12_noveg_train0113_0303,
catboost_v12_noveg_train0113_0310, lgbm_v12_noveg_vw015_train1215_0208, xgb_v12_noveg_train0113_0303
This is expected behavior — they were auto-registered by weekly-retrain CF but kept disabled.

### MLB Services (restored this session)
| Service | Revision | Status |
|---------|----------|--------|
| mlb-prediction-worker | 00024-hpd (TODAY fix all endpoints) | 100% LATEST |
| mlb-phase6-grading | 00005-622 (import bug fixed) | 100% healthy |

---

## What Was Done This Session

### Full System Validation

#### NBA — All Healthy
- Deployment drift: all services current except nba-phase1-scrapers (LOW, MLB features)
- Phase 3: Today 1/5 (same-day mode, correct), Yesterday 4/5 (triggered, missing upcoming_team_game_context — normal)
- Feature store clean rate 29-40%: structural — 59% of players have no Vegas line prop (expected)
- Grading coverage 90-92%: HEALTHY
- Scheduler: 141/164 jobs passing; failures are MLB pre-season + known timeouts

#### Signal Health — No Action Needed
- `mean_reversion_under` (0% HR, N=5): already in SHADOW_SIGNALS, no impact on best bets
- `star_favorite_under` (31.6% HR): already in SHADOW_SIGNALS, only 2 actual BB picks this season
- Shadow models in model_performance_daily: all enabled=FALSE in registry — expected behavior

### MLB Bug Fixes (3 bugs found and fixed)

#### Bug 1: MLB grading service startup crash (503 on all endpoints)
**Root cause:** `main_mlb_grading_service.py` imported `MLBShadowGradingProcessor` but class
is named `MlbShadowModeGradingProcessor`. Service crashed on every cold start since deployment.
**Fix:** `from mlb_shadow_grading_processor import MlbShadowModeGradingProcessor as MLBShadowGradingProcessor`
**Commit:** `1f7240b7`
**Deployed:** mlb-phase6-grading 00005-622 (build 341fb5ba)

#### Bug 2: MLB worker TODAY literal in 3 remaining endpoints
Session 481 fixed `/predict-batch`. Three other endpoints still crashed on TODAY:
- `/predict-single` (line 319): no TODAY check
- `/best-bets` (line 608): no TODAY check
- Pub/Sub handler (line 728): no TODAY check
**Fix:** Added `if game_date_str.upper() == 'TODAY': game_date_str = date.today().isoformat()` to all three
**Commit:** `1f7240b7`
**Deployed:** mlb-prediction-worker 00024-hpd (build de7f9ac7)
**Verified:** `curl /predict-batch -d '{"game_date":"TODAY"}' → game_date: 2026-03-22` ✅

#### Bug 3: .gcloudignore missing .venv/ and models/
Cloud Build uploads were 1.1 GiB (15,166 files) instead of 100 MB (3,284 files) because .venv/ (1.7G)
and models/ (327M) weren't excluded. Added both to .gcloudignore.
**Commit:** `aed38023`

### Scheduler Fixes
- `self-heal-predictions`: 900s → 1800s timeout (was DEADLINE_EXCEEDED)
- `nba-props-evening-closing`: already at 1800s, still timing out — workflow runs longer than 1800s. Known issue.

---

## Today's Schedule
```
Mar 22 (today):   5 games  ← 0 picks expected (RED signal)
Mar 23:          10 games  ← first real pick day this week
Mar 24:           4 games  ← mlb-resume-reminder fires 8 AM ET
Mar 25:          12 games  ← biggest NBA slate; lgbm_1215_0214 decision point
Mar 26:           3 games
Mar 27:          10 games  ← MLB Opening Day
```

---

## Immediate Next Steps

### Mar 23 (tomorrow)
- 10-game slate — first real pick volume this week
- Watch avg_edge for lgbm_v12_noveg_train1215_0214 (currently 1.34, approaching collapse threshold ~1.1)

### Mar 24 (2 days)
- `mlb-resume-reminder-mar24` Slack alert fires 8 AM ET
- Run: `./bin/mlb-season-resume.sh` (verifies all MLB jobs ENABLED)
- Verify pitcher props scrapers are operational

### Mar 25 (3 days)
- 12-game NBA slate — biggest volume this week
- `lgbm_v12_noveg_train1215_0214` decision point: deactivate if HR < 52.4%

### Mar 27 (MLB Opening Day, 5 days)
All MLB services are now fixed and ready:
- `mlb-predictions-generate` scheduler → `/predict-batch` with TODAY → working
- `mlb-phase6-grading` → health check passing, grade-shadow fixed
- `mlb-grading-daily` → sends YESTERDAY, processor handles it with `.upper()`
- Verify `mlb_predictions.pitcher_strikeout_predictions` has rows on Mar 27
- `mlb-pitcher-props-validator-4hourly` restricted to Apr-Oct — may need manual trigger

### NBA Ongoing
- Vegas MAE 5.43, approaching 5.0 retrain gate — **keep weekly-retrain CF PAUSED** until <5.0
- Do NOT lower OVER floor to 4.5
- Do NOT re-enable `catboost_v9_low_vegas` (DEGRADING)

---

## Known Constraints (unchanged)
- `weekly-retrain` CF: **KEEP PAUSED** — Vegas MAE 5.43 vs 5.0 gate
- OVER floor: **KEEP AT 5.0**
- `catboost_v9_low_vegas`: **DO NOT RE-ENABLE**

---

## Key Gotchas Learned This Session

**MLB grading service wasn't monitored after Session 481 deploy.**
The service was 503 on all endpoints since deployment due to import error. The mlb-shadow-grading-daily
scheduler's NOT_FOUND error (gRPC 5) was the signal, but it wasn't caught in the prior session because
it fired after the handoff was written. Always test MLB service health with `/health` endpoint after deploy.

**Cloud Run traffic must be explicitly routed to LATEST after `services update`.**
When a service has explicit revision routing (e.g., 100% → 00022-mlg), `gcloud run services update --image`
creates new revisions but they get "Retired" without traffic. Must follow with:
`gcloud run services update-traffic SERVICE --to-latest`
OR use `gcloud run deploy` which defaults to LATEST.

**.gcloudignore missing .venv/ inflates Cloud Build uploads 10x.**
Always check for `.venv/` (dotfile — not caught by `venv/` pattern) and `models/` in .gcloudignore.
The archive was 1.1 GiB → 100 MB after fix. This was causing 10+ minute upload times.

**MLB INTERNAL scheduler failures pre-season are expected.**
mlb-lineups-pregame, mlb-props-morning, etc. fail with INTERNAL when no MLB games exist.
These will resolve once Opening Day arrives (Mar 27). Do not attempt to debug.

---

## Morning Checks (START keyword)
```bash
/daily-steering          # Model health, signal health, macro trends
/validate-daily          # Full pipeline validation
./bin/check-deployment-drift.sh --verbose
/best-bets-config        # BB thresholds, models, signals
```

---

## Deployed Services (current)
| Service | Revision | Status |
|---------|----------|--------|
| prediction-worker | latest (commit 6b631ac) | 100% |
| prediction-coordinator | latest (commit 6b631ac) | 100% |
| nba-grading-service | latest (commit dbfc99a7) | 100% |
| mlb-prediction-worker | 00024-hpd (commit 1f7240b7, TODAY all endpoints) | 100% LATEST |
| mlb-phase6-grading | 00005-622 (commit 1f7240b7, import fix) | 100% |
| nba-phase1-scrapers | STALE (MLB features) | LOW priority |
