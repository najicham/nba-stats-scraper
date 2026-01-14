# Best Bets Selection Strategy

**Created:** 2026-01-14
**Updated:** 2026-01-14 (Major findings added)
**Status:** Analysis Complete - Critical Findings Require Implementation

---

## Executive Summary

Analysis of 10,000+ graded picks reveals **massive performance variations** that should fundamentally change our best bets strategy:

### Critical Finding: UNDER Dramatically Outperforms OVER

| Recommendation | 90%+ Confidence | Hit Rate |
|----------------|-----------------|----------|
| **UNDER** | 7,709 picks | **95.4%** |
| OVER | 1,794 picks | **53.2%** |

**This is the single biggest edge in our system.**

### Optimal Strategy (Prioritized)

1. **UNDER only** at high confidence (95%+ hit rate vs 53% for OVER)
2. **5+ point edge** (92.9% hit rate vs 24% for <2 edge)
3. **Bench/rotation players** (89% hit rate vs 43% for stars)
4. **Mid-week games** (Thu-Fri 83-85% vs Mon 76%)
5. **Exclude 88-90% confidence tier** (already implemented)

**See Also:** [ANALYSIS-FRAMEWORK.md](../ml-model-v8-deployment/ANALYSIS-FRAMEWORK.md) for complete dimensional analysis.

---

## Performance Analysis by Tier

### Confidence × Edge Matrix (2025-26 Season)

| Confidence | Edge 4+ pts | Edge 2-4 pts | Edge <2 pts |
|------------|-------------|--------------|-------------|
| **92%+** | **92.8%** (209) | 72.5% (327) | 61.3% (238) |
| **90-92%** | **80.5%** (256) | 71.7% (145) | 62.8% (86) |
| 88-90% | ❌ 42.1% (133) | ❌ 54.2% (59) | ❌ 33.3% (27) |
| 80-88% | 73.6% (212) | 59.5% (126) | 48.5% (97) |
| <80% | 45.5% (11) | 38.9% (18) | 39.5% (38) |

*Numbers in parentheses = sample size*

### Key Findings

1. **High Edge is Crucial**
   - 92%+ conf + 4+ edge: **92.8%** hit rate
   - 92%+ conf + <2 edge: **61.3%** hit rate
   - **Δ = 31.5 percentage points!**

2. **88-90% Tier is Broken at ALL Edge Levels**
   - Even high edge (4+ pts) only hits 42.1%
   - Filter is correctly applied

3. **OVER vs UNDER (90%+ tier) - CRITICAL UPDATE**

   **Previous analysis was WRONG.** Updated with full season data:

   | Rec | Confidence | Picks | Wins | Hit Rate |
   |-----|------------|-------|------|----------|
   | **UNDER** | 92%+ | 5,358 | 5,089 | **95.0%** |
   | **UNDER** | 90-92% | 2,351 | 2,250 | **95.7%** |
   | OVER | 92%+ | 908 | 521 | 57.4% |
   | OVER | 90-92% | 886 | 433 | 48.9% |

   **Recommendation:** Best bets should be **UNDER only** at high confidence

---

## Current Best Bets System

### Location
`data_processors/publishing/best_bets_exporter.py`

### Current Formula
```python
composite_score = confidence_score
                × edge_factor      # min(1.5, 1.0 + edge/10)
                × player_accuracy  # historical hit rate
```

### Current Selection
- Top 15 picks by composite score
- Filters: OVER/UNDER only, has prop line

### Issues with Current Approach

| Issue | Impact |
|-------|--------|
| No minimum edge threshold | Includes <2 pt edge (61% hit rate) |
| No minimum confidence threshold | Includes 80%+ (vs optimal 90%+) |
| Player accuracy may not be available | Defaults to 0.85 |
| No edge tier weighting | 4+ edge dramatically better |

---

## Recommended Improvements

### Tier 1: Best Bets (Premium Picks)

**Criteria:**
```python
confidence >= 0.90 AND edge >= 4.0
```

**Expected Performance:**
- Hit rate: **85-93%**
- Volume: ~50-100 picks/month
- ROI: 60-80%+ at -110 juice

### Tier 2: Strong Bets (High Confidence)

**Criteria:**
```python
confidence >= 0.90 AND edge >= 2.0
```

**Expected Performance:**
- Hit rate: **72-80%**
- Volume: ~200-300 picks/month
- ROI: 30-50%

### Tier 3: Value Bets (Positive EV)

**Criteria:**
```python
confidence >= 0.80 AND edge >= 4.0
AND NOT (confidence >= 0.88 AND confidence < 0.90)
```

**Expected Performance:**
- Hit rate: **70-75%**
- Volume: ~100-150 picks/month
- ROI: 25-40%

### Tier 4: All Actionable (Current)

**Criteria:**
```python
confidence >= 0.70 AND is_actionable = true
```

**Expected Performance:**
- Hit rate: **65-72%**
- Volume: ~400-500 picks/month
- ROI: 15-30%

---

## Implementation Recommendations

### 1. Update Best Bets Exporter

```python
# Proposed changes to best_bets_exporter.py

# Add tier-based selection
BEST_BETS_TIERS = {
    'premium': {
        'min_confidence': 0.90,
        'min_edge': 4.0,
        'max_picks': 5
    },
    'strong': {
        'min_confidence': 0.90,
        'min_edge': 2.0,
        'max_picks': 10
    },
    'value': {
        'min_confidence': 0.80,
        'min_edge': 4.0,
        'max_picks': 10
    }
}

# New composite score that weights edge more heavily
def calculate_composite_score(confidence, edge, player_accuracy):
    # Edge is now more important
    edge_multiplier = 1.0 + (edge / 5.0)  # 4pt edge = 1.8x
    edge_multiplier = min(edge_multiplier, 2.5)  # cap at 2.5x

    return confidence * edge_multiplier * player_accuracy
```

### 2. Add Edge Filtering to Worker (Optional)

```python
# In worker.py, add low_edge filter
if abs(predicted_margin) < 2.0:
    is_actionable = False
    filter_reason = 'low_edge_under_2pts'
```

**Caution:** This would reduce volume significantly. Recommend starting with exporter-level filtering.

### 3. Website Display Tiers

```json
{
  "premium_picks": [
    {"player": "...", "confidence": 0.94, "edge": 5.2, "tier": "🔥 Premium"}
  ],
  "strong_picks": [
    {"player": "...", "confidence": 0.91, "edge": 3.1, "tier": "💪 Strong"}
  ],
  "value_picks": [
    {"player": "...", "confidence": 0.85, "edge": 4.5, "tier": "📈 Value"}
  ]
}
```

---

## Monitoring & Validation

### Daily Queries

```sql
-- Monitor tier performance
SELECT
  CASE
    WHEN confidence_score >= 0.90 AND ABS(predicted_margin) >= 4 THEN 'Premium'
    WHEN confidence_score >= 0.90 AND ABS(predicted_margin) >= 2 THEN 'Strong'
    WHEN confidence_score >= 0.80 AND ABS(predicted_margin) >= 4 THEN 'Value'
    ELSE 'Standard'
  END as tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY tier
ORDER BY tier
```

### Alert Thresholds

| Tier | Target Hit Rate | Alert if Below |
|------|-----------------|----------------|
| Premium | 85%+ | 75% |
| Strong | 72%+ | 65% |
| Value | 70%+ | 62% |
| Standard | 65%+ | 55% |

---

## Risk Considerations

### Volume vs Quality Tradeoff

| Strategy | Picks/Day | Hit Rate | Total Wins |
|----------|-----------|----------|------------|
| Premium only | ~2 | 90% | 1.8 |
| Premium + Strong | ~8 | 78% | 6.2 |
| All Tiers | ~20 | 70% | 14.0 |

**Recommendation:** Offer multiple tiers to users, let them choose risk tolerance.

### Bankroll Management

For -110 juice, breakeven is 52.4%. Recommended bet sizing by tier:

| Tier | Hit Rate | Kelly % | Recommended Unit |
|------|----------|---------|------------------|
| Premium | 90% | 38% | 3-5 units |
| Strong | 75% | 23% | 2-3 units |
| Value | 70% | 18% | 1-2 units |
| Standard | 65% | 13% | 1 unit |

---

## Next Steps

1. **Phase 1:** Update best_bets_exporter with tier-based selection
2. **Phase 2:** Add tier labels to website output
3. **Phase 3:** Add historical performance tracking by tier
4. **Phase 4:** Consider low_edge worker filter (after monitoring)

---

---

## Additional Dimensional Analysis

### Player Scoring Tier (NEW FINDING)

| Player Tier | Predicted Pts | Hit Rate | MAE |
|-------------|---------------|----------|-----|
| **Bench** | <12 | **89.0%** | 3.13 |
| **Rotation** | 12-17 | 73.1% | 5.31 |
| Starter | 18-24 | 36.3% | 7.13 |
| Star | 25+ | 43.6% | 16.55 |

**Key Insight:** We are MUCH better at predicting bench/rotation players than stars!
- Star players: 43.6% hit rate with MAE of 16.55 (terrible)
- Bench players: 89% hit rate with MAE of 3.13 (excellent)

**Recommendation:** Exclude star players (predicted 25+) from best bets entirely.

---

### Day of Week Patterns

| Day | Hit Rate | Recommendation |
|-----|----------|----------------|
| Thursday | **85.2%** | Prioritize |
| Friday | **83.3%** | Prioritize |
| Wednesday | **83.2%** | Prioritize |
| Saturday | 77.8% | Standard |
| Sunday | 78.2% | Standard |
| Tuesday | 76.8% | Caution |
| Monday | 75.8% | Caution |

**Recommendation:** Weight Thu-Fri picks higher; de-prioritize Monday/Tuesday.

---

### Multi-System Comparison

| System | Picks | Hit Rate | MAE |
|--------|-------|----------|-----|
| **xgboost_v1** | 6,548 | **87.5%** | 4.71 |
| catboost_v8 | 8,769 | 74.8% | 6.24 |
| similarity_balanced_v1 | 5,717 | 68.4% | 5.03 |
| ensemble_v1 | 8,756 | 63.4% | 4.60 |
| moving_average_baseline_v1 | 8,216 | 59.6% | 4.37 |
| zone_matchup_v1 | 8,756 | 59.3% | 5.34 |

**Key Insight:** xgboost_v1 significantly outperforms catboost_v8!

**Recommendations:**
1. Investigate why xgboost_v1 (87.5%) beats catboost_v8 (74.8%)
2. Consider system-specific selection for best bets
3. May want to filter by system_id = 'xgboost_v1' for premium tier

---

### Multi-System Strategy Options

**Option A: Best System Only**
- Filter best bets to xgboost_v1 predictions only
- Reduces volume, increases quality

**Option B: System-Specific Thresholds**
- xgboost_v1: 85%+ confidence threshold
- catboost_v8: 90%+ confidence threshold
- ensemble_v1: 92%+ confidence threshold

**Option C: Time-Based System Selection**
- Early slate (afternoon): similarity_balanced (recency weighted)
- Prime time (evening): ensemble (full context)
- Late slate (West Coast): xgboost (fatigue handling)

---

### Team-Specific Performance (Top Teams)

| Team | Picks | Hit Rate |
|------|-------|----------|
| UTA | 229 | **90.0%** |
| LAC | 327 | **89.3%** |
| LAL | 295 | **88.1%** |
| PHI | 274 | 86.5% |
| MIL | 384 | 85.9% |
| BOS | 237 | 85.2% |

**Recommendation:** Consider team-based filters for premium tier.

---

## Revised Optimal Best Bets Criteria

Based on ALL analysis above, the revised optimal pick profile is:

### Tier 1: Premium (Target: 92%+ hit rate)

```sql
WHERE recommendation = 'UNDER'
  AND confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 5.0
  AND predicted_points < 18
  -- Optional: AND system_id = 'xgboost_v1'
  -- Optional: AND EXTRACT(DAYOFWEEK FROM game_date) IN (4, 5, 6)  -- Wed-Fri
```

### Tier 2: Strong (Target: 85%+ hit rate)

```sql
WHERE recommendation = 'UNDER'
  AND confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 4.0
  AND predicted_points < 20
```

### Tier 3: Value (Target: 75%+ hit rate)

```sql
WHERE recommendation = 'UNDER'
  AND confidence_score >= 0.80
  AND ABS(predicted_points - line_value) >= 5.0
  AND predicted_points < 22
```

### AVOID (Never Include)

```sql
-- These criteria should EXCLUDE picks:
WHERE recommendation = 'OVER'  -- 53% hit rate
  OR ABS(predicted_points - line_value) < 2.0  -- 17-24% hit rate
  OR predicted_points >= 25  -- Star players, 43% hit rate
  OR (confidence_score >= 0.88 AND confidence_score < 0.90)  -- Broken tier
```

---

## Related Documents

- [ANALYSIS-FRAMEWORK.md](../ml-model-v8-deployment/ANALYSIS-FRAMEWORK.md) - Complete dimensional analysis
- [CONFIDENCE-TIER-FILTERING-IMPLEMENTATION.md](./CONFIDENCE-TIER-FILTERING-IMPLEMENTATION.md)
- [FILTER-DECISIONS.md](./FILTER-DECISIONS.md)
- [TRAINING-DATA-STRATEGY.md](../ml-model-v8-deployment/TRAINING-DATA-STRATEGY.md)
- [CHAMPION-CHALLENGER-FRAMEWORK.md](../ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md)
