# Handoff — INC-4: BB-pipeline injection (fresh chat)

**Date:** 2026-06-19
**Why a fresh chat:** INC-1/2/3 of the eval-foundation rebuild are DONE (this session). INC-4 is the
remaining piece — the most code-heavy/finicky one (modifies the shared signal pipeline) and deserves a
clean context window. **Nothing in this program deploys** — it's all read-only walk-forward evaluation
until an explicit, governance-gated decision.

## STATUS UPDATE (2026-06-19) — capability PROVEN; non-zero picks is the next step

The injection **works end-to-end**. Built this session:
- `scripts/nba/training/discovery/build_sim_predictions_table.py` → loads the 5-season cache into scratch
  table `nba_predictions.walkforward_sim_predictions` (47,521 rows, system_id `wf_sim_v12noveg`, game_id
  joined 100%).
- One inert production edit: `query_predictions_with_supplements(..., predictions_table=None)` in
  `ml/signals/supplemental_data.py` (default = prod table; swaps only the 2 prediction-SOURCE refs).
- `scripts/nba/training/discovery/bb_injection_run.py` → monkeypatches the prediction source onto the
  scratch table and runs the REAL `simulate_date` (signals, filters, edge floor, combos, caps).

**Result of the first run (2025-12-01..2026-01-31, 10 dates):** the real pipeline executed on every date
(filter-dominance warnings, combo registry, model-profile lookback all fired) — but **picks = 0 on every
date.** Diagnosed (this is the "main risk" below, now confirmed):
1. **Edges too tight for the OVER `edge_floor` (6.0):** the single V12_NOVEG model on in-store lines
   produces edges mostly <3 (the edge5+-sparsity finding) → `edge_floor` rejected 71-84% of candidates.
2. **No signal history for the synthetic system_id:** `wf_sim_v12noveg` has no `model_performance_daily`/
   `signal_health_daily` rows → model-dependent signals can't fire → UNDER can't reach `real_sc>=2`
   (`signal_stack_2plus_obs` rejected 65%).

**⇒ Next step (the actual remaining work):** get non-zero BB picks by EITHER (a) injecting **fleet-scale
edges** (load multiple models' walk-forward preds into the scratch table under distinct system_ids and run
`multi_model=True`, so cross-model edges + selection produce larger spreads), OR (b) seed minimal
`model_performance_daily`/`signal_health` rows for the sim model(s), OR (c) add a sim-only floor override.
(a) is the most faithful. THEN measure BB-pipeline edge5+ HR vs raw (the original INC-4 goal). Also noted: a
**pre-existing prod bug** surfaced — the DvP fallback query in `supplemental_data.py` (~line 821) errors
`Name minutes not found inside g` (caught/warned, non-fatal) — worth a separate fix.

## One-paragraph context (what's already true)

Off-season NBA ML prep. **Settled & closed:** fleet diversity is a dead end (tree models clone, r≈0.93-0.99);
retrain cadence 7d≈14d (HR-equivalent, paired walk-forward); MQ/quantile diversity FAIL. **Built this
session (the eval foundation):** a leak-clean **5-season walk-forward prediction cache** + **6 enrichment
extracts** that revive the signal-discovery stack (`feature_scanner.py`/`combo_tester.py` run again).
Key finding that motivates INC-4: **edge5+ is structurally sparse for a single model (~249 picks/5 seasons)**
and the discovery tools evaluate at RAW model edge / flat −110 — so signal/filter findings are not yet
BB-pipeline-trustworthy. INC-4 makes them trustworthy by running the FULL best-bets pipeline on
counterfactual predictions.

## Goal of INC-4

Run the **full BB pipeline** (signals → negative filters → ranking → caps; `ml/signals/aggregator.py`)
on the cache's counterfactual walk-forward predictions, so we can measure **true BB-pipeline HR + real-odds
P/L** for any model/cadence/signal-config across clean multi-season data — instead of raw single-model edge.
Acceptance: produce BB-pipeline edge5+ HR per season and confirm signals/filters add value over raw
(documented BB edge5+ ≈ 65.6% vs raw ≈ 53%).

## The injection path (already traced — verify before editing)

- `bin/simulate_best_bets.py::simulate_date()` runs the real pipeline for one date. It calls
  `query_predictions_with_supplements(bq, target_date, system_id=model_id, multi_model=False)` in
  `ml/signals/supplemental_data.py`.
- That function reads predictions from **`nba_predictions.player_prop_predictions` filtered by `system_id`**
  (~lines 145-160 and 228-238). Everything else (feature store, game summary, injuries, pbp) is shared.
- `simulate_best_bets.py::grade_picks()` grades against **`nba_predictions.prediction_accuracy`** by
  `player_lookup::game_id::recommendation` (~line 207-235) — this is per-production-model, so it will NOT
  grade counterfactual picks whose direction differs from production. **Replace grading** with actuals
  (`nba_analytics.player_game_summary.points`) + the struck line, and attach real odds for P/L.

## Plan (incremental)

1. **Scratch table.** Write counterfactual preds into `nba_predictions.walkforward_sim_predictions`
   (schema-match `player_prop_predictions`): system_id=`wf_sim_<config>`, game_date, player_lookup,
   **game_id** (cache lacks it → join from `player_game_summary`/schedule on player_lookup+game_date),
   current_points_line(=cache `line`), predicted_points, edge, recommendation(=direction), is_active=TRUE,
   line_source='WF_SIM'. Source rows = `results/nba_walkforward_*/predictions_w56_r7.csv` +
   `results/bb_simulator/predictions_2025_26_all_models.csv`. **Do NOT write into prod player_prop_predictions.**
2. **Table override param.** Add optional `predictions_table='nba_predictions.player_prop_predictions'`
   kwarg to `query_predictions_with_supplements` (and thread from `simulate_best_bets.py`), so the sim reads
   the scratch table. Minimal, backward-compatible (default unchanged).
3. **Real grading.** New grade path: join picks to `player_game_summary.points` + struck line → win/loss;
   P/L from real odds (`results/bb_simulator/bettingpros_multibook.csv` has `over_odds_median`; pull
   under-side too — see reckoning script). Flat −110 already shown to mislead (see real-odds result).
4. **Run** `simulate_best_bets.py --model wf_sim_<config> --start <season> --end <season>` per season →
   BB picks, HR by edge, real-odds ROI. Compare vs raw edge HR from `edge_belief_audit.py`.

## ⚠️ The main risk (read first)

The BB pipeline's **signal evaluation pulls LIVE per-date context** from production tables that **don't
exist for historical/walk-forward dates**: `model_performance_daily` (model health), `signal_health_daily`,
`filter_overrides`, player blacklist, regime (`league_macro_daily`), combo registry. For 2021-2024 these are
empty → many signals silently won't fire, so "BB-pipeline HR" historically ≈ raw + negative-filters only.
**Decide up front:** (a) scope INC-4 to **2024-25 + 2025-26** where production context exists (simplest,
recommended first cut), OR (b) build a "historical signal context" shim that recomputes signal health/regime
from the cache. Start with (a); only build (b) if multi-season BB HR is needed. This is the crux — don't
sink time into full historical signal context before proving the injection works on recent seasons.

## Gotchas (verified this session)

- **`bq` CLI hangs in this WSL env — use the Python BigQuery client** for everything.
- Local gcloud default project is **`jett-prod` (WRONG)** — pass `project='nba-props-platform'` (the Python
  client calls in these scripts already do).
- `quick_retrain.py` production-line eval is hardcoded to catboost_v9 → use `--no-production-lines`.
- Cache `results/` dirs are **gitignored** (reproducible). Rebuild: `build_walkforward_predictions.py` then
  `build_bb_simulator_cache.py` (both in `scripts/nba/training/discovery/`).
- Bettingpros table **requires a `game_date` partition filter** or BQ 400s.

## Required reads for the executor

`ml/signals/supplemental_data.py` (query_predictions_with_supplements full body) ·
`bin/simulate_best_bets.py` (simulate_date, grade_picks) · `ml/signals/aggregator.py`
(BestBetsAggregator.aggregate signature + which signals need live context) · the `player_prop_predictions`
BQ schema.

## Assets from this session

- Builders: `scripts/nba/training/discovery/build_walkforward_predictions.py`,
  `build_bb_simulator_cache.py`. Audit: `edge_belief_audit.py`.
- Cache (gitignored): `results/nba_walkforward_*/predictions_w56_r7.csv`,
  `results/bb_simulator/*.csv` (incl. `bettingpros_multibook.csv` with real odds).
- Reckoning: `/tmp/cadence/real_odds_reckoning.py` (real-odds P/L by edge band; promote to repo if useful).
- Docs: `2026-06-18-eval-foundation-progress.md` (full INC-1/2/3 writeup), `2026-06-18-cadence-RESULT.md`,
  `2026-06-18-morning-briefing.md` (100 verified improvement items), `2026-06-18-mq-diversity-RESULT.md`.
- Memory: `eval-foundation-rebuild-2026-06.md`, and MEMORY.md cadence/diversity lines.

## After INC-4 — the queued value work (now unblocked by the foundation)

1. Cross-BOOK `combo_3way` replacement search (`combo_tester.py --min-edge 5`, filter cross-book combos —
   the only fleet-diversity-proof rescue path).
2. Gate + productionize the low-line/low-var UNDER archetype (62% HR) at BB level.
3. Triage `feature_scanner.py`'s 63 cross-season signals for genuinely NEW promotable ones (not already in
   `shared/registry/signals.yaml`).
All of the above should be evaluated at BB-pipeline level + real odds (i.e., AFTER INC-4), not raw edge.
