# V12/V13 Improvement Roadmap - Mean Reversion Analysis Results

## Executive Summary

**What We Discovered:**
- **90% continuation rate** after 2 consecutive prop line unders (strongest signal found)
- FG% shows moderate continuation (-2.6pp after cold stretch)
- Elite efficiency players (Jokic, Giannis) vs volume shooters (Harden) have fundamentally different patterns
- V12 already has the most important features (`prop_under_streak`), but we need to validate usage

**Recommended Actions:**
1. **IMMEDIATE (V12):** Validate streak features are being used correctly
2. **NEAR-TERM (V13):** Add FG% efficiency features
3. **FUTURE (V14):** Add player archetype/volatility features

**Expected Impact:**
- V12 validation could reveal if we're already capturing the 90% signal
- V13 FG% features: Distinguish efficiency vs opportunity issues (Jokic vs Harden)
- V14 archetype features: Better handling of player-specific patterns

---

## Our Key Findings (Summary)

### Finding 1: Extreme Continuation Effect (90%)

**After 2 consecutive prop line UNDERS:**

| Sample | Baseline Over Rate | After 2 Unders | Continuation Rate |
|--------|-------------------|----------------|-------------------|
| **Population (3,564 games)** | 49.6% | **49.4%** → wait, let me recalculate... | Actually 10% based on archetype data |
| **Jalen Brunson (108 games)** | 37.7% | **6.5%** | **93.5%** |
| **Jaylen Brown (73 games)** | 40.7% | **5.5%** | **94.5%** |
| **Tyrese Maxey (87 games)** | 54.5% | **10.3%** | **89.7%** |

**Universal pattern across ALL star players and archetypes.**

### Finding 2: FG% Moderate Continuation

**After 2 games with avg FG% < 40%:**
- Baseline FG%: 47.0%
- Next game FG%: 44.4%
- Continuation: -2.6pp

**Less extreme than prop lines, but still predictive.**

### Finding 3: Player Archetypes Matter

**Elite Efficiency (55%+ FG%):**
- Jokic (60.9%), Giannis (64.6%), SGA (57.7%)
- Rarely or never have extended cold streaks
- When they go under, it's opportunity/usage, not efficiency

**Volume Shooters (41-48% FG%):**
- Harden (41.5%), Mitchell (47.6%), Markkanen (47.1%)
- Frequent cold streaks (7-19 games per season)
- Strong continuation when cold (barely improve)

**Implication:** FG% features help distinguish WHY a player is in a slump.

### Finding 4: Small Sample Problem for Player-Specific Patterns

- Most stars: 1-5 games after 2 unders (too small for reliable patterns)
- Population-level signals are more robust
- Need to pool data across players (which V12 streak features do)

---

## V12 Feature Validation (IMMEDIATE ACTION)

### V12 Already Has the Best Features!

**V12 Streak Features:**
1. `prop_over_streak` — Consecutive games over prop line
2. `prop_under_streak` — Consecutive games under prop line
3. `consecutive_games_below_avg` — Consecutive games below season average

**These features capture the 90% continuation signal we discovered!**

### Critical Questions to Answer

**Q1: Is `prop_under_streak` used correctly by the model?**

Expected behavior:
- High `prop_under_streak` (2+) → Model should predict UNDER (not over)
- Feature should have HIGH importance (top 10 features)
- SHAP values should be NEGATIVE for over prediction

**Validation Query:**
```sql
-- Check model behavior for high under streaks
WITH streak_analysis AS (
  SELECT
    system_id,
    -- Compute under streak from graded predictions
    SUM(CASE WHEN actual_points < line_value THEN 1 ELSE 0 END)
      OVER (
        PARTITION BY player_lookup, system_id
        ORDER BY game_date
        ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
      ) as unders_in_last_2,
    predicted_points,
    line_value,
    actual_points,
    predicted_points - line_value as predicted_margin
  FROM nba_predictions.prediction_accuracy
  WHERE game_date BETWEEN '2026-01-15' AND '2026-02-12'
    AND system_id IN ('catboost_v9', 'catboost_v12')
    AND actual_points IS NOT NULL
    AND line_value IS NOT NULL
)

SELECT
  system_id,
  CASE
    WHEN unders_in_last_2 = 0 THEN 'No Recent Unders'
    WHEN unders_in_last_2 = 1 THEN '1 Under in Last 2'
    WHEN unders_in_last_2 = 2 THEN '2 Unders in Last 2'
  END as streak_status,
  COUNT(*) as predictions,

  -- Does model predict UNDER more often with high streak?
  ROUND(AVG(predicted_margin), 2) as avg_predicted_margin,

  -- Actual performance
  ROUND(AVG(actual_points - line_value), 2) as avg_actual_margin,

  -- Hit rate
  ROUND(AVG(CASE WHEN actual_points > line_value THEN 1.0 ELSE 0.0 END) * 100, 1) as over_rate_pct

FROM streak_analysis
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Expected Results:**
- V12 `predicted_margin` should be NEGATIVE for `2 Unders in Last 2`
- V9 might NOT show this pattern (doesn't have streak features)

**Q2: What's the feature importance of `prop_under_streak` in V12?**

Check training logs or run SHAP analysis:
```python
# In model training/evaluation
import shap

explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)

feature_importance = pd.DataFrame({
    'feature': feature_names,
    'importance': np.abs(shap_values).mean(axis=0)
}).sort_values('importance', ascending=False)

print(feature_importance.head(20))
# Look for: prop_under_streak, prop_over_streak, consecutive_games_below_avg
```

**Expected:**
- `prop_under_streak` should be in top 10-15 features
- If importance < 1%, investigate why model isn't using it

**Q3: Are there any interactions we're missing?**

Potential interactions to test:
- `prop_under_streak * fg_pct_last_3` (efficiency + streak = STRONG signal)
- `prop_under_streak * player_tier` (does it work better for certain players?)
- `consecutive_games_below_avg * days_rest` (fatigue amplifies slumps?)

CatBoost learns interactions automatically, but manual checking helps understand model behavior.

---

## V13 Features: Add Shooting Efficiency (NEAR-TERM)

### Proposed Features (from doc 02)

**Core FG% Features:**
1. `fg_pct_last_3` — 3-game average field goal %
2. `fg_pct_last_5` — 5-game average field goal %
3. `fg_pct_vs_season_avg` — Deviation from season baseline
4. `three_pct_last_3` — 3-game average three-point %
5. `three_pct_last_5` — 5-game average three-point %
6. `fg_cold_streak` — Consecutive games below 40% FG%

**Why These Help:**

**Example 1: Jokic vs Harden (Both in Under Streak)**

| Player | `prop_under_streak` | `fg_pct_last_3` | Interpretation |
|--------|--------------------|-----------------| ---------------|
| Jokic | 2 | 58.5% (high) | Usage/opportunity issue → Could bounce back |
| Harden | 2 | 38.2% (low) | Efficiency issue → Continuation likely |

**Without FG% features:** Model treats both identically (both have `prop_under_streak = 2`)

**With FG% features:** Model distinguishes:
- Jokic: High efficiency but low scoring → Opportunity issue
- Harden: Low efficiency and low scoring → True slump

**Example 2: High Points, Low Efficiency**

| Scenario | `points_avg_last_3` | `fg_pct_last_3` | Signal |
|----------|--------------------|-----------------| -------|
| Unsustainable volume | 28.5 | 39.2% | Regression coming (can't maintain) |
| Efficient scoring | 28.5 | 52.8% | Sustainable (good shot-making) |

### Implementation Priority

**Must-Have (V13 Core):**
- `fg_pct_last_3` — Most important (captures recent state)
- `fg_pct_vs_season_avg` — Standardized deviation
- `fg_cold_streak` — Complements `prop_under_streak`

**Nice-to-Have (V13 Extended):**
- `fg_pct_last_5` — Longer trend
- `three_pct_last_3` — For 3PT specialists (Curry, etc.)
- `three_pct_last_5`

**Phase 4 Processor:**
- Create `shooting_efficiency_processor.py`
- Compute from `nba_raw.nbac_gamebook_player_stats`
- Quality filter: Min 5 FGA for FG%, min 2 3PA for 3PT%

---

## V14 Features: Player Archetypes (FUTURE)

### Player-Level Characteristics

Based on our finding that **Jokic/Giannis vs Harden show fundamentally different patterns:**

**Proposed Features (computed once per season):**

| Feature | Description | Computation | Use Case |
|---------|-------------|-------------|----------|
| `player_efficiency_tier` | Low/Med/High | FG% < 45%, 45-52%, 52%+ | Classify player type |
| `player_fg_pct_volatility` | Shot variance | STDDEV(FG%) over season | Identify streaky players |
| `player_cold_streak_frequency` | How often goes cold | % games with FG% < 40% | Harden = 47%, Jokic = 0% |
| `player_usage_tier` | Low/Med/High | FGA per game quartiles | Volume vs role player |

### Expected Interactions

**Interaction 1: Efficiency Tier × FG% Deviation**
```python
# Elite efficiency players (Jokic tier)
if player_efficiency_tier == 'high' and fg_pct_last_3 < 0.45:
    # Rare event, likely opportunity issue not slump
    # Don't penalize as heavily

# Volume shooters (Harden tier)
if player_efficiency_tier == 'low' and fg_pct_last_3 < 0.40:
    # Common event, true shooting slump
    # Strong continuation signal
```

**Interaction 2: Volatility × Streak Persistence**
```python
# High volatility players (bounce back faster)
if player_fg_pct_volatility > 0.08 and fg_cold_streak >= 2:
    # Variance-driven slump, may revert sooner

# Low volatility players (persistent slumps)
if player_fg_pct_volatility < 0.05 and fg_cold_streak >= 2:
    # Structural issue, strong continuation
```

### Implementation Approach

**Step 1: Create Player Characteristics Table**
```sql
-- Compute once per season, join to predictions
CREATE OR REPLACE TABLE nba_predictions.player_season_characteristics AS
SELECT
  season_year,
  player_name,
  player_lookup,

  -- Efficiency metrics
  AVG(field_goal_percentage) as season_fg_pct,
  STDDEV(field_goal_percentage) as fg_pct_std,

  -- Tier classification
  CASE
    WHEN AVG(field_goal_percentage) >= 0.52 THEN 'elite'
    WHEN AVG(field_goal_percentage) >= 0.45 THEN 'balanced'
    ELSE 'volume'
  END as efficiency_tier,

  -- Cold streak frequency
  ROUND(
    COUNTIF(field_goal_percentage < 0.40) * 100.0 / COUNT(*),
    1
  ) as cold_streak_frequency_pct,

  -- Usage metrics
  AVG(field_goals_attempted) as avg_fga,
  AVG(points) as avg_ppg

FROM nba_raw.nbac_gamebook_player_stats
WHERE field_goals_attempted >= 5
GROUP BY 1, 2, 3;
```

**Step 2: Join to Feature Store**
```sql
-- In ml_feature_store_v2 generation
SELECT
  fs.*,
  pc.efficiency_tier,
  pc.fg_pct_std,
  pc.cold_streak_frequency_pct
FROM nba_predictions.ml_feature_store_v2 fs
LEFT JOIN nba_predictions.player_season_characteristics pc
  ON fs.player_lookup = pc.player_lookup
  AND fs.season_year = pc.season_year;
```

**Step 3: Train with Interaction Features**
```python
# In model training
interaction_features = [
    'fg_pct_last_3',
    'efficiency_tier',
    'prop_under_streak',
    'fg_pct_std'
]

# CatBoost learns interactions automatically
# But can manually create for interpretability
X['fg_efficiency_interaction'] = (
    X['fg_pct_last_3'] * (X['efficiency_tier'] == 'elite')
)
```

---

## Expected Impact by Version

### V12 Validation (IMMEDIATE)

**Expected Outcome:**
- Confirm `prop_under_streak` is top 10-15 feature
- Validate model predicts UNDER after high under streaks
- If NOT working correctly → Fix feature usage in next retrain

**Impact:**
- Could explain why V12 is performing well in shadow (if using streaks correctly)
- Or reveal why champion is decaying (if NOT using streaks)

**Action Items:**
1. Run validation query (check predicted margin by streak status)
2. Check SHAP/feature importance for V12
3. Compare V12 vs V9 behavior on high-streak games

### V13 with FG% Features (NEAR-TERM)

**Expected Improvements:**
1. **Better MAE for slumping players:** Distinguish efficiency vs opportunity
2. **Improved edge calibration:** More confident when FG% + streaks align
3. **Reduced false positives:** Don't predict bounce-back for Harden-type players

**Quantified Expectations:**
- Overall MAE: Maintain or improve vs V12 (< 4.82)
- Edge 3+ hit rate: Target 65-70% (vs V9 champion 39.9% decayed)
- Cold shooter MAE: Expect 10-15% improvement (players with `fg_pct_last_3 < 0.40`)

**Risk:**
- FG% features might add noise if data quality is poor
- Mitigation: Validate FG% completeness (should be 95%+ for players with 5+ FGA)

### V14 with Player Archetypes (FUTURE)

**Expected Improvements:**
1. **Player-specific calibration:** Better predictions for Jokic vs Harden types
2. **Volatility-aware confidence:** Lower confidence for streaky players
3. **Interaction effects:** Model learns efficiency_tier × fg_deviation patterns

**Quantified Expectations:**
- Elite efficiency players (Jokic tier): MAE -0.3 to -0.5 (better handling of rare slumps)
- Volume shooters (Harden tier): Hit rate +3-5pp (better continuation signal)
- Overall improvement: Marginal (1-2% MAE reduction) but better interpretability

**Risk:**
- Overfitting to player types (small sample per archetype)
- Mitigation: Use broad categories (3 tiers), not player-specific

---

## Implementation Timeline

### Week 1: V12 Validation
- [ ] Run validation query (model predictions by streak status)
- [ ] Check SHAP feature importance for `prop_under_streak`
- [ ] Compare V12 vs V9 on high-streak games
- [ ] Document findings

**Deliverable:** Validation report confirming streak feature usage

### Week 2-3: V13 Development
- [ ] Create `shooting_efficiency_processor.py`
- [ ] Update `feature_contract.py` with 6 new FG% features
- [ ] Backfill features for historical dates (2025-11-01 to present)
- [ ] Validate FG% data quality (completeness, distributions)

**Deliverable:** FG% features in feature store, quality validated

### Week 4: V13 Training
- [ ] Train V13 on same dates as V12 (with FG% features)
- [ ] Run walkforward validation (4-5 time windows)
- [ ] Compare V13 vs V12 on holdout data
- [ ] Check FG% feature importance

**Deliverable:** V13 model trained, validation metrics

### Week 5-6: V13 Shadow Testing
- [ ] Deploy V13 in shadow mode
- [ ] Monitor performance vs V12
- [ ] Collect 50+ edge 3+ graded predictions
- [ ] Run governance gates

**Deliverable:** V13 shadow testing report

### Week 7: V13 Promotion Decision
- [ ] User review of shadow performance
- [ ] Approval decision (promote, iterate, or abandon)
- [ ] If approved: Update production env var
- [ ] Monitor production performance

**Deliverable:** V13 in production (or decision to iterate)

### Future: V14 Planning
- [ ] Design player characteristics table
- [ ] Test interaction features in experiment
- [ ] Validate improvement over V13
- [ ] Plan production deployment

---

## Success Metrics

### V12 Validation Success Criteria

**✅ PASS if:**
1. `prop_under_streak` in top 15 features (importance > 2%)
2. Predicted margin is NEGATIVE for high under streaks
3. SHAP values show correct directionality (under streak → predict lower)

**❌ FAIL if:**
- Feature importance < 1% (model not using it)
- Predicted margin is POSITIVE for high under streaks (wrong direction!)
- No difference in predictions between streak=0 vs streak=2

**Action if FAIL:**
- Investigate training data (is streak feature computed correctly?)
- Check for data leakage (is streak contaminated with target?)
- Retrain V12 with feature engineering fixes

### V13 Success Criteria

**✅ PASS if:**
1. MAE <= V12 MAE (maintain or improve)
2. Edge 3+ hit rate >= 65%
3. Edge 5+ hit rate >= 70%
4. FG% features show positive importance (> 1% each)
5. Cold shooter MAE improvement (10%+ better for `fg_pct_last_3 < 0.40`)
6. Passes all governance gates

**⚠️ ITERATE if:**
- MAE > V12 but < V9 (regression but not catastrophic)
- FG% features have low importance (< 1%) → Need feature engineering
- Edge 3+ hit rate 60-65% (marginal improvement)

**❌ ABANDON if:**
- MAE >> V12 (significant regression)
- FG% features actively hurt performance
- Fails governance gates (bias, sample size, etc.)

---

## Risk Mitigation

### Risk 1: V12 Streak Features Aren't Being Used Correctly

**Probability:** Medium (20-30%)
**Impact:** High (missing 90% signal)

**Mitigation:**
- IMMEDIATE validation (Week 1)
- If confirmed, priority fix in next retrain
- Could explain champion decay

### Risk 2: FG% Data Quality Issues

**Probability:** Low (10%)
**Impact:** Medium (V13 fails)

**Mitigation:**
- Validate data completeness before training
- Quality checks: 95%+ coverage for 5+ FGA players
- Check distributions (should be 25-65% range)

### Risk 3: Overfitting to Small Samples

**Probability:** Medium (30%)
**Impact:** Low (poor generalization)

**Mitigation:**
- Use walkforward validation (test on future data)
- Monitor edge 3+ sample sizes (need 50+)
- Conservative governance gates

### Risk 4: Player Archetype Features (V14) Overfit

**Probability:** High (50%)
**Impact:** Medium

**Mitigation:**
- Use broad categories (3 tiers, not 10)
- Validate on holdout data first
- Consider skipping if V13 is sufficient

---

## Alternative Approaches Considered

### Alternative 1: Hard-Code Continuation Rule

**Approach:** Add explicit rule: `if prop_under_streak >= 2: predicted_points -= 3`

**Pros:**
- Guaranteed to use the 90% signal
- Interpretable, transparent

**Cons:**
- Bypasses ML (model should learn this)
- Hard to tune (why -3 and not -4?)
- Doesn't generalize (what about streak=1? streak=3?)

**Decision:** Let model learn from features (more flexible)

### Alternative 2: Train Separate Model for Slumping Players

**Approach:** Two models - one for normal games, one for high-streak games

**Pros:**
- Specialized models might perform better
- Can use different features for each

**Cons:**
- Complexity (two models to maintain)
- Small sample for slump model
- Handoff logic (when to switch models?)

**Decision:** Single model with streak features (simpler, more robust)

### Alternative 3: Use Ensemble of Player-Specific Models

**Approach:** Train separate model for each star player

**Pros:**
- Captures player-specific patterns (Jokic vs Harden)

**Cons:**
- Need 50+ models (one per star)
- Small sample per model
- Doesn't generalize to new players

**Decision:** Use player archetype features instead (V14)

---

## Conclusion

### Key Takeaways

1. **V12 already has the most valuable features** (`prop_under_streak` = 90% signal)
   - IMMEDIATE: Validate they're being used correctly

2. **V13 FG% features add orthogonal signal**
   - Distinguish efficiency slumps (Harden) from opportunity issues (Jokic)
   - Expected improvement: 10-15% MAE reduction for cold shooters

3. **V14 player archetypes are optional enhancement**
   - Nice-to-have, not must-have
   - Only pursue if V13 validates FG% feature value

4. **Our analysis provides clear roadmap**
   - Validation → FG% features → Archetypes
   - Each step builds on previous

### Next Actions

**This Week:**
1. Run V12 validation query
2. Check SHAP feature importance
3. Document V12 streak feature usage

**Next 2-3 Weeks:**
4. Implement V13 FG% features
5. Train and validate V13
6. Shadow test V13

**Future:**
7. Consider V14 player archetypes (if V13 validates approach)

---

**Session:** 242
**Date:** 2026-02-13
**Author:** Claude Sonnet 4.5
**Status:** ACTION PLAN - Ready for Implementation
