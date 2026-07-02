# Session Handoff — 2026-05-13 — MLB roadmap Session 4 startup

**Prior session (2026-05-13, this afternoon):** Session 3 of the multi-session MLB roadmap. Shipped the **A5 CLV foundation** end-to-end (schema, materializer CF, daily scheduler, backfill, paused burst schedulers) and completed the **A4 Poisson vs RMSE walk-forward A/B** in foreground (much faster than the 4-12h estimate — both runs finished in ~3 minutes each). This handoff sets up Session 4.

**Source-of-truth docs:**
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/06-MULTI-SESSION-ROADMAP.md` — canonical plan
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/09-B1-BACKTEST-QUERY.md` — Session 4 build spec (B1 backtest design)
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-3.md` — Session 3 startup

## TL;DR

A5 is live and collecting (table exists, materializer scheduled, backfill loaded 9,928 historical rows). Burst schedulers exist PAUSED — Odds API quota check is the only blocker to enabling. A4's Poisson vs RMSE bake-off is done: **RMSE wins all four metrics** (HR, P&L, ROI, picks/day). Per the roadmap's branch logic, Session 4 should drop Poisson and try **Quantile(0.5)** before deciding A4's deploy fate.

## What shipped (Session 3)

| Item | Status |
|---|---|
| `mlb_raw.pitcher_props_closing` table (21 cols, partitioned by `game_date`, clustered by `player_lookup, bookmaker`) | CREATED in BQ |
| `mlb_predictions.prediction_accuracy` ALTER — 7 new CLV cols (`pick_time_line`, `closing_line`, `closing_bookmaker`, `closing_snapshot_time`, `clv_raw`, `clv_directional`, `clv_quality_flag`) | APPLIED |
| `orchestration/cloud_functions/mlb_pitcher_props_closing_materializer/` CF (Gen2, idempotent, 180-min closing window) | DEPLOYED + test-fired on 2026-05-03 → 187 rows |
| `mlb-pitcher-props-closing-materialize` scheduler (cron `0 9 * 3-10 *` UTC, body `{}`) | CREATED ENABLED |
| `bin/mlb/backfill_pitcher_props_closing.sql` (one-time, 720-min window for historical capture) | EXECUTED → 9,928 rows over 43 dates (2026-03-27 → 2026-05-12) |
| `mlb-oddsa-pitcher-props-burst-afternoon` (cron `0,30 13-19 * 3-10 *` ET) | CREATED **PAUSED** (quota check required) |
| `mlb-oddsa-pitcher-props-burst-evening` (cron `0,30 0-3 * 3-10 *` UTC) | CREATED **PAUSED** |
| `bin/schedulers/setup_mlb_schedulers.sh` updated with both burst entries | SOURCE-OF-TRUTH committed (paused-on-create helper added) |
| `scripts/mlb/training/{train_regressor_v2,season_replay}.py` — added `--loss-function` CLI flag (default `RMSE` — zero behavior change) + `--output-tag` on `season_replay.py` | CHANGED |
| A4 walk-forward: RMSE vs Poisson, 2024-04-01 → 2025-10-01, 14-day retrain | BOTH RUNS COMPLETE |

Schema migration applied via stdin (the `bq query` shell expansion of `--` SQL comments breaks `argparse`; use `bq query < file.sql` for any future ALTER/CREATE).

## A4 walk-forward A/B results

Both ran against the same 6,409-sample 2024-04-01 → 2025-10-01 replay, 14-day fixed retrain, identical hyperparameters except `loss_function`.

| Metric | RMSE (control) | Poisson (challenger) | Δ |
|---|---|---|---|
| Best Bets record | 933-603 | 878-581 | -55 / -22 |
| HR | **60.7%** | 60.2% | -0.5pp |
| P&L | +231.5u | +186.8u | -44.7u |
| ROI | 12.0% | 10.4% | -1.6pp |
| Picks/day | 4.5 | 4.3 | -0.2 |
| Ultra HR | 68.1% (N=395) | 66.3% (N=338) | -1.8pp |
| Home HR | 64.3% | 63.9% | -0.4pp |
| Away HR | 56.7% | 56.0% | -0.7pp |
| 2025-04 HR | 53.9% (+3.1u) | 47.9% (-6.9u) | **-6pp** (Poisson tanks April) |

**Verdict per the roadmap's branch logic:** Poisson is **FLAT** (lost by 0.5pp HR, < 2pp threshold). Branch: "If Poisson WF flat → fall back to Quantile(0.5), redo WF." That's Session 4's first task before B1.

Raw logs: `/tmp/wf_rmse.log` (full report), `/tmp/wf_poisson.log` (same). Result CSVs: `results/mlb_walkforward_a4_rmse/`, `results/mlb_walkforward_a4_poisson/` (best_bets_picks.csv, all_predictions.csv, daily_summary.csv, retrain_log.csv, model_inventory.csv, simulation_summary.json — same layout as season_replay normal output).

Walk-forward speed surprise: the handoff doc estimated 4-12h compute; reality was ~3 min/run on the dev box. The `season_replay.py` retrain cadence (14 days = 25 retrains over 351 game days) plus modest training samples per retrain (~3K-5K rows) keep CatBoost training under 5s per retrain.

## Session 4 plan (per roadmap, 3-4h)

| Step | Effort | Notes |
|---|---|---|
| **A4 Quantile(0.5) WF** | 10 min | `PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py --start-date 2024-04-01 --end-date 2025-10-01 --output-dir results/mlb_walkforward_a4 --loss-function "Quantile:alpha=0.5" --output-tag quantile`. Compare to RMSE baseline. If still flat/worse, **abandon A4 entirely** → skip to Session 6 with current model. |
| B1 backtest on 2024/2025 | 1h | Run the false-positive check from `09-B1-BACKTEST-QUERY.md`. If T1 fires > 3 times/season historically, recalibrate thresholds before building. |
| B1 build | 2h | Assumes backtest validates. Extend `bin/monitoring/mlb_daily_performance.py`. Slack alerts to `#nba-alerts`. |
| A4 decision write-up | 30 min | Document RMSE vs Poisson vs Quantile (if run) and recommendation for Session 5. |

**Deploy at session end:** B1 monitor live. A4 deploy decision documented but NOT executed.

**Branch on A4 final result (after Quantile run):**
- Quantile beats RMSE by ≥ 2pp HR → proceed to Session 5 deploy with Quantile.
- Both Poisson and Quantile flat-to-worse → **abandon A4**, skip Session 5, jump to Session 6 with current RMSE model.

## Stop conditions for Session 4

ABORT and surface to user if:
- Quantile WF crashes (less mature CatBoost path; check feature contract).
- B1 historical backtest fires > 3 times/season — recalibrate thresholds before building, OR drop B1 entirely if the data suggests it's miscalibrated by design.
- `mlb_raw.pitcher_props_closing` shows < 50% `true_closing=true` row coverage starting 24h after the burst schedulers were enabled (i.e., Session 4 starts with bursts paused; if user enables them between sessions, Session 4 should verify the materializer is finding within-30-min snapshots before relying on the data).

## Carry-over items

1. **A2 7-day monitor — DUE 2026-05-20.** Still pending. Run query in `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/07-A2-MONITOR-QUERY.md`. If `mlb_v9_max_edge_125` total Wilson LB < 43.6%, revert with `gcloud run services update mlb-prediction-worker --update-env-vars="MLB_MAX_EDGE=1.5" --region=us-west2`.

2. **4:30 PM ET fire of `mlb-best-bets-generate-late` (2026-05-13).** The handoff doc for Session 3 expected this fire to have already happened, but Session 3 started at 15:24 UTC and the cron is 20:30 UTC. The build that bumped `algorithm_version` to `mlb_v9_max_edge_125` completed at 15:06 UTC, so the 20:30 fire should produce `mlb_v9` picks. **Verify at start of Session 4:**
   ```bash
   gcloud scheduler jobs describe mlb-best-bets-generate-late --project=nba-props-platform --location=us-west2 --format="yaml(lastAttemptTime,status)"
   bq query --use_legacy_sql=false "SELECT DISTINCT algorithm_version, COUNT(*) FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` WHERE game_date = '2026-05-13' GROUP BY 1"
   ```
   Expected: `mlb_v9_max_edge_125` rows present. If still only `mlb_v8...`, the 20:30 fire either didn't happen or the worker is on a stale revision — check `gcloud run services describe mlb-prediction-worker` for the latest-revision routing.

3. **`OPENWEATHERMAP_API_KEY` blocker** for A3 Components A+B. Procedure in Session 2 handoff carry-over #2. Free tier covers usage (30 stadiums × 1/day = 30 calls/day, limit 1000).

4. **Odds API quota check for A5 burst schedulers.** Both burst schedulers are PAUSED in prod. Estimated added load: 22 fires/day × ~15 events × 1 market (`pitcher_strikeouts`) × 1 region. Existing `mlb-props-morning` + `mlb-props-pregame` total 2 fires/day. New bursts add ~11x the current pitcher-props API load. **Decision before resuming:**
   - If monthly Odds API budget tolerates 11x: enable both with `gcloud scheduler jobs resume mlb-oddsa-pitcher-props-burst-afternoon …` and `… burst-evening …`.
   - If not: drop to the cheaper "conditional fire CF" alternative from `08-A5-CLV-DESIGN.md` Layer C (5-min cadence scheduler → CF that checks `mlb_reference.mlb_schedule` and only invokes the scraper when first pitch is within 90 min).

5. **X1 lineup pipeline (deferred indefinitely).** A1 features confirmed vapor in Session 1's X2 verification. Don't touch unless the user explicitly asks.

## What this session will NOT do

- Promote A5 to influence predictions/picks — still observation-only data collection in Sessions 3-4. Auto-demote integration lives in Session 5+.
- Deploy A4 — Session 5, requires user approval per CLAUDE.md governance gates.
- Anything UNDER-related — Phase C decision lives in Session 6 (after ≥14 days of post-A4-deploy data, if A4 ships at all).

## Useful pointers

- A5 materializer CF: `https://mlb-pitcher-props-closing-materialize-f7p3g7f6ya-wl.a.run.app/`, fires daily 09:00 UTC. Idempotent on `target_date` (defaults to yesterday ET). To replay a specific date manually:
  ```bash
  gcloud scheduler jobs update http mlb-pitcher-props-closing-materialize \
    --location=us-west2 --project=nba-props-platform \
    --message-body='{"target_date": "YYYY-MM-DD"}'
  gcloud scheduler jobs run mlb-pitcher-props-closing-materialize \
    --location=us-west2 --project=nba-props-platform
  # then reset body
  gcloud scheduler jobs update http mlb-pitcher-props-closing-materialize \
    --location=us-west2 --project=nba-props-platform --message-body='{}'
  ```
- A4 walk-forward A/B harness: `scripts/mlb/training/season_replay.py --loss-function {RMSE,Poisson,Quantile:alpha=0.5} --output-tag <tag>`. Output goes to `results/mlb_walkforward_a4_<tag>/`. Compare runs by `cat results/.../simulation_summary.json` or `head -85 /tmp/wf_<tag>.log`.
- The `train_regressor_v2.py:83` `loss_function='RMSE'` was deliberately NOT touched — production retrain stays RMSE until Session 5 deploy decision. The CLI flag is the override path.
- `season_replay.py` 14-day retrain interval is from production config. Don't change for B1's historical backtest — it's the apples-to-apples comparison.

## Calendar context

Today is 2026-05-13. MLB regular season mid-stride (game density ~15 events/day). NBA in playoffs (dormant — halt active since ~Mar 28). Session 3 ended at ~15:55 UTC; Session 4 entry condition is "user reads this handoff" — no calendar gate.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-roadmap-session-4.md.
Execute Session 4 as described. Start with the A4 Quantile walk-forward.
```
