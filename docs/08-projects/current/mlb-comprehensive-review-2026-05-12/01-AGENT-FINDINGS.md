# Agent findings — 20-agent MLB comprehensive review

**Investigation date:** 2026-05-12
**Method:** 20 parallel general-purpose agents, each briefed on a distinct lane. Lanes 1-10 critique the existing MLB UNDER shadow-rollout plan + walk-forward auditability proposal. Lanes 11-20 are open-ended improvement-idea generators. Each agent capped at 400-600 words and instructed to be opinionated.

This file preserves the auditable trail of what each agent claimed and what evidence backed it.

---

## Lane 1 — Statistical rigor (Wilson 95% CIs)

**Verdict:** Plan-killer found. **Graduation gate is statistically impotent.**

Key Wilson lower bounds at z=1.96:

| Claim | N | HR | Wilson LB | Verdict |
|---|---|---|---|---|
| May 2026 UNDER | 66 | 40.9% | **29.9%** | STAND (CI excludes 53%) |
| Week May 11 | 3 | 0% | ~0% | REJECT as evidence |
| Edge ≥1.0 "100%" | 8 | 100% | 67.6% | REJECT (N<30) |
| Elite-K + line 7+ 2025 | ~23 | 65.2% | 44.5% | REJECT (N<30, LB<50%) |
| Line 5-6.5 UNDER | 53 | 56.6% | 43.3% | WAIT |
| Agent5 archetype 47-53% | 34 | ~50% | 33.9% | REJECT |
| Agent5 49-55% | 83 | ~52% | 41.4% | REJECT |
| 2026 UNDER overall | 204 | 53.4% | 46.5% | WAIT |
| April 59.4% | 138 | 59.4% | 51.1% | STAND |
| **Grad gate exactly 60/56%** | **60** | **56%** | **43.4%** | **REJECT GATE** |

Bonferroni at k=10 sub-checks pushes all N<100 claims into reject territory. Agent 5's filter HRs all reject under Bonferroni.

**Plan-killer:** Graduation gate (N=60, HR≥56%) Wilson LB = 43.4% — statistically indistinguishable from breakeven at vig. **Raise to N≥150, HR≥58%, with monthly minimum requiring Wilson LB > 50%** (not just point estimate). Otherwise the rollout graduates noise.

Lane verdict: Don't kill the plan (directional finding is real), but the graduation criteria as written would promote noise.

---

## Lane 2 — OOS overfit risk

**Per-filter verdict:**

- **`high_line_under_block` (line ≥ 7.0, edge < 1.5) — OVERFIT.** N=34 single-season. Two cuts on 34-row sample. FWER ~19-84% depending on threshold-grid assumption. Below the "no filter at N<100" hard rule.
- **`elite_k9_under_block` (k_per_9 ≥ 9.5, line ≥ 6.5) — OVERFIT (worst offender).** Agent 5's own evidence shows 96.9% (2024) → 65.2% (2025) — that IS the OOS test, and it failed. Plan re-frames the failure as justification. Thresholds 9.5 / 6.5 look like exact decile cuts.
- **`k_rate_reversion_under` promotion — NEEDS OOS.** Justified solely on NBA cross-sport transfer, no MLB data.

**Cross-cutting:** Agent 1 says "no MLB UNDER subset with N≥100 clears 56%." Agent 5 then proposes ACTIVE filters at N=34. Plan ships Agent 5's anyway. Contradicts.

**Recommendation:** Ship entire Phase 0 Step 2 filter set as SHADOW/OBSERVATION-ONLY. Adopt the sibling project's Reviewer 1 hard rule verbatim: no filter at N<100, no signal graduation at Wilson-LB <55%.

---

## Lane 3 — Engineering & deploy risk

**Top 5 risks ranked by blast radius:**

1. **`blacklist_shadow_picks` mutual annihilation — HIGH.** Existing `_write_shadow_picks` at `best_bets_exporter.py:1020` does unscoped `DELETE WHERE game_date = X`. Without retrofit in same PR, new `_write_shadow_under_picks` will trample blacklist rows (and vice versa). Also: `data_processors/grading/mlb/main_mlb_grading_service.py:325` UPDATE doesn't discriminate by `shadow_reason`. **BLOCKING.**

2. **Schema migration races auto-deploy of Phase 0 Step 3 — HIGH.** Push-to-main of `ml/analysis/mlb_model_performance.py` changes auto-deploys (via `cloudbuild-mlb-worker.yaml` `ml/**` trigger). If `ALTER TABLE ADD COLUMN` runs AFTER code deploy, next scheduled run fails with "Column not found." Schema MUST land first.

3. **Step 7 historical backfill side-effects — HIGH.** `dry_run=True` does NOT suppress `_evaluate_shadow_picks` writes nor explicit BQ writes. Could fire 500+ historical alerts to `#nba-alerts`. Add `backfill_mode=True` kwarg that hard-disables alerts.

4. **`season_replay.py:55` hardcoded `UNDER_ENABLED=False` — MEDIUM.** Drift after Phase 1 ships; anyone running replay to validate graduation gets false-negatives. Plan misses this file.

5. **Documentation drift in 10+ runbooks — MEDIUM.** `bin/schedulers/setup_mlb_reminders.sh:122` and 8 handoffs reference `MLB_UNDER_ENABLED` as the single switch. New two-flag world creates operator footgun.

**Verdict:** BLOCK PR until risks #1 (scoped DELETE retrofit) and #2 (schema-first ordering) are addressed.

---

## Lane 4 — Independent priority re-ranking

**Plan is sequenced wrong on the strategic question.**

Top item should be: **Quantile-loss retrain (Thread 1) BEFORE shadow.** If RMSE → Quantile fixes Agent 3's structural OVER bias, the entire 23h/45-day shadow project may be moot. The plan defers Quantile to "after shadow has 30d data so we can A/B" — that's backwards. A/B against the cheaper alternative first, not after spending 4 working days building the workaround.

Specific answers:
- Phase 0 Step 1 (signal repair) is NOT highest priority — ranked #3. Prerequisite ONLY IF shadow path is the answer.
- Quantile retrain should jump ahead — **emphatically yes.** One-line change at `train_regressor_v2.py:83`. Plan's deferral logic is inverted.
- `model_raw_predictions` (Thread 3) — strategically valuable but ranked #9. Infrastructure, not a fix. UNDER is broken NOW.

**Other disagreements:**
- Thread 2 (walk-forward → BQ) should be Phase 0 Step 0, not unranked.
- Thread 6 (book-count scaling) under-weighted — if `book_disagree_under` ships, std thresholds must be calibrated against 12-book regime first (NBA Session 515 lesson).

---

## Lane 5 — NBA pattern skeptic

**Mostly disciplined porting.** Per-pattern verdict:

- **`book_disagreement` → `book_disagree_under`:** PORTS WITH ADAPTATION (correctly). Direction inverted because MLB OOS shows the inverse. Best example of non-template thinking.
- **`hot_3pt_under` → `k_rate_reversion_under`:** PORTS CLEANLY. Mechanism is sport-agnostic.
- **`line_drifted_down_under` → MLB:** DOES NOT PORT YET. Blocked on `opening_line` never being wired.
- **`real_sc ≥ 3`:** PORTS WITH HARMFUL ADAPTATION. `UNDER_MIN_SIGNALS=3` was lifted from NBA without auditing MLB's signal inventory — silently killed UNDER for entire season.
- **Edge floors:** PORTS CLEANLY (scaled by K vs PTS).
- **Regime auto-halt:** Not invoked in this plan (correctly — can't auto-halt a shadow).

**Sharp questions:**
- NBA OVER bias is +5pp on the line; MLB is -8.9pp directional. Different problem. Plan's RMSE→Quantile diagnosis is MLB-native, but routing through shadow inverts priority. Shadow data collected with biased model is selection-biased garbage.
- "Top combos 74-83% HR" cannot exist in MLB — single-CatBoost fleet means `combo_3way` loses multi-model character.
- **45-day shadow window is NBA-borrowed without justification.** Agent 1 showed MLB May regime collapse. 45 days straddles May/June regime shifts + ASB/trade deadline. Should be calendar-bounded, not duration-bounded.

**Not fatal.** Three reviewer-corrected NBA myths were caught. The sequencing inversion is the remaining template smell.

---

## Lane 6 — Devil's advocate (kill case)

**The shadow rollout is a sunk-cost spiral disguised as rigor. Abandon now.**

1. **Opportunity cost:** 3-4 days pre-work + 45-day wait. Same time ships T2.10 Statcast features, T2.13 retrain CF, fixes cross-season contamination guard that gave +1.15 K bias and 37.5% April HR.

2. **Measuring noise:** May 40.9% HR is current. By the time N=60 accumulates (~Jun 27), trade deadline + ASB will have shifted regime again. Calibrating gate on worst possible window.

3. **OVER alone is the EV story:** 60.3% live, 67.5% at edge 1.8-2.0. UNDER's best subset (line 5-6.5, N=53, 56.6%) is below N=100 floor and below OVER mean. Hyper-focus on OVER is higher EV.

4. **Engineering scarcity:** every LOC in UNDER pipeline is borrowed from `model_raw_predictions`, Quantile retrain, NBA edge-halt monitor, assists/rebounds expansion.

5. **Empirical record:** UNDER walk-forward 48.1% / -6.8% ROI was bad enough to disable; nobody bothered to enshrine it. Market prices OVER's asymmetry; we have no structural counter-thesis.

**Abandon UNDER. Ship instead:** (1) Quantile-loss retrain NOW, A/B vs RMSE; (2) MLB retrain CF (T2.13); (3) Statcast workload feature wiring (T2.10).

---

## Lane 7 — BQ claim verification

**All 5 claims CONFIRMED exact (verified against `mlb_predictions.prediction_accuracy` with `has_prop_line=TRUE AND prediction_correct IS NOT NULL AND is_voided=FALSE`).**

| Claim | Said | Actual |
|---|---|---|
| 2026 UNDER overall N=204, HR=53.4% | 53.4% | 53.43% |
| May 2026 N=66, HR=40.9% | 40.9% | 40.91% |
| Week May 11 N=3, HR=0% | 0% | 0.0% |
| Edge ≥1.0 N=8, HR=100% | 100% | 100.0% |
| UNDER bias -0.45 K | -0.45 | -0.446 |

Downstream agents can trust Agent 1 + Agent 3 numbers. The picture (53.4% overall, 40.9% May, 0/3 recent week, +100% at edge ≥1.0, -0.45 K UNDER bias) holds.

---

## Lane 8 — Strategic / ROI

**EV math is unfavorable.**

At -110 vig, breakeven HR = 52.38%, payout 0.909u.

- **UNDER at gate (HR=56%, 1 pick/day):** +0.069u/day = +3.1u over 45d
- **UNDER at live trend (HR=53%):** +0.03u/day. Marginal.
- **OVER current (60.3%, 3 picks/day):** +0.453u/day
- **OVER doubled (6 picks/day, est 55-60% HR):** ~+0.72u/day (+59% vs current)

Adding UNDER adds ~15% to daily P/L. **Not transformational.**

**Alternative analyses:**
- **Quantile first:** mechanically surfaces +5-7pp more UNDER picks with CORRECTED prediction centers. Shadow on biased model ranks corrupted picks. **Quantile first = shadow becomes 30-40% redundant.**
- **OVER doubling:** edge 0.5-0.75 historical HR ~55%. At +0.12u/pick × 6 = +0.72u/day. Far more leverage.
- **`model_raw_predictions` first:** makes EVERY downstream investigation auditable. Shadow generates 200 UNDER rows; this generates ALL raw outputs ongoing. They're orthogonal, not duplicative.

**Day-47 signal vs noise:** N=15/month bucket at HR=56% has 95% CI of ±25pp. Monthly ≥ 50% gate has zero statistical power.

**Recommended path: Quantile first.**

---

## Lane 9 — Walk-forward schema critique

**Severity-tagged issues:**

- **BLOCKER — missing columns:** `random_seed`, `git_commit_sha`, `feature_hash` (sha of feature_cols list), `train_window_start_date`/`end_date` per row, `prediction_pk` for Thread 3 joins, `n_train_rows`, `model_artifact_uri` (GCS path of .cbm).

- **MAJOR — `simulation_id` collision risk.** Second-resolution timestamp collides on parallel grid runs / retry. Append 8-char hash or content-hash of config.

- **MAJOR — `require_partition_filter=TRUE` will bite analysis.** Dominant query is "all picks for `simulation_id = X`" — scans every partition. Drop the require flag OR add a `simulation_metadata` sibling with date ranges.

- **MAJOR — denormalized `simulation_config_json` (1KB × 9M = 9GB).** Doc admits this. Hoist to a `walk_forward_simulations` parent table (one row per `simulation_id`).

- **MAJOR — scoped DELETE keyed only on `simulation_id`** is fine for full reruns but if sim crashes at month 6 and re-runs with narrower range, DELETE silently leaves orphan rows. Require `--resume` to extend, not narrow.

- **MINOR — clustering `(simulation_id, system_id)` won't help cross-sim aggregates.** Consider `(simulation_id, model_type)`.

- **MINOR — `load_table_from_dataframe` is correct.** Streaming would be wrong.

Cost: 9GB if `config_json` not hoisted. ~$0.04/mo storage; query cost negligible. Hoist `config_json` to fix.

---

## Lane 10 — Walk-forward scope critique

**Verdict: TOO BIG. Merge with `model_raw_predictions` under a unified `model_predictions_audit` table.**

- **Same table or different table?** Same table with `prediction_type IN ('live', 'walk_forward')` discriminator. Killer query becomes `GROUP BY` instead of JOIN.
- **Wrong problem framing:** The doc solves the next claim, not the original 48.1% one. Reproducing the original is a 2-hour script re-run, not a schema project.
- **Scope creep:** `simulation_config_json` + `feature_set_version` + `signed_error` + denormalized retrain columns + open-question sibling tables = research warehouse, not audit log.
- **Minimum viable:** 11 columns + CSV-to-GCS by `simulation_id`. 30 minutes of work versus the doc's 4h estimate.
- **What's missing:** the model binary itself must go to GCS keyed by `simulation_id`. Without it, "reproducible" is a lie. Also missing: feature_importance per retrain, train/validation row counts.

**Recommendation:** Fold into a unified `model_predictions_audit` project. Ship MVP (CSV→GCS + 11-column table) in the meantime.

---

## Lane 11 — New feature ideas (7 generated)

1. **`f80_lineup_projected_k_sum`** — Sum of per-batter season K% × projected PA from lineup slot. Bottom-up lineup K (NOT the dead `batter_strikeouts` market). Expected lift: +1-2pp.
2. **`f81_lineup_handedness_split_interaction`** — % same-handed batters × (pitcher K% vs same-hand − vs opposite-hand). +0.5-1.5pp.
3. **`f82_lineup_recent_k_streak`** — Today's confirmed 9 batters' last-7d K rate / PA. Captures cold-bat / hot-bat regime. +1-1.5pp.
4. **`f83_umpire_zone_x_pitcher_fastball_pct`** — (ump_called_strike_outside_zone − league_avg) × pitcher_FB_pct. Multiplicative interaction. +0.5-1pp once T1.2 + T2.10 land.
5. **`f84_bullpen_freshness_index`** — Opposing bullpen workload last 3 days. Indirect: tired pen ↔ longer starters ↔ more K opportunities. +0.3-0.8pp.
6. **`f85_pitcher_velo_drop_signal`** — `fb_velo_last_2 − fb_velo_prior_5`. Threshold drop > 0.8 mph = injury risk. Distinct from f53. +0.5-1pp.
7. **`f86_weather_x_pitcher_fb_pct`** — Hot/wind interactions with arsenal. +0.3-0.6pp once weather + statcast pipelines unblocked.

Ideas 1-3 hit "daily-changing context" priority hardest. Ideas 4-7 ride T2.10/T2.11 pipeline backfill already in flight.

---

## Lane 12 — Loss function & calibration

**Single highest-leverage change: `loss_function='RMSE'` → `'Poisson'` at `train_regressor_v2.py:83`.**

Why Poisson beats Agent 3's Quantile(0.5):
- Fixes outlier tilt (no quadratic penalty on 10-K games)
- **Yields a calibrated probability for free:** `p_over = 1 - poisson.cdf(floor(line), mu=predicted_K)`. Replaces the decorative `SIGMOID_SCALE=0.7` hack.
- Enables proper edge: `prob_edge = p_over − over_implied_prob`. Sharp vs market, both probabilities.
- One-line model change + ~5 lines in predictor for CDF.

Empirical K per-9-inning σ ≈ √μ within 10% — dispersion isn't extreme, NegBin overkill.

Calibration finding: model is ABSOLUTELY calibrated (pred 5.12 vs actual 5.16) but **directionally miscalibrated under selection.** OVER picks: +0.19 bias; UNDER picks: -0.45 bias. RMSE isn't the only culprit; line itself is informative (f32 = 33.7% feature importance), so picks form non-random slice.

The fundamental question: regressor predicts E[K], decision needs P(K > line). **Direct classification on `actual_K > line` would dissolve the OVER-tilt problem** — model optimizes the exact quantity edge needs. Cost: loses magnitude info.

Fallback: if Poisson underperforms in walk-forward, Quantile(0.5) is the Agent 3 minimum.

---

## Lane 13 — Market microstructure (5 ideas)

Data substrate: `oddsa_pitcher_props` has 12 books × ~60 snapshots/day with `last_update`, `snapshot_time`, `minutes_before_tipoff`. **NO Pinnacle, NO Circa** — only US retail. `bp_pitcher_props` exposes best-line book IDs but only consensus.

1. **`k_line_velocity_60min`** — Absolute change in median `point` across 12 books over last 60 min before first pitch. Late ≥0.5 K moves are informed; pre-lock moves are square drift.

2. **`k_line_skew_zscore`** — `(MEAN(point) − MEDIAN(point)) / STDDEV(point)` across the 12 books. Outlier book pricing 0.5 K higher = stale → fade their side.

3. **`vig_tilt_side`** — Per book, `over_implied_prob − under_implied_prob` after removing avg juice. Median across 12 books. Negative tilt = books fear UNDER more.

4. **`late_move_steam_flag`** — Within last 90 min, count books moving point concordantly in 15-min windows. Steam (≥6/12 in 15 min) = follow. Drift = ignore.

5. **`bp_best_book_repeat`** — 7-day rolling fraction where same book held best OVER line for a given pitcher. High concentration (≥60%) = one book consistently slow → CLV mirage.

**Regime-mismatch flags:**
- Sharp-book weighting (Pinnacle/Circa) BLOCKED — needs new scraper.
- Idea 2 (skew_z) regime-fragile — std at 12 books ≠ 4-5 books (NBA Session 515 lesson). Calibrate on 12-book data only.
- Cross-market consistency (K vs game total) BLOCKED — no `oddsa_mlb_game_totals` join key.

---

## Lane 14 — OVER ranking optimality

**OVER ranking is INVERTED — actively prefers losers.**

| 2026 OVER edge bucket | N | HR |
|---|---|---|
| < 1.0 | 295 | **54.9%** |
| 1.0-1.49 | 48 | **43.75%** |
| 0.5-0.99 | 127 | **59.0%** (sweet spot) |

Current `_over_sort_key = edge + tiebreaker` ranks edge DESC. **Pure-edge ranking selects the 43.75% bucket first.** Same MAX_EDGE pathology that drove cap 2.0→1.5 (Session 438b) lives in the 1.0-1.49 zone.

Specific findings:
- **Away edge floor 1.25 validated.** Away edge 1.00-1.24 = 33.3% HR (N=33). CF audit of 192 blocked = 48.4% HR. Filter is correctly killing losers.
- **Top-5/day cap NOT currently binding.** Only 7/24 days hit cap. System is volume-starved, not volume-capped.
- **`whole_line_over` filter CF HR = 52.8% (N=309).** Borderline — not auto-demote eligible but not adding value either.

**Recommendations (priority order):**
1. **Tighten MAX_EDGE from 1.5 → 1.25** (1.0-1.49 = 43.75% HR)
2. **Re-rank by edge bucket, not raw edge** (sweet spot = 0.5-0.99 K)
3. **Audit `whole_line_over` for CF HR drift** quarterly

**OVER optimization could lift HR by 3-6pp** via these two changes. Higher EV than entire UNDER project.

---

## Lane 15 — NBA→MLB ports unmade (top-3 starred)

★ **1. Filter counterfactual evaluator + auto-demote (NBA Session 432).** `best_bets_filter_audit` is populated but no CF evaluator job, no `filter_overrides` table, no auto-demote. 1.5d effort.

★ **2. Health-aware signal weighting (NBA Session 469).** `mlb_signal_health.py` writes HEALTHY/HOT/COLD but exporter doesn't consume them as multipliers. Picks fire at full weight even when signal is COLD. 1d effort.

★ **3. Edge-based auto-halt with MLB thresholds (NBA Session 515).** No equivalent. Suggested thresholds: `7d avg edge < 0.8 K` AND `edge-1.5+ rate < 30%`. 1d effort.

4. **`prediction_accuracy_deduped` view (Session 493).** MLB `pitcher_strikeouts` has no dedup constraint — high dup risk corrupting `model_performance_daily`. 1d.

5. **Brier score calibration tracking (Session 399).** No `brier_score_7d/14d/30d` on MLB. `prob_over` is Bernoulli → Brier applies. 0.5d.

6. **Signal graduation framework (Sessions 466/514).** 30 shadow signals; no graduation playbook. 0.5d.

7. **Daily-steering report (NBA `/daily-steering`).** `bin/monitoring/mlb_daily_performance.py` exists but no skill wrapper, no recommendations layer. 1d.

8. **Tonight content guard (2026-05-03).** `mlb_best_bets_exporter.export_all()` writes JSON with no empty-payload guard. PLAYOFF/off-day → frontend shows broken state. 0.5d.

---

## Lane 16 — Lineup data audit (BIGGEST FINDING)

**6 lineup features are already computed every game and silently discarded before the model.**

`pitcher_features_processor.py` writes:
- `f25_bottom_up_k_expected`
- `f26_lineup_k_vs_hand`
- `f27_platoon_advantage`
- `f33_lineup_weak_spots`
- `f34_matchup_edge`

…to the precompute table. **NONE are in `CATBOOST_V2_FEATURES`.**

Lineup data inventory:

| Table | Rows | Status |
|---|---|---|
| `mlb_raw.mlb_lineup_batters` | 188K | Live but spotty (45 rows on 15-game day = 3/team — scraper failure) |
| `mlb_analytics.batter_game_summary` | 106K | Live, healthy |
| `mlb_raw.bdl_batter_splits` | **DOES NOT EXIST** | Code references it; silent fallback; f26 = NULL for all rows |
| `mlb_raw.oddsa_lineup_expected_ks` | **0 rows** | Dead market |
| `mlb_precompute.lineup_k_analysis` | **0 rows** | Processor never scheduled |

**Concrete proposals (effort tags):**

1. **[XS, 30min]** Add f25, f26, f33, f34 to `CATBOOST_V2_FEATURES`. Retrain. Likely best single-PR lift.
2. **[S, 4h]** Audit precompute timing — re-run after 1 PM lineup scrape.
3. **[S, 4h]** Fix lineup coverage (3/team is scraper failure).
4. **[M, 2d]** Replace dead `bdl_batter_splits` with FanGraphs handedness scrape.
5. **[M, 3d]** Two-stage batter-K model as feature.

**Top single change: wire f25/f26/f33/f34 into `CATBOOST_V2_FEATURES` — 30-minute edit unlocks 6 abandoned features.**

---

## Lane 17 — Pregame data integration

**Pipeline-level findings:**

1. **Weather:** Scraper exists, never scheduled. `mlb_raw.mlb_weather` has **zero rows**. `WeatherColdUnderSignal` + `ColdWeatherKOverSignal` silently dead all season.

2. **Late scratches: NO pre-export protection.** Pitcher scratched at 4 PM stays published on `playerprops.io/best-bets` until next-morning grading.

3. **`bullpen_game_skip` wired but data-less.** `sup.get('is_opener') or sup.get('is_bullpen_game')` — `supplemental_loader.py` never sets either key. Filter fires never.

4. **Umpire scheduler at 12:30 ET, export at 12:55 UTC.** Tight margin. If umpire data arrives after, no re-export trigger.

5. **No MLB injury scraper at all.** Blind spot isn't 1 hour — it's the entire game.

**Pipeline timing (single export, no re-runs):**
- 10:00 UTC: schedule, events, game-lines
- 10:30-10:45: props morning (bp, oddsa)
- 11:00: lineups-morning
- 12:00: lineups-pregame, events-pregame
- 12:30: bp/oddsa pitcher props pregame, umpire-assignments
- **12:55: mlb-best-bets-generate (only export)**
- 13:00: mlb-pitcher-export-pregame, predictions-generate

**Highest-leverage fix:** Schedule `mlb_weather` (T2.11) + add 2nd export at ~16:30 UTC (~2h pre-first-pitch). Three wins: (a) weather signals come alive, (b) scratched-pitcher picks dropped before publication, (c) confirmed-lineup-driven `is_bullpen_game` flag derivable. Single new scheduler + Pub/Sub fan-out.

---

## Lane 18 — CLV tracking design

**MLB has ZERO CLV tracking. Greenfield.**

- `bp_pitcher_props`: upserted, latest only.
- `oddsa_pitcher_props`: time-series, 24 snapshots/day, but closest snapshot to first pitch on 5/11 = 340 min before. **No true closing line captured.**
- `prediction_accuracy`: no `closing_line`, `opening_line`, or `clv` columns in either sport.

**Design:**

**Layer A — new `mlb_raw.pitcher_props_closing`:**
```
game_date, player_lookup, bookmaker, closing_line, closing_over_price,
closing_under_price, closing_snapshot_time, minutes_before_first_pitch
```
Scheduler fires `oddsa_pitcher_props` every 15 min from -90 to 0 min pre-game.

**Layer B — extend `prediction_accuracy`:**
```
pick_time_line, closing_line, clv_raw (closing − pick_time),
clv_directional (signed by recommendation)
```

**Implementation: ~7 hours total.**
- New scheduler job: 1h
- BQ table + materializer: 2h
- Schema add + grading service writes: 2h
- Backfill from existing oddsa history: 1h
- Daily-summary view + Slack canary: 1h

**Operational use:**
- Pre-grading diagnosis (T+30min): know if you beat market 6h before grading
- Model eval: rank by `AVG(clv_directional)`, not HR
- Signal validation: which signals consistently buy good numbers

**Killer use case — CLV auto-demote.** Mirror existing `filter_counterfactual_evaluator` pattern: signals with 14d CLV < -0.15K (N≥20) auto-demoted to observation. Fires ~10 days earlier than HR-based demotion.

CLV would have caught the May UNDER collapse ~10 days before HR did.

---

## Lane 19 — Early regime detection

**7d UNDER HR crossed below 50% on April 28 (45.2%, N=42). Memory reacted May 12 — 14 days late.**

| Date | 7d UNDER N | 7d HR |
|---|---|---|
| Apr 18 | 39/59 | 66.1% (peak) |
| Apr 24 | 30/45 | 66.7% |
| **Apr 28** | **19/42** | **45.2% ← first sub-50%** |
| May 1 | 16/42 | 38.1% |
| **May 11** | **14/40** | **35.0%** |

**Proposed triggers:**

| Trigger | Threshold | Earliest fire |
|---|---|---|
| T1: 7d HR < 50% (N≥25) | | **Apr 28** |
| T2: 7d HR < 45% (N≥25) | severity escalation | Apr 28 |
| T3: 7d slope < -2pp/day | direction trigger | **Apr 25** |
| T4: z-score vs 28d < -2 | regime shift | **Apr 26** |
| T5: streak — k=3 of last 5 sub-50 at N≥3 | | Apr 27 |
| T6: Mann-Kendall trend p<0.05 over 10d | | Apr 27 |

**Combined trigger:** T1 OR (T3 AND T4). Belt-and-suspenders.

**Cross-direction shape classifier:**

| OVER 7d | UNDER 7d | Action |
|---|---|---|
| Stable >55% | Drops <50% | **Disable UNDER, keep OVER** |
| Both drop | | Halt + retrain |
| Drops <50% | Stable | Disable OVER |

For this case: Apr 28 OVER 59.8%, UNDER 45.2% → directional → "disable UNDER, keep OVER" — exactly memory's eventual decision.

**Implementation: 6 hours.** Extend `bin/monitoring/mlb_daily_performance.py` + state machine + Cloud Function on existing scheduler.

---

## Lane 20 — Pitcher archetype segmentation

**Yes, global model under-performs on specific archetypes.**

2026 OVER/UNDER HR by archetype:

| Archetype | OVER | UNDER |
|---|---|---|
| Elite (k9 ≥ 9.5) | 55.6% (N=117) | 53.3% (N=75) |
| Solid (8-9.5) | **50.0%** (N=68) | **51.0%** (N=51) |
| Avg (6.5-8) | 55.0% | 59.5% |
| Contact (<6.5) | 54.2% | 50.0% |

**Solid_K is flat 50% both directions — global model has zero predictive power on this band.** Combined with Agent 5's elite × line ≥ 7 collapse (96.9% → 65.2% YoY), segment-specific elite-K model could plausibly have caught the 2025 collapse.

**Variance angle — strong signal:**

| k_std_last_10 | OVER HR | UNDER HR |
|---|---|---|
| Low (<1.5) | 49.3% | **61.9%** (N=42) |
| Mid (1.5-2.5) | 55.7% | 53.2% |
| High (>=2.5) | 55.2% | 48.1% |

**NBA finding ports directly: low-variance pitchers = best UNDER candidates (61.9%).** Matches NBA's "low line + low variance UNDER = 62.0% HR."

**Concrete proposal:** Add 3 categorical features to V2 regressor — `archetype_k9_bucket` (4 levels), `archetype_variance_bucket` (3 levels), `archetype_pitchcount_bucket`. Mark `cat_features` in CatBoost. Retrain on 2024-2025 data.

**Expected lift: +2-3pp HR on UNDER picks. Effort: 4 hours.**

---

## Cross-cutting tensions

| Tension | Lanes |
|---|---|
| Abandon vs proceed with UNDER | 6 (abandon) vs 1, 7 (motivation real) |
| Quantile-first vs shadow-first | 4, 5, 6, 8 all say Quantile first; original plan says shadow first |
| Walk-forward standalone vs unified with `model_raw_predictions` | 9 critiques schema; 10 says merge tables |
| OVER focus vs UNDER focus | 8 (OVER doubled = +0.72u/d vs UNDER at gate = +0.07u/d) |

## Cross-cutting opportunities not in original plan

- Lineup features already computed and discarded (Lane 16 — biggest)
- OVER ranking inverted (Lane 14)
- Poisson loss (Lane 12)
- 8 NBA ports unmade (Lane 15)
- Weather + scratch protection (Lane 17)
- CLV tracking (Lane 18)
- Early-warning system (Lane 19)
- Archetype categoricals (Lane 20)
- 7 new features (Lane 11)
- 5 market microstructure signals (Lane 13)
