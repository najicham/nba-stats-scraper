# Recommended plan — re-sequenced after 20-agent review

**Status:** DRAFT — to be validated by 5-agent follow-up review in `04-FINAL-REVIEW.md`
**Source evidence:** `01-AGENT-FINDINGS.md`
**Cross-cutting analysis:** `02-SYNTHESIS.md`

---

## Overview

The 20-agent review concluded the existing MLB UNDER shadow rollout plan is:
- Statistically incapable of distinguishing signal from noise at its proposed graduation gate
- Built on overfit filters that contradict the agent's own cross-season collapse evidence
- Sequenced backwards (Quantile retrain deferred to phase 3 when it likely moots the need for shadow)
- Engineering-hazard-prone at deploy time
- Targeting the wrong problem — 4 of 7 top opportunities have nothing to do with UNDER

This file proposes a re-sequenced plan that ships the highest-leverage items first, defers UNDER pipeline work until after foundational improvements land, and explicitly re-evaluates UNDER after foundational work to decide if shadow is still needed.

---

## Recommended sequence

Effort estimates and rationale below. Each item is bounded (4h-2d), each ships independently with rollback, each has a clear success metric.

### Phase A — Foundational fixes (this week, ~3 days total)

These items have high evidence, low effort, no dependencies on each other. Ship in any order.

**A1. Wire 6 already-computed lineup features into `CATBOOST_V2_FEATURES`** ★ HIGHEST
- **Effort:** 30 minutes + retrain runtime
- **File:** `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py:29-48` (the 36-feature contract)
- **Add:** `f25_bottom_up_k_expected`, `f26_lineup_k_vs_hand`, `f27_platoon_advantage`, `f33_lineup_weak_spots`, `f34_matchup_edge`
- **Caveat:** `f26` source `bdl_batter_splits` doesn't exist; will be NULL for all rows. Either ship without f26 OR fix source first (separate 2d work to wire FanGraphs handedness).
- **Validation:** Walk-forward HR @ edge 0.75 must equal or beat baseline. Run governance gates.
- **Rollback:** Revert the feature list; old model continues to ship.
- **Expected impact:** Unknown — could be the biggest single lift in the system OR could be flat (if features are degenerate). User said "prefers trying over assuming."

**A2. Fix OVER ranking** ★ HIGH
- **Effort:** 4 hours
- **File:** `ml/signals/mlb/best_bets_exporter.py` (`_over_sort_key` function and `MAX_EDGE` constant)
- **Changes:**
  1. Tighten `MAX_EDGE` from 1.5 to 1.25
  2. Re-rank OVER picks by edge bucket: prefer 0.5-0.99 over 1.0-1.49 over 1.5+
  3. Document the inversion rationale in code comments
- **Validation:** Backtest 2026 OVER picks under new ranker — confirm HR ≥ current 60.3%.
- **Rollback:** Revert constants + sort_key. Picks change next run.
- **Expected impact:** +3-6pp OVER HR. Highest EV single change.

**A3. Schedule weather + add 2nd pre-game export** ★ HIGH
- **Effort:** 6 hours
- **Files:**
  - `bin/schedulers/setup_mlb_schedulers.sh` — add `mlb-weather-pregame` job
  - `predictions/mlb/supplemental_loader.py:230` — wire weather to supplemental dict
  - New scheduler: `mlb-best-bets-generate-late` at 16:30 UTC (2h pre-game)
- **Validation:** `mlb_raw.mlb_weather` has rows next day. `WeatherColdUnderSignal` fires on appropriate games. Scratch protection works (manually test by checking a scratched pitcher).
- **Rollback:** Disable new schedulers. Pipeline returns to single-export.
- **Expected impact:** Weather signals come alive; scratched pitchers don't reach public site; `is_bullpen_game` flag derivable.

**A4. Switch loss function RMSE → Poisson** ★ HIGH
- **Effort:** 4 hours (model change + predictor CDF update + walk-forward validation)
- **Files:**
  - `scripts/mlb/training/train_regressor_v2.py:83` — `loss_function='Poisson'`
  - `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py` — replace `SIGMOID_SCALE` math with `p_over = 1 - poisson.cdf(floor(line), mu=predicted_K)`
- **Validation:** Walk-forward shows OVER prediction rate drops 60% → 53-55%, UNDER picks become available at edge ≥ 0.75. Governance gates pass.
- **Rollback:** Revert to RMSE; redeploy old model from GCS.
- **Expected impact:** Directly addresses Agent 3's -0.45K UNDER bias diagnosis. May obsolete shadow rollout entirely.
- **Coordinate with A1:** Don't ship A1 and A4 in the same retrain — attribution becomes impossible. Sequence: A1 retrain → measure → A4 retrain → measure.

### Phase B — Monitoring & infrastructure (next week, ~2 days)

**B1. Early-warning regime detector** ★
- **Effort:** 6 hours
- **File:** Extend `bin/monitoring/mlb_daily_performance.py` with `direction_regime_monitor()`
- **Triggers:** T1 (7d HR<50% N≥25) OR (T3 slope<-2pp/day AND T4 z-score<-2). Plus cross-direction shape classifier.
- **Output:** Slack alert to `#nba-alerts`, state machine HEALTHY → WATCH → WARN → CRITICAL.
- **Validation:** Backtest on April-May 2026 data — must fire by April 28.
- **Expected impact:** Catches future regime collapses ~14 days earlier than manual detection.

**B2. CLV tracking + auto-demote** ★
- **Effort:** ~7 hours total (see Lane 18 breakdown)
- **Components:**
  - New `mlb-pitcher-props-closing` scheduler (every 15 min from -90 to 0)
  - New `mlb_raw.pitcher_props_closing` table
  - Schema add to `mlb_predictions.prediction_accuracy` (`clv_raw`, `clv_directional`)
  - Backfill from existing oddsa history (proxy = `MIN(minutes_before_tipoff)` per pick)
  - CLV-based auto-demote CF (mirror `filter_counterfactual_evaluator` pattern)
- **Validation:** Day 1 CLV computed; Day 14 CLV trend stable for `book_disagreement` (sanity check).
- **Expected impact:** ~10-day-earlier signal decay detection vs HR.

### Phase C — Re-evaluate UNDER (after Phase A measured)

**Decision point: After A1 + A4 measured (~1-2 weeks of data with the new model):**

Run BQ check on retrained model's UNDER predictions:
- If walk-forward UNDER HR ≥ 56% at edge ≥ 0.75 with N ≥ 50 → consider live ship with OBSERVATION-ONLY filters, skip shadow
- If 53% ≤ UNDER HR < 56% → ship corrected shadow rollout (Phase D below)
- If UNDER HR < 53% → leave UNDER disabled indefinitely; revisit only after archetype categoricals (D4) ship

### Phase D — Corrected shadow rollout (if Phase C indicates)

If Phase C result triggers Phase D:

**D1. Phase 0 Step 1 — UNDER signal pipeline repair (from original plan)** — necessary regardless of shadow design. 6h.

**D2. Phase 0 Step 3 — Un-hardcode `recommendation='OVER'` in bookkeeping** — necessary regardless. 3h.

**D3. Corrected shadow infrastructure:**
- Reuse `blacklist_shadow_picks` with `shadow_reason='under_shadow'`
- BLOCK PR until existing `_write_shadow_picks` DELETE is scoped to `shadow_reason='blacklist'` in same commit
- Schema migration MUST precede code deploy
- Add `backfill_mode=True` kwarg to `MLBBestBetsExporter.export()` that suppresses alert paths

**D4. Corrected graduation gate:**
- N ≥ 150 (not 60)
- Rolling HR ≥ 58% (not 56%)
- Monthly Wilson LB > 50% (not point estimate)
- Vig-adjusted ROI ≥ +3% retained

**D5. Filters as OBSERVATION-ONLY, not ACTIVE blocks:**
- Both `high_line_under_block` and `elite_k9_under_block` write to `best_bets_filter_audit` with `filter_result='WOULD_BLOCK'`
- Promote to ACTIVE only after N≥100 graded shadow-blocks at Wilson-LB ≥ 55% in 2026 live data

**D6. Skip D's pre-work entirely** if walk-forward UNDER HR ≥ 56% under new model — directly ship live with corrected filters.

### Phase E — Larger experiments (4+ weeks out)

Defer until A/B/C decided. These have lower per-item EV but compound over time.

- **E1. Archetype categoricals (Lane 20):** 4h. Expected +2-3pp HR on UNDER.
- **E2. NBA→MLB port: filter counterfactual evaluator + auto-demote (Lane 15):** 1.5d. Structural infrastructure.
- **E3. NBA→MLB port: health-aware signal weighting:** 1d.
- **E4. NBA→MLB port: edge-based auto-halt with MLB thresholds:** 1d.
- **E5. Lineup data fixes (Lane 16 follow-ups):**
  - Audit precompute timing (4h)
  - Fix lineup scraper coverage (4h)
  - Replace dead `bdl_batter_splits` with FanGraphs scrape (2d)
- **E6. Unified `model_predictions_audit` table (Lanes 9, 10):** ~1d for MVP. Merges walk-forward and live audit needs.

### Phase F — Experimental ideas (no commitment, run when bored)

- 7 new feature ideas (Lane 11)
- 5 market microstructure signals (Lane 13)
- Two-stage batter-K model (Lane 16 #5)
- Direct OVER/UNDER classification model (Lane 12)
- Per-archetype model fleet (Lane 20)

---

## What this plan explicitly DOES NOT include

- The original Phase 0 Step 1 weight changes for `UNDER_SIGNAL_WEIGHTS` (deferred until Phase D — needs new model first)
- The original Phase 0 Step 2 filter additions (deferred to Phase D as observation-only)
- The original Phase 1 Steps 4-7 (shadow infrastructure) (deferred until Phase C decides shadow is needed)
- The original Phase 3 (Quantile retrain) — promoted to Phase A4 (Poisson, not Quantile)
- The original Walk-forward Auditability proposal as a standalone table — merged into Phase E6

---

## Effort summary

| Phase | Items | Effort | Calendar |
|---|---|---|---|
| A — Foundational | A1+A2+A3+A4 | ~14h | This week |
| B — Monitoring | B1+B2 | ~13h | Next week |
| C — Decision point | reading + 1 BQ check | 1h | Week 3 (after A measured) |
| D — Shadow (conditional) | full shadow if needed | ~20h | Weeks 4-9 |
| E — Compound improvements | ports + categoricals + lineup fixes + audit table | ~5d | Ongoing |
| F — Experiments | open-ended | ad hoc | as time permits |

---

## Decision the user must make

This plan implicitly chooses Path A (re-sequence, don't abandon UNDER). The alternative is:

**Path B (Lane 6's kill case):** Abandon UNDER entirely. Replace Phase A with: Quantile retrain (or Poisson, A4), wiring lineup features (A1), OVER ranking fix (A2), weather (A3). Skip Phases C/D entirely. Use freed engineering time for Statcast backfill (T2.10 from sibling project) and weekly retrain CF (T2.13).

Path B is essentially "this plan minus Phase C/D." Path A keeps the option open.

**The 5-agent follow-up review should help decide:**
1. Is Phase A sequenced correctly within itself?
2. Is the A1/A4 attribution sequencing (don't retrain together) right or paranoid?
3. Should Path A or Path B be chosen? Why?
4. Are any of the deferred-to-Phase-E items actually higher-priority than items in Phase B?
5. What's the single most-likely-to-disappoint item in Phase A?
