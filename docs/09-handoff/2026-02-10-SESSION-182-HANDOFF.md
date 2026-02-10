# Session 182 Handoff — Feb 10 Predictions + A1 Vegas Sweep Re-run with Segmented HR

**Date:** 2026-02-10
**Previous:** Session 181 (segmented hit rates added to quick_retrain.py)
**This session:** Feb 10 operations + A1 Vegas Weight Sweep re-run with segmented breakdowns

---

## What Was Done

### 1. P0: Re-triggered Feb 10 Predictions

Session 180 (ops) found 0 prop lines at 1:30 AM ET. By this session (11 AM ET), 222 prop records were available for Feb 10.

**State found:**
- 79 feature store records, 52 quality-ready
- 4 games scheduled: IND@NYK, LAC@HOU, DAL@PHX, SAS@LAL
- 18 predictions already existed per system from the daily auto-run (13:01 UTC)
- `_0131` and `_0131_tuned` challengers had NO predictions (not in deployed coordinator config)

**Actions taken:**
1. Triggered prediction coordinator (`/start` with `REAL_LINES_ONLY`) — batch completed with 0 new predictions (earlier run already covered all 20 players with prop lines)
2. Backfilled all 3 challengers:
   - `_0108`: Already had 18, skipped
   - `_0131`: 18 predictions written (0 actionable, avg |edge| = 0.74)
   - `_0131_tuned`: 18 predictions written (0 actionable, avg |edge| = 0.75)

**Result:** All 4 models now have 18 predictions for Feb 10.

| Model | Total | Actionable |
|-------|-------|------------|
| Champion (`catboost_v9`) | 18 | 4 |
| `_train1102_0108` | 18 | 0 |
| `_train1102_0131` | 18 | 0 |
| `_train1102_0131_tuned` | 18 | 0 |

**Key observation:** Challengers produce 0 actionable picks because they track Vegas too closely (avg |edge| < 1 point). Only the champion, with its "stale" Vegas model, generates edge. This is the retrain paradox in production.

### 2. P2: A1 Vegas Weight Sweep Re-run (with Segmented Hit Rates)

Re-ran all 6 A1 experiments using Session 181's segmented hit rate code (uncommitted from Session 181, present on disk). These re-runs contain richer output than the Session 180 originals: per-tier, per-direction, tier x direction, edge bucket, and line range breakdowns.

**Results (walk-forward, Feb 1-8, n=269):**

| Experiment | Vegas Wt | Vegas Imp% | Overall HR | E3+ N | E3+ HR | MAE |
|-----------|----------|-----------|-----------|-------|--------|-----|
| A1a BASELINE | 1.0 | 33.4% | 59.0% | 5 | 20.0% | 4.97 |
| A1b VEG10 | 0.1 | 12.1% | 54.9% | 32 | 50.0% | 5.12 |
| A1c VEG30 | 0.3 | 15.8% | 52.0% | 27 | 44.4% | 5.13 |
| A1d VEG50 | 0.5 | 17.0% | 54.9% | 21 | 52.4% | 5.02 |
| A1e VEG70 | 0.7 | 23.5% | 60.6% | 15 | 46.7% | 5.01 |
| A1f NO_VEG | 0.0 | 0% | 50.0% | 54 | 51.9% | 5.36 |

**All 6 failed governance gates.** No experiment achieved both sufficient volume (50+) and accuracy (58%+) at edge 3+.

### 3. Key Segmented Findings from Re-run

**Systematic OVER weakness confirmed (all models):**
- OVER HR ranged from 33-38% across all 6 experiments (never reached breakeven 52.4%)
- UNDER HR ranged from 50-62% — consistently profitable

**Best segments discovered (HR >= 58%, N >= 5):**

| Experiment | Segment | HR | N |
|-----------|---------|-----|---|
| A1b VEG10 | High lines (>20.5) | 71.4% | 7 |
| A1d VEG50 | High lines (>20.5) | 80.0% | 5 |
| A1d VEG50 | Role UNDER | 66.7% | 6 |
| A1d VEG50 | UNDER (all) | 61.5% | 13 |
| A1e VEG70 | Role UNDER | 80.0% | 5 |
| A1e VEG70 | Role (all) | 66.7% | 9 |
| A1f NO_VEG | Starters UNDER | 83.3% | 6 |
| A1f NO_VEG | Edge 7+ | 83.3% | 6 |
| A1f NO_VEG | High lines (>20.5) | 70.0% | 10 |
| A1f NO_VEG | Stars UNDER | 60.0% | 5 |

**Emerging pattern:** UNDER + high lines is consistently profitable across models. NO_VEG model has the richest niche segments despite lowest overall HR.

### 4. Feature Importance Shift Across Vegas Weights

Vegas dominance shifts predictably as weight decreases:

| Vegas Weight | #1 Feature | #2 Feature | #3 Feature |
|-------------|-----------|-----------|-----------|
| 1.0 (default) | vegas_points_line (33.4%) | vegas_opening_line (14.9%) | points_avg_season (11.0%) |
| 0.5 | points_avg_last_10 (17.1%) | vegas_points_line (17.0%) | points_avg_season (16.7%) |
| 0.1 | points_avg_season (23.3%) | points_avg_last_10 (16.4%) | vegas_points_line (12.1%) |
| 0.0 | points_avg_season (27.6%) | points_avg_last_10 (23.6%) | points_avg_last_5 (11.2%) |

At `vegas=0.5`, the model transitions from Vegas-led to player-stats-led. Below 0.5, player performance history dominates.

---

## Current State Summary

### Model Landscape (as of Feb 10)

| Model | Status | HR (Feb 4-9, matched n=301) | Notes |
|-------|--------|---------------------------|-------|
| `catboost_v9` (champion) | PRODUCTION (decaying) | 49.5% | Below breakeven, still only one generating edge 3+ picks |
| `catboost_v9_train1102_0108` | Shadow | 50.5% | Marginal improvement over champion |
| `catboost_v9_train1102_0131` | Shadow | 54.2% | Leading defaults candidate |
| **`catboost_v9_train1102_0131_tuned`** | **Shadow** | **55.1%** | **Best overall, +24pp disagreement signal** |
| C4_MATCHUP_ONLY | Experiment only | 60.0% (n=25) | Needs extended eval |
| C1_CHAOS | Experiment only | 58.3% (n=12) | Needs extended eval |

### Experiment Status

- **Session 180:** 34 experiments run (A1-A5, B1-B5, C1-C8) — none passed all gates
- **Session 182 (this session):** A1 re-run with segmented HR — confirmed no variant passes gates, but identified UNDER + high lines niche
- **Total experiments registered:** ~40+ in `nba_predictions.ml_experiments`

---

## Files Modified

- `docs/09-handoff/2026-02-10-SESSION-182-HANDOFF.md` — This file
- `docs/08-projects/current/session-179-validation-and-retrain/03-A1-VEGAS-WEIGHT-SWEEP-RESULTS.md` — New: detailed experiment results and analysis
- `docs/08-projects/current/session-179-validation-and-retrain/01-RETRAIN-PARADOX-AND-STRATEGY.md` — Updated with A1 empirical results
- `docs/09-handoff/NEXT-SESSION-PROMPT.md` — Updated next session prompt

*No code changes this session — all work was operational (predictions, backfills) and experimental (A1 re-run).*

---

## What Still Needs Doing

### P0 (Immediate — tonight/next session)

1. **Grade Feb 10** once games complete (~11 PM ET):
   ```bash
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-10","trigger_source":"manual"}' --project=nba-props-platform
   ```

2. **Run updated 4-way comparison:**
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 7
   ```

### P1 (Commit Session 181 changes)

3. **Commit and push Session 181's uncommitted changes** (segmented hit rates in `quick_retrain.py`). These are on disk but not committed:
   ```bash
   git add ml/experiments/quick_retrain.py
   git add docs/09-handoff/
   git add docs/08-projects/current/session-179-validation-and-retrain/
   ```

### P2 (When 2+ weeks eval data available, ~Feb 15+)

4. **Re-run C1_CHAOS and C4_MATCHUP_ONLY with extended eval:**
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C1_CHAOS_EXT" \
     --rsm 0.3 --random-strength 10 --subsample 0.5 --bootstrap Bernoulli \
     --train-start 2025-11-02 --train-end 2026-01-31 \
     --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force

   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C4_MATCHUP_EXT" \
     --category-weight "matchup=3.0" \
     --train-start 2025-11-02 --train-end 2026-01-31 \
     --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force
   ```

5. **Investigate segment-restricted deployment.** The A1 sweep found UNDER + high lines profitable across models. Could we deploy a model that only makes UNDER recommendations above a line threshold? Would need:
   - Extended eval of NO_VEG or VEG50 with UNDER-only filter
   - Custom actionability logic in prediction worker
   - Signal system changes

### P3 (Promotion Decision — ~Feb 17-20)

6. **Monitor Jan 31 tuned.** Currently leads at 55.1% HR with +24pp disagreement signal. Need ~2 more weeks.

7. **Investigate systematic OVER weakness.** All experiments show OVER HR < 40%. Is this model-specific or systemic? Query:
   ```sql
   SELECT recommendation, COUNT(*) as n,
     ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 1) as hr
   FROM nba_predictions.prediction_accuracy
   WHERE game_date >= '2026-01-01' AND system_id = 'catboost_v9'
     AND prediction_correct IS NOT NULL
   GROUP BY 1
   ```

### P4 (Future Experiments)

8. **Remaining experiment sweeps from 179B Master Plan:**
   - **A2: RSM Sweep** (already done in Session 180, but without segmented HR)
   - **A3: Loss Function Sweep** (same)
   - **A4: Tree Structure** (same)
   - **A5: Bootstrap/Sampling** (same)
   - Re-runs with segmented HR would add value if time permits

9. **Phase B/C experiments to re-run with segmented HR:**
   - **B5_2STG_BOOST** (52.2% HR, n=46) — close to passing volume gate
   - **C5_CONTRARIAN** (51.1% HR, n=45) — high volume, check UNDER niche
   - **C4_MATCHUP_ONLY** (60.0% HR, n=25) — highest HR, check niche

10. **Signal recalibration** — 9 of 15 recent days RED. Signal tuned for champion's wider distribution.

---

## Key References

- **This session's experiment results:** `docs/08-projects/current/session-179-validation-and-retrain/03-A1-VEGAS-WEIGHT-SWEEP-RESULTS.md`
- **Full 34-experiment sweep (Session 180):** `docs/09-handoff/2026-02-09-SESSION-180-HANDOFF.md`
- **Segmented HR implementation (Session 181):** `docs/09-handoff/2026-02-10-SESSION-181-HANDOFF.md`
- **Experiment infrastructure (Session 179B):** `docs/09-handoff/2026-02-09-SESSION-179B-HANDOFF.md`
- **Retrain paradox strategy:** `docs/08-projects/current/session-179-validation-and-retrain/01-RETRAIN-PARADOX-AND-STRATEGY.md`
- **Master Experiment Plan:** `.claude/skills/model-experiment/SKILL.md`
- **Parallel models guide:** `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md`
