# Session Handoff — 2026-05-13 — MLB roadmap Session 3 startup

**Prior session (2026-05-13, earlier today):** Session 2 of the multi-session MLB roadmap. Shipped A2 narrowed (MAX_EDGE 1.5 → 1.25, `algorithm_version` bumped to `mlb_v9_max_edge_125`) and wrote design-only docs for A5 (CLV foundation) and B1 (early-warning backtest). This handoff sets up Session 3.

**Source-of-truth docs:**
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/06-MULTI-SESSION-ROADMAP.md` — canonical plan
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/08-A5-CLV-DESIGN.md` — Session 3 build spec
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-2.md` — Session 2 startup (carry-overs flagged at bottom)

## TL;DR

Session 2 deployed cleanly. Session 3 builds **A5 (CLV foundation)** so the 14-day measurement window for the Phase C UNDER decision can start collecting data, and kicks off the **A4 Poisson walk-forward** as a long-running background task. Both pieces unblock Session 4-6.

## What shipped (Session 2)

| Item | Status |
|---|---|
| `MAX_EDGE` 1.5 → 1.25 in `ml/signals/mlb/best_bets_exporter.py:71` | DEPLOYED via `deploy-mlb-prediction-worker` |
| `algorithm_version` → `mlb_v9_max_edge_125` (line 631) | DEPLOYED |
| `07-A2-MONITOR-QUERY.md` — 7d Wilson-LB monitor + revert procedure | Saved |
| `08-A5-CLV-DESIGN.md` — schema/scheduler/materializer design | Saved |
| `09-B1-BACKTEST-QUERY.md` — false-positive backtest design | Saved |
| Memory updated (`mlb-system.md` MAX_EDGE line) | Done |

Pre-deploy baseline captured for the A2 monitor: 66 graded OVER picks under `mlb_v8_s456_v3final_away_5picks`, HR 57.6%, Wilson LB 45.6%. Stop threshold for revert: Wilson LB < 43.6% at 2026-05-20.

## Session 3 plan (per roadmap, 4-5h)

**Goal:** Build the CLV foundation (live data collection starts) and kick off the Poisson walk-forward.

| Step | Effort | Notes |
|---|---|---|
| A5 schema migration | 30 min | `mlb_raw.pitcher_props_closing` (DDL in `08-A5-CLV-DESIGN.md` Layer A) + `ALTER TABLE mlb_predictions.prediction_accuracy ADD COLUMN ...` (4 columns, Layer B). **Migration MUST land before code deploy** (Lane 3 #1 BLOCKER). |
| A5 materializer | 2h | New `data_processors/raw/mlb/pitcher_props_closing_materializer.py` (logic in `08-A5-CLV-DESIGN.md` Layer D). Cloud Scheduler `mlb-pitcher-props-closing-materialize` at 09:00 UTC daily. |
| A5 pre-game burst schedulers | 30 min | Two new cron entries (afternoon + evening ET windows) in `bin/schedulers/setup_mlb_schedulers.sh`. Quota-check the Odds API before enabling — 24 fires/day × ~12 books per event. Consider the cheaper "conditional fire CF" alternative noted in the design doc. |
| A5 backfill from existing oddsa | 30 min | One-time SQL replay over `mlb_raw.oddsa_pitcher_props` from 2026-03-01 → yesterday. Most rows will land as `is_synthetic=TRUE` — that's expected; flag distinguishes the post-A5 high-quality rows. |
| A4 dev — Poisson loss | 30 min | `scripts/mlb/training/train_regressor_v2.py:83` swap `loss_function='RMSE'` → `'Poisson'`. Adapt predictor for CDF math (Poisson is integer-valued; current code may assume continuous output). |
| A4 walk-forward kickoff | 1h dev + 4-12h compute | `scripts/mlb/training/walk_forward_simulation.py --training-start 2024-04-01 --start 2024-04-01 --end 2025-10-01` for both RMSE-current and Poisson variants. Run in background — see ScheduleWakeup if you want progress notifications. |

**Deploy at session end:**
- A5 foundation LIVE (table exists, schedulers running, data collecting — but no behavior change for predictions/picks).
- A4 walk-forward RUNNING in background (4-12h compute, bridges to Session 4).

## Stop conditions for Session 3

ABORT and surface to user if:
- A5 schema migration fails on either table — investigate dependent queries (`prediction_accuracy` is wide-fanout) before retrying.
- `pitcher_props_closing` materializer dry-run on 2026-05-12 produces 0 rows — means the upstream `oddsa_pitcher_props` snapshot cadence isn't dense enough yet; defer the live cutover until the burst scheduler has at least 1 day of dense data.
- Odds API quota check shows 24 fires/day would exceed monthly budget — drop to the cheaper "conditional fire CF" alternative or 30-min cadence.
- Poisson loss change in `train_regressor_v2.py` breaks training (CatBoost Poisson loss requires target ≥ 0; check feature contract).
- A4 walk-forward produces obviously broken output (e.g., all predictions = 0 or all = mean) within the first 100 days of replay — kill the run and inspect.

## Carry-over items (from Session 1 and Session 2)

1. **A2 7-day monitor — DUE 2026-05-20.** Run the query in `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/07-A2-MONITOR-QUERY.md`. If `mlb_v9_max_edge_125` total Wilson LB < 43.6%, revert with `gcloud run services update mlb-prediction-worker --update-env-vars="MLB_MAX_EDGE=1.5" --region=us-west2`.

2. **4:30 PM ET fire of `mlb-best-bets-generate-late` (2026-05-13, today).** Should have already fired by the time Session 3 starts. Verify it ran and stamped `mlb_v9_max_edge_125`:
   ```bash
   gcloud scheduler jobs describe mlb-best-bets-generate-late --project=nba-props-platform --location=us-west2 --format="yaml(lastAttemptTime,status)"
   bq query --use_legacy_sql=false "SELECT DISTINCT algorithm_version, COUNT(*) FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` WHERE game_date = '2026-05-13' GROUP BY 1"
   ```
   If `algorithm_version` is still `mlb_v8_s456_v3final_away_5picks`, the worker rolled back or the deploy failed. Check `gcloud builds list --filter='triggerName=deploy-mlb-prediction-worker' --limit=3`.

3. **`OPENWEATHERMAP_API_KEY` blocker** for Components A+B of the weather pipeline. Procedure in Session 2 handoff carry-over #2. Free tier covers usage (30 stadiums × 1/day = 30 calls/day, limit 1000).

4. **X1 lineup pipeline (deferred indefinitely).** A1 features confirmed vapor in Session 1's X2 verification. Don't touch unless the user explicitly asks.

## What this session will NOT do

- Promote A5 to influence predictions/picks — A5 is observation-only data collection in Session 3. Auto-demote integration lives in Session 5+.
- Deploy A4 — walk-forward output gets reviewed in Session 4; deploy is Session 5 (requires user approval per CLAUDE.md).
- B1 build — Session 4. Backtest design from Session 2 (`09-B1-BACKTEST-QUERY.md`) gets executed first.
- Model retrain or governance gates — first touchpoint is Session 5.
- Anything UNDER-related — Phase C decision lives in Session 6 (after ≥14 days of post-Poisson data).

## Useful pointers

- Auto-deploy is live on push to main. The MLB worker has its own Cloud Build trigger (`deploy-mlb-prediction-worker`).
- `mlb-phase1-scrapers` is NOT auto-deployed — manual deploy via `./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` if Session 3 adds new schedulers that need scraper changes (it shouldn't — A5 reuses the existing `mlb_pitcher_props` scraper).
- `train_regressor_v2.py` is the V2 regressor (current). `quick_retrain_mlb.py` is the V1 classifier — DO NOT confuse.
- A4 walk-forward results land as CSVs in `results/mlb_walkforward_*/`, NOT in BigQuery. For Session 4's B1 backtest, the CSVs must be uploaded to a temp BQ table (instructions in `09-B1-BACKTEST-QUERY.md`).

## Calendar context

Today is 2026-05-13. MLB regular season mid-stride. NBA in playoffs (dormant — playoff-started halt active since ~Mar 28). Session 2 deployed at ~11:06 UTC; this Session 3 handoff doc was written immediately after.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-roadmap-session-3.md.
Execute Session 3 as described. Start with the A5 schema migration.
```
