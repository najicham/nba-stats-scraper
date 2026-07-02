# Session Handoff — 2026-05-13 — MLB roadmap Session 5 startup

**Prior session (2026-05-13 morning, this afternoon):** Session 4 of the multi-session MLB roadmap. Ran the **A4 Quantile(0.5) walk-forward** (worst of the three loss functions tested — RMSE wins decisively), executed the **B1 historical backtest** which failed with spec thresholds, recalibrated B1 to pass, and built the **B1 regime monitor CF + scheduler** (NOT YET DEPLOYED — user decision needed on Slack webhook env). This handoff sets up Session 5.

**Source-of-truth docs:**
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/06-MULTI-SESSION-ROADMAP.md` — canonical plan
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/10-A4-DECISION.md` — A4 closure write-up (Session 4)
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/09-B1-BACKTEST-QUERY.md` — original B1 design (spec thresholds rejected)
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-4.md` — Session 4 startup

## TL;DR

A4 is **CLOSED** — Quantile(0.5) lost every metric to RMSE (-1.7pp HR, -93.3u P&L). Both Poisson and Quantile were flat-to-worse, triggering the roadmap's "abandon A4, skip Session 5 deploy" branch. Production stays on RMSE. B1 historical backtest **FAILED** the spec thresholds (8 fires/2024, 12 fires/2025 vs ≤3 limit) but **PASSED with recalibrated thresholds** (N≥35, slope -3pp, T1 AND (T3 OR T4) → 1 fire/season each). All B1 code is written and tested locally; **deployment requires user to set `SLACK_WEBHOOK_URL_SIGNALS` and run `deploy.sh`**.

## What shipped (Session 4)

| Item | Status |
|---|---|
| `results/mlb_walkforward_a4_quantile/` — Quantile(0.5) WF | COMPLETE (3 min runtime). 59.0% HR, +138.2u, 7.7% ROI |
| `docs/.../10-A4-DECISION.md` | WRITTEN — RMSE/Poisson/Quantile bake-off + abandon decision |
| B1 historical backtest on 2024-2025 walk-forward UNDER predictions | RUN — spec thresholds rejected |
| `test_mlb_predictions.b1_backtest_wf_2024_2025` (BQ temp table, 6,091 rows) | LOADED — kept for re-use; safe to drop after Session 5 |
| **Recalibrated B1 thresholds** (N≥35, slope -3pp, T1 AND (T3 OR T4)) | VALIDATED — 1 fire/season each on 2024-2025 |
| `mlb_orchestration.direction_regime_state` table (one row per sport/direction) | CREATED in BQ |
| `bin/monitoring/mlb_regime_monitor.py` (standalone CLI, dry-run capable) | WRITTEN + tested locally (DEGRADING right now) |
| `orchestration/cloud_functions/mlb_regime_monitor/{main.py,requirements.txt,deploy.sh}` | WRITTEN — not yet deployed |
| `bin/schedulers/setup_mlb_schedulers.sh` — added `mlb-regime-monitor-daily` entry (UTC, cron `0 9 * 3-10 *`, OIDC auth) | UPDATED (source-of-truth; scheduler NOT yet created in GCP) |

## A4 final verdict (closed)

| Metric | RMSE | Poisson | Quantile(0.5) |
|---|---|---|---|
| BB HR | **60.7%** | 60.2% | 59.0% |
| P&L | **+231.5u** | +186.8u | +138.2u |
| ROI | **12.0%** | 10.4% | 7.7% |
| 2025-04 HR | **53.9%** | 47.9% | 50.7% |

Both alternatives lose every metric. Production retrain (`train_regressor_v2.py:83`) stays on `loss_function='RMSE'`. The `--loss-function` CLI flag (Session 3) remains as the override path for future experiments but is NOT used by `weekly_retrain` CF.

**No deploy work needed in Session 5.** The roadmap's Session 5 (A4 deploy) is skipped entirely. Resume at Session 6.

## B1 backtest results

**Spec thresholds** (`09-B1-BACKTEST-QUERY.md`: T1 N≥25, slope -2pp, T1 OR (T3 AND T4)) — **FAILED stop condition**:

| Season | combined_fires | t1_fires | t3∧t4_fires |
|---|---|---|---|
| 2024 | 8 | 6 | 4 |
| 2025 | 12 | 7 | 6 |

Spot-check confirmed the failure mode: T3∧T4 cluster fires at low N (6-19) where day-to-day HR swings of 10pp+ are common — false positives from noise, not regime degradation.

**Recalibrated thresholds** (Session 4: T1 N≥35, slope -3pp, T1 AND (T3 OR T4)) — **PASSES**:

| Season | combined_and_fires | t1_only_fires |
|---|---|---|
| 2024 | 1 | 1 |
| 2025 | 1 | 2 |

T3 and T4 became corroborating signals rather than independent triggers; T1's volume floor doubled. The "AND" structure means at least one of {slope, z-score} must agree with T1's absolute-level breach.

**Production data check (2026-05-12 evaluation):** 7d HR = 30.4% (N=46), z = -2.19σ, slope -4.6pp. ALL THREE triggers fire. **The first production run of B1 will alert immediately** — the regime IS legitimately degrading right now.

## Session 5 plan (deploy B1 + finalize carry-overs)

| Step | Effort | Notes |
|---|---|---|
| **1. Deploy `mlb-regime-monitor` CF** | 10 min | `export SLACK_WEBHOOK_URL_SIGNALS=...; ./orchestration/cloud_functions/mlb_regime_monitor/deploy.sh`. Webhook is REQUIRED for alerts; deploy will still succeed without it (alerts silently no-op). |
| **2. Create `mlb-regime-monitor-daily` scheduler** | 5 min | `./bin/schedulers/setup_mlb_schedulers.sh` — idempotent, skips existing jobs. Verify with `gcloud scheduler jobs describe mlb-regime-monitor-daily --location=us-west2`. |
| **3. Test-fire the CF** | 5 min | `gcloud scheduler jobs run mlb-regime-monitor-daily --location=us-west2 --project=nba-props-platform`. Expected: 200, prior_state=null, new_state=DEGRADING, transition=DEGRADING, alert_sent=true (if webhook set). |
| **4. Verify state row written** | 2 min | `bq query --use_legacy_sql=false "SELECT * FROM \`nba-props-platform.mlb_orchestration.direction_regime_state\`"` — expect one MLB/UNDER row in DEGRADING. |
| **5. Drop B1 backtest temp table** | 1 min | `bq rm -f -t nba-props-platform:test_mlb_predictions.b1_backtest_wf_2024_2025` — safe to delete after Session 5; results captured in this doc. |
| **6. Run A2 7-day monitor** | 15 min | DUE 2026-05-20. Use query in `docs/.../07-A2-MONITOR-QUERY.md`. Decide MAX_EDGE 1.25 vs 1.5. |
| **7. Update roadmap doc** | 15 min | Mark Session 5 done in `06-MULTI-SESSION-ROADMAP.md`. Cross out A4 deploy. Set Session 6 as next active session. |
| **8. Author Session 6 handoff** | 30 min | Resume MLB roadmap at Session 6 (UNDER pipeline decision, X1 lineup pipeline pending). |

**Optional in Session 5** (defer to Session 6 if time-constrained):
- Wire `SLACK_WEBHOOK_URL_SIGNALS` to Secret Manager instead of env var (`--update-secrets=SLACK_WEBHOOK_URL_SIGNALS=projects/...`). The deploy script currently uses `--update-env-vars` for simplicity; Secret Manager is cleaner but requires the secret to exist.

## Stop conditions for Session 5

ABORT and surface to user if:
- B1 CF deploy fails: check `gcloud functions logs read mlb-regime-monitor --region=us-west2 --limit 50`. Most likely cause: `functions-framework` import error (rare; pin version in requirements.txt if so) or BQ permissions (service account `756957797294-compute@developer.gserviceaccount.com` needs `bigquery.dataEditor` on `mlb_orchestration` dataset — should already be granted).
- Test-fire returns non-200 OR `alert_sent=false` AND Slack webhook IS set: investigate webhook URL, channel routing.
- State row writes prior_state=DEGRADING (instead of null) on first run: someone manually inserted a row; drop it and re-run.

## Carry-over items

1. **A2 7-day monitor — DUE 2026-05-20.** Pending. See Session 4 handoff carry-over #1. Query in `docs/.../07-A2-MONITOR-QUERY.md`. If `mlb_v9_max_edge_125` total Wilson LB < 43.6%, revert with `gcloud run services update mlb-prediction-worker --update-env-vars="MLB_MAX_EDGE=1.5" --region=us-west2`.

2. **Verify 4:30 PM ET fire of `mlb-best-bets-generate-late` (2026-05-13).** Session 4 verification was inconclusive — scheduler is ENABLED, schedule is `30 16 * 3-10 *` ET (= 20:30 UTC), but only `mlb_v8_s456_v3final_away_5picks` picks existed at 16:00 UTC when checked. Re-check at start of Session 5:
   ```bash
   bq query --use_legacy_sql=false "SELECT DISTINCT algorithm_version, COUNT(*) as n FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` WHERE game_date = '2026-05-13' GROUP BY 1 ORDER BY 1"
   ```
   Expected: `mlb_v9_max_edge_125` rows present after 20:30 UTC 2026-05-13. If only `mlb_v8...`, check `gcloud run services describe mlb-prediction-worker --region=us-west2 --format="value(status.traffic[0].latestRevision)"` — must be `True` (latest-revision routing). The build that bumped algorithm_version was `mlb-prediction-worker-00055-pv8` (Session 524 retrain Apr 2024-Sep 2025).

3. **`OPENWEATHERMAP_API_KEY` blocker** for A3 Components A+B. Procedure in Session 2 handoff carry-over #2. Free tier covers usage (30 stadiums × 1/day = 30 calls/day, limit 1000).

4. **Odds API quota check for A5 burst schedulers.** Both burst schedulers still PAUSED in prod. Estimated added load: ~11x current pitcher-props API load. Decision before resuming: enable both OR drop to "conditional fire CF" alternative from `08-A5-CLV-DESIGN.md` Layer C.

5. **X1 lineup pipeline (deferred indefinitely).** Don't touch unless user explicitly asks.

6. **MLB weather pipeline BLOCKED** — `mlb_weather` scraper needs `OPENWEATHERMAP_API_KEY` (same blocker as #3). Weather signals (`WeatherColdUnderSignal`, `ColdWeatherKOverSignal`) silently use mock data (75°F neutral) until this lands.

7. **`mlb_precompute.lineup_k_analysis` empty (2026-05-13 diagnostic).** Processor wired but never writes rows. Of `pitcher_ml_features`'s 6 lineup-derived features, only `f25` has any non-zero values (119/946). A1 lineup features confirmed vapor; X1 deeper rebuild deferred.

## What this session will NOT do

- Anything UNDER-related in production. UNDER stays disabled. B1 monitors the raw regressor's UNDER predictions in `prediction_accuracy` (which are graded but not published) — B1 is a leading indicator for IF/WHEN UNDER is ever turned on.
- Retrain or deploy a new MLB model. RMSE baseline holds.
- Touch the NBA system (still in playoffs, halted).

## Useful pointers

- **B1 monitor manual run** (after CF deploy):
  ```bash
  # Dry-run, evaluates yesterday ET:
  curl -X POST https://mlb-regime-monitor-f7p3g7f6ya-wl.a.run.app \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" -d '{"dry_run": true}'

  # Evaluate a specific historical date:
  curl ... -d '{"target_date": "2026-05-12", "dry_run": true}'
  ```

- **B1 standalone Python run** (no CF needed):
  ```bash
  PYTHONPATH=. .venv/bin/python bin/monitoring/mlb_regime_monitor.py --dry-run
  PYTHONPATH=. .venv/bin/python bin/monitoring/mlb_regime_monitor.py --as-of 2026-05-12
  ```

- **A4 walk-forward A/B harness** (still operational for future loss functions):
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2024-04-01 --end-date 2025-10-01 \
    --output-dir results/mlb_walkforward_a4 \
    --loss-function "Quantile:alpha=0.5" --output-tag quantile
  ```
  Output: `results/mlb_walkforward_a4_<tag>/simulation_summary.json`. Three runs already exist in `results/mlb_walkforward_a4_{rmse,poisson,quantile}/` for reference.

- **Drop B1 backtest temp table** (after Session 5):
  ```bash
  bq rm -f -t nba-props-platform:test_mlb_predictions.b1_backtest_wf_2024_2025
  ```

## Calendar context

Today is 2026-05-13. MLB regular season mid-stride (~15 events/day). NBA in playoffs (dormant — halt active since ~Mar 28). Session 5 entry condition: "user reads this handoff" + has Slack webhook env var ready.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-roadmap-session-5.md.
Execute Session 5 as described. Start with deploying the B1 monitor CF.
Make sure SLACK_WEBHOOK_URL_SIGNALS is exported in the shell before running deploy.sh.
```
