# Session 497 Handoff — 2026-03-27

**Date:** 2026-03-27 (afternoon ET)
**Commits:** `155a1710`, `b89cf0ef`, `f2eaf8ba`

---

## What Happened Today

### MLB Pipeline — 3 Cascading Bugs Fixed

Today was MLB Opening Day. Session 496 had wired the Pub/Sub subscriptions but the pipeline was still broken. Investigation found three independent bugs that would have silently prevented any MLB predictions from ever running.

#### Bug 1: Missing OIDC on Phase 3–6 Push Subscriptions

Session 496 fixed `mlb-phase2-raw-sub` (gave it OIDC) but the remaining four subscriptions had none:

| Subscription | Topic | Had OIDC? |
|---|---|---|
| `mlb-phase2-raw-sub` | `mlb-phase1-scrapers-complete` | ✓ (Session 496) |
| `mlb-phase3-analytics-sub` | `mlb-phase2-raw-complete` | ✗ → **fixed** |
| `mlb-phase4-precompute-sub` | `mlb-phase3-analytics-complete` | ✗ → **fixed** |
| `mlb-phase5-predictions-sub` | `mlb-phase4-precompute-complete` | ✗ → **fixed** |
| `mlb-phase6-grading-sub` | `mlb-phase5-predictions-complete` | ✗ → **fixed** |

Cloud Run rejects unauthenticated push requests with 403. Without OIDC, Pub/Sub retries until DLQ — silently dropping every message.

**Fix:** `gcloud pubsub subscriptions modify-push-config` with `--push-auth-service-account=756957797294-compute@developer.gserviceaccount.com` on all four subs. Also updated `bin/pubsub/setup_mlb_subscriptions.sh` to include OIDC on all subscriptions so future re-runs don't repeat this.

**Applied immediately** (infra change, no deploy needed). Verified: `mlb-phase3-analytics-sub` now shows `oidcToken.serviceAccountEmail` in describe output.

---

#### Bug 2: `analytics_base.py` Hardcoded NBA Topic

`AnalyticsProcessorBase._publish_completion_message()` had:
```python
topic='nba-phase3-analytics-complete'  # HARDCODED
```

MLB analytics processors (`MlbPitcherGameSummaryProcessor`, `MlbBatterGameSummaryProcessor`) inherit from this base. When they completed, they published to the NBA Phase 4 topic — which the NBA Phase 4 orchestrator ignored since it wasn't MLB data. `mlb-phase3-analytics-complete` received nothing. MLB Phase 4 never triggered.

**Fix:** Changed to `TOPICS.PHASE3_ANALYTICS_COMPLETE` — a `@property` that reads `SPORT` env var at call time. With `SPORT=mlb` on the MLB Phase 3 service, it returns `mlb-phase3-analytics-complete`. NBA behavior unchanged.

**Commit:** `b89cf0ef` — auto-deploys `nba-phase3-analytics-processors` and `mlb-phase3-analytics-processors`.

---

#### Bug 3: `precompute_base.py` Hardcoded NBA Topic

Same pattern in `PrecomputeProcessorBase._publish_completion_message()`:
```python
topic='nba-phase4-precompute-complete'  # HARDCODED
```

MLB precompute processors (`MlbPitcherFeaturesProcessor`, etc.) inherit from `PrecomputeProcessorBase`. They were publishing to the NBA Phase 5 topic. MLB Phase 5 (prediction worker) never received a trigger.

**Fix:** Changed to `TOPICS.PHASE4_PRECOMPUTE_COMPLETE` (sport-aware). Commit `f2eaf8ba` — auto-deploys MLB and NBA Phase 4 services.

---

### End-to-End Test

Confirmed OIDC fix is working by directly triggering Phase 3:
```bash
curl -X POST https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"game_date": "2026-03-27", "skip_schedule_check": true}'
# → {"status":"success","processors_run":2,"success_count":2}
```

Phase 3 ran successfully (0 records — games haven't been played yet, expected).

---

## Current State

### MLB Pipeline Status

| Component | Status |
|---|---|
| `mlb-phase2-raw-sub` OIDC | ✓ Fixed Session 496 |
| Phase 3–6 subscription OIDC | ✓ Fixed this session |
| `analytics_base.py` sport-aware topic | ✓ Fixed, deploying |
| `precompute_base.py` sport-aware topic | ✓ Fixed, deploying |
| Opening Day game data in BQ | ✗ Games play tonight (~7 PM ET) |
| Phase 1 scrape | ✗ Runs ~10:30 PM ET tonight |

### NBA State (unchanged from Session 496)

- 0 picks today (Friday) — correct (`friday_over_block` + `under_low_rsc`)
- 4 enabled models (see Session 496 handoff for fleet details)
- `home_over_obs` in observation — home OVER picks eligible tomorrow
- Weekly retrain Monday 5 AM ET

---

## Pending Items for Next Session

### 1. MLB Pipeline Verification (FIRST THING — HIGH PRIORITY)

After Phase 1 runs tonight (~10:30 PM ET), check that the cascade fired:

```bash
# Did Phase 3 run for March 27?
TOKEN=$(gcloud auth print-identity-token --audiences="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
curl -s https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health | python3 -m json.tool

# Check BQ for Phase 3 output (pitcher game summaries)
bq query --nouse_legacy_sql --format=pretty \
  "SELECT MAX(game_date) AS latest, COUNT(*) AS cnt FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\` WHERE game_date >= '2026-03-27'"

# Check for MLB predictions
bq query --nouse_legacy_sql --format=pretty \
  "SELECT prediction_date, COUNT(*) AS cnt FROM \`nba-props-platform.mlb_predictions.pitcher_strikeout_predictions\` WHERE prediction_date >= '2026-03-27' GROUP BY 1 ORDER BY 1 DESC"
```

**If Phase 3 didn't run automatically** (pipeline still broken despite fixes), manually trigger:
```bash
TOKEN=$(gcloud auth print-identity-token --audiences="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
curl -s -X POST https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-03-27"}'
```

### 2. Saturday NBA Picks Verification (~1 PM ET Saturday)

```sql
SELECT recommendation, COUNT(*) AS picks, ROUND(AVG(edge),2) AS avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-28'
GROUP BY 1;
```
**Expected:** 5–15 picks, OVER picks present (`friday_over_block` off, `home_over_obs` in observation).

### 3. CatBoost 0118 Auto-Disable Watch (passive)

```sql
SELECT model_id, state, rolling_hr_7d, rolling_n_7d, consecutive_days_below_alert
FROM nba_predictions.model_performance_daily
WHERE game_date >= '2026-03-28'
  AND model_id = 'catboost_v12_noveg_train0118_0315'
ORDER BY game_date DESC LIMIT 3;
```
Will auto-disable when N ≥ 15 + consecutive_alert ≥ 3. No action needed.

### 4. Monday Retrain (March 30, 5 AM ET)

1. Check Slack `#nba-alerts` for pass/fail
2. If PASS: `./bin/model-registry.sh sync`
3. Watch: `lgbm_v12_noveg_train0103_0227` (54 days old) likely replaced — confirm replacement passes governance
4. Note: `catboost_v12_noveg_train0121_0318` is 0-OVER biased — monitor if it gets retrained

---

## Key Pattern Learned

**When adding multi-sport support to base classes:** Always use `TOPICS.*` properties instead of hardcoded strings. The `TOPICS` singleton uses `@property` decorators that read `SPORT` env var dynamically at call time — not at import time. This makes them safe for services with `SPORT=mlb`.

**Audit checklist for any new processor base class:**
- `_publish_completion_message()` → use `TOPICS.PHASE_X_COMPLETE`, not `'nba-phase-X-...'`
- `_publish_completion_event()` in `processor_base.py` → already correct (`TOPICS.PHASE2_RAW_COMPLETE`)

---

## Commits This Session

| Commit | Description |
|---|---|
| `155a1710` | fix: add OIDC auth to MLB pub/sub subscriptions (phase 3-6) |
| `b89cf0ef` | fix: use sport-aware topic in analytics_base _publish_completion_message |
| `f2eaf8ba` | fix: use sport-aware topic in precompute_base _publish_completion_message |
