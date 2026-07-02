# Session Handoff — 2026-05-16 (Session 2) — Admin dashboard deploy + bias CF wiring

**Predecessor:** [`2026-05-16-bias-monitoring-and-model-health-dashboard.md`](2026-05-16-bias-monitoring-and-model-health-dashboard.md). That session shipped the bias monitoring code + Model Health dashboard page; this session deployed them.

## TL;DR

1. **Verified the bias columns on `model_performance_daily` work** — backfilled rows for Apr 12/15/17 have populated `pred_bias_7d` (-2.73 to -3.44 K) and `mae_gap_7d` (0.58–0.87 K). Last night's row is NULL because NBA has been halted since Apr 17 — expected, not a bug.
2. **`/model-health` page is LIVE** at `https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/model-health?key=…`. Required an unrelated Dockerfile fix — `WORKDIR /app/services/admin_dashboard` was shadowing the `services` namespace package via the sibling `services/` subdir, breaking `from services.admin_dashboard…` imports. Both rev 22 and rev 23 had been silently broken; nobody noticed because NBA halted before anyone hit the page.
3. **`bias_decay_monitor` Cloud Function deployed**. HTTP-triggered Gen2 CF at `https://bias-decay-monitor-f7p3g7f6ya-wl.a.run.app`. Cloud Scheduler `bias-decay-monitor-daily` created at 11:30 ET, **currently PAUSED while NBA is halted**. First two test-fires surfaced missing `google-cloud-firestore` (fixed in `d6510052`) and `google-cloud-storage` (fixed in `8fdb2a66`) — both deps are pulled in transitively by `shared.monitoring/__init__.py` → `processor_heartbeat` and the `shared.clients` chain. Rebuild in flight.
4. **`OPENWEATHERMAP_API_KEY` plumbed end-to-end** — secret created, IAM granted to `756957797294-compute@developer.gserviceaccount.com`, mounted on `mlb-phase1-scrapers`, `mlb-weather-pregame` scheduler created PAUSED at 11:30 ET. Live key still returning **401 from OWM** — free-tier keys take ~2 hours to activate. Re-test before resuming.
5. **Best-bets situation diagnosed for the user** — NBA `halt_state` is `between_rounds` (`halt_since 2026-05-10`, `games_today=0`, `has_future_games_14d=false`); MLB May 14–16 had zero picks because `avg_abs_edge` collapsed to 0.38–0.47 K (below the 0.75 K home OVER floor). System working as designed.

## What landed (commits)

### `a51f37e7` — feat(monitoring): wrap bias_decay_monitor as Cloud Function

| File | Change |
|---|---|
| `orchestration/cloud_functions/bias_decay_monitor/main.py` | **New** — mirrors `signal_decay_monitor` pattern. Wraps `bias_decay_monitor_impl.http_handler` (the impl is copied alongside main.py by the Cloud Build step via `MONITOR_MAP`). |
| `orchestration/cloud_functions/bias_decay_monitor/requirements.txt` | **New** — minimal set; deps added in follow-up commits. |
| `cloudbuild-functions.yaml` | Added `bias_decay_monitor` to the `MONITOR_MAP` so `bin/monitoring/bias_decay_monitor.py` is renamed `bias_decay_monitor_impl.py` in the deploy package. |

Live infra also created this session (not in git):
- Cloud Build trigger `deploy-bias-decay-monitor` (mirrors `deploy-signal-decay-monitor` watch paths, plus `shared/monitoring/**` and `bin/monitoring/bias_decay_monitor.py`).
- Cloud Scheduler `bias-decay-monitor-daily` (30 11 \* \* \* America/New_York, OIDC `756957797294-compute@…`, currently PAUSED).

### `d6510052` — chore: add OWM secret deps + mlb-weather-pregame scheduler entry

| File | Change |
|---|---|
| `orchestration/cloud_functions/bias_decay_monitor/requirements.txt` | Added `google-cloud-firestore>=2.11.0`. `shared.monitoring/__init__.py` eager-imports `processor_heartbeat`, which does `from google.cloud import firestore` unconditionally. |
| `bin/schedulers/setup_mlb_schedulers.sh` | Documented `mlb-weather-pregame` (already created live via gcloud at 11:30 ET, PAUSED until OWM key activates). |

Live infra also created this session (not in git):
- Secret `OPENWEATHERMAP_API_KEY` (single version, raw key).
- IAM binding: `roles/secretmanager.secretAccessor` granted to `756957797294-compute@developer.gserviceaccount.com`.
- `mlb-phase1-scrapers` revision `00020-9xx` mounts the secret as env var (used `--update-secrets`, preserved existing `BDL_API_KEY`, `BETTINGPROS_API_KEY`, `DECODO_PROXY_CREDENTIALS`, `SLACK_WEBHOOK_URL`).
- Cloud Scheduler `mlb-weather-pregame` (30 11 \* \* \* America/New_York, PAUSED).

### `8fdb2a66` — fix: admin dashboard WORKDIR + bias_decay_monitor storage dep

| File | Change |
|---|---|
| `services/admin_dashboard/Dockerfile` | Moved `WORKDIR` from `/app/services/admin_dashboard` to `/app`; qualified `CMD` to `services.admin_dashboard.main:app`. Live image rev `nba-admin-dashboard-00024-rqx` already has the fix; this commit just keeps the next CI rebuild healthy. |
| `orchestration/cloud_functions/bias_decay_monitor/requirements.txt` | Added `google-cloud-storage>=2.0.0`. Same eager-import chain as firestore: `shared/clients/__init__.py` wraps storage in try/except, but `shared.utils.scraper_logging` / `smart_alerting` (pulled in transitively elsewhere) import it directly. |

## Verification — first 24 hours

### 1. Confirm bias-decay CF deploys clean from `8fdb2a66` and test-fires return ok

```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=3 \
  --filter='substitutions.TRIGGER_NAME:bias' \
  --format='table(id,status,createTime.date("%H:%M",tz=America/Los_Angeles))'
# Expect newest build SUCCESS, started ~16:50 PT on 2026-05-16

curl -s -X POST https://bias-decay-monitor-f7p3g7f6ya-wl.a.run.app | head -c 300
# Expect: '{"status": "ok"}' or 'No model_performance_daily rows found'
# NOT: 'cannot import name X from google.cloud'
```

If still failing with another missing import, just add the dep to the CF's `requirements.txt`. Three commits in for this pattern — the right long-term fix is to make `shared.monitoring/__init__.py` lazy-import `processor_heartbeat`, but that's a separate refactor.

### 2. Re-test OWM key activation (~2 hours after secret creation @ 16:30 PT)

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  'https://api.openweathermap.org/data/2.5/weather?lat=40&lon=-74&appid=56be88c49799e497c7d3405709e62e35'
# Expect 200 once activated. If still 401 after ~6h, the key may be wrong.

# If 200, resume the scheduler:
gcloud scheduler jobs resume mlb-weather-pregame --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs run    mlb-weather-pregame --location=us-west2 --project=nba-props-platform
# Then check mlb_raw.mlb_weather (or wherever the scraper writes) for non-mock rows.
```

### 3. Resume `bias-decay-monitor-daily` only after NBA Round 2 starts

Currently PAUSED with no graded predictions in scope; firing now would just log "No model_performance_daily rows found" and exit 200. When NBA Round 2 begins (~June 3):

```bash
gcloud scheduler jobs resume bias-decay-monitor-daily --location=us-west2 --project=nba-props-platform
```

Also: `filter-counterfactual-evaluator-daily` is PAUSED for the same reason and needs the same resume action — flag with the user before doing it.

## Open work — ordered by priority

### 🔥 Immediately (~30 min)

1. **Confirm `8fdb2a66` rebuild succeeded and test-fire bias-decay CF clean.** (Section 1 above.)
2. **Decide: resume `filter-counterfactual-evaluator-daily` now or wait for Round 2?** Pre-decided in predecessor handoff to keep it running — verify with a query against `filter_counterfactual_daily` whether the auto-pause was deliberate this session or pre-existing.

### 🟡 This week (~1 day)

3. **30-min triage of MLB `mlb_precompute.lineup_k_analysis` empty table.** Unchanged from predecessor — start by checking 7d freshness of `mlb_raw.mlb_lineup_batters` (MEMORY says 8/14 days populated). 6 of `pitcher_features`'s lineup-derived features (f25/f26/f27/f33/f34/f44) are vapor; only f25 has any nonzero values.
4. **3 deferred Slack→Secret Manager migrations.** Unchanged from predecessor — still needs channel-naming decision from user before proceeding:
   - `shadow-performance-report` `SLACK_WEBHOOK_URL`
   - `validation-runner` `SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH`
   - `mlb-regime-monitor` `SLACK_WEBHOOK_URL_SIGNALS`

### 🔵 Pre-Tier-2 architectural cleanup (~1 day)

5. **Extract SQL `consec` CTE helper** in `shared/monitoring/bias_decay_thresholds.py` so `bias_decay_monitor.py` and the admin dashboard share windowing SQL. Predecessor item #6.
6. **Add `extra_metrics JSON` column to `model_performance_daily`** to absorb Tier 2 diagnostics. Predecessor item #7.
7. **Make `shared.monitoring/__init__.py` lazy-load `processor_heartbeat`.** Discovered this session — the eager import forces every CF that touches `shared.monitoring.*` to ship `google-cloud-firestore` even if it doesn't need it. Three commits in this session were unnecessary deps cascading from this one design choice. Pattern fix: move heartbeat exports behind a function or `__getattr__` shim.

### 🟢 Days 8-30 — Tier 2 prevention (~2 days)

8. **Tier 2.4 fleet-diversity monitor.** Unchanged from predecessor #8.
9. **Tier 2.3 training-data recency gate.** Unchanged from predecessor #9.
10. **MLB Path D — auto-retrain CF.** Unchanged from predecessor #10.

### ⚪ Days 31-60 — NBA pre-resumption (~June 3)

11. **Pre-resumption retrain.** Unchanged from predecessor #11.
12. **Verify `weekly-retrain` fires June 8.** Unchanged from predecessor #12.
13. **Verify `bias-decay-monitor-daily` fires once unpaused** and writes a sensible Slack message to `#nba-betting-signals` (currently the alerter falls back to `SLACK_WEBHOOK_URL` because the CF doesn't have `SLACK_WEBHOOK_URL_SIGNALS` mounted). Decide whether to mount the signals webhook or leave fallback.

### ❌ Explicitly deferring

- **Tier 2.2 Bayesian calibration layer** — unchanged.
- **`source_blocks_bp` cleanup** — unchanged (resilient loader contains it).
- **Tier 1.1 NBA pre-season cold-boot retrain** — unchanged.

## Operational state at handoff

- **NBA halted between rounds.** `halt_state.halt_active=true` since 2026-05-10, `halt_reason='between_rounds'`. No live picks until Round 2 starts (~June 3). Latest graded NBA prediction is Apr 17.
- **MLB in season, low-edge.** Days 5/14–5/16 produced 0 picks because `avg_abs_edge` 0.38–0.47 K is under the 0.75 K home OVER floor. Picks resume automatically when the market loosens.
- **`/model-health` page live.** Shows 3 NBA models all `INSUFFICIENT_DATA` (correct — rolling_n_7d=0 with NBA halted). Page will populate once Round 2 graded predictions arrive.
- **Both new schedulers (`bias-decay-monitor-daily`, `mlb-weather-pregame`) are PAUSED.** Don't resume until verifications above complete.
- **Auto-deploys still triggering on push to main.** This session's three commits triggered the standard cascade plus the new `deploy-bias-decay-monitor` trigger. All builds SUCCESS as of last check.
- **Three unstaged commits in tree are unrelated.** `git status` shows 1284 files modified with trailing-whitespace-only deltas across `bin/`, `validation/`, `data_processors/` etc. Not this session's work — pre-existing. Don't `git add -A`; stage explicit files only.

## What we learned (process notes)

1. **Don't call `ScheduleWakeup` outside `/loop` mode.** I scheduled one mid-session by mistake. The harness re-invoked itself ~4 min later with the `<<autonomous-loop-dynamic>>` sentinel; harmless this time because there was real follow-up work, but cancel/skip the call if not in a loop.
2. **Local `docker build` + push to GCR needs `gcloud auth configure-docker`.** First admin-dashboard deploy attempt via `services/admin_dashboard/deploy.sh` died at the push step with `Unauthenticated request … artifactregistry.repositories.uploadArtifacts`. Workaround was `gcloud builds submit --config=/dev/stdin` with an inline build YAML — faster anyway (no local Docker image to push).
3. **Eager imports in `shared/*/__init__.py` cascade into every CF that touches them.** Three rebuilds this session each added one missing `google.cloud.*` dep. Treat this as a real architecture smell — see item #7 above.
4. **When staging into a tree with pre-existing whitespace deltas, use `git checkout HEAD -- file` to reset before re-applying targeted edits.** Otherwise `git diff --cached` is impossible to review. Hit this twice on `bin/schedulers/setup_mlb_schedulers.sh`.
5. **Cloud Build trigger creation via `gcloud builds triggers create github` is finicky** — `INVALID_ARGUMENT` with no detail. `gcloud builds triggers import --source=…yaml` (export an existing trigger, edit, re-import) worked first try.

## Key references

- **Live admin dashboard:** `https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/model-health?key=2213d5889a51120549ef3abe5546cb7f`
- **Live bias-decay CF:** `https://bias-decay-monitor-f7p3g7f6ya-wl.a.run.app`
- **Predecessor handoff:** `docs/09-handoff/2026-05-16-bias-monitoring-and-model-health-dashboard.md`
- **Anomaly diagnosis:** `docs/08-projects/current/2026-05-15-2025-26-anomaly-rootcause/00-FINDINGS.md`
- **Shared thresholds:** `shared/monitoring/bias_decay_thresholds.py`
- **CF deploy template:** `cloudbuild-functions.yaml` (single parametric build used by ~20 CFs)

## First message for the next session

> Read `docs/09-handoff/2026-05-16-2-admin-dashboard-deploy-and-bias-cf-wiring.md`.
>
> Start by running the three verification checks in the "Verification — first 24 hours" section:
> 1. Confirm `8fdb2a66` rebuilt the bias-decay CF clean and a test-fire returns `{"status": "ok"}`.
> 2. Re-test the OWM key with `curl …openweathermap.org/data/2.5/weather?…` — if 200, resume `mlb-weather-pregame` scheduler and test-fire the `mlb_weather` scraper.
> 3. Decide whether to resume `filter-counterfactual-evaluator-daily` now or wait for NBA Round 2.
>
> Then pick the highest-priority "Open work" item that's not blocked.
