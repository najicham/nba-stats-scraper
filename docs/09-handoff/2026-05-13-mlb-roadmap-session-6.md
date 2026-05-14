# Session Handoff — 2026-05-13 — MLB roadmap Session 6 startup

**Prior session (Session 5, evening of 2026-05-13):** Deployed the B1 regime monitor CF + scheduler, test-fired (first state row = MLB/UNDER DEGRADING — HR 30.4%, N=46, all 3 triggers fired). Dropped the B1 backtest temp table. Ran A2 monitor query — no `mlb_v9_max_edge_125` graded data exists yet (first day of picks was today). Confirmed `mlb-best-bets-generate-late` 4:30 PM ET scheduler fired and produced 3 OVER picks under `mlb_v9_max_edge_125`. Marked Session 5 done in `06-MULTI-SESSION-ROADMAP.md`; original Session 5 (A4 deploy) is annotated as SKIPPED. This handoff sets up Session 6.

**Source-of-truth docs:**
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/06-MULTI-SESSION-ROADMAP.md` — canonical plan (Session 6 redefined; A4 deploy skipped)
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/10-A4-DECISION.md` — A4 closure (Session 4)
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/07-A2-MONITOR-QUERY.md` — A2 monitor query
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-5.md` — Session 5 plan
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-4.md` — Session 4 plan

## TL;DR

Sessions 1-5 of the MLB roadmap are complete. Session 5 deployed the B1 regime monitor — UNDER state is **DEGRADING** as of 2026-05-12 (HR 30.4% on 46 graded UNDER predictions over 7 days, slope -4.6pp, z -2.19σ). All three triggers fired on first run. **`SLACK_WEBHOOK_URL_SIGNALS` was NOT set during deploy** — CF deployed with empty env var, alerts no-op until patched. **A2 7-day monitor still pending** (DUE 2026-05-20). Session 6 = UNDER pipeline decision + first NBA-port work (E2 filter CF evaluator). Entry condition is 2026-05-20 minimum to let A2 + B1 accumulate.

## What shipped (Session 5)

| Item | Status |
|---|---|
| `mlb-regime-monitor` Cloud Function (Gen2) deployed to us-west2 | LIVE — revision `mlb-regime-monitor-00001-ges`, URL `https://mlb-regime-monitor-f7p3g7f6ya-wl.a.run.app`. Service account `756957797294-compute@developer.gserviceaccount.com` has `run.invoker` |
| `mlb-regime-monitor-daily` scheduler | ENABLED — cron `0 9 * 3-10 *` UTC, OIDC auth, targets CF URL |
| First state row in `mlb_orchestration.direction_regime_state` | WRITTEN — MLB/UNDER, state DEGRADING since 2026-05-12, last_evaluated_at 2026-05-13 17:42 UTC |
| `test_mlb_predictions.b1_backtest_wf_2024_2025` dropped | DONE — dataset is now empty |
| A2 monitor query test-run | DONE — no `mlb_v9_max_edge_125` graded data yet (picks first appeared today, 3 OVER picks for 2026-05-13); cannot evaluate revert threshold until ≥1 game-day of graded data |
| Confirmed `mlb-best-bets-generate-late` 4:30 PM ET fire works | DONE — 3 `mlb_v9_max_edge_125` OVER picks present for 2026-05-13 |
| Confirmed `mlb-prediction-worker` traffic on latest revision | DONE — `latestRevision=True`, revision `mlb-prediction-worker-00074-xsc` |
| `06-MULTI-SESSION-ROADMAP.md` updated | DONE — Session log added, Session 5 marked complete, original "A4 deploy" Session 5 annotated as SKIPPED, Session 6 prerequisites rewritten |

## B1 state (live)

Read with:
```bash
bq query --use_legacy_sql=false \
  "SELECT sport, direction, state, state_since, last_evaluated_date,
          last_fire_hr_7d, last_fire_n_7d, last_fire_t1, last_fire_t3, last_fire_t4
   FROM \`nba-props-platform.mlb_orchestration.direction_regime_state\`"
```

Current row (2026-05-13 evening):

| sport | direction | state | state_since | last_evaluated_date | hr_7d | n_7d | t1 | t3 | t4 |
|---|---|---|---|---|---|---|---|---|---|
| MLB | UNDER | DEGRADING | 2026-05-12 | 2026-05-12 | 30.4% | 46 | true | true | true |

T1 (absolute HR <40% with N≥35) + T3 (slope -3pp) + T4 (z < -1.5σ) all fired. This is a legitimate signal that the raw regressor's UNDER predictions have degraded — relevant because UNDER is currently DISABLED in production, and B1 is the early-warning indicator for whether to keep it that way.

## Critical follow-up: SLACK_WEBHOOK_URL_SIGNALS

The CF deployed with `SLACK_WEBHOOK_URL_SIGNALS=''` (empty). Alerts silently no-op. Two ways to patch:

```bash
# Option A — env var
export SLACK_WEBHOOK_URL_SIGNALS='https://hooks.slack.com/services/T0900NBTAET/B0AC8KCNGNA/...'
gcloud functions deploy mlb-regime-monitor \
  --project=nba-props-platform --region=us-west2 --gen2 \
  --update-env-vars=SLACK_WEBHOOK_URL_SIGNALS="$SLACK_WEBHOOK_URL_SIGNALS"

# Option B — Secret Manager (preferred long-term)
echo -n 'https://hooks.slack.com/services/...' | gcloud secrets create slack-webhook-signals --data-file=- --project=nba-props-platform
gcloud functions deploy mlb-regime-monitor \
  --project=nba-props-platform --region=us-west2 --gen2 \
  --update-secrets=SLACK_WEBHOOK_URL_SIGNALS=slack-webhook-signals:latest
```

Webhook prefix is documented in `shared/utils/slack_channels.py:31` (`B0AC8KCNGNA/...`) — full URL is sensitive and not in source/secrets currently. User has the URL.

**Until patched:** The CF runs daily and updates `direction_regime_state` correctly. Only the Slack post is silent. State transitions HEALTHY → DEGRADING (or back) will not page anyone.

## Session 6 plan (UNDER pipeline decision + first NBA-port)

**Entry condition:** 2026-05-20 (lets A2 monitor produce signal, B1 accumulate 7+ days of state).

| Step | Effort | Notes |
|---|---|---|
| **1. Patch SLACK_WEBHOOK_URL_SIGNALS on `mlb-regime-monitor`** | 5 min | See above. Don't ship Session 6 without alerts wired. |
| **2. Run A2 7-day monitor** | 15 min | Query in `docs/.../07-A2-MONITOR-QUERY.md`. Decision: hold `MLB_MAX_EDGE=1.25` if Wilson LB ≥ 43.6%, revert otherwise. By 2026-05-20 there should be ~7 days × 3 picks/day = ~21 graded `mlb_v9_max_edge_125` picks. Sample is small; weigh Wilson LB carefully. |
| **3. B1 7-day review** | 15 min | Query `direction_regime_state` daily history (state_since dates). If state stays DEGRADING for 7+ days OR HR_7d trends below 30%, factor into UNDER decision. |
| **4. UNDER pipeline decision** | 30 min | The original Phase C decision tree (Session 6 plan in `06-MULTI-SESSION-ROADMAP.md`) assumed post-Poisson UNDER data — which doesn't exist. Use CURRENT graded UNDER state instead. Three branches: |
|   |   | • **UNDER 7d HR ≥ 56% AND B1 HEALTHY** → enable UNDER live with observation-only filters (skip shadow). Unlikely given current 30% HR. |
|   |   | • **UNDER 7d HR 50-56%** → corrected shadow rollout per Scenario B (45-60 day shadow). Phase D work begins. |
|   |   | • **UNDER 7d HR <50% AND B1 DEGRADING** → leave UNDER disabled, revisit only after model improvements. Move to Scenario C (compound improvements only). |
| **5. Start E2 — Filter CF evaluator** | 2-3h | First NBA-port. Daily CF computes hit rate of BLOCKED picks for MLB filters. Observation only — no auto-demote in Session 6. Model on NBA's `filter-counterfactual-evaluator` CF + `filter_overrides` table. |
| **6. Author Session 7 handoff** | 30 min | Branch path depends on UNDER decision in step 4. |

## Carry-over items

1. **`OPENWEATHERMAP_API_KEY` blocker** for A3 weather pipeline + weather signals. Procedure in Session 2 handoff carry-over #2. Free tier covers usage (30 stadiums × 1/day = 30 calls/day, limit 1000). Weather signals (`WeatherColdUnderSignal`, `ColdWeatherKOverSignal`) silently use mock data until this lands.

2. **Odds API quota check for A5 burst schedulers.** Both burst schedulers still PAUSED in prod. Estimated added load: ~11x current pitcher-props API load. Decision before resuming: enable both OR drop to "conditional fire CF" alternative from `08-A5-CLV-DESIGN.md` Layer C.

3. **X1 lineup pipeline (deferred indefinitely).** `mlb_precompute.lineup_k_analysis` empty since inception. Don't touch unless user explicitly asks.

4. **MLB weather pipeline BLOCKED** — same as #1.

5. **`mlb_precompute.lineup_k_analysis` empty diagnostic** (2026-05-13). Processor wired but never writes rows. Of `pitcher_ml_features`'s 6 lineup-derived features, only `f25` has any non-zero values (119/946). A1 lineup features confirmed vapor; X1 deeper rebuild deferred.

6. **A2 monitor — DUE 2026-05-20.** Carried from Session 4/5. See Session 6 plan step 2.

7. **`MLB_UNDER_ENABLED=false`** in prod. Decision in Session 6 step 4 determines whether to keep it that way.

## Stop conditions for Session 6

ABORT and surface to user if:
- B1 state row missing or stale (last_evaluated_at > 24h old): CF or scheduler broken. Check `gcloud functions logs read mlb-regime-monitor --region=us-west2 --limit 50`.
- A2 Wilson LB < 43.6% on `mlb_v9_max_edge_125` TOTAL row: revert `MLB_MAX_EDGE=1.5` per procedure in `07-A2-MONITOR-QUERY.md`. Defer UNDER work until A2 settled.
- All three Slack alerts fire from B1 in 7 days (HEALTHY → DEGRADING → HEALTHY → DEGRADING): thresholds are still too sensitive; recalibrate before relying on signal.

## What this session will NOT do

- Deploy a new MLB model. RMSE baseline holds.
- Touch NBA system (still in playoffs, halt active).
- Build A4 successor experiments (unless user requests; Lane 11/13 ideas still deferred).
- Re-run A4 walk-forward (closed in Session 4).
- Touch X1 lineup pipeline unless user explicitly asks.

## Useful pointers

- **B1 manual run:**
  ```bash
  PYTHONPATH=. .venv/bin/python bin/monitoring/mlb_regime_monitor.py --dry-run
  PYTHONPATH=. .venv/bin/python bin/monitoring/mlb_regime_monitor.py --as-of 2026-05-19
  ```

- **CF direct invoke:**
  ```bash
  curl -sS -X POST https://mlb-regime-monitor-f7p3g7f6ya-wl.a.run.app \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" -d '{"dry_run": true}'
  ```

- **Read B1 state history** (no built-in history table; this is a single-row-per-(sport,direction) table — to see history, would need to add a `direction_regime_history` table or query CF logs):
  ```bash
  bq query --use_legacy_sql=false \
    "SELECT * FROM \`nba-props-platform.mlb_orchestration.direction_regime_state\`"
  gcloud functions logs read mlb-regime-monitor --region=us-west2 --limit 50
  ```

- **A2 monitor query** — in `07-A2-MONITOR-QUERY.md`, saved-query-able.

## Calendar context

Today is 2026-05-13. MLB regular season mid-stride (~15 events/day). NBA in playoffs (dormant — halt active since ~Mar 28).

Session 6 entry condition: 2026-05-20 minimum (lets A2 monitor + B1 produce signal). Earlier entry is possible if the user wants to start the E2 NBA-port work (which doesn't depend on A2/B1 results) but the UNDER decision step should wait for data.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-roadmap-session-6.md.
Execute Session 6 as described. Confirm A2 + B1 data are accumulating before
making the UNDER decision. Patch SLACK_WEBHOOK_URL_SIGNALS on mlb-regime-monitor
as step 1.
```
