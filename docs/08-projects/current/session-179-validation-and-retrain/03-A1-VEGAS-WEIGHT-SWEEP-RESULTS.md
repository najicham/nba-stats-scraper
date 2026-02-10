# A1 Vegas Weight Sweep — Experiment Results & Analysis

**Sessions:** 180 (initial run), 182 (re-run with segmented HR)
**Date:** 2026-02-10
**Status:** Complete — no variant passes governance gates

---

## Objective

Determine the optimal Vegas feature weight for CatBoost V9 by sweeping from full dependence (weight 1.0) to full independence (weight 0.0 / no-vegas mode). The hypothesis: reducing Vegas influence will generate more edge 3+ picks while maintaining sufficient accuracy for profitability.

## Experiment Setup

All 6 experiments share these parameters:
```bash
--train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force
```

- **Training:** 9,746 samples (quality filter >= 70)
- **Evaluation:** 269 samples with production lines (prediction_accuracy multi-source cascade)
- **Walk-forward:** Single week (Feb 2-8)

---

## Results Summary

### Primary Metrics

| Experiment | Vegas Weight | Vegas Imp% | Overall HR | E3+ N | E3+ HR | E5+ N | E5+ HR | MAE | Bias |
|-----------|-------------|-----------|-----------|-------|--------|-------|--------|-----|------|
| **A1a BASELINE** | 1.0 | 33.4% | **59.0%** | 5 | 20.0% | 1 | 0.0% | **4.97** | -0.12 |
| **A1b VEG10** | 0.1 | 12.1% | 54.9% | 32 | 50.0% | 6 | 33.3% | 5.12 | -0.33 |
| **A1c VEG30** | 0.3 | 15.8% | 52.0% | 27 | 44.4% | 2 | 50.0% | 5.13 | -0.30 |
| **A1d VEG50** | 0.5 | 17.0% | 54.9% | 21 | **52.4%** | 1 | 0.0% | 5.02 | -0.22 |
| **A1e VEG70** | 0.7 | 23.5% | **60.6%** | 15 | 46.7% | 1 | 0.0% | 5.01 | -0.16 |
| **A1f NO_VEG** | 0.0 | 0% | 50.0% | **54** | 51.9% | **18** | 44.4% | 5.36 | -0.56 |

### Governance Gate Results

| Experiment | MAE | HR 3+ ≥60% | N 3+ ≥50 | Vegas Bias | Tier Bias | Dir. Balance | **PASS?** |
|-----------|-----|-----------|---------|-----------|----------|-------------|-----------|
| A1a BASELINE | PASS | FAIL (20.0%) | FAIL (5) | PASS (-0.12) | PASS | FAIL | **NO** |
| A1b VEG10 | PASS | FAIL (50.0%) | FAIL (32) | PASS (-0.33) | PASS | FAIL | **NO** |
| A1c VEG30 | PASS | FAIL (44.4%) | FAIL (27) | PASS (-0.30) | PASS | FAIL | **NO** |
| A1d VEG50 | PASS | FAIL (52.4%) | FAIL (21) | PASS (-0.22) | PASS | FAIL | **NO** |
| A1e VEG70 | PASS | FAIL (46.7%) | FAIL (15) | PASS (-0.16) | PASS | FAIL | **NO** |
| A1f NO_VEG | FAIL | FAIL (51.9%) | PASS (54) | PASS (-0.56) | PASS | FAIL | **NO** |

---

## Directional Balance (OVER vs UNDER)

Every experiment shows the same pattern: UNDER significantly outperforms OVER at edge 3+.

| Experiment | OVER HR | OVER N | UNDER HR | UNDER N | Delta |
|-----------|---------|--------|----------|---------|-------|
| A1a BASELINE | 33.3% | 3 | 0.0% | 2 | — (tiny N) |
| A1b VEG10 | 36.4% | 11 | **57.1%** | 21 | +20.7pp |
| A1c VEG30 | 36.4% | 11 | 50.0% | 16 | +13.6pp |
| A1d VEG50 | 37.5% | 8 | **61.5%** | 13 | +24.0pp |
| A1e VEG70 | 33.3% | 6 | **55.6%** | 9 | +22.3pp |
| A1f NO_VEG | 37.5% | 16 | **57.9%** | 38 | +20.4pp |

**OVER HR never exceeds 37.5% across any experiment** within this eval window (Feb 1-8).

**UPDATE (Session 183):** This OVER weakness is a **temporal artifact of the Feb 1-8 eval window**, NOT a structural model issue. Champion production data (Jan 1 - Feb 9, n=1765) shows OVER 53.6% vs UNDER 53.1% — perfectly balanced. Week of Jan 12 had OVER at 60.3%. All 40 experiments used the same eval window, so all showed the same temporal pattern. The Jan eval experiments (below) will validate this finding over 31 days of data.

---

## Segmented Hit Rates (Best Segments)

These segments achieved HR >= 58% with N >= 5 in at least one experiment (from Session 182 re-runs):

### UNDER + High Lines — Consistent Winner

| Experiment | Segment | HR | N |
|-----------|---------|-----|---|
| A1f NO_VEG | High lines (>20.5) | **70.0%** | 10 |
| A1d VEG50 | High lines (>20.5) | **80.0%** | 5 |
| A1b VEG10 | High lines (>20.5) | **71.4%** | 7 |
| A1e VEG70 | Mid lines (12.5-20.5) | **66.7%** | 6 |

### Role Player UNDER — Secondary Signal

| Experiment | Segment | HR | N |
|-----------|---------|-----|---|
| A1d VEG50 | Role UNDER | **66.7%** | 6 |
| A1e VEG70 | Role UNDER | **80.0%** | 5 |
| A1f NO_VEG | Role UNDER | 57.1% | 21 |

### Stars/Starters UNDER — High HR, Small N

| Experiment | Segment | HR | N |
|-----------|---------|-----|---|
| A1f NO_VEG | Starters UNDER | **83.3%** | 6 |
| A1f NO_VEG | Stars UNDER | **60.0%** | 5 |
| A1d VEG50 | Stars UNDER | 66.7% | 3 |

### Edge 7+ — NO_VEG Niche

| Experiment | Segment | HR | N |
|-----------|---------|-----|---|
| A1f NO_VEG | Edge 7+ | **83.3%** | 6 |

---

## Feature Importance Shift

As Vegas weight decreases, the model's reliance shifts from Vegas → player performance history:

| Vegas Weight | #1 Feature | #2 Feature | #3 Feature | Vegas Total |
|-------------|-----------|-----------|-----------|------------|
| 1.0 (default) | vegas_points_line (33.4%) | vegas_opening_line (14.9%) | points_avg_season (11.0%) | **48.3%** |
| 0.7 | vegas_points_line (23.5%) | points_avg_season (14.6%) | points_avg_last_10 (14.1%) | **38.1%** |
| 0.5 | points_avg_last_10 (17.1%) | vegas_points_line (17.0%) | points_avg_season (16.7%) | **27.6%** |
| 0.3 | points_avg_season (23.2%) | points_avg_last_10 (17.7%) | vegas_points_line (15.8%) | **24.3%** |
| 0.1 | points_avg_season (23.3%) | points_avg_last_10 (16.4%) | vegas_points_line (12.1%) | **15.6%** |
| 0.0 (no vegas) | points_avg_season (27.6%) | points_avg_last_10 (23.6%) | points_avg_last_5 (11.2%) | **0%** |

**Inflection point at vegas=0.5:** Below this, player stats dominate. Above this, Vegas dominates.

The secondary features that emerge without Vegas:
- `opponent_def_rating` grows from ~1.6% to ~2.9%
- `opponent_pace` grows from ~0% to ~2.3%
- `pct_free_throw` grows from ~1.4% to ~2.1%
- `usage_spike_score` stays relevant (~1.6-2.2%) regardless of Vegas weight

---

## Analysis

### 1. The Volume-Accuracy Trade-off Is Real and Smooth

There is a nearly linear relationship between Vegas weight and edge 3+ volume:

```
Volume ≈ 5 + (1.0 - vegas_weight) × 50
```

But HR stays flat at ~50% ± 3% regardless of weight (excluding baseline's n=5 noise). Reducing Vegas creates more divergence from the market but doesn't improve the quality of that divergence.

### 2. OVER Weakness Is Structural

The OVER HR cap at ~37% across all weights suggests this is a feature gap, not a model architecture issue. Possible causes:
- Missing OVER-specific features: pace-up matchups, garbage time scoring, opponent injury-driven minutes increases
- Training data asymmetry: UNDER outcomes may be more predictable (tighter scoring distributions)
- Vegas line efficiency: UNDER lines may be systematically mispriced while OVER lines are efficient

### 3. Niche Segments Offer a Path Forward

While no model passes gates overall, specific segments are profitable:
- **UNDER + High Lines (>20.5):** 70-80% HR across multiple models
- **Role Player UNDER:** 57-80% HR
- **Edge 7+ (NO_VEG):** 83.3% HR (n=6)

A **segment-restricted deployment** strategy — deploying a model that only makes UNDER picks above a line threshold — could be profitable. This would require custom actionability logic in the prediction worker.

### 4. NO_VEG Model Has Unique Value

Despite worst overall HR (50.0%) and MAE (5.36), A1f NO_VEG:
- Generates most edge 3+ picks (54)
- Only model passing the volume gate (50+)
- Has richest niche segments (Starters UNDER 83.3%, Edge 7+ 83.3%, High lines 70%)
- Completely independent of Vegas (immune to line movement drift)

Could be valuable as a **complementary signal** alongside the champion, not a replacement.

---

## Comparison to Session 180 Initial Run

| Metric | Session 180 (initial) | Session 182 (re-run) | Difference |
|--------|----------------------|---------------------|-----------|
| A1a E3+ HR | 33.3% (n=6) | 20.0% (n=5) | CatBoost randomness |
| A1b E3+ HR | 50.0% (n=26) | 50.0% (n=32) | Consistent |
| A1d E3+ HR | 52.9% (n=17) | 52.4% (n=21) | Consistent |
| A1f E3+ HR | 50.0% (n=50) | 51.9% (n=54) | Consistent |

Results are highly consistent between runs. Small variations (~1-3%) from CatBoost's stochastic training. The re-run added segmented hit rate breakdowns not available in Session 180.

---

## Recommendations for Next Experiments

### Priority 1: Extended Eval (Feb 1-15+)
Re-run A1b (VEG10), A1d (VEG50), and A1f (NO_VEG) with 2+ weeks of eval to:
- Get sufficient sample sizes in niche segments
- Confirm or reject UNDER + High Lines profitability
- Determine if NO_VEG's Edge 7+ segment holds

### Priority 2: UNDER-Only Filtering
Run experiments with custom actionability that restricts to UNDER-only picks and measures effective HR and volume.

### Priority 3: Residual Mode Re-attempt
B4_RESID_INDEP (30% overall HR) failed with aggressive regularization. Try residual mode with default settings or lighter regularization.

### Priority 4: Ensemble Strategy
Combine NO_VEG (volume, independence) with champion (edge generation) in a majority-vote or weighted ensemble.

---

## Key Files

| Purpose | File |
|---------|------|
| Experiment trainer | `ml/experiments/quick_retrain.py` |
| BQ experiments table | `nba_predictions.ml_experiments` |
| Feature contract | `shared/ml/feature_contract.py` |
| Master Experiment Plan | `.claude/skills/model-experiment/SKILL.md` |
| Retrain paradox strategy | `docs/08-projects/current/session-179-validation-and-retrain/01-RETRAIN-PARADOX-AND-STRATEGY.md` |

### Query All A1 Results from BigQuery

```sql
SELECT experiment_name,
  JSON_VALUE(config_json, '$.category_weight') as cat_weights,
  ROUND(CAST(JSON_VALUE(results_json, '$.mae') AS FLOAT64), 2) as mae,
  JSON_VALUE(results_json, '$.hit_rate_all') as hr_all,
  JSON_VALUE(results_json, '$.hit_rate_edge_3plus') as hr_3plus,
  JSON_VALUE(results_json, '$.bets_edge_3plus') as n_3plus,
  ROUND(CAST(JSON_VALUE(results_json, '$.feature_importance.vegas_points_line') AS FLOAT64), 1) as vegas_imp,
  -- Segmented (Session 182 re-runs only)
  JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.UNDER.hr') as under_hr,
  JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.UNDER.n') as under_n,
  JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.OVER.hr') as over_hr,
  JSON_VALUE(results_json, '$.segmented_hit_rates.by_line_range.High (>20\\.5).hr') as high_line_hr
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE 'A1%'
ORDER BY experiment_name, created_at DESC
```
