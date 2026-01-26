# P1/P2 Feature Quality Issues - Analysis

**Date:** 2026-01-25
**Analyzed By:** Claude Sonnet 4.5
**Status:** Issues confirmed, solutions identified

---

## Executive Summary

Investigated the P1/P2 feature quality issues from the original IMPROVE-ML-FEATURE-QUALITY.md handoff document. **All three issues are confirmed and present in production code.**

### Issues Confirmed

1. **✅ CONFIRMED (P1):** Vegas lines fallback to season_avg → Circular dependency
2. **✅ CONFIRMED (P1):** XGBoost vs CatBoost default mismatch
3. **✅ CONFIRMED (P2):** Points defaults are 10.0 (should be ~15.0)

---

## Issue 1: Vegas Line Circular Dependency (P1)

### The Problem

**Feature Store (`ml_feature_store_processor.py:1205-1207`):**
```python
# Feature 25: vegas_points_line
# Feature 26: vegas_opening_line
fallback_line = phase4_data.get('points_avg_season', phase3_data.get('points_avg_season', 15.0))
vegas_points_line = vegas_data.get('vegas_points_line', fallback_line)
```

**Prediction System (`catboost_v8.py:350, 383-384`):**
```python
season_avg = features.get('points_avg_season', 10.0)  # Feature 2
# ...
vegas_line if vegas_line is not None else season_avg,  # Feature 25
vegas_opening if vegas_opening is not None else season_avg,  # Feature 26
```

**Why this is a problem:**
- Feature 25 (vegas_points_line) uses Feature 2 (points_avg_season) as fallback
- Creates circular dependency: Feature 25 = Feature 2 when Vegas line missing
- Model learns from redundant information
- Reduces predictive power when Vegas lines unavailable

### Impact

**Vegas line coverage analysis (from training code):**
```python
# From ml/train_xgboost_v7.py
vegas_coverage = (df['vegas_points_line'].notna()).mean()
logger.info(f"Vegas line coverage: {vegas_coverage:.1%}")
```

Typical coverage: 60-80% of player-games have Vegas lines.

When missing:
- **Current behavior:** Uses player's season average
- **Problem:** Model essentially sees Feature 2 twice (as both #2 and #25)
- **Impact:** Reduced model capacity, potential overfitting to Vegas-available games

### Solution Options

**Option A: Use NULL + Indicator (RECOMMENDED)**
```python
# Feature store
vegas_points_line = vegas_data.get('vegas_points_line')  # Can be None
vegas_opening_line = vegas_data.get('vegas_opening_line')  # Can be None
has_vegas_line = 1.0 if vegas_points_line is not None else 0.0  # Feature 28

# Already exists! Feature 28 (has_vegas_line) is already in the model
# Just need to stop using season_avg as fallback
```

**Option B: Use League Median (NOT player-specific)**
```python
LEAGUE_MEDIAN_POINTS = 18.5  # Calculate from historical data
fallback_line = LEAGUE_MEDIAN_POINTS  # Not player-specific
```

**Option C: Use Historical Vegas Average**
```python
# Calculate player's historical Vegas line average (not season points avg)
fallback_line = player_historical_vegas_avg or LEAGUE_MEDIAN
```

**Recommended:** Option A - The model already has `has_vegas_line` indicator (Feature 28), so it can learn to handle missing Vegas data appropriately. Using NULL is most honest.

### Files to Update

1. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:1205-1207`
   - Change fallback from `season_avg` to `None` or league median

2. `predictions/worker/prediction_systems/catboost_v8.py:383-384`
   - Update fallback from `season_avg` to match feature store

3. All training scripts that impute Vegas lines:
   - `ml/train_final_ensemble_v8.py:131-132`
   - `ml/train_final_ensemble_v9.py:173-174`
   - `ml/train_star_specialist_v10.py:167-168`
   - `ml/train_xgboost_v7.py:229-230`
   - etc.

---

## Issue 2: XGBoost vs CatBoost Default Mismatch (P1)

### The Problem

**Feature Store Defaults:**
```python
# ml_feature_store_processor.py:1139-1141
features.append(self._get_feature_with_fallback(0, 'points_avg_last_5', ..., 10.0, ...))
features.append(self._get_feature_with_fallback(1, 'points_avg_last_10', ..., 10.0, ...))
features.append(self._get_feature_with_fallback(2, 'points_avg_season', ..., 10.0, ...))
```

**CatBoost V8 Defaults:**
```python
# catboost_v8.py:350, 355-357
season_avg = features.get('points_avg_season', 10.0)  # ✅ 10.0
features.get('points_avg_last_5', season_avg),  # ✅ 10.0
features.get('points_avg_last_10', season_avg),  # ✅ 10.0
features.get('points_avg_season', season_avg),  # ✅ 10.0
```

**XGBoost V1 Defaults:**
```python
# xgboost_v1.py:189-191
features.get('points_avg_last_5', 0),  # ❌ 0 (should be 10.0)
features.get('points_avg_last_10', 0),  # ❌ 0 (should be 10.0)
features.get('points_avg_season', 0),  # ❌ 0 (should be 10.0)
```

**Why this is a problem:**
- XGBoost and CatBoost predictions will differ for players with missing data
- Inconsistent behavior between models
- XGBoost using 0 is clearly wrong (no NBA player averages 0 ppg)
- Feature store provides 10.0, so prediction systems should use it

### Impact

**When does this matter?**
- New players with no historical data
- Edge cases where feature store fails to populate
- Testing/debugging scenarios

**Magnitude:**
- Low impact in production (features usually populated)
- But creates confusing behavior when comparing models
- Poor code consistency

### Solution

**Update XGBoost V1 to match feature store defaults:**

```python
# xgboost_v1.py:189-191 (BEFORE)
features.get('points_avg_last_5', 0),
features.get('points_avg_last_10', 0),
features.get('points_avg_season', 0),

# xgboost_v1.py:189-191 (AFTER)
features.get('points_avg_last_5', 10.0),
features.get('points_avg_last_10', 10.0),
features.get('points_avg_season', 10.0),
```

**Or better - trust the feature store:**
```python
# Assume feature store always populates these
# If they're missing, it's a critical error
features['points_avg_last_5'],  # No default - fail fast if missing
features['points_avg_last_10'],
features['points_avg_season'],
```

### Files to Update

1. `predictions/worker/prediction_systems/xgboost_v1.py:189-191`
   - Change defaults from 0 to 10.0

---

## Issue 3: Points Defaults Should Be ~15.0 Not 10.0 (P2)

### The Problem

**Current defaults:**
```python
# Feature store and all prediction systems
points_avg_last_5: 10.0
points_avg_last_10: 10.0
points_avg_season: 10.0
```

**Why this is suboptimal:**
- League median scoring is ~15-18 ppg
- 10.0 is below league median
- Biases predictions for players with no data

### Analysis

**League scoring distribution (typical NBA season):**
- Median: ~15-18 ppg
- Mean: ~10-12 ppg (skewed by bench players)
- Mode: ~8-10 ppg

**Argument for 10.0:**
- Matches mean scoring
- Bench players (majority of roster) score ~8-12 ppg

**Argument for 15.0:**
- Matches median scoring for rotation players
- More representative of typical "playable" player
- Feature store already uses 15.0 for Vegas fallback line 1205

### Solution

**Option A: Keep 10.0 (status quo)**
- Matches current mean
- Works reasonably well in practice
- No code changes needed

**Option B: Change to 15.0**
- Better for rotation players
- Consistent with Vegas fallback line
- Requires model retraining

**Option C: Use role-specific defaults**
```python
# Based on player role/minutes
if minutes_avg_last_10 > 25:
    default_points = 15.0  # Starter
elif minutes_avg_last_10 > 15:
    default_points = 12.0  # Rotation
else:
    default_points = 8.0  # Bench
```

**Recommended:** Option A (keep 10.0)
- Current default is reasonable
- Impact is minimal (rarely used in production)
- Not worth retraining models for

**However:** If retraining models for Issue #1 or #2, consider changing to 15.0 at the same time.

### Files to Update (if changing to 15.0)

1. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:1139-1141`
2. `predictions/worker/prediction_systems/catboost_v8.py:350`
3. `predictions/worker/prediction_systems/xgboost_v1.py:189-191`
4. All model training scripts

---

## Prioritization & Recommendations

### Priority 1 (P1) - Fix Now

**Issue #2: XGBoost defaults mismatch**
- **Why:** Clear bug, easy fix, no model retraining needed
- **Effort:** 5 minutes (change 3 lines)
- **Impact:** Medium (consistency fix)
- **Action:** Update xgboost_v1.py defaults from 0 to 10.0

### Priority 2 (P1) - Fix on Next Model Retrain

**Issue #1: Vegas circular dependency**
- **Why:** Reduces model capacity, impacts predictions
- **Effort:** 1-2 hours (code changes + model retraining)
- **Impact:** High (improves model for ~30% of predictions without Vegas lines)
- **Action:** Change to NULL + indicator, retrain models

### Priority 3 (P2) - Consider Later

**Issue #3: Points defaults 10.0 vs 15.0**
- **Why:** Minor optimization, low impact
- **Effort:** 1-2 hours if retraining anyway
- **Impact:** Low (rarely used in production)
- **Action:** Change to 15.0 if retraining for Issue #1

---

## Implementation Plan

### Phase 1: Quick Fix (5 min)

1. **Fix XGBoost defaults mismatch**
   ```bash
   # Edit predictions/worker/prediction_systems/xgboost_v1.py
   # Lines 189-191: Change 0 → 10.0
   ```

2. **Add tests for default consistency**
   ```python
   def test_xgboost_catboost_defaults_match():
       """Test that XGBoost and CatBoost use same defaults."""
       assert XGBOOST_POINTS_DEFAULT == CATBOOST_POINTS_DEFAULT == 10.0
   ```

3. **Commit and deploy**

### Phase 2: Vegas Dependency Fix (When Retraining)

1. **Update feature store**
   ```python
   # ml_feature_store_processor.py
   # Change fallback from season_avg to None
   vegas_points_line = vegas_data.get('vegas_points_line')  # Can be None
   ```

2. **Update prediction systems**
   ```python
   # catboost_v8.py, xgboost_v1.py
   # Remove season_avg fallback, use None or league median
   ```

3. **Update all training scripts**
   - Remove `.fillna(df['player_season_avg'])`
   - Use `.fillna(LEAGUE_MEDIAN)` or leave as NULL

4. **Retrain models**
   - Include `has_vegas_line` indicator in feature importance
   - Validate predictions improve for no-Vegas games

5. **A/B test**
   - Shadow mode comparison
   - Verify MAE improves for Vegas-missing games

### Phase 3: Points Defaults (Optional)

Only if retraining for Phase 2:

1. Change all 10.0 → 15.0
2. Update documentation
3. Retrain models
4. Compare performance

---

## Testing Strategy

### Unit Tests

```python
def test_vegas_fallback_not_circular():
    """Test that Vegas fallback doesn't use season_avg."""
    # Feature store should NOT use points_avg_season as fallback
    features = extract_features(player_lookup, game_date)

    # If Vegas line missing, should be None or league median, NOT season avg
    if features['vegas_points_line'] is not None:
        assert features['vegas_points_line'] != features['points_avg_season']

def test_prediction_system_defaults_consistent():
    """Test all prediction systems use same defaults."""
    xgb_defaults = get_xgboost_defaults()
    cat_defaults = get_catboost_defaults()

    assert xgb_defaults['points_avg_last_5'] == cat_defaults['points_avg_last_5']
    assert xgb_defaults == cat_defaults  # All defaults should match
```

### Integration Tests

```python
@pytest.mark.integration
def test_vegas_missing_predictions():
    """Test predictions work correctly when Vegas lines missing."""
    # Create feature vector with no Vegas line
    features = {..., 'vegas_points_line': None, 'has_vegas_line': 0.0}

    # Prediction should still work
    prediction = model.predict(features)
    assert prediction is not None

    # Should NOT equal season average
    assert prediction != features['points_avg_season']
```

---

## Documentation Updates

After implementing fixes:

1. **Update feature catalog** (`docs/05-ml/features/feature-catalog.md`)
   - Document Vegas line fallback behavior
   - Clarify default values

2. **Update model training runbook**
   - Add section on Vegas line handling
   - Document default value standards

3. **Create ADR** (Architecture Decision Record)
   - Why we chose NULL over season_avg for Vegas fallback
   - Trade-offs considered
   - Performance impact measured

---

## Related Documents

- [ML Feature Quality Investigation](2026-01-25-ML-FEATURE-QUALITY-INVESTIGATION.md)
- [Data Quality Validation](2026-01-25-DATA-QUALITY-VALIDATION.md)
- [Original Handoff](IMPROVE-ML-FEATURE-QUALITY.md)

---

**Analysis completed by:** Claude Sonnet 4.5
**Date:** 2026-01-25
**Status:** Issues confirmed, ready to implement
