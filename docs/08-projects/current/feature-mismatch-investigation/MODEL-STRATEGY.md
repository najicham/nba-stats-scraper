# Model Strategy & Feature Architecture

**Date:** 2026-02-03
**Session:** 103

## Current State

### Feature Store vs Model Training

| Component | Feature Count | Notes |
|-----------|---------------|-------|
| Feature Store | 37 features | Full set available |
| V8 Model | 33 features | Production (historical) |
| V9 Model | 33 features | Production (current season) |
| Training Script | 33 features | Uses `row[:33]` to extract |

**The 4 unused features (indices 33-36):**
- `dnp_rate` - Player DNP pattern detection
- `pts_slope_10g` - Points trajectory slope
- `pts_vs_season_zscore` - How current performance differs from season
- `breakout_flag` - Indicator for breakout performance

These trajectory features were added to the store but not incorporated into model training.

## Do We Need to Backfill?

### For Tier Metadata (scoring_tier, tier_adjustment)
**No backfill needed.** These are computed at prediction time from `points_avg_season` which already exists. New predictions automatically get these fields.

### For Adding scoring_tier as Training Feature
**Would need:**
1. Add `scoring_tier` as feature #34 in feature store (or use existing unused slot)
2. Backfill historical records with the tier classification
3. Retrain model with 34 features
4. Update prediction systems to pass 34 features

### For Using Existing Trajectory Features (33-36)
**No backfill needed.** Data already exists in feature store since 2025-11-13.
Just need to update training script to use `row[:37]` instead of `row[:33]`.

## Does /spot-check-features Do Deep Validation?

**Current:** Checks aggregate quality metrics
- Quality score distribution
- Vegas line coverage (overall and by tier)
- Data source distribution
- Missing feature detection

**Not Currently Checking:**
- Per-player validation (is player X's data consistent?)
- Feature value sanity (are values in expected ranges?)
- Feature correlation (are features providing unique signal?)
- Temporal consistency (do features vary naturally over time?)

### Recommended Deep Validation Additions

```sql
-- Check for suspicious feature patterns per player
SELECT
  player_lookup,
  COUNT(*) as games,
  -- Suspicious: all same values (no variation)
  STDDEV(features[OFFSET(0)]) as pts_l5_stddev,
  STDDEV(features[OFFSET(2)]) as pts_season_stddev,
  -- Suspicious: extreme values
  MAX(features[OFFSET(0)]) as max_pts_l5,
  MIN(features[OFFSET(0)]) as min_pts_l5
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
GROUP BY player_lookup
HAVING COUNT(*) >= 10
  AND (STDDEV(features[OFFSET(0)]) = 0  -- No variation = suspect
    OR MAX(features[OFFSET(0)]) > 50     -- Extreme high
    OR MIN(features[OFFSET(0)]) < 0)     -- Impossible negative
```

## Do We Need More Features?

**The question isn't "more features" but "better signal."**

### Current Issue
The model has good feature coverage but still exhibits regression-to-mean bias because:
1. **Vegas lines themselves are biased** - sportsbooks set conservative lines
2. **Model follows Vegas too closely** - doesn't learn to diverge appropriately
3. **Missing tier context** - model treats a 25-point star and 25-point breakout player the same

### Feature Categories

| Category | Current Features | Signal Quality |
|----------|-----------------|----------------|
| Scoring History | points_avg_l5/l10/season, std | Good |
| Vegas/Lines | vegas_line, opening, move, has_flag | Good but biased |
| Opponent | def_rating, pace, avg_vs_opponent | Medium |
| Context | home/away, b2b, rest | Good |
| Team | pace, off_rating, win_pct | Medium |
| Efficiency | ppm, minutes_avg | Good |
| Shot Profile | pct_paint/mid/3pt/ft | Low signal |
| **Trajectory (Unused)** | slope, zscore, breakout | **Untested** |

### Recommended Feature Strategy

**Don't add random features. Improve signal in key areas:**

1. **Add scoring_tier as categorical feature**
   - Helps model understand player role
   - Reduces regression-to-mean
   - Simple to implement (use existing unused slot)

2. **Test trajectory features (already in store)**
   - `pts_slope_10g` - Are they trending up/down?
   - `pts_vs_season_zscore` - How different from their norm?
   - `breakout_flag` - Is this a breakout game?

3. **Consider removing low-signal features**
   - Shot profile features (pct_paint, etc.) may not help
   - Feature importance analysis needed

4. **Improve Vegas line handling**
   - Train on residuals (actual - vegas) instead of raw actual
   - Add feature for "vegas line vs season avg" divergence

## Strategy for Helping the Model

### Short-term (Implemented)
- Store `scoring_tier` and `tier_adjustment` as prediction metadata
- Apply calibration at query time
- Filter suspicious picks (star UNDER, low edge)

### Medium-term (Next Steps)
1. **Test trajectory features in training:**
   ```python
   # In quick_retrain.py, change:
   X = pd.DataFrame([row[:33] for row in df['features'].tolist()], columns=FEATURES)
   # To:
   X = pd.DataFrame([row[:37] for row in df['features'].tolist()], columns=FEATURES_37)
   ```

2. **Add scoring_tier as feature:**
   ```python
   # Add to feature array:
   tier_numeric = {'star': 4, 'starter': 3, 'role': 2, 'bench': 1}
   features.append(tier_numeric[scoring_tier])
   ```

3. **Run experiment with tier feature:**
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V10_WITH_TIER" \
       --hypothesis "Add scoring_tier to reduce bias"
   ```

### Long-term (Investigation Needed)
1. **Train on residuals:**
   - Target = actual_points - vegas_line
   - Model learns "divergence from market"
   - More directly addresses the bias problem

2. **Quantile regression:**
   - Predict median instead of mean
   - Naturally reduces mean-seeking behavior

3. **Tier-specific models:**
   - Separate models for stars vs bench
   - Each model optimized for its tier

## Validation Before Training

**Always run `/spot-check-features` before `/model-experiment`**

Check for:
1. Quality score >= 70 for training data
2. No data source anomalies
3. Tier coverage balance (expect low bench coverage)
4. Vegas bias matches expectations (~8 pts for stars)

## Files to Modify

| To Do | File | Change |
|-------|------|--------|
| Use 37 features | `ml/experiments/quick_retrain.py` | Change `row[:33]` to `row[:37]` |
| Add tier feature | `data_processors/precompute/ml_feature_store/` | Add scoring_tier calculation |
| Update prediction | `predictions/worker/prediction_systems/catboost_v9.py` | Update feature count |

## Summary

1. **We're NOT adding to ML features yet** - just metadata fields
2. **No backfill needed** for current changes
3. **Deep validation skill** could be enhanced (per-player checks)
4. **V8/V9 both use 33 features** - 4 trajectory features available but unused
5. **More features ≠ better** - need targeted improvements to signal quality
