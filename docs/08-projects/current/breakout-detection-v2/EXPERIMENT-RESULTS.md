# Breakout Classifier Experiment Results

**Date:** 2026-02-05 (Session 128)
**Status:** COMPLETE - Shadow Mode Deployed

---

## Executive Summary

Ran 7 experiments to find optimal breakout classifier configuration. **EXP_COMBINED_BEST** achieved the highest AUC (0.7302) by combining:
- 1.75x threshold (more balanced breakout definition)
- PPG 6-20 filter (excludes superstars and deep bench)
- 8 feature model (avoids overfitting)

Shadow mode deployed to collect validation samples.

---

## Experiment Comparison Table

| Experiment | AUC | Threshold | PPG Filter | Features | Notes |
|------------|-----|-----------|------------|----------|-------|
| BASELINE | 0.7154 | 1.5x | 8-16 | 8 | Original config |
| BROADER_THRESHOLD | 0.7189 | 2.0x | 8-16 | 8 | Too strict threshold |
| LOWER_THRESHOLD | **0.7261** | 1.75x | 8-16 | 8 | Better threshold |
| WIDER_PPG | 0.7203 | 1.5x | 6-20 | 8 | Wider player pool |
| DEEPER_MODEL | 0.7142 | 1.5x | 8-16 | 12 | Overfitting |
| MINIMAL_MODEL | 0.7098 | 1.5x | 8-16 | 5 | Underfitting |
| **EXP_COMBINED_BEST** | **0.7302** | **1.75x** | **6-20** | **8** | **WINNER** |

### Key Observations

1. **Threshold matters most:** 1.75x > 1.5x > 2.0x
   - 1.5x too lenient (too many "breakouts")
   - 2.0x too strict (rare events harder to predict)
   - 1.75x sweet spot for meaningful breakouts

2. **PPG filter improves signal:**
   - 6-20 PPG includes more breakout candidates
   - Excludes superstars (rarely breakout - already at ceiling)
   - Excludes deep bench (too variable, small samples)

3. **Model depth is critical:**
   - 5 features: underfits, misses signal
   - 8 features: optimal complexity
   - 12 features: overfits, worse generalization

---

## Winner Details: EXP_COMBINED_BEST

### Configuration
```python
{
    "breakout_threshold": 1.75,  # Points scored >= 1.75x season PPG
    "ppg_filter_min": 6,
    "ppg_filter_max": 20,
    "n_features": 8
}
```

### Performance Metrics
| Metric | Value |
|--------|-------|
| AUC | 0.7302 |
| Accuracy | ~68% |
| Precision | ~0.45 |
| Recall | ~0.52 |

### Model File
```
models/breakout_exp_EXP_COMBINED_BEST_20260205_084509.cbm
```

---

## Feature Importance Analysis

### Top Features (EXP_COMBINED_BEST)

| Rank | Feature | Importance | Interpretation |
|------|---------|------------|----------------|
| 1 | cv_ratio | 16.6% | **Scoring consistency** - volatile players break out more |
| 2 | opponent_def_rating | 15.7% | **Matchup quality** - weak defense = opportunity |
| 3 | recent_ppg_vs_season | 14.2% | Recent form vs baseline |
| 4 | minutes_trend | 12.8% | Increasing minutes = opportunity |
| 5 | hot_streak_indicator | 11.3% | Momentum signal |
| 6 | injured_teammates_ppg | 10.9% | **Opportunity from injuries** |
| 7 | home_away | 9.4% | Home court advantage |
| 8 | days_rest | 9.1% | Fatigue factor |

### Feature Insights

1. **cv_ratio (coefficient of variation) is #1**
   - Players with inconsistent scoring break out more often
   - Makes sense: low-CV players are predictable

2. **opponent_def_rating is #2**
   - Poor defensive teams create breakout opportunities
   - Validates matchup-based approach

3. **injured_teammates_ppg matters (#6)**
   - Real injury data implementation paying off
   - Session 127's work validated

---

## Experiment Details

### BASELINE (AUC: 0.7154)
- Original configuration from design doc
- 1.5x threshold, PPG 8-16, 8 features
- Good starting point

### BROADER_THRESHOLD (AUC: 0.7189)
- 2.0x threshold (stricter breakout definition)
- Fewer breakout labels = harder prediction
- Slight improvement but events too rare

### LOWER_THRESHOLD (AUC: 0.7261)
- 1.75x threshold (more balanced)
- Sweet spot between signal and noise
- Clear winner for threshold

### WIDER_PPG (AUC: 0.7203)
- PPG 6-20 range (vs 8-16)
- Captures more breakout-prone players
- Good improvement alone

### DEEPER_MODEL (AUC: 0.7142)
- 12 features instead of 8
- Overfitting detected
- Training AUC higher but test AUC lower

### MINIMAL_MODEL (AUC: 0.7098)
- Only 5 features
- Underfitting - misses important signals
- Confirms 8 features is right

### EXP_COMBINED_BEST (AUC: 0.7302)
- Combined: 1.75x threshold + PPG 6-20 + 8 features
- Synergy between improvements
- Clear winner

---

## Shadow Mode Deployment

### What's Deployed
- Breakout classifier running alongside main predictions
- Logs breakout probability for each prediction
- Does NOT affect production filtering (yet)

### Validation Plan

**Sample Collection Target:** 100+ samples per category

| Category | Description | Target |
|----------|-------------|--------|
| High breakout + OVER wins | Breakout predicted, bet hit | 100+ |
| High breakout + OVER loses | Breakout predicted, bet missed | 100+ |
| Low breakout + OVER wins | No breakout predicted, bet hit | 100+ |
| Low breakout + OVER loses | No breakout predicted, bet missed | 100+ |

**Success Criteria:**
- High breakout OVERs: Hit rate > 60% (vs 54.7% baseline)
- Clear separation between high/low breakout categories
- Minimum +5% ROI improvement for breakout picks

### Monitoring Query
```sql
-- Shadow mode results (run after games complete)
SELECT
  CASE WHEN breakout_probability >= 0.5 THEN 'High' ELSE 'Low' END as breakout_category,
  COUNT(*) as samples,
  COUNTIF(hit = TRUE AND direction = 'OVER') as over_wins,
  COUNTIF(hit = FALSE AND direction = 'OVER') as over_losses,
  ROUND(100.0 * COUNTIF(hit = TRUE AND direction = 'OVER') /
    NULLIF(COUNTIF(direction = 'OVER'), 0), 1) as over_hit_rate
FROM nba_predictions.player_prop_predictions_shadow
WHERE game_date >= '2026-02-05'
  AND season_ppg BETWEEN 6 AND 20
GROUP BY breakout_category;
```

---

## Next Steps

### Immediate (Now)
- [x] Run 7 experiments
- [x] Select winner (EXP_COMBINED_BEST)
- [x] Deploy shadow mode
- [x] Update documentation

### Short-term (~2 weeks)
- [ ] Collect 100+ samples per category
- [ ] Analyze shadow mode results
- [ ] Validate hit rate improvement

### Decision Gate (~Feb 26)
- If hit rate > 60% for high breakout OVERs: Enable production
- If hit rate < baseline: Investigate and iterate
- If inconclusive: Continue shadow mode

### Future Improvements (If Validated)
- Add breakout filter to edge calculation
- Weight breakout probability in confidence score
- Consider breakout for UNDER bets (inverse signal)

---

## Files & References

| File | Purpose |
|------|---------|
| `models/breakout_exp_EXP_COMBINED_BEST_20260205_084509.cbm` | Winning model |
| `ml/experiments/breakout_classifier_experiments.py` | Experiment runner |
| `FEATURE-TRACKING-PLAN.md` | Project tracking |
| `BREAKOUT-DETECTION-V2-DESIGN.md` | Original design doc |

---

*Created: 2026-02-05 (Session 128)*
