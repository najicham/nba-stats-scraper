# V8 Performance by Confidence Level - Deep Analysis

**Date:** 2026-01-31
**Session:** 55 (continued)

---

## Key Finding: High-Confidence Picks Are Still Excellent

The overall hit rate dropped from 57.5% (Dec) to 41.9% (Jan), but this masks a critical detail:

**90+ confidence picks at 5+ edge: Still 79% hit rate in January**

---

## Monthly Performance by Confidence (3+ Edge)

| Month | 90+ Conf | 85-89 Conf | 80-84 Conf | Overall |
|-------|----------|------------|------------|---------|
| Nov '25 | 56.0% (166) | 47.0% (66) | N/A (2) | 48.8% |
| **Dec '25** | **75.3% (801)** | **65.0% (294)** | 55.6% (27) | **72.1%** |
| **Jan '26** | **77.0% (243)** | **48.8% (459)** | 48.6% (247) | **56.0%** |

### What Happened:

1. **90+ confidence stayed great**: 75.3% → 77.0% (actually improved!)
2. **85-89 confidence crashed**: 65.0% → 48.8% (below breakeven)
3. **Volume shifted to medium confidence**: Dec had 801 high-conf picks, Jan only 243

---

## Why Did Confidence Distribution Change?

### Model-Vegas Correlation Increased

| Month | Model-Vegas Corr | Avg Edge | % Predictions Over Vegas |
|-------|-----------------|----------|-------------------------|
| Nov '25 | 0.791 | 6.86 pts | 59.1% |
| Dec '25 | 0.743 | 5.18 pts | 60.4% |
| Jan '26 | **0.842** | **2.84 pts** | **45.0%** |

**The model started echoing Vegas lines more closely in January:**
- Average edge dropped from 6.86 → 2.84 (smaller predicted differences)
- Model flipped from predicting OVER Vegas to UNDER Vegas
- Higher correlation with Vegas = fewer unique insights

### Vegas Got More Accurate

| Month | Vegas MAE | Model MAE | Model Beats Vegas % |
|-------|-----------|-----------|---------------------|
| Nov '25 | 5.00 | 7.80 | 37.9% |
| Dec '25 | 5.37 | 5.51 | 52.8% |
| Jan '26 | 5.04 | 5.38 | 45.2% |

Vegas improved its lines in January, making it harder for the model to find edges.

---

## Most Mispredicted Players (January 2026)

### Overpredicted (Model Too High)

| Player | Predicted | Actual | Error | Games |
|--------|-----------|--------|-------|-------|
| Jerami Grant | 22.8 | 12.6 | +10.2 | 5 |
| Domantas Sabonis | 18.9 | 10.0 | +8.9 | 5 |
| Lauri Markkanen | 24.9 | 16.8 | +8.2 | 9 |
| Tyler Herro | 19.9 | 13.5 | +6.4 | 6 |
| Jalen Brunson | 23.3 | 17.7 | +5.6 | 10 |
| Karl-Anthony Towns | 20.3 | 14.7 | +5.5 | 10 |

### Underpredicted (Model Too Low)

| Player | Predicted | Actual | Error | Games |
|--------|-----------|--------|-------|-------|
| Kyshawn George | 12.9 | 18.2 | -5.3 | 5 |
| Mikal Bridges | 12.5 | 17.6 | -5.1 | 10 |
| Anfernee Simons | 11.9 | 16.7 | -4.9 | 11 |
| Klay Thompson | 8.9 | 13.6 | -4.7 | 8 |

**Pattern:** Established stars underperformed; emerging/role players overperformed.

---

## Root Cause Analysis

### Why Early Season Was Better

1. **Fresh Vegas lines**: Vegas starts season with less data, model had edge
2. **Stable player roles**: No mid-season trades/injuries yet
3. **Model predictions varied more**: Larger edges = more confidence in unique insights

### Why January Degraded (for medium-confidence picks)

1. **Vegas adapted**: Vegas improved its accuracy (MAE 5.37 → 5.04)
2. **Model converged on Vegas**: 0.84 correlation, only 2.84 avg edge
3. **Star underperformance**: Model expected established scorers to maintain averages
4. **Role changes**: Emerging players outperformed, model missed this
5. **Fewer high-confidence opportunities**: Volume shifted to medium-confidence picks

---

## Actionable Recommendations

### 1. Only Trade 90+ Confidence, 3+ Edge

| Filter | Hit Rate | Bets/Month | Status |
|--------|----------|------------|--------|
| 90+ conf, 5+ edge | **78.7%** | ~108 | Excellent |
| 90+ conf, 3+ edge | **77.0%** | ~243 | Excellent |
| 85-89 conf, 3+ edge | 48.8% | ~459 | Below breakeven |
| 80-84 conf, 3+ edge | 48.6% | ~247 | Below breakeven |

**Action:** Raise confidence threshold from 80 to 90 for all picks.

### 2. The JAN_DEC Model May Not Need Confidence Filter

The JAN_DEC model (trained on December only) achieved 54.7% at 3+ edge WITHOUT confidence filtering. Need to test if JAN_DEC's confidence calibration is better.

### 3. Consider Inverse-Vegas Strategy

When model closely agrees with Vegas (edge < 2), there's no edge. Only bet when model DISAGREES with Vegas significantly.

---

## Experiment: JAN_DEC by Confidence

Need to run this experiment to see if JAN_DEC model has better confidence calibration than V8.

```bash
# TODO: Evaluate JAN_DEC predictions with confidence breakdown
PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path "ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_*.cbm" \
    --eval-start 2026-01-01 --eval-end 2026-01-30 \
    --experiment-id JAN_DEC_CONF \
    --confidence-breakdown
```

---

## Summary Table

| Metric | V8 Dec '25 | V8 Jan '26 | Change |
|--------|------------|------------|--------|
| Overall hit rate | 57.5% | 41.9% | -15.6% |
| 90+ conf, 3+ edge | 75.3% | **77.0%** | +1.7% |
| 85-89 conf, 3+ edge | 65.0% | 48.8% | **-16.2%** |
| Model-Vegas correlation | 0.743 | 0.842 | +0.099 |
| Average edge | 5.18 | 2.84 | -2.34 |
| Vegas MAE | 5.37 | 5.04 | -0.33 |

**Conclusion:** High-confidence picks remained excellent. The degradation was in medium-confidence picks, which increased in volume as the model converged more closely with Vegas lines.

---

*Session 55 - Confidence Analysis Complete*
