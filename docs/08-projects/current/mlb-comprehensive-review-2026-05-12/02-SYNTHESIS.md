# Synthesis — cross-cutting analysis from 20-agent review

This file pulls signal from the 20 lane reports. Three sections: what's wrong with the existing plan, what bigger opportunities the plan missed, and how to resolve the contradictions between lanes.

---

## Section 1 — Plan-killers (specific to MLB UNDER shadow rollout)

### 1.1 The graduation gate cannot distinguish signal from noise

Wilson 95% lower bound for N=60 at exactly 56% HR = **43.4%**. Below breakeven at -110 vig. The plan's "monthly bucket ≥ 50% at N=10" gate has near-zero power — a 50% bucket at N=10 has 95% CI of ±30pp.

**Bonferroni-adjusted requirement** (~10 simultaneous sub-checks): N ≥ 150 at observed HR ≥ 58% to claim >50% true HR with confidence. The plan's gate would graduate noise into production roughly 1 in 4 launches.

**Fix:** Raise gate to N≥150, HR≥58%, with monthly minimum requiring Wilson LB > 50%, not just point estimate.

### 1.2 Both proposed UNDER filters are overfit

| Filter | N (in-sample) | Cross-season collapse |
|---|---|---|
| `high_line_under_block` | 34 | not assessed (single season) |
| `elite_k9_under_block` | 23 (2025) | 96.9% → 65.2% — agent re-frames the failure as justification |

These fail the sibling project's Reviewer 1 hard rule ("no filter at N<100, no signal graduation at Wilson-LB <55%"). The cross-season collapse is the canonical SIGN that an archetype is non-stationary, not the canonical signal that a filter is justified.

**Fix:** Ship entire Phase 0 Step 2 filter set as OBSERVATION-ONLY. Promote only after N≥100 graded shadow-blocks at Wilson-LB ≥ 55% in 2026 live data.

### 1.3 Engineering hazards block PR

- **BLOCKER:** Existing `_write_shadow_picks` at `best_bets_exporter.py:1020` does unscoped DELETE. Adding a new `_write_shadow_under_picks` without retrofitting the old one = mutual annihilation on every run.
- **BLOCKER:** Schema migration for new `n_under_*` columns must precede auto-deploy of `mlb_model_performance.py` changes, or scheduled runs fail with "Column not found."
- **MEDIUM:** `season_replay.py:55` hardcodes old `UNDER_ENABLED` constant — drift footgun for graduation evaluation.
- **MEDIUM:** 10+ runbooks reference single-flag world; new two-flag setup creates operator footgun.

### 1.4 Sequencing inverted — Quantile retrain should come BEFORE shadow, not after

The plan defers Quantile-loss retrain to Phase 3 "so we can A/B against shadow." This is backwards:

- Quantile retrain is a one-line model change at `train_regressor_v2.py:83`
- If it fixes the -0.45K UNDER bias (Agent 3's diagnosis), shadow becomes 30-40% redundant
- Shadow data collected with a biased model trains the ranker on selection-biased garbage
- A/B the cheaper alternative first, not after spending 4 days on the workaround

**Lane 12 escalates:** Poisson loss beats Quantile loss because K is count data. Poisson:
- Eliminates RMSE outlier penalty natively
- Gives `p_over = 1 - poisson.cdf(floor(line), mu=predicted_K)` for free — a calibrated probability replacing the decorative `SIGMOID_SCALE=0.7`
- Enables `prob_edge = p_over − over_implied_prob` — sharp probability comparison vs market

---

## Section 2 — Bigger opportunities the plan missed

Ranked by independent agent assessment of EV per effort:

### 2.1 Lineup features already computed and discarded (Lane 16) ★ HIGHEST

**`pitcher_features_processor.py` writes 6 lineup features to the precompute table — none are in `CATBOOST_V2_FEATURES`:**
- `f25_bottom_up_k_expected`
- `f26_lineup_k_vs_hand`
- `f27_platoon_advantage`
- `f33_lineup_weak_spots`
- `f34_matchup_edge`
- (plus `f15_opponent_team_k_rate` which IS used but is just flat mean of 9 batter K rates)

Adding these to the feature contract is a **30-minute edit + retrain**. The pipeline already pays the compute cost.

Caveats:
- `bdl_batter_splits` source for f26 doesn't exist — feature is silently NULL for all rows. Fix by switching to FanGraphs or Savant handedness scrape (separate 2-day work).
- Lineup coverage is spotty (45 rows on 15-game day = 3/team — scraper failure). Worth fixing in parallel.

### 2.2 OVER ranking is inverted (Lane 14) ★ HIGH

2026 OVER edge bucket HR:
- 0.5-0.99: **59.0%** (N=295) — sweet spot
- < 1.0: 54.9% (N=295)
- 1.0-1.49: **43.75%** (N=48) — losing bucket
- 1.5+: 80% (N=5) — noise

Current `_over_sort_key = edge + tiebreaker` ranks edge DESC — selecting the 43.75% bucket first when more than 5 OVER picks qualify per day. Same MAX_EDGE pathology that drove cap 2.0→1.5 in Session 438b.

**Fixes (priority order):**
1. Tighten MAX_EDGE 1.5 → 1.25
2. Re-rank by edge bucket: prefer 0.5-0.99 over 1.0-1.49 over 1.5+
3. Re-audit `whole_line_over` (CF HR 52.8%) quarterly

**Expected lift: +3-6pp HR on the cash cow.** Higher EV than the entire UNDER project.

### 2.3 Switch loss function RMSE → Poisson (Lane 12) ★ HIGH

One-line change at `train_regressor_v2.py:83`:
```python
loss_function='Poisson'  # was 'RMSE'
```
Plus ~5 lines in predictor to derive `p_over` from Poisson CDF. Fallback to Quantile(0.5) if walk-forward shows no improvement.

Expected: OVER prediction rate drops 60% → 53-55%, UNDER picks become statistically available at edge ≥ 0.75, AND `p_over` becomes a real probability.

### 2.4 Weather scheduler + 2nd pre-game export (Lane 17) ★ HIGH

Three free wins from one new scheduler:
- Weather signals come alive (currently silently dead — `mlb_weather` has zero rows season-to-date)
- Scratched-pitcher picks dropped before publication (currently stay published until next-morning grading)
- `is_bullpen_game` flag derivable from confirmed lineups

Effort: ~6 hours (new scheduler + Pub/Sub fan-out).

### 2.5 Early-warning regime detection (Lane 19) ★ HIGH

Combined trigger `T1 (7d HR<50%, N≥25) OR (T3 slope<-2pp/day AND T4 z-score<-2)` plus a cross-direction shape classifier would have fired April 28 instead of May 12 — **14 days earlier**.

Cross-direction shape classifier: OVER stable + UNDER drops → "disable UNDER, keep OVER." Exactly the decision memory eventually made manually.

Effort: ~6 hours. Extends existing `bin/monitoring/mlb_daily_performance.py`.

### 2.6 CLV tracking (Lane 18) ★ MEDIUM-HIGH

MLB has zero closing-line value tracking today. `oddsa_pitcher_props` has 24 snapshots/day but stops 5h+ before first pitch — no true closing line captured.

Implementation: ~7 hours total:
- New scheduler for closing snapshots (every 15 min from -90 to 0 min)
- New `mlb_raw.pitcher_props_closing` table
- Extend `prediction_accuracy` with `clv_raw, clv_directional`

**Killer use case — CLV auto-demote.** Mirror existing `filter_counterfactual_evaluator` pattern. Signals with 14d CLV < -0.15K (N≥20) auto-demoted. Fires ~10 days earlier than HR-based demotion.

### 2.7 Archetype categoricals (Lane 20) ★ MEDIUM

Add 3 categorical features to V2 regressor:
- `archetype_k9_bucket` (4 levels: Elite/Solid/Avg/Contact)
- `archetype_variance_bucket` (3 levels)
- `archetype_pitchcount_bucket` (opener/normal/workhorse)

Mark as `cat_features` in CatBoost. Retrain.

**Evidence:** Low-variance pitchers UNDER = 61.9% HR (matches NBA's low-line+low-var UNDER = 62.0%). Solid_K archetype 50% both directions (global model has zero predictive power). Elite × line≥7 cross-season collapse signals archetype × regime interaction.

Effort: 4h. Expected lift: +2-3pp HR on UNDER picks.

### 2.8 NBA→MLB ports (Lane 15) — top 3 starred

- Filter counterfactual evaluator + auto-demote — 1.5d
- Health-aware signal weighting (COLD × 0.5, HOT × 1.2) — 1d
- Edge-based auto-halt with MLB thresholds — 1d

Each is structural infrastructure that has paid off in NBA repeatedly.

### 2.9 7 new feature ideas (Lane 11) — for later experimentation

Top 3 by expected lift × feasibility:
- `f80_lineup_projected_k_sum` — bottom-up batter K via per-batter season K%
- `f82_lineup_recent_k_streak` — last-7d K rate / PA aggregated over confirmed 9
- `f85_pitcher_velo_drop_signal` — 2-start vs 5-start velocity decline

Ideas 4-7 ride T2.10 (Statcast) / T2.11 (weather) backfill already in flight.

### 2.10 5 market microstructure ideas (Lane 13) — for later experimentation

Best two:
- `k_line_velocity_60min` — late line move detector
- `late_move_steam_flag` — concordant moves across ≥6 of 12 books in 15-min window

---

## Section 3 — Resolving contradictions between lanes

### 3.1 "Abandon UNDER" (Lanes 4, 6, 8) vs "directional motivation is real" (Lanes 1, 7)

**Both can be true.** The motivation for keeping UNDER disabled IS statistically real (Lane 1: May 40.9% Wilson LB = 29.9% — CI excludes 53%). The PLAN built on top of that motivation is poorly designed (gate is noise, filters are overfit, sequencing is inverted).

**Synthesized verdict:** Don't ship the shadow rollout as drafted. Either:
- (a) Re-design with corrected gate (N≥150, HR≥58%, Wilson-LB monthly check) and Quantile/Poisson retrain FIRST, then re-evaluate whether shadow is still needed
- (b) Abandon shadow entirely; focus on the larger opportunities; revisit UNDER only after Poisson retrain + lineup features are in production

Both paths agree on: ship Poisson + lineup features first, then decide on UNDER.

### 3.2 "Walk-forward standalone" (my proposal) vs "merge with model_raw_predictions" (Lane 10)

**Lane 10 is right.** A unified `model_predictions_audit` table with `prediction_type IN ('live', 'walk_forward')` is the correct shape. Same columns, same migration, killer cross-query becomes `GROUP BY`.

**Lane 9's schema critique stands independently:** even in unified form, the schema needs `random_seed`, `git_commit_sha`, `feature_hash`, retrain-window boundaries per row, `prediction_pk`, and GCS `model_artifact_uri`.

**Minimum viable version (Lane 10):** 11 columns + CSV-to-GCS by simulation_id. ~30 min of work. Bigger schema later.

### 3.3 "Shadow is needed for ranking discovery" (original plan D3) vs "Quantile retrain may moot the need"

If Poisson/Quantile retrain corrects the -0.45K UNDER bias, the population of qualified UNDER picks expands and their distribution shifts. Pre-retrain shadow data ranks the OLD population. **Pre-retrain shadow is wasted research.**

**Synthesized verdict:** Ship Poisson retrain first. If it produces walk-forward UNDER HR ≥ 56% at edge ≥ 0.75 with non-trivial volume, ship UNDER live with OBSERVATION-ONLY filters and skip the 45-day shadow window. If walk-forward UNDER is still <53%, then design a corrected shadow window WITH the retrained model.

---

## Section 4 — What survives from the original plan

- **Phase 0 Step 3 (un-hardcode `recommendation='OVER'` in bookkeeping):** necessary regardless of which path is chosen
- **Phase 0 Step 1 (signal pipeline repair, minus the weight changes):** wiring `velocity_change` and removing dead signals is good hygiene regardless
- **Reuse `blacklist_shadow_picks` with `shadow_reason` discriminator:** correct table-level design, but BLOCK PR until the existing unscoped DELETE is retrofitted in the same commit
- **`MLB_UNDER_SHADOW` env var separation from `MLB_UNDER_ENABLED`:** correct flag design — additive, low coupling risk

## Section 5 — What dies

- The two proposed UNDER filters as ACTIVE blocks
- The N=60/HR≥56% graduation gate
- The "Quantile retrain deferred to Phase 3" sequencing
- The standalone `walk_forward_results` table (merge with `model_raw_predictions`)

---

## Section 6 — The fundamental tension to surface to the user

**The shadow rollout was framed as fixing UNDER. The 20-agent review revealed that 4 of the top-7 opportunities have nothing to do with UNDER:**

1. Wire 6 already-computed lineup features (helps both directions)
2. Fix OVER ranking (OVER-specific)
3. Poisson loss (helps both directions, especially UNDER bias)
4. Weather + scratch protection (helps both directions)
5. (UNDER-specific) Early-warning detection
6. (Cross-cutting) CLV tracking
7. Archetype categoricals (helps both directions)

The investigation started as "why are MLB picks all OVER?" but the answer is structural across the entire pipeline, not UNDER-specific.

This reframing is the central question for the 5-agent follow-up review.
