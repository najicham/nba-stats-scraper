# Revised plan — after 5-agent review

**Status:** RECOMMENDED. Supersedes `03-RECOMMENDED-PLAN.md`.
**Source evidence:** `04-FINAL-REVIEW.md` (5-agent audit) + `01-AGENT-FINDINGS.md` (original 20-agent review).

## What changed from `03-RECOMMENDED-PLAN.md`

Three load-bearing changes, all from the 5-agent review:

1. **A1 (lineup features) is REMOVED from Phase A.** Agent D's BQ check on `mlb_precompute.pitcher_ml_features` (2026-04-01 forward) revealed 5 of 6 features are 0.0 constants across all 976 rows. Wiring them ships placeholders. Replaced with an upstream-investigation task (X1 below).

2. **Phase A sequencing reversed.** A4 (Poisson) ships first because every other measurement is biased without it. Agents A, B, C, D converged independently on this.

3. **B2 (CLV) promoted to Phase A.** Without CLV, the Phase C decision relies on HR alone — the lagging indicator that let the May collapse run 14 days.

---

## Phase A — Foundational fixes (this week, ~3 days)

### A4 — Switch loss function RMSE → Poisson **★ ship first**
- **Effort:** 4h dev + walk-forward + governance gates + user approval
- **Files:**
  - `scripts/mlb/training/train_regressor_v2.py:83` — `loss_function='Poisson'`
  - `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py` — replace `SIGMOID_SCALE` math with `p_over = 1 - poisson.cdf(floor(line), mu=predicted_K)`
- **Walk-forward FIRST:** Run all variants offline (current vs Poisson, both with training-start 2024-04-01). Compare WF HR at edge 0.75 and bias on OVER/UNDER subsets. **Don't ship to prod until WF results are reviewed.**
- **Validation:** OVER prediction rate drops 60% → 53-55%; UNDER bias absolute value drops below 0.30K; governance gates (HR ≥ 53%, Vegas bias ±1.5) pass.
- **Fallback:** If Poisson WF is flat/worse, fall back to Quantile(0.5) per Agent 3's original proposal. If both flat, abandon and skip to A2.
- **User-approval gate:** YES — present WF results before any deploy.
- **Expected impact:** Single root-cause fix for the -0.45K UNDER bias. May obsolete shadow rollout entirely.

### A2 — Fix OVER ranking (ship in parallel — code-only)
- **Effort:** 4h, no retrain, same-day ship
- **Files:** `ml/signals/mlb/best_bets_exporter.py` — `MAX_EDGE` and `_over_sort_key`
- **Changes:**
  1. Tighten `MAX_EDGE` from 1.5 to 1.25
  2. Re-rank OVER picks by edge bucket: prefer 0.5-0.99 over 1.0-1.49 over 1.5+
- **Caveat from Agent D:** N=48 evidence for the 43.75% bucket has Wilson CI overlap with 59% sweet spot. Tightening `MAX_EDGE` is safer than the bucket re-rank. Consider shipping the tighten first, monitoring 7 days, then deciding on bucket re-rank separately.
- **Validation:** Backtest 2026 OVER picks under new ranker; confirm HR ≥ 60.3%. After ship: 7-day OVER HR must not regress >2pp Wilson LB.
- **Rollback:** Revert constants. Picks change next run.
- **User-approval gate:** NO — code-only.
- **Expected impact:** +3-6pp OVER HR (with caveat above on bucket re-rank).

### A3 — Weather scheduler + 2nd pre-game export (ship in parallel — config-only)
- **Effort:** 6h
- **Files:**
  - `bin/schedulers/setup_mlb_schedulers.sh` — add `mlb-weather-pregame` job
  - `predictions/mlb/supplemental_loader.py:230` — wire weather to supplemental dict
  - New `mlb-best-bets-generate-late` scheduler at 16:30 UTC (2h pre-game)
- **Validation:** `mlb_raw.mlb_weather` has rows next day. Scratched pitchers don't reach the published JSON.
- **Rollback:** Disable new schedulers. Pipeline returns to single-export.
- **User-approval gate:** NO — additive infra.
- **Expected impact:** Operational hardening (correctness fix for scratched picks); weather signals come alive as side benefit but agent B rates the signal lift only 20-30% likely.

### A5 — CLV tracking foundation (was B2, promoted)
- **Effort:** 7h
- **Files / artifacts:**
  - New `mlb-pitcher-props-closing` scheduler (every 15 min from -90 to 0)
  - New `mlb_raw.pitcher_props_closing` table
  - Extend `mlb_predictions.prediction_accuracy` with `clv_raw`, `clv_directional` columns
  - Schema migration MUST precede code deploy
  - Backfill from existing oddsa history using proxy = `MIN(minutes_before_tipoff)` per pick
- **Skip the auto-demote** until 60+ days of CLV data accumulated and the auto-demote rule is validated on MLB-native data (Agent B flagged this killer-use-case as low-P).
- **User-approval gate:** NO — additive infra.
- **Why promoted:** Phase C decision (re-evaluate UNDER post-Poisson) needs a leading indicator beyond HR. Agent A: "Move B2 from Phase B to A IF Phase C decision will rely on anything other than raw HR."

---

## Phase B — Monitoring (next week, ~6h)

### B1 — Early-warning regime detector
- **Effort:** 6h
- **File:** Extend `bin/monitoring/mlb_daily_performance.py` with `direction_regime_monitor()`
- **Trigger:** T1 (7d HR<50%, N≥25) OR (T3 slope<-2pp/day AND T4 z-score<-2). Plus cross-direction shape classifier.
- **Critical validation (Agent B caveat):** Backtest on 2024 AND 2025 walk-forward data — confirm false-positive rate ≤ 3/season. The original Lane 19 only validated against the May 2026 event. April/June low-N false-positives are a real risk.
- **Backtest BQ:**
```sql
SELECT game_date, COUNTIF(recommendation='UNDER' AND prediction_correct) / COUNTIF(recommendation='UNDER') AS under_hr_7d
FROM mlb_predictions.prediction_accuracy WHERE has_prop_line
GROUP BY game_date HAVING under_hr_7d < 0.50
```
- **Defer if backtest fails:** If T1 fires >3 times/season on historical data, recalibrate before deploy.

---

## Phase C — Decision point (Week 3, after Phase A measured)

**This is a 1-hour BQ check, not a build.** After A4 has 14+ days of live data:

```sql
SELECT
  EXTRACT(MONTH FROM game_date) AS month,
  COUNT(*) AS n_picks,
  COUNTIF(prediction_correct) / COUNT(*) AS hr,
  AVG(ABS(predicted_strikeouts - line_value)) AS avg_edge
FROM mlb_predictions.prediction_accuracy
WHERE recommendation='UNDER' AND has_prop_line AND is_voided=FALSE
  AND prediction_correct IS NOT NULL
  AND model_version LIKE 'catboost_v2_poisson%'  -- new model only
GROUP BY 1;
```

**Decision tree:**

- If post-Poisson UNDER HR ≥ 56% at N ≥ 50 → consider ship live with OBSERVATION-ONLY filters, skip 45-day shadow entirely
- If 53% ≤ UNDER HR < 56% → ship corrected shadow rollout (Phase D)
- If UNDER HR < 53% → leave disabled, revisit only after archetype categoricals (Phase E)

**Use CLV data from A5 as cross-check.** If CLV trend on post-Poisson UNDER predictions is positive (avg `clv_directional` > 0) over 14d N≥30, that's confirming signal even if HR is borderline.

---

## Phase D — Corrected shadow rollout (conditional on Phase C)

Only if Phase C indicates 53% ≤ UNDER HR < 56%. Detailed contents in `03-RECOMMENDED-PLAN.md` Phase D — corrections are unchanged:

- Reuse `blacklist_shadow_picks` with `shadow_reason` discriminator AND retrofit the existing `_write_shadow_picks` DELETE in the same commit (Lane 3 #1 BLOCKER)
- Graduation gate: **N≥150, HR≥58%, monthly Wilson LB > 50%** (corrected from original N=60/HR=56% which Lane 1 showed is statistically impotent)
- Filters ship as OBSERVATION-ONLY first; promote to ACTIVE only after N≥100 graded shadow-blocks at Wilson-LB ≥ 55%
- Schema migrations MUST precede code deploys
- Add `backfill_mode=True` kwarg to suppress alerts during historical replay

---

## Phase E — Compound improvements (defer until A/B/C decided)

- **E1.** Archetype categoricals (Lane 20) — 4h, expected +2-3pp on UNDER
- **E2.** NBA→MLB port: filter counterfactual evaluator + auto-demote — 1.5d
- **E3.** NBA→MLB port: health-aware signal weighting — 1d
- **E4.** NBA→MLB port: edge-based auto-halt with MLB thresholds — 1d
- **E5.** Unified `model_predictions_audit` table (Lane 10's merged proposal) — 1d MVP

---

## Phase X — Upstream investigation (background task; replaces original A1)

### X1 — Investigate why lineup features are 0.0 constants
- **Trigger:** Agent D's BQ finding (f25 = 12.2% populated, f26/f27/f33/f34 = 0% populated across 976 rows in `mlb_precompute.pitcher_ml_features`)
- **Files to investigate:**
  - `data_processors/precompute/mlb/lineup_k_analysis_processor.py` — does it run? what's its schedule? what tables does it read? (`mlb_precompute.lineup_k_analysis` has 0 rows ever per Lane 16)
  - `data_processors/precompute/mlb/pitcher_features_processor.py` (search for f25, f26, f27, f33, f34) — what does it read to populate these?
  - Source data: `mlb_raw.mlb_lineup_batters` (188K rows but spotty — Lane 16 found 45 rows on 15-game day = 3/team, scraper failure); `bdl_batter_splits` (doesn't exist in BQ)
- **Diagnostic queries:**
  ```sql
  -- Schedule check
  SELECT name, schedule, last_attempt_time FROM cloud_scheduler.jobs WHERE name LIKE '%lineup%';

  -- Lineup coverage check
  SELECT game_date, COUNT(*) AS rows, COUNT(DISTINCT team_abbr) AS teams
  FROM mlb_raw.mlb_lineup_batters
  WHERE game_date >= CURRENT_DATE() - 14 GROUP BY 1 ORDER BY 1 DESC;

  -- lineup_k_analysis check
  SELECT COUNT(*) FROM mlb_precompute.lineup_k_analysis;
  ```
- **Decision after diagnosis:**
  - If fix is <1 week: schedule it as Phase A6 next week
  - If fix is ≥1 week (e.g. needs FanGraphs handedness scrape + scraper repair + reschedule): file in Phase E5

### X2 — Verify Agent D's BQ check
- **Trigger:** Trust-but-verify. Agent D's evidence is load-bearing for killing A1.
- **Query:**
  ```sql
  SELECT
    COUNT(*) AS total,
    COUNTIF(f25_bottom_up_k_expected != 0) AS f25_nonzero,
    COUNTIF(f26_lineup_k_vs_hand != 0) AS f26_nonzero,
    COUNTIF(f27_platoon_advantage != 0) AS f27_nonzero,
    COUNTIF(f33_lineup_weak_spots != 0) AS f33_nonzero,
    COUNTIF(f34_matchup_edge != 0) AS f34_nonzero
  FROM mlb_precompute.pitcher_ml_features
  WHERE game_date >= '2026-04-01';
  ```
- **Confirm before deciding to skip A1.**

---

## Effort summary

| Phase | Items | Effort | Calendar |
|---|---|---|---|
| A — Foundational | A4+A2+A3+A5 | ~21h | This week |
| B — Monitoring | B1 | ~6h | Next week |
| C — Decision point | BQ check | 1h | Week 3 |
| D — Shadow (conditional) | full shadow if needed | ~20h | Weeks 4-9 |
| E — Compound improvements | E1-E5 | ~5d | Ongoing |
| X — Upstream investigation | X1+X2 | ~4h | Day 0 — before Phase A |

---

## Day-by-day (Agent E shape, revised)

**Day 0 (before any Phase A ships):** Run X2 verification query. If confirms Agent D, proceed. If contradicts, re-add A1 to Phase A.

**Day 1 (Mon):**
- Ship A2 (`MAX_EDGE` tighten only, defer bucket re-rank pending 7-day monitor)
- Ship A3 (weather scheduler + late export)
- Start A4 walk-forward (offline — no deploy)
- Start X1 (lineup pipeline investigation, background)

**Day 2-3 (Tue-Wed):**
- A5 (CLV scheduler + table) — schema migration first, then code
- Continue A4 walk-forward
- Continue X1 investigation

**Day 4-5 (Thu-Fri):**
- A4 walk-forward results review with user → approval gate → ship (or fall back to Quantile/abandon)
- B1 backtest (validate false-positive rate on 2024/2025 data)

**Week 2:**
- B1 deploy if backtest clean
- Phase C BQ check after 14d of new model data
- X1 follow-up actions based on diagnosis

**Stop and reassess on:**
- A2 7-day OVER HR regresses >2pp Wilson LB → revert
- A4 walk-forward shows no improvement vs RMSE → fall back to Quantile or abandon
- B1 backtest fires >3 times/season historically → recalibrate
- X1 reveals lineup pipeline is months of work → file in Phase E, don't block

---

## What this plan does NOT include

- Original A1 (lineup features as 30-min edit) — REMOVED, replaced with X1 upstream investigation
- Original Phase 0 Step 2 filter additions — deferred to Phase D as observation-only
- Original Phase 1 Steps 4-7 shadow infrastructure — deferred to Phase D
- Original N=60/HR≥56% graduation gate — replaced with N≥150/HR≥58%/Wilson-LB-monthly
- Standalone `walk_forward_results` table — folded into E5 unified `model_predictions_audit`

## Decision the user must make now

1. **Approve Phase A4 walk-forward run** (no deploy) — minimal commitment, gathers evidence
2. **Approve Phase A2 + A3 + A5 to ship in parallel** — code/config/infra only, no model changes
3. **Approve X1 + X2 investigation** — diagnostic, no commitments
4. **Defer Phase B1 deploy until backtest validates false-positive rate**
5. **Phase C, D are decisions for Week 3 after A measured** — no commitment now
