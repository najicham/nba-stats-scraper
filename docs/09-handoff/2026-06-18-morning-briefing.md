# Morning Briefing — NBA off-season improvements (20-agent review)

**Date:** 2026-06-18
**Method:** 20 domain reviewers → adversarial verification (grep repo + dead-end docs) → synthesis.
**Yield:** 102 candidates → 72 REAL_NEW, 24 PARTIAL, 4 NEEDS_DATA, 2 killed as DEAD_END.
**Companion:** cadence experiment settled same day (`2026-06-18-cadence-RESULT.md`). Diversity thread CLOSED (`2026-06-18-mq-diversity-RESULT.md`).
Full verified item list (with file:line + verdicts): workflow result JSON. Nothing here is deployed — all items are proposals.

---

## TL;DR — top 5 to do this week

1. **Truth-in-accounting: replace flat -110 with real `odds_american`** (P0/S) — every staking/promotion verdict trusts fictional juice; the batter-props sweep proved flat juice flips GOs. First: BQ-join graded 2025-26 picks to `bettingpros_player_points_props` at struck line/side, convert `odds_american`→decimal, recompute `profit_units` vs flat 0.909 by edge bucket.
2. **Rebuild missing `bb_enriched_simulator.py` + walk-forward CSV cache** (P0/L) — the ENTIRE off-season discovery stack (feature_scanner/combo_tester/archetype) `FileNotFoundError`s without it; unblocks ~10 other items. First: drive `ml/experiments/season_walkforward.py` to dump `results/nba_walkforward_<season>/predictions_w56_r7.csv`, then write thin simulator emitting `results/bb_simulator/*.csv` to satisfy `data_loader.py:22,64-68`.
3. **Add `has_regular_season_games()` guard to Phase 4 precompute entrypoint** (P0/S) — kills the off-season shot-zone retry storm (102K fails/2d) at the source. First: import from `shared.utils.schedule_guard` and early-return in `data_processors/precompute/main_precompute_service.py:93-101` when `sport=='nba'` and guard is False.
4. **Bring the 4 pipeline-state CFs into auto-deploy** (P0/M) — `halt_state_writer`, `expected_outputs_planner`, `phase_completion_reconciler`, `gap_detector` are absent from every `cloudbuild*.yaml`, so shared/ refactors silently rot the completeness net. First: add per-CF build steps running each `orchestration/cloud_functions/<fn>/deploy.sh` (mirror weekly_retrain).
5. **Grade BB picks against the published (locked) line, not the latest intraday line** (P0/M) — latest-row dedup + exact line/rec join silently censors picks whose line moved or flipped to HOLD, biasing every public W-L metric. First: run the diff query (`signal_best_bets_picks` LEFT JOIN `prediction_accuracy` over 2025-11..2026-03, count `line_value`/`recommendation` mismatches), then add `bb_line_value`/`bb_recommendation` grading in `prediction_accuracy_processor.py`.

## Quick wins (S effort, P0/P1)

| Item | Why | First step |
|------|-----|-----------|
| Auto-halt edge metric diluted by edge-1.0 noise (P0) | `7d avg edge 1.45` reflects noise floor, not pickable pool — halt mis-fires | BQ compare AVG(edge) all-rows vs `>=3` Feb-Apr; if material, fix WHERE in `regime_context.py:~199` + `halt_state_writer/main.py:208-223` (**recompute metric AND recalibrate 5.0 threshold together — tightly coupled**) |
| Real odds capture (P0) | Flat -110 is fictional; de-risks every simulator verdict | `bettingpros` join, convert `odds_american`, add odds col to `signal_best_bets_picks` |
| Drop `prediction_grades` reads from `daily_data_quality_check.sh` (P0) | Checks 4&5 join frozen table + dead `catboost_v8` → 5-month-blind gate | rewrite Check 4 to LEFT JOIN `prediction_accuracy ON prediction_id`; replace Check 5 with live system_id check |
| Phase 4 off-season guard (P0) | 102K fails/2d masking real failures | `schedule_guard` early-exit in `main_precompute_service.py:93-101` |
| Feature-store concentrated-date canary (P1) | One-day upstream outage thins slate, misattributed to edge collapse | add `clean_candidates` trailing-median check to `pipeline_canary_queries.py`; backtest vs 2026-01-24 |
| Demote `line_drifted_down_under` (P1) | season HR decayed 59.8%→40% (N=25), 30d 34.8% (N=23) — not variance | `aggregator.py:154` weight 2.0→1.0; remove from `RESCUE_SIGNAL_PRIORITY:172` (keep registered) |
| Filter reactivation deadlock (P1) | `check_reactivation()` reads empty CF table → `hr_3d=100.0` → 2 filters stuck demoted forever | `filter_counterfactual_evaluator/main.py:435` — replace fail-closed `else 100.0` with longer lookback + fail-open on re_eval expiry |
| Fix bogus `brier_score=edge/15` (P1) | hand-picked normalizer feeds health dashboards as if a probability | quantify distortion in BQ first; patch `model_performance.py:312-345` (sequence after isotonic item) |
| Per-family merge cap (P1) | 40% SINGLE_MODEL_DOMINANCE is warning-only; clone can concentrate slate risk | pandas sim per-family cap=6 on `model_bb_candidates`; if variance drops, add at `pipeline_merger.py` near `:228` |
| Per-model `min_edge` floor → 3.0 (P1) | Session 533 directive documented but unexecuted; floors 1.0-2.0 pollute halt metric | **do AFTER halt-metric items 1/3** then raise floors in `prediction_systems/*.py` |
| `under_after_streak` into edge5+ (P0) | model 44.7% blind spot capped at edge<5; losers may leak at edge5+ | LAG-streak BQ split by edge bucket; if e5+ HR<50% N>=50, drop cap in `filters.yaml:~221` |
| DLQ undelivered alert (P1) | 7 new DLQ subs have no alert policy — poison msgs drop after 7d | author `monitoring/alert-policies/dlq-undelivered.yaml`, threshold `num_undelivered>0` |
| Deactivate `quantile_ceiling_under` (P1) | weight 3.0 but no enabled model emits `quantile_p75` (MQ dead) — pure dead weight | move to `SHADOW_SIGNALS` in `aggregator.py`; remove from `UNDER_SIGNAL_WEIGHTS:160` |

## Experiments to run

| Hypothesis | How to test | Effort |
|-----------|-------------|--------|
| `model_hr_weight` should feed ranking (it's computed/exported but never multiplies composite_score) | Read-only pandas A/B on `model_bb_candidates`: composite vs composite×hr_weight; re-apply merger caps; compare edge5+ top-15 HR | M |
| Line-shopping best book line beats single `current_points_line` | BQ join picks × `bettingpros` `is_best_line` (min OVER/max UNDER); recompute `prediction_correct`; align to pick-time `bookmaker_last_update` | M |
| Isotonic edge→P(win) on **BB-level** picks (raw-level failed S370) | walk-forward fit `IsotonicRegression(out_of_bounds='clip')` per direction via `edge_calibration.py:67-93` join; report ECE+Brier — **keystone unblocks Kelly/weighting** | M |
| Half-Kelly staking keyed to tier-prior HR | `bin/simulate_kelly_staking.py`: walk-forward prior-HR per `ultra_tier`, sim `f=0.5*(bp-(1-p))/b` at b=0.909 vs flat (downstream of isotonic) | M |
| Monotonic +1 constraint on vegas_line + scoring avgs | `quick_retrain.py --monotone-constraints '<vec>' --no-production-lines` over `season_walkforward.py`; **watch edge5+ volume doesn't collapse** | M |
| Re-validate 0.15x vs 0.25x vegas weight (docs directly conflict, both pre-leakage) | sweep `--feature-weights 'vegas_points_line={0.10,0.15,0.25,0.50}'`; pick highest stable edge5+ CI LB, OVER/UNDER separately | M |
| Decompose `shot_zone_mismatch` into 3 raw zone×tendency interactions | add `backfill_zone_interaction_v1` to `bin/backfill_experiment_features.py` (NOT ml/experiments), backfill, `experiment_harness.py` 5 seeds | M |
| Productionize `low_var_under` (62% HR, 4/4 seasons, not implemented) | gate first via item below (quantify drought overlap), then `feature_scanner.py --direction UNDER` on `points_std_last_10`; add to `UNDER_SIGNAL_WEIGHTS:135` | M |
| **Size UNDER second-signal payoff FIRST** (P0/S go-no-go) | BQ: `best_bets_filtered_picks WHERE filter_reason='under_low_rsc'`, join feature store, would-be HR by archetype predicate — gates the 3 UNDER items above | S |
| Star-out vacated-touches OVER rescue (79.4% HR, N=509, zero code) | **simulator backtest FIRST** (`bb_enriched_simulator`, 3+/4 seasons positive ROI) before any build — book already lifts line +1.73 | L |
| HSE OVER rescue survives TIGHT markets? (only OVER rescue, Feb-resilient 64.3%) | BQ join `league_macro_daily`: OVER picks ITT≥120 on `vegas_mae_7d<4.5` days; if HR≥55% N≥20, add `hse_rescued` carve-out to `aggregator.py:609-614` | M |
| Direction-aware auto-halt (halt is direction-agnostic; UNDER stable 57-71% late-season) | split halt query by `recommendation` (`regime_context.py:195-239`); walk-forward replay blanket vs OVER-only-halt P/L | M |
| Vig-aware PnL in simulators (find -110 vig artifacts) | `--odds-source` in `simulate_best_bets.py:253`; re-run edge6-8 + low-var UNDER; net-negative under real prices = artifact | M |
| Tracking-stats USAGE-SHIFT delta (static failed; dynamic untested) | rolling last-3-vs-baseline touches delta from `nba_tracking_stats`; verify <0.7 corr vs box-score usage_surge | M |
| DvP UNDER side + continuous differential (OVER-only today) | BQ on `hashtagbasketball_dvp`; if `dvp_tough_under`≥55% N≥40, add to `dvp_mismatch.py` | M |
| Volatile + edge5+ OVER (mirror of volatile_starter_under, 61.9% HR documented) | add CoV bucket to `feature_scanner.py:305`, `--direction OVER --min-edge 5.0` | M |
| Re-test Huber + two-stage on clean data (drop recency — clean-data failure on record) | `season_walkforward.py` wrapping `quick_retrain.py --loss-function 'Huber:delta=5'` + `--two-stage` | L |

## Infra / reliability / off-season prep

- **Pipeline-state CFs (P0)**: auto-deploy the 4 completeness-contract CFs + add deployed-updateTime-vs-commit drift assertion to `morning_deployment_check.py`.
- **Off-season false-DEGRADED loop (P1)**: reconciler defaults `halt_active=False` on missing halt rows → DEGRADED → backfill spam; add "halt row absent → EXPECTED" branch in `phase_completion_reconciler/main.py` decide_status. Pairs with the deploy fix.
- **Reconciler `_games_scheduled` has no game_id filter (P1)**: counts ALL `nba_schedule` rows while `schedule_guard` restricts to `002%/004%` — preseason/all-star placeholders keep zero-PBP dates looping. Add the game_id filter at `main.py:174` after a BQ diagnostic confirms residual class.
- **Pipeline-state CF tests (P1)**: zero tests on the 4 CFs; write pytest for `decide_status` branches + Sep/Oct season rollover, wire `gap_detector dry_run` into the 6 AM startup check.
- **`prediction_accuracy_deduped` migration (P1)**: 1,918 dup groups remain in base; core HR consumers (signal_health, model_performance, league_macro, exporters) all read base, only canary uses deduped. Run each query base-vs-deduped, migrate divergent, add pre-commit grep.
- **NBA CLV grading (P1/L)**: NBA has zero closing-line columns; `closing_line_value.py` reads a column that doesn't exist. Copy the MLB 6-column template, capture pre-tip snapshot from `odds_api_player_points_props`.
- **`player_shot_zone_analysis` ready-but-empty corruption (P1)**: 2,458 rows `is_production_ready=TRUE` with NULL `paint_pct_last_10`; add `paint_pct_last_10 IS NOT NULL` guard before marking ready (`processor:259/360`).
- **Fringe-player over-enrollment (P1)**: 2025-26 enrolls +58% no-line fringe rows (root cause "not investigated"); trace enrollment predicate, propose active-roster/min-minutes floor — de-risks the misleading "vegas collapse" metric.
- **DLQ undelivered alert + de-dup `SEASON_WINDOWS`** (copy-pasted in 2 CFs → hoist to `shared/config/`).
- **Scheduler governance (P2)**: dump all 167 GCP jobs, classify NBA-paused / MLB-enabled(3-10) / infra, flag stale URIs (`nba-phase1-scrapers`, `756957797294`). Produce pause/delete list only — **do NOT auto-execute**.
- **Hygiene (P3)**: 13 Task #35 orphan CF dirs already deleted on disk — reconcile `CLAUDE.md:130,170` + tracker. Decommission `quantile_ceiling_under` dead weight.

## Needs next-season data (park until games)

- **Referee O/U signal** — `covers_referee_stats.over_percentage` 100% NULL + ref-assignment scraper produced zero 2025-26 rows (two-feed repair).
- **VSiN sharp-money** — only 25 days of data, last 2026-03-28; diagnose scraper gap now, set threshold on the 25 days, validate next season.
- **Assists/rebounds models** — smoke-test conditional edge NOW (P0, data exists Dec-Apr); build models/discovery only after a stratum clears 55% HR. Park `market_type` plumbing as buildable off-season work; full-season clean labels needed for Oct launch.
- **`projection_consensus` contrarian inversion** — only 203 BB picks / 58 days 2025-26; needs multi-season replay before acting.
- **RotoWire `play_probability`** late-scratch signal — testable but thin N (data only flows 2026-03-04+).

## Notable disagreements / risks

- **Halt-metric items are tightly coupled, not independent**: restricting avg_edge to edge≥3 mechanically pushes it well above 5.0 (selection effect) → halt would *never fire* unless the 5.0 threshold is re-fit on the restricted population simultaneously. Do edge-metric restriction + threshold recalibration + min_edge-floor cleanup as **one sequenced unit** (items couple #1↔#3↔floor-cleanup). Also validate the "never fires 2021-2025" claim — it's a single unbacked handoff sentence; build `halt_threshold_audit.py` before relying on the kill-switch next season.
- **Doc contradictions, both pre-leakage-fix**: MEMORY says 0.15x vegas weight, dead-ends says ≥0.25x — settle by sweep, don't trust either.
- **Stale/overstated premises in candidates**: `consistent_scorer_over` blocking comment stale (N=7→27) but single-season N=27 risks the exact variance over-promotion that burned `usage_surge_over` (S506) — gate behind the reachable graduation-gate rewrite, not a snap promote. Shot-zone "977 solely-blocked / 33%" headline is overstated (true ≈91 rows). `under_low_rsc` "make eligible" and `line_jumped_under_obs`/`tanking_risk_obs` "promote" premises are **already done** — re-scope. `bench_under` 76.5% used look-ahead `starter_flag` (pre-game proxy 51.8%) — not actionable.
- **CF HR rebuild is the unappreciated P0 dependency**: `filter_counterfactual_daily` + `best_bets_filtered_picks` only span 2026-03-03..04-07 (toxic 46.7% regime). Every filter promote/kill verdict (`friday_over_block`, obs filters, `under_low_rsc`) is calibrated on March noise. Rebuild Jan-Feb CF HR via `bin/post_filter_eval.py` loop FIRST — it makes the rest of the neg-filters lane trustworthy.
- **Diversity is settled-dead — do NOT retry**: feature-set/GBDT-algo grids and MQ/quantile heads produce r≈0.94 clones. The clone fleet also means per-model calibration spread (calibration-weighting item) may be too small to differentiate — verify weights actually differ before the full replay. Clone-pruning upside is mostly compute/clarity, not HR.
