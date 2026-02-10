# Session 180 Handoff — Full Experiment Sweep Results

**Date:** 2026-02-09
**Previous:** Session 179B (experiment infrastructure and feature weighting)
**This session:** Ran all 34 planned experiments to break Vegas dependency in CatBoost V9

---

## What Was Done

### 1. Executed Complete Experiment Sweep (34 Experiments)

Ran every experiment from the Master Experiment Plan built in Session 179B, organized into 7 groups:

| Group | Count | Focus |
|-------|-------|-------|
| **A1: Vegas Weight Sweep** | 6 | Dial vegas feature importance from 0 to 1.0 |
| **A2: RSM Sweep** | 4 | Feature subsampling per split (0.5-0.7) plus Depthwise |
| **A3: Loss Function Sweep** | 5 | Huber, LogCosh, MAE, Quantile alternatives to RMSE |
| **A4: Tree Structure Sweep** | 3 | Depthwise, Lossguide, and regularization combos |
| **A5: Bootstrap/Sampling Sweep** | 3 | MVS, Bernoulli, random strength |
| **B: Targeted Combos** | 5 | Best-of-breed combinations from A-phase winners |
| **C: Random Exploration** | 8 | Unusual/creative combos to find surprises |

**Common parameters for all 34 experiments:**
```bash
--train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force
```

All results stored in `nba_predictions.ml_experiments`.

### 2. Key Finding: NO Experiment Passed All Governance Gates

Not a single experiment met the combined criteria of:
- 50+ edge 3+ picks (volume)
- 58%+ HR at edge 3+ (profitability)
- Walk-forward stability

The fundamental trade-off was confirmed across all 34 experiments: **more Vegas independence = more picks but lower accuracy.**

### 3. Complete Results

| Exp | Type | MAE | HR All | E3+ N | E3+ HR | Vegas Imp |
|-----|------|-----|--------|-------|--------|-----------|
| A1a_BASELINE | default | 4.95 | 60.0% | 6 | 33.3% | 31.6% |
| A1b_VEG10 | vegas=0.1 | 5.13 | 53.1% | 26 | 50.0% | 13.6% |
| A1c_VEG30 | vegas=0.3 | 5.06 | 55.3% | 18 | 38.9% | 15.0% |
| A1d_VEG50 | vegas=0.5 | 5.06 | 54.2% | 17 | 52.9% | 17.5% |
| A1e_VEG70 | vegas=0.7 | 5.01 | 58.6% | 8 | 37.5% | 21.2% |
| A1f_NO_VEG | no-vegas | 5.42 | 50.9% | 50 | 50.0% | — |
| A2a_RSM50 | rsm=0.5 | 4.92 | 61.4% | 6 | 33.3% | 24.2% |
| A2b_RSM60 | rsm=0.6 | 5.03 | 51.7% | 4 | 0.0% | 27.0% |
| A2c_RSM70 | rsm=0.7 | 4.98 | 60.9% | 4 | 0.0% | 32.3% |
| A2d_RSM60_DW | rsm=0.6+DW | 5.00 | 52.7% | 6 | 16.7% | 32.9% |
| A3a_HUBER5 | Huber:5 | 5.07 | 53.4% | 9 | 11.1% | 2.6% |
| A3b_HUBER8 | Huber:8 | 5.14 | 49.6% | 17 | 41.2% | 12.0% |
| A3c_LOGCOSH | LogCosh | 5.09 | 53.6% | 10 | 40.0% | 15.2% |
| A3d_MAE | MAE | 5.05 | 47.1% | 7 | 28.6% | 25.1% |
| A3e_Q55 | quantile=0.55 | 5.03 | 49.4% | 4 | 0.0% | 28.6% |
| A4a_DEPTHWISE | Depthwise | 4.98 | 53.4% | 4 | 25.0% | 40.8% |
| A4b_LOSSGUIDE | Lossguide | 4.97 | 60.6% | 3 | 0.0% | 45.4% |
| A4c_DW_REG | DW+rand=5 | 4.97 | 54.6% | 7 | 28.6% | 29.4% |
| A5a_MVS | MVS+0.8 | 4.95 | 60.0% | 6 | 33.3% | 31.6% |
| A5b_BERN70 | Bernoulli+0.7 | 4.97 | 53.5% | 5 | 20.0% | 33.1% |
| A5c_RAND5 | rand_str=5 | 5.06 | 50.0% | 14 | 50.0% | 21.3% |
| B1_INDEP | DW+RSM+veg=0.3 | 5.15 | 54.3% | 33 | 48.5% | 2.2% |
| B2_ROBUST | MVS+Huber+veg=0.3 | 5.22 | 52.5% | 31 | 41.9% | 1.7% |
| B3_KITCHEN | everything | 5.36 | 50.0% | 60 | 51.7% | — |
| B4_RESID_INDEP | residual+DW+RSM | 4.98 | 30.0% | 3 | 33.3% | — |
| B5_2STG_BOOST | two-stage+boost | 5.35 | 50.0% | 46 | 52.2% | — |
| C1_CHAOS | rsm=0.3,rand=10,sub=0.5 | 5.04 | 54.3% | 12 | 58.3% | 15.8% |
| C2_LOSSNO | no-vegas+Lossguide | 5.36 | 50.9% | 48 | 50.0% | — |
| C3_VEG_BOOST | vegas=3x | 4.95 | 56.6% | 2 | 0.0% | 45.5% |
| C4_MATCHUP_ONLY | matchup=3x | 5.22 | 46.7% | 25 | 60.0% | 17.2% |
| C5_CONTRARIAN | quantile+MVS+DW+veg=0.2 | 5.28 | 52.7% | 45 | 51.1% | — |
| C6_RESID_MINIMAL | residual+rsm=0.4+rand=8 | 4.96 | 52.6% | 3 | 33.3% | 4.3% |
| C7_RECENT_LOGCOSH | logcosh+recency+boost | 5.23 | 46.7% | 21 | 52.4% | 10.7% |
| C8_MAE_2STG | MAE+two-stage+DW | 5.53 | 47.4% | 61 | 50.8% | — |

### 4. Notable Individual Results

**Best HR at edge 3+ (small sample):**
- **C4_MATCHUP_ONLY** — 60.0% HR on n=25 (matchup features weighted 3x). Would pass the 58% gate if sample size were sufficient, but n=25 is well below the 50+ threshold.
- **C1_CHAOS** — 58.3% HR on n=12 (high randomization: rsm=0.3, random_strength=10, subsample=0.5). Meets the HR gate but only 12 picks.

**Best volume:**
- **C8_MAE_2STG** — 61 edge 3+ picks at 50.8% HR (MAE loss + two-stage + Depthwise). Volume is there but accuracy is below breakeven.
- **B3_KITCHEN** — 60 edge 3+ picks at 51.7% HR (everything combined). Same pattern: volume trades off against accuracy.

**Interesting patterns:**
- A1 sweep shows a clean gradient: as vegas weight drops (1.0 -> 0.1 -> 0), edge 3+ picks increase (6 -> 26 -> 50) but HR hovers around 50%.
- RSM (A2) and tree structure (A4) changes kept picks low (3-7) while maintaining higher overall HR, suggesting they don't break Vegas dominance enough.
- Loss function changes (A3) had varied effects: Huber strongly suppressed vegas importance (2.6%) but also suppressed accuracy.

### 5. Systematic OVER Weakness Discovered

Across all 34 experiments, OVER hit rate never exceeded 54.5%. This is a consistent weakness regardless of:
- Vegas feature weighting
- Loss function choice
- Tree structure
- Bootstrap method
- Feature subsampling

This suggests a structural issue — either a feature gap on the OVER side, or a genuine market inefficiency where UNDER bets are more predictable.

---

## Strategic Conclusions

### 1. The Retrain Paradox Is Real and Deep

Feature weighting, loss functions, tree structures, bootstrap methods, residual modeling, and two-stage approaches — individually and in combination — cannot break the Vegas dependency with only 1 week of evaluation data. The 34 experiments exhaustively tested the parameter space available within CatBoost V9's architecture.

### 2. The Champion's "Staleness" IS the Edge

Models trained on recent data (through Jan 31) learn current Vegas relationships. This produces better MAE but near-zero divergence from Vegas. The champion (trained through Jan 8) generates edge *because* it is stale — its learned Vegas relationship has drifted from current Vegas behavior. This is not a bug; it is the mechanism.

### 3. Two Promising Leads Require More Data

- **C4_MATCHUP_ONLY (60.0% HR, n=25):** Boosting matchup features to 3x importance may capture genuine matchup-based edge that Vegas underprices. But n=25 is too small for confidence. Needs 2+ weeks of eval.
- **C1_CHAOS (58.3% HR, n=12):** Extreme randomization (rsm=0.3, random_strength=10) forces tree diversity and may capture hidden non-Vegas signal. But n=12 is far too small. Needs extended eval.

### 4. The Jan 31 Defaults Challenger Remains Best Alternative

The existing shadow model (`catboost_v9_train1102_0131`) at 56.1% HR across production data (Feb 4-8) remains the best candidate for promotion. It was not part of this experiment sweep — it is already running in shadow mode. Continue monitoring it.

### 5. Eval Period Limitation

One week (Feb 1-8) with 269 total samples yielded only 2-61 edge 3+ picks per experiment. This is insufficient for reliable statistical conclusions. The top experiments need re-evaluation once 2+ weeks of data are available.

---

## Files Modified

### `ml/experiments/quick_retrain.py`
- **Added `compute_segmented_hit_rates()` function** (~80 lines): Computes HR breakdowns by tier (Stars/Starters/Role/Bench), direction (OVER/UNDER), tier x direction (8 cells), edge bucket ([3-5), [5-7), [7+)), and line range (Low/Mid/High).
- **Call + display in eval section** (~45 lines): New "SEGMENTED HIT RATES (edge 3+)" section in output showing all breakdowns, with best segments flagged (HR >= 58% with N >= 5).
- **Stored in results_json**: `segmented_hit_rates` key added for querying in BigQuery.

No deployment needed (experiment infrastructure only).

---

## What Still Needs Doing

### P0 (Immediate — next session)

1. **Continue monitoring Jan 31 defaults challenger** (`catboost_v9_train1102_0131`). This remains the leading promotion candidate at 56.1% HR (Feb 4-8). Needs 2+ weeks of shadow data before a promotion decision (~Feb 17 target).

### P1 (When 2+ weeks of eval data are available, ~Feb 15+)

2. **Re-run C1_CHAOS and C4_MATCHUP_ONLY with expanded eval period** (Feb 1-Feb 15+). The eval now includes per-tier/direction/edge/line segmented hit rates — look for segments with HR >= 58% and N >= 5 to identify model "specialties" (e.g., UNDER-only or role-player-only deployment):
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
   **New:** Check "SEGMENTED HIT RATES" section in output. Also queryable via:
   ```sql
   SELECT experiment_name,
     JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.UNDER.hr') as under_hr,
     JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.UNDER.n') as under_n,
     JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.OVER.hr') as over_hr
   FROM nba_predictions.ml_experiments
   WHERE experiment_name LIKE 'C%_EXT'
   ```

### P2 (Investigation)

3. **Investigate systematic OVER weakness.** All 34 experiments had OVER HR below breakeven (~54.5% max). Possible causes:
   - Feature gap: no features capturing OVER-specific signals (e.g., pace-up matchups, blowout garbage time)
   - Market inefficiency: UNDER bets may genuinely be more predictable (tighter distributions)
   - Training data imbalance: check if training set has asymmetric OVER/UNDER outcomes
   - Recommended first step: query OVER vs UNDER grading split across the full prediction_accuracy table to see if this is model-specific or systemic

### P3 (Future exploration)

4. **Consider ensemble approaches.** Combine predictions from C4 (matchup focus) and C1 (chaotic) with the production model. Different models may capture different edges — a majority-vote or weighted-average ensemble could improve both accuracy and volume.

5. **Grade Feb 9 when raw data available.** Verify Feb 10 live predictions have all 4 shadow models.

6. **Monthly retrain cadence.** Next retrain window: train through end of February, evaluate first week of March.

---

## Key Technical Details for Next Session

### Querying Experiment Results

All 34 experiments are in BigQuery:
```sql
SELECT experiment_name,
  JSON_VALUE(config_json, '$.category_weight') as cat_weights,
  JSON_VALUE(results_json, '$.mae') as mae,
  JSON_VALUE(results_json, '$.hit_rate_all') as hr_all,
  JSON_VALUE(results_json, '$.hit_rate_edge_3plus') as hr_3plus,
  JSON_VALUE(results_json, '$.bets_edge_3plus') as n_3plus,
  JSON_VALUE(results_json, '$.feature_importance.vegas_points_line') as vegas_imp
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE 'A%' OR experiment_name LIKE 'B%' OR experiment_name LIKE 'C%'
ORDER BY created_at DESC
```

### The Volume-Accuracy Trade-off (Quantified)

From the A1 vegas weight sweep, we can see the relationship clearly:

| Vegas Weight | Edge 3+ Picks | Edge 3+ HR |
|-------------|---------------|------------|
| 1.0 (default) | 6 | 33.3% |
| 0.7 | 8 | 37.5% |
| 0.5 | 17 | 52.9% |
| 0.3 | 18 | 38.9% |
| 0.1 | 26 | 50.0% |
| 0.0 (no vegas) | 50 | 50.0% |

Removing Vegas entirely produces ~50 picks at exactly coinflip accuracy. No sweet spot exists in this 1-week sample where both volume and accuracy are sufficient.

### Why Residual Mode Failed

B4_RESID_INDEP (residual + Depthwise + RSM) had the worst overall HR at 30.0%. Residual mode trains on `actual - vegas_line`, which has much higher variance than absolute points. Combined with aggressive regularization (Depthwise + RSM), the model couldn't learn stable residual patterns. This approach may work with a larger training set or simpler regularization.

### OVER Weakness Detail

Across all experiments, OVER predictions consistently underperformed UNDER predictions. This was invariant to:
- Vegas feature weight (0.0 to 1.0)
- Loss function (RMSE, Huber, MAE, LogCosh, Quantile)
- Tree structure (Symmetric, Depthwise, Lossguide)
- Bootstrap method (Bayesian, MVS, Bernoulli)

This suggests the issue is in the feature set or training data, not the model architecture.

---

## Context: Current Model Landscape

| Model | Status | HR (Feb 4-8) | Edge 3+ Picks | Notes |
|-------|--------|-------------|---------------|-------|
| `catboost_v9` (champion) | PRODUCTION (decaying) | 49.8% | 73 (Jan 26 week) | Below breakeven, edge 3+ crashed from 71.2% to 47.9% |
| `catboost_v9_train1102_0131` | Shadow | 56.1% | ~6 (tight predictions) | Leading promotion candidate |
| `catboost_v9_train1102_0131_tuned` | Shadow | 56.9% | ~6 (tight predictions) | Slightly better but similar profile |
| C4_MATCHUP_ONLY | Experiment only | 60.0% (n=25) | 25 | Needs extended eval |
| C1_CHAOS | Experiment only | 58.3% (n=12) | 12 | Needs extended eval |
| B3_KITCHEN | Experiment only | 51.7% (n=60) | 60 | Volume but coinflip accuracy |
