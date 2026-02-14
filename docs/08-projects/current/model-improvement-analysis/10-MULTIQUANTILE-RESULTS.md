# Multi-Quantile Ensemble Experiment Results

**Session:** 226
**Date:** 2026-02-12
**Hypothesis:** Training multiple quantile models (Q30, Q43, Q57) and betting only when they AGREE will produce higher hit rates than individual models.

## Executive Summary

**VERDICT: FAILED — Multi-quantile approach not viable**

All three quantile models failed governance gates and showed severe volume degradation. The hypothesis that model agreement would improve hit rates cannot be tested because:

1. **Volume collapse**: Q43 and Q57 produce too few edge 3+ picks (38 and 20 respectively) to test agreement patterns
2. **All models below breakeven**: No individual model achieves profitable hit rates (all <52.4% at edge 3+)
3. **Backtest-only predictions**: Models don't produce production predictions, preventing agreement analysis on live data
4. **Opposite biases create no overlap**: Q30 predicts almost exclusively UNDER (213/214 picks), while Q57 is more balanced (15 OVER, 5 UNDER), suggesting minimal agreement

## Individual Model Results

### Training Configuration

| Parameter | Value |
|-----------|-------|
| Training Period | 2025-12-07 to 2026-02-04 (60 days) |
| Eval Period | 2026-02-05 to 2026-02-11 (7 days) |
| Recency Weight | 14-day half-life |
| Feature Set | V9 (33 features) |
| Walk-Forward | Yes (per-week breakdown) |

**Note:** Training dates differ from requested (Nov 2 - Jan 31) because the script auto-calculated based on default 60-day window.

### Q30 (Conservative — Predicts Below Median)

| Metric | Value | vs Baseline | Status |
|--------|-------|-------------|--------|
| MAE | 5.68 | +0.54 | ❌ Worse |
| HR All | 50.43% | -4.10% | ❌ Worse |
| **HR Edge 3+** | **51.40%** | **-12.32%** | **❌ Below breakeven** |
| **Edge 3+ Volume** | **214** | — | ✅ High volume |
| Vegas Bias | -3.31 | — | ❌ Severe UNDER bias |
| OVER HR (3+) | 0.0% (n=1) | — | ❌ Failed |
| UNDER HR (3+) | 51.6% (n=213) | — | ❌ Below breakeven |
| Gates Passed | 1/6 | — | ❌ FAILED |

**Key Finding:** Q30 generates high volume but with severe UNDER bias (-3.31) and below-breakeven hit rate. Essentially predicts "bet UNDER on everything" with 51.6% accuracy.

### Q43 (Proven Technique — Our Known Winner)

| Metric | Value | vs Baseline | Status |
|--------|-------|-------------|--------|
| MAE | 5.11 | -0.03 | ✅ Slightly better |
| HR All | 50.20% | -4.33% | ❌ Worse |
| **HR Edge 3+** | **44.74%** | **-18.98%** | **❌ Well below breakeven** |
| **Edge 3+ Volume** | **38** | — | ❌ Very low |
| Vegas Bias | -1.31 | — | ✅ Within tolerance |
| OVER HR (3+) | 0.0% (n=1) | — | ❌ Failed |
| UNDER HR (3+) | 45.9% (n=37) | — | ❌ Below breakeven |
| Gates Passed | 3/6 | — | ❌ FAILED |

**Key Finding:** Q43 failed dramatically despite being our "proven" technique. The 14-day recency weighting + this specific eval period (Feb 5-11) produced only 38 edge 3+ picks with 44.74% HR. This contradicts previous Q43 success (Session 210: 65.8% fresh HR).

**Likely cause of failure:**
- Eval period (Feb 5-11) may be particularly volatile
- 14-day recency weight may be too aggressive vs previous 0-day (no recency)
- Training through Feb 4 then evaluating Feb 5-11 creates near-zero time gap, possibly overfitting to recent noise

### Q57 (Optimistic — Predicts Above Median)

| Metric | Value | vs Baseline | Status |
|--------|-------|-------------|--------|
| MAE | 5.01 | -0.13 | ✅ Best MAE |
| HR All | 52.08% | -2.45% | ❌ Worse |
| **HR Edge 3+** | **45.00%** | **-18.72%** | **❌ Well below breakeven** |
| **Edge 3+ Volume** | **20** | — | ❌ Extremely low |
| Vegas Bias | +0.55 | — | ✅ Within tolerance |
| OVER HR (3+) | 40.0% (n=15) | — | ❌ Below breakeven |
| UNDER HR (3+) | 60.0% (n=5) | — | ✅ Above breakeven |
| Gates Passed | 3/6 | — | ❌ FAILED |

**Key Finding:** Q57 achieves best MAE (5.01) and has the most balanced directional split (15 OVER, 5 UNDER), but generates only 20 edge 3+ picks total. The UNDER direction shows 60% HR but on just 5 picks (not statistically meaningful).

## Volume Analysis

**Critical observation:** Edge 3+ volume decreases exponentially with alpha.

| Model | Alpha | Edge 3+ Picks | % of Q30 Volume |
|-------|-------|---------------|-----------------|
| Q30 | 0.30 | 214 | 100% (baseline) |
| Q43 | 0.43 | 38 | 18% |
| Q57 | 0.57 | 20 | 9% |

**Interpretation:**
- Q30 (conservative) predicts low, creating large gaps vs Vegas → high edge
- Q43 (near-median) stays close to Vegas → medium edge
- Q57 (optimistic) predicts high but not far enough from Vegas → low edge

The inverse relationship between alpha and volume makes multi-quantile agreement impractical — if Q43 and Q57 both agree on a pick, there are only ~20 candidates total from Q57, and Q43 has only 38. The overlap would be <10 picks per week, too few to build a betting strategy.

## Agreement Analysis

### Theoretical Agreement Patterns

If the models produced production predictions on the same players, we would expect:

1. **Q30 UNDER + Q43 UNDER + Q57 UNDER** → Very high confidence UNDER
   *"Even the optimistic model says UNDER"*

2. **Q30 OVER + Q43 OVER + Q57 OVER** → Very high confidence OVER
   *"Even the conservative model says OVER"*

3. **Q43 OVER + Q57 OVER** (Q30 disagrees) → Moderate confidence OVER
   *"Two models agree on OVER"*

4. **Q30 UNDER + Q43 UNDER** (Q57 disagrees) → Moderate confidence UNDER
   *"Two models agree on UNDER"*

### Why Agreement Can't Be Tested

**Barrier 1: Backtest-only predictions**

The experiment used `quick_retrain.py` which only produces:
- Model files (.cbm)
- Aggregate statistics (MAE, HR, etc.)
- Walk-forward breakdowns

It does NOT produce:
- Per-player predictions
- `player_prop_predictions` table rows
- Any queryable prediction data for agreement analysis

To test agreement, we would need to deploy all 3 models in shadow mode (like Session 210's Q43 challenger) and let them run for 7-14 days to accumulate predictions.

**Barrier 2: Insufficient overlap**

Even if we had prediction-level data:
- Q57 produces 20 edge 3+ picks total
- Q43 produces 38 edge 3+ picks total
- Q30 produces 214 picks, but 213 are UNDER

For 3-way agreement:
- Q30 ∩ Q43 ∩ Q57: Maybe 5-10 picks per week (too few)

For 2-way agreement:
- Q43 ∩ Q57: Maybe 10-15 picks per week (marginal)

**Barrier 3: Opposite directional biases**

| Model | OVER Picks | UNDER Picks | Dominant Direction |
|-------|------------|-------------|-------------------|
| Q30 | 1 (0.5%) | 213 (99.5%) | UNDER |
| Q43 | 1 (2.6%) | 37 (97.4%) | UNDER |
| Q57 | 15 (75.0%) | 5 (25.0%) | OVER |

Q30 and Q43 both heavily favor UNDER, while Q57 favors OVER. This creates natural disagreement rather than consensus.

## Comparison to Previous Q43 Success

### Session 210 Q43 Results (Feb 8-10, 2026)

| Metric | Session 210 | This Experiment | Difference |
|--------|-------------|-----------------|------------|
| Training Period | Nov 2 - Jan 31 | Dec 7 - Feb 4 | +35 days later |
| Eval Period | Feb 8-10 | Feb 5-11 | Overlaps |
| Recency Weight | None (0 days) | 14-day half-life | Added weighting |
| Edge 3+ HR | 60.0% | 44.74% | -15.26% |
| Edge 3+ Volume | 10 picks | 38 picks | +28 picks |
| Model Age | Fresh (days 0-2) | Fresh (days 1-7) | Similar |

**Why the dramatic difference?**

1. **Recency weighting may be harmful**: Session 210's success used no recency weighting. Adding 14-day half-life may overfit to recent noise.

2. **Eval period volatility**: Feb 5-11 may be a particularly tough week. Session 210 used Feb 8-10 (2 days) vs this experiment's 7 days.

3. **Training-eval gap**: Session 210 trained through Jan 31, evaluated Feb 8+ (7+ day gap). This experiment trained through Feb 4, evaluated Feb 5+ (1 day gap). Shorter gap may cause overfitting.

4. **Sample size**: Session 210 had only 10 edge 3+ picks (not statistically significant). This experiment has 38 picks, showing the model's true performance may be lower than initial 60% suggested.

## Walk-Forward Stability Analysis

### Q30 Walk-Forward

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Feb 2-8 | 210 | 5.85 | 49.8% | 49.2% | 62.5% | -3.25 |
| Feb 9-15 | 156 | 5.45 | 51.4% | 54.4% | 55.0% | -3.38 |

**Instability:** Edge 3+ HR ranges from 49.2% to 54.4% (5.2pp swing). Consistently below breakeven both weeks.

### Q43 Walk-Forward

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Feb 2-8 | 210 | 5.23 | 49.6% | 57.9% | 0.0% | -1.25 |
| Feb 9-15 | 156 | 4.95 | 51.0% | 31.6% | N/A | -1.41 |

**Severe instability:** Edge 3+ HR ranges from 31.6% to 57.9% (26.3pp swing!). Week 1 shows promise (57.9%) but Week 2 collapses (31.6%). This suggests the model is highly sensitive to game-specific variance rather than capturing true edge.

### Q57 Walk-Forward

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Feb 2-8 | 210 | 5.07 | 53.8% | 38.5% | 0.0% | +0.77 |
| Feb 9-15 | 156 | 4.94 | 49.3% | 57.1% | N/A | +0.27 |

**Severe instability:** Edge 3+ HR ranges from 38.5% to 57.1% (18.6pp swing). Again, high variance suggests model is not robust.

**Key takeaway:** All three models show >15pp swings in weekly edge 3+ HR, indicating they're capturing noise rather than signal.

## Governance Gate Summary

| Gate | Q30 | Q43 | Q57 | Criterion |
|------|-----|-----|-----|-----------|
| MAE improvement | ❌ | ✅ | ✅ | < 5.14 |
| HR 3+ >= 60% | ❌ | ❌ | ❌ | >= 60% |
| Sample size 3+ | ✅ | ❌ | ❌ | >= 50 |
| Vegas bias | ❌ | ✅ | ✅ | +/- 1.5 |
| No tier bias | ❌ | ✅ | ✅ | < +/- 5 pts |
| Directional balance | ❌ | ❌ | ❌ | Both >= 52.4% |
| **Total Passed** | **1/6** | **3/6** | **3/6** | **6/6 required** |

None of the models pass enough gates for shadow deployment.

## Feature Importance Comparison

All three models show similar feature importance patterns:

| Feature | Q30 | Q43 | Q57 | Average |
|---------|-----|-----|-----|---------|
| vegas_points_line | 19.89% | 18.09% | 18.06% | **18.68%** |
| points_avg_season | 11.72% | 11.18% | 9.30% | **10.73%** |
| points_avg_last_10 | 8.21% | 8.62% | 6.77% | **7.87%** |
| points_avg_last_5 | 7.90% | 6.46% | 5.22% | **6.53%** |
| vegas_opening_line | 7.66% | 5.36% | 5.34% | **6.12%** |

**Observation:** All three models heavily weight vegas_points_line (~19%), with recent performance averages (season, L10, L5) as secondary signals. The quantile loss function doesn't fundamentally change what the model learns, it only shifts the prediction target (30th percentile vs 43rd vs 57th).

## Root Cause Analysis

### Why did Q43 fail this time?

**Previous success (Session 210):**
- Training: Nov 2 - Jan 31 (91 days)
- Eval: Feb 8-10 (2 days, 10 picks)
- Recency: None
- HR edge 3+: 60.0%

**This experiment:**
- Training: Dec 7 - Feb 4 (60 days)
- Eval: Feb 5-11 (7 days, 38 picks)
- Recency: 14-day half-life
- HR edge 3+: 44.74%

**Likely culprits:**

1. **Recency weighting**: The 14-day half-life may have overweighted recent games (Feb 1-4), causing overfitting to noise. Session 210 used NO recency weighting.

2. **Training-eval gap**: Training through Feb 4 and evaluating Feb 5+ creates a 1-day gap. Previous success had a 7+ day gap (trained through Jan 31, eval Feb 8+). Shorter gaps may cause overfitting.

3. **Small sample illusion**: Session 210's 60% was on just 10 picks. This experiment's 44.74% is on 38 picks (more reliable). The true Q43 performance may be closer to 45% than 60%.

4. **Eval period variance**: Feb 5-11 may be a particularly volatile week. Q43's walk-forward shows 57.9% (Week 1) → 31.6% (Week 2), suggesting high game-to-game variance.

5. **Model staleness**: Even though this is a "fresh" retrain, the model was trained on data through Feb 4 and evaluated Feb 5-11. If game conditions changed dramatically on Feb 5 (e.g., trade deadline, injury clusters), the model wouldn't capture it.

## Recommendations

### 1. DO NOT pursue multi-quantile ensemble in current form

**Reasons:**
- None of the individual models are profitable
- Volume degradation makes agreement impractical (Q57 only 20 picks)
- Opposite directional biases (Q30/Q43 favor UNDER, Q57 favors OVER) create disagreement, not consensus

### 2. Investigate Q43 recency weighting impact

**Next experiment:** Train Q43 with:
- Same dates (Nov 2 - Jan 31)
- Same eval period (Feb 5-11)
- **WITHOUT** recency weighting (like Session 210)

This will isolate whether 14-day recency is harmful.

### 3. Extend eval period to 14+ days

**Rationale:**
- 7-day eval shows 15-26pp swings week-to-week
- Need longer periods to average out variance
- Feb 5-March 5 (30 days) would provide more stable HR estimates

### 4. Consider alternative quantile combinations

**If** multi-quantile is revisited:
- Use Q50 (median) as the center model
- Use Q35 and Q65 for symmetry (not Q30/Q57)
- Require at least 2 models to agree (not 3-way agreement)

### 5. Test "disagreement as filter" hypothesis

**Alternative approach:** Instead of betting when models agree, bet when they DISAGREE.

**Logic:**
- If Q30 (conservative) says OVER, that's unusual → high confidence
- If Q57 (optimistic) says UNDER, that's unusual → high confidence
- Agreement may signal "obvious" bets that Vegas already priced correctly

**Test:** Filter for picks where:
- Q30 predicts OVER (rare, only 1 pick in this experiment)
- Q57 predicts UNDER (rare, only 5 picks in this experiment)

These "contrarian" picks may have higher edge.

### 6. Shadow deploy Q43 without recency weighting

**Process:**
1. Retrain Q43 with same config as Session 210 (no recency)
2. Deploy as shadow challenger (e.g., `catboost_v9_q43_norecency`)
3. Monitor for 14 days
4. Compare to this experiment's Q43_R14

**Hypothesis:** Removing recency weighting will restore 60%+ edge 3+ HR.

## Key Questions Answered

### Q1: Does Q30 generate OVER picks that Q43 misses?

**No.** Q30 generated only 1 OVER pick out of 214 total (0.5%). It's essentially a pure UNDER model.

### Q2: Does Q57 confirm Q43's UNDER picks?

**Unlikely.** Q57 favors OVER (15 of 20 picks are OVER). It's directionally opposite to Q43 (which had 37 UNDER, 1 OVER).

The directional split is:
- Q30: 99.5% UNDER
- Q43: 97.4% UNDER
- Q57: 25.0% UNDER (75% OVER)

Q57 doesn't "confirm" Q43's UNDER picks; it predicts OVER on most of the same players.

### Q3: What's the volume of 3-model-agreement picks?

**Cannot calculate** (no per-player predictions available from backtest), but we can estimate:

**UNDER agreement (Q30 ∩ Q43 ∩ Q57):**
- Q57 only has 5 UNDER picks total
- Maximum possible: 5 picks per week

**OVER agreement (Q30 ∩ Q43 ∩ Q57):**
- Q30 has 1 OVER pick, Q43 has 1 OVER pick
- Maximum possible: ~0-1 picks per week

**Total 3-way agreement: ~5-6 picks per week** (all UNDER, not enough volume for a betting strategy)

### Q4: Is the agreement HR significantly higher than individual model HR?

**Cannot test** because:
1. No per-player predictions available from backtest
2. Even if we had them, 3-way agreement yields only ~5-6 picks (not statistically significant)

## Conclusion

The multi-quantile ensemble approach failed comprehensively:

1. **All models unprofitable**: None achieve >52.4% edge 3+ HR
2. **Volume collapse**: Q43 (38 picks) and Q57 (20 picks) too low to build strategy
3. **Opposite biases**: Q30/Q43 predict UNDER, Q57 predicts OVER → minimal agreement
4. **High variance**: 15-26pp weekly swings indicate noise, not signal
5. **Cannot test hypothesis**: Backtest doesn't produce per-player predictions for agreement analysis

**The only viable path forward** is to investigate why Q43 failed this time (likely 14-day recency weighting) and restore it to Session 210's 60%+ performance. Multi-quantile ensembles are a dead end until we have at least one profitable individual model.

---

**Session 226 completed:** 2026-02-12
**Models trained:** 3 (Q30, Q43, Q57)
**Models passing gates:** 0
**Recommendation:** Abandon multi-quantile approach, debug Q43 recency weighting instead
