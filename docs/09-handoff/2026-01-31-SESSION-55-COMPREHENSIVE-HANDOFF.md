# Session 55 Comprehensive Handoff

**Date:** 2026-01-31
**Focus:** Model ensemble research, confidence/edge analysis, Vegas sharpness monitoring
**Status:** Research complete, multiple key discoveries, ready for implementation

---

## Executive Summary

Session 55 answered critical questions from Sessions 52-54 and made several important discoveries:

1. **Production V8 uses ONLY CatBoost** (not the full stacked ensemble)
2. **High-confidence (90+) picks at 3+ edge still hit 77%** in January
3. **The overall hit rate drop (57% → 42%) was from medium-confidence picks**
4. **Vegas got sharper in January** (model beats Vegas dropped from 53% to 45%)
5. **Recency weighting on historical data doesn't help** - training on recent data only is key
6. **Created monitoring tools** for drift detection and Vegas sharpness

---

## Critical Finding: Confidence + Edge Filtering

### January 2026 V8 Performance Matrix

| Confidence | Edge | Hit Rate | Bets | Profitable? |
|------------|------|----------|------|-------------|
| **90+** | **5+** | **78.7%** | 108 | ✅ Excellent |
| **90+** | **3-5** | **75.6%** | 135 | ✅ Excellent |
| 90+ | 2-3 | 59.2% | 169 | ✅ Yes |
| 90+ | <2 | 33.4% | 398 | ❌ Terrible |
| 85-89 | 5+ | 53.3% | 195 | ✅ Barely |
| 85-89 | 3-5 | 45.5% | 264 | ❌ No |
| 85-89 | <2 | 21.8% | 586 | ❌ Terrible |
| 80-84 | 5+ | 51.7% | 120 | ❌ No |
| 80-84 | 3-5 | 45.7% | 127 | ❌ No |

### Key Insight

**The 77-79% hit rate at 90+ confidence, 3+ edge is STILL EXCELLENT in January.**

The overall hit rate dropped because:
1. More predictions shifted to medium confidence (85-89)
2. Medium confidence predictions degraded from 65% → 49%
3. Model started echoing Vegas more closely (smaller edges)

### Recommended Trading Filter

```sql
WHERE confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 3
```

This yields ~240 bets/month at 77% hit rate.

---

## What is Confidence vs Edge?

### Confidence (Model Certainty)

**Definition:** How certain the model is in its prediction

**Calculated in `catboost_v8.py`:**
```python
confidence = 75  # base
confidence += feature_quality_bonus    # +2 to +10
confidence += player_consistency_bonus # +2 to +10
# Range: 79% to 95%
```

**Components:**
- Feature quality score (data completeness)
- Player consistency (low std deviation = higher confidence)

### Edge (Market Disagreement)

**Definition:** How much the model disagrees with Vegas

**Calculated:**
```python
edge = abs(predicted_points - vegas_line)
```

### Why Both Matter

| Scenario | Confidence | Edge | Result |
|----------|------------|------|--------|
| High conf, low edge | 92% | 0.5 | ❌ Confident about agreeing with Vegas - no value |
| Low conf, high edge | 79% | 6.0 | ❌ Disagrees but unreliable - may be wrong |
| **High conf, high edge** | **92%** | **5.0** | ✅ Confident AND found something Vegas missed |

**Documentation:** `docs/08-projects/current/model-ensemble-research/CONFIDENCE-VS-EDGE.md`

---

## V8 Architecture Discovery

### The Misconception

The `catboost_v8.py` docstring says:
> "Uses stacked ensemble (XGBoost + LightGBM + CatBoost with Ridge meta-learner)"

### The Reality

**Production only loads CatBoost:**
```python
# catboost_v8.py line 478
model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))
self.model = cb.CatBoostRegressor()
self.model.load_model(str(model_path))
```

XGBoost and LightGBM models exist in `models/` but are **never loaded**.

### Training vs Production

| Phase | What's Used |
|-------|-------------|
| Training | XGBoost + LightGBM + CatBoost + Ridge meta-learner |
| Production | **Only CatBoost** |

### Stacked Ensemble Coefficients (from training)

```python
stacked_coefs = [0.38, -0.10, 0.74]
#                XGB   LGB    CB (dominates)
```

CatBoost contributed 74% of the ensemble weight, which is why using just CatBoost works almost as well.

**Documentation:** `docs/08-projects/current/model-ensemble-research/V8-ARCHITECTURE-ANALYSIS.md`

---

## Stacked Ensemble Experiments

### Question: Does recency weighting help the full ensemble?

Session 52 found 65% hit rate with 60-day recency on single CatBoost. We tested if this helps the full stacked ensemble.

### Results (January 2026)

| Configuration | Training Data | Recency | Hit Rate (3+ edge) |
|--------------|--------------|---------|-------------------|
| V8 Production | 2021-2024 | None | 49.4% |
| ENS_BASELINE | 2021-2024 | None | 50.0% |
| ENS_REC60 | 2021-2024 | 60d half-life | 50.1% |
| **JAN_DEC_ONLY** | **Dec 2025** | **Implicit** | **54.7%** |

### Conclusion

**Recency weighting on old data doesn't help.** Training on recent data only (JAN_DEC) is the winning approach.

The 65% from Session 52 was likely:
1. Small sample noise (40 bets)
2. Different evaluation methodology
3. Different model (experimental vs production)

**Documentation:** `docs/08-projects/current/model-ensemble-research/SESSION-55-FINDINGS.md`

---

## Why Did Performance Drop in January?

### Model-Vegas Correlation Increased

| Month | Model-Vegas Corr | Avg Edge | Model Beats Vegas |
|-------|-----------------|----------|-------------------|
| Nov '25 | 0.791 | 6.86 pts | 37.9% |
| Dec '25 | 0.743 | 5.18 pts | 52.8% |
| **Jan '26** | **0.842** | **2.84 pts** | **45.2%** |

The model started **echoing Vegas** more closely in January:
- Higher correlation (0.84 vs 0.74)
- Smaller edges (2.84 vs 5.18)
- Fewer unique insights

### Vegas Got More Accurate

| Month | Vegas MAE | Model MAE | Who's Better |
|-------|-----------|-----------|--------------|
| Dec '25 | 5.37 | 5.51 | Vegas slightly |
| Jan '26 | 5.04 | 5.38 | Vegas more |

### Confidence Distribution Shifted

| Month | 90+ Conf Predictions | 85-89 Conf Predictions |
|-------|---------------------|------------------------|
| Dec '25 | 1,552 | 416 |
| Jan '26 | 810 | 1,261 |

More predictions shifted to medium confidence (which performs worse).

### Most Mispredicted Players (January)

**Overpredicted (model too high):**
- Jerami Grant: +10.2 pts (predicted 22.8, actual 12.6)
- Domantas Sabonis: +8.9 pts
- Lauri Markkanen: +8.2 pts
- Tyler Herro: +6.4 pts

**Underpredicted (model too low):**
- Kyshawn George: -5.3 pts
- Mikal Bridges: -5.1 pts
- Anfernee Simons: -4.9 pts

**Pattern:** Established stars underperformed; emerging players overperformed.

**Documentation:** `docs/08-projects/current/model-ensemble-research/CONFIDENCE-ANALYSIS.md`

---

## Vegas Sharpness Monitoring

### Created: `bin/monitoring/vegas_sharpness_monitor.py`

Tracks how accurate Vegas lines are by player tier.

### January 2026 Sharpness by Tier

| Tier | Vegas MAE | Model MAE | Model Beats Vegas |
|------|-----------|-----------|-------------------|
| Star | 7.54 | 8.13 | 44.8% |
| Starter | 5.80 | 6.28 | 43.3% |
| Rotation | 4.51 | 4.77 | 46.0% |
| Bench | 2.98 | 3.05 | 46.7% |

**Vegas is more accurate than our model on ALL tiers in January.**

### Sharpest Lines (Hardest to Beat)

| Player | Vegas MAE | Model Beats |
|--------|-----------|-------------|
| Ben Sheppard | 1.51 | 37.5% |
| Dorian Finney-Smith | 1.82 | 30.0% |
| Alex Caruso | 1.88 | 16.7% |

### Softest Lines (Potential Opportunities)

| Player | Vegas MAE | Model Beats |
|--------|-----------|-------------|
| **Jalen Brunson** | 10.64 | **80.0%** ✅ |
| **Cooper Flagg** | 10.63 | **71.4%** ✅ |
| Lauri Markkanen | 11.91 | 33.3% ❌ |

**Documentation:** `docs/08-projects/current/model-ensemble-research/VEGAS-SHARPNESS-ANALYSIS.md`

---

## Drift Detection System

### Created: `bin/monitoring/model_drift_detection.py`

Monitors prediction performance for early warning of model degradation.

### Current Status (January 2026)

```
DRIFT SCORE: 60% (CRITICAL)
Alerts: 6/10 signals

Recommendation: URGENT - Consider immediate model retraining
```

### Signals Monitored

| Signal | Status | Value |
|--------|--------|-------|
| 7-day hit rate | ALERT | 45.1% |
| 14-day hit rate | ALERT | 46.9% |
| 30-day hit rate | OK | 58.8% |
| Star deviation | OK | +0.4 pts |
| Surprise rate | OK | 11.4% |
| Error distribution | ALERT | MAE 5.89 |
| Starter tier | ALERT | 45.2% |
| Rotation tier | ALERT | 48.3% |
| Bench tier | ALERT | 33.3% |

---

## Cross-Year January Analysis

### Do January patterns repeat?

| Year | Star Deviation | Star Underperform % | Surprise Rate |
|------|---------------|---------------------|---------------|
| 2024 | -2.18 pts | 37.2% | 11.4% |
| 2025 | -0.65 pts | 30.3% | 11.1% |
| 2026 | -1.70 pts | 31.9% | 9.7% |

**Yes, stars consistently underperform in January** (all years show negative deviation).

### V8 January Performance by Year

| Year | Hit Rate | MAE |
|------|----------|-----|
| Jan 2025 | 55.5% | 4.0 |
| Jan 2026 | 41.9% | 5.38 |

V8 degraded from 55.5% → 41.9% because it's now 18 months out of distribution.

---

## Hit Rate Analysis Skill

### Created: `/hit-rate-analysis` skill

Provides consistent, standardized hit rate analysis.

### Usage

Ask about hit rates or type `/hit-rate` to get:
- Confidence × Edge matrix
- Player tier breakdown
- Weekly/monthly trends
- System comparison

### Key Definitions (Consistent Everywhere)

| Metric | Calculation |
|--------|-------------|
| Confidence | `confidence_score` from model (0.75-0.95) |
| Edge | `ABS(predicted_points - line_value)` |
| Hit Rate | `prediction_correct = TRUE` / total |
| Breakeven | 52.4% (with -110 odds) |

| Tier | Points Avg |
|------|------------|
| Star | ≥22 ppg |
| Starter | 14-22 ppg |
| Rotation | 6-14 ppg |
| Bench | <6 ppg |

---

## Files Created This Session

### Scripts

| File | Purpose |
|------|---------|
| `ml/experiments/train_stacked_ensemble_recency.py` | Train full ensemble with recency |
| `ml/experiments/evaluate_stacked_ensemble.py` | Evaluate ensemble on date range |
| `bin/monitoring/model_drift_detection.py` | Drift detection system |
| `bin/monitoring/vegas_sharpness_monitor.py` | Vegas accuracy tracking |

### Documentation

| File | Purpose |
|------|---------|
| `docs/08-projects/current/model-ensemble-research/V8-ARCHITECTURE-ANALYSIS.md` | V8 architecture discovery |
| `docs/08-projects/current/model-ensemble-research/SESSION-55-FINDINGS.md` | Ensemble experiment results |
| `docs/08-projects/current/model-ensemble-research/CONFIDENCE-VS-EDGE.md` | Confidence/edge explanation |
| `docs/08-projects/current/model-ensemble-research/CONFIDENCE-ANALYSIS.md` | Full confidence breakdown |
| `docs/08-projects/current/model-ensemble-research/VEGAS-SHARPNESS-ANALYSIS.md` | Vegas sharpness findings |

### Skills

| File | Purpose |
|------|---------|
| `.claude/skills/hit-rate-analysis/SKILL.md` | Standardized hit rate queries |

### Experiment Results

| File | Description |
|------|-------------|
| `ml/experiments/results/ensemble_exp_ENS_REC60_*` | Recency-weighted ensemble |
| `ml/experiments/results/ensemble_exp_ENS_BASELINE_*` | Baseline ensemble |

---

## Recommendations for Next Session

### Immediate Actions (P0)

1. **Deploy JAN_DEC model to production**
   - It achieves 54.7% vs V8's 49.4%
   - Already trained: `ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm`
   ```bash
   gsutil cp ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm \
       gs://nba-props-models/catboost_jan_dec_v1.cbm
   ```

2. **Update trading filters**
   - Only trade 90+ confidence, 3+ edge
   - This gives 77% hit rate vs 52.4% breakeven

3. **Fix V8 docstring**
   - Currently misleading about "stacked ensemble"
   - Should state it only uses CatBoost

### Short-Term Actions (P1)

4. **Set up monthly retraining pipeline**
   - Train on last 60 days at start of each month
   - JAN_DEC's advantage comes from recency

5. **Run monitoring daily**
   ```bash
   PYTHONPATH=. python bin/monitoring/model_drift_detection.py
   PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py
   ```

6. **Consider January seasonal adjustment**
   - Stars consistently underperform by 1-2 pts
   - Could add penalty for star players in January

### Research Questions for Next Session

1. **Why does model echo Vegas more in January?**
   - Is the `vegas_points_line` feature dominating?
   - Should we reduce Vegas feature weight?

2. **Can we predict when Vegas will be sharp?**
   - Build sharpness forecasting model
   - Reduce bets when Vegas is sharp

3. **Should we retrain with trajectory features?**
   - Stars underperforming → add breakout detection
   - Session 28 added `pts_slope_10g`, `breakout_flag`

4. **Is the JAN_DEC model's confidence calibration better?**
   - Need to evaluate with confidence breakdown
   - May not need 90+ filter if calibration is good

---

## Key Queries Reference

### Standard Hit Rate Matrix

```sql
SELECT
  CASE WHEN confidence_score >= 0.90 THEN '90+' WHEN confidence_score >= 0.85 THEN '85-89' ELSE '<85' END as confidence,
  CASE WHEN ABS(predicted_points - line_value) >= 5 THEN '5+' WHEN ABS(predicted_points - line_value) >= 3 THEN '3-5' ELSE '<3' END as edge,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date BETWEEN '2026-01-01' AND '2026-01-31'
  AND line_value IS NOT NULL
GROUP BY 1, 2
HAVING bets >= 20
ORDER BY 1, 2
```

### Vegas Sharpness Check

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(absolute_error), 2) as model_mae,
  ROUND(100.0 * COUNTIF(absolute_error < ABS(line_value - actual_points)) / COUNT(*), 1) as model_beats_vegas_pct
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2025-10-01'
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1
```

### Drift Detection

```bash
PYTHONPATH=. python bin/monitoring/model_drift_detection.py
```

---

## Commands Quick Reference

```bash
# Run drift detection
PYTHONPATH=. python bin/monitoring/model_drift_detection.py

# Run Vegas sharpness monitor
PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py

# Train new model on recent data
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 --train-end 2026-01-31 \
    --experiment-id FEB_2026

# Evaluate model
PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path "ml/experiments/results/catboost_v9_exp_*.cbm" \
    --eval-start 2026-01-01 --eval-end 2026-01-31 \
    --experiment-id TEST

# Train stacked ensemble with recency
PYTHONPATH=. python ml/experiments/train_stacked_ensemble_recency.py \
    --train-start 2021-11-01 --train-end 2024-06-30 \
    --experiment-id TEST --use-recency-weights --half-life 60
```

---

## Summary Table

| Question | Answer |
|----------|--------|
| Does V8 use ensemble? | No, only CatBoost in production |
| Does recency help ensemble? | No, train on recent data only instead |
| What's the best filter? | 90+ confidence, 3+ edge → 77% hit rate |
| Why did January degrade? | Medium-confidence picks crashed, Vegas got sharper |
| Is the high-conf signal still good? | Yes, 77-79% in January |
| What should we deploy? | JAN_DEC model (54.7% overall) |
| Should we use tier-based routing? | No, Session 54 disproved it |

---

*Session 55 Complete*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
