# Best Bets Selection Strategy

**Created:** 2026-01-14
**Status:** Analysis Complete - Recommendations for Implementation

---

## Executive Summary

Analysis of 2,000+ graded picks reveals that **confidence + edge combination** is the strongest predictor of success. The optimal "Best Bets" strategy should prioritize:

1. **90%+ confidence** (72-76% base hit rate)
2. **4+ point edge** (adds 10-20% to hit rate)
3. **Exclude 88-90% confidence tier** (already implemented)

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

3. **OVER vs UNDER (90%+ tier)**
   - OVER: 74.0% (749 picks)
   - UNDER: 75.6% (512 picks)
   - Slight UNDER advantage (not significant)

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

## Related Documents

- [CONFIDENCE-TIER-FILTERING-IMPLEMENTATION.md](./CONFIDENCE-TIER-FILTERING-IMPLEMENTATION.md)
- [FILTER-DECISIONS.md](./FILTER-DECISIONS.md)
- [TRAINING-DATA-STRATEGY.md](../ml-model-v8-deployment/TRAINING-DATA-STRATEGY.md)
