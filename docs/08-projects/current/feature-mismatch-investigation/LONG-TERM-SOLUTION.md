# Long-Term Solution: Edge Filtering & Model Bias

**Created:** Session 102
**Status:** Proposal for Review

---

## Problems Identified

### Problem 1: Write-Time Edge Filtering
**Status:** ✅ FIXED in Session 102

Predictions with edge < 3 were filtered during MERGE, causing data loss during regeneration.

**Fix:** Removed write-time filtering. All predictions stored. Edge filtering at query time.

### Problem 2: Model Regression-to-Mean Bias
**Status:** ❌ NOT YET FIXED

CatBoost V9 shrinks predictions toward the mean (~13 pts), causing:
- Stars (25+ pts actual) under-predicted by 9 pts
- Bench (<5 pts actual) over-predicted by 6 pts
- "High edge" is actually model error, not genuine insight

| Tier | Model | Actual | Bias |
|------|-------|--------|------|
| Stars | 21.1 | 30.4 | **-9.3** |
| Starters | 15.9 | 18.7 | **-2.8** |
| Role | 11.0 | 9.5 | +1.5 |
| Bench | 7.8 | 2.2 | **+5.6** |

---

## Recommended Architecture

### Layer 1: Store ALL Predictions (✅ Done)
```
Worker → Staging Tables → MERGE (no filter) → player_prop_predictions
```
All predictions stored, regardless of edge.

### Layer 2: Mark Predictions as Actionable
Use `is_actionable` field to mark which predictions to bet on:

```python
# In format_prediction_for_bigquery()
is_actionable = True
filter_reason = None

# Existing: Confidence tier filter (88-90% has low hit rate)
if 0.88 <= confidence <= 0.90:
    is_actionable = False
    filter_reason = 'confidence_tier_88_90'

# NEW: Low edge filter (edge < 3 has ~50% hit rate)
edge = abs(predicted_points - line_value)
if edge < 3.0:
    is_actionable = False
    filter_reason = 'low_edge'

# NEW: Model bias detector (star player UNDER with high edge)
if features.get('points_avg_season', 0) >= 25 and recommendation == 'UNDER' and edge >= 5:
    is_actionable = False
    filter_reason = 'star_under_bias_suspect'
```

### Layer 3: Fix the Model (Long-Term)

**Option B from investigation: Retrain with tier features**

Add features that help model understand player scoring tiers:
```python
NEW_FEATURES = [
    'player_tier',  # Categorical: star/starter/role/bench
    'season_avg_anchor',  # Season average (explicit)
    'scoring_percentile',  # Player's rank (0-100)
]
```

**Why this is better than recalibration:**
- Addresses root cause (model doesn't understand tiers)
- No post-hoc adjustments that could over-fit
- Model learns to use tier context itself

### Layer 4: Validation & Monitoring

Add to `/validate-daily` skill:

```sql
-- Check model bias by tier (should be <2 pts for all)
SELECT tier, avg_bias
FROM (
  SELECT
    CASE WHEN actual_points >= 25 THEN 'Stars'
         WHEN actual_points >= 15 THEN 'Starters'
         WHEN actual_points >= 5 THEN 'Role'
         ELSE 'Bench' END as tier,
    AVG(predicted_points - actual_points) as avg_bias
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1
)
WHERE ABS(avg_bias) > 3  -- Alert if any tier has >3 pt bias
```

---

## Implementation Plan

### Phase 1: Quick Wins (Today)
1. ✅ Remove write-time edge filter (done)
2. [ ] Add `filter_reason = 'low_edge'` for edge < 3
3. [ ] Add `filter_reason = 'star_under_bias_suspect'` for star UNDERs

### Phase 2: Model Fix (This Week)
1. [ ] Add tier features to feature engineering
2. [ ] Retrain V10 with tier features
3. [ ] A/B test V10 vs V9 for 3-5 days
4. [ ] Deploy V10 if bias reduced

### Phase 3: Monitoring (Ongoing)
1. [ ] Add bias check to `/validate-daily`
2. [ ] Alert if any tier has >3 pt bias
3. [ ] Monthly model retraining with bias validation

---

## Key Insight

**Edge is not a quality metric - it can indicate model error.**

For CatBoost V9:
- Low edge = model agrees with Vegas → more likely correct
- High edge on stars = model is biased → systematically wrong

Until model bias is fixed, high-edge star UNDERs should be filtered.

---

## Queries for Validation

### Check Model Bias
```sql
SELECT
  CASE WHEN actual_points >= 25 THEN 'Stars'
       WHEN actual_points >= 15 THEN 'Starters'
       WHEN actual_points >= 5 THEN 'Role'
       ELSE 'Bench' END as tier,
  COUNT(*) as n,
  ROUND(AVG(predicted_points - actual_points), 1) as avg_bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1
ORDER BY 1
```

### Check Betting by Filter Reason
```sql
SELECT
  COALESCE(filter_reason, 'actionable') as filter,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy a USING (player_lookup, game_date, system_id)
WHERE p.system_id = 'catboost_v9'
  AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1
ORDER BY 1
```
