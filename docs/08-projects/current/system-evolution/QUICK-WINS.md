# Quick Wins: Highest ROI Improvements

**Created:** 2025-12-11
**Purpose:** Identify the easiest improvements with highest impact

---

## Prioritization Framework

```
                        High Impact
                             │
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        │   QUICK WINS       │   BIG BETS         │
        │   (Do First)       │   (Plan Carefully) │
        │                    │                    │
  Low ──┼────────────────────┼────────────────────┼── High
 Effort │                    │                    │  Effort
        │   SKIP             │   MAYBE LATER      │
        │   (Not Worth It)   │   (Backlog)        │
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                        Low Impact
```

---

## Quick Wins (Do First)

### 1. Confidence Adjustment Based on System Agreement

**Impact:** Medium-High (better confidence scores → better user trust)
**Effort:** Low (analysis + simple adjustment)

When all 4 systems agree (spread < 2 points), we should be more confident.
When systems disagree widely (spread > 6 points), lower confidence.

```python
# Simple implementation
def adjust_confidence(base_confidence: float, system_spread: float) -> float:
    if system_spread < 2:
        return min(base_confidence * 1.15, 0.95)  # Boost 15%
    elif system_spread > 6:
        return base_confidence * 0.85  # Reduce 15%
    else:
        return base_confidence
```

**Validation:** Check if adjusted confidence correlates better with actual accuracy.

---

### 2. Player Predictability Modifier

**Impact:** Medium-High (avoid bad recommendations)
**Effort:** Low (one-time computation + lookup)

Some players are just hard to predict. Don't make high-confidence calls on them.

```sql
-- Compute once, store in table
CREATE TABLE nba_predictions.player_predictability AS
SELECT
  player_lookup,
  COUNT(*) as games,
  AVG(absolute_error) as historical_mae,
  STDDEV(absolute_error) as error_volatility,
  CASE
    WHEN AVG(absolute_error) < 4 THEN 'HIGHLY_PREDICTABLE'
    WHEN AVG(absolute_error) < 5 THEN 'PREDICTABLE'
    WHEN AVG(absolute_error) < 6 THEN 'AVERAGE'
    WHEN AVG(absolute_error) < 7 THEN 'VOLATILE'
    ELSE 'UNPREDICTABLE'
  END as predictability_tier
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'
GROUP BY 1
HAVING games >= 20;
```

**Use:** Reduce confidence for VOLATILE/UNPREDICTABLE players.

---

### 3. Minutes Volatility Guard

**Impact:** High (minutes variance is #1 error driver)
**Effort:** Low (feature already in MLFS)

Players with high minutes variance are risky. Flag them.

```python
# In MLFS, we have minutes_recent_std
# Use it to modify confidence

def minutes_confidence_modifier(minutes_std: float) -> float:
    if minutes_std < 3:
        return 1.0      # Consistent minutes
    elif minutes_std < 6:
        return 0.9      # Some variance
    elif minutes_std < 10:
        return 0.75     # High variance
    else:
        return 0.5      # Very unpredictable minutes
```

---

### 4. Back-to-Back Flag in Predictions

**Impact:** Medium (known effect, easy to surface)
**Effort:** Very Low (already have the data)

Simply add `is_back_to_back` flag to published predictions so users know.

```sql
-- Add to publishing query
SELECT
  ...,
  mlfs.is_back_to_back,
  CASE WHEN mlfs.is_back_to_back THEN 'B2B game - may see reduced performance' END as warning
FROM predictions p
JOIN ml_feature_store_v2 mlfs USING (player_lookup, game_date);
```

---

### 5. Avoid Predictions in Blowout-Risk Games

**Impact:** Medium (reduces catastrophic errors)
**Effort:** Low (Vegas spread available)

When Vegas spread is > 12 points, starters may rest in garbage time.

```python
# Flag high blowout risk
def blowout_risk(vegas_spread: float) -> str:
    if abs(vegas_spread) > 15:
        return 'HIGH'      # Very likely blowout
    elif abs(vegas_spread) > 10:
        return 'MODERATE'  # Possible blowout
    else:
        return 'LOW'       # Competitive game

# Lower confidence for high blowout risk games
```

---

## Medium Effort, High Impact

### 6. Error Pattern Detection

**Impact:** High (understand why we fail)
**Effort:** Medium (analysis + categorization)

Categorize every error:
- `EARLY_EXIT`: Predicted 20+, actual < 8 (injury, foul trouble, blowout)
- `EXPLOSION`: Actual 15+ higher than predicted (career night)
- `MINUTES_MISS`: Minutes were way off from expected
- `EFFICIENCY_MISS`: Minutes were right, efficiency was off

```sql
-- Categorize errors
SELECT
  CASE
    WHEN actual_points < 8 AND predicted_points > 18 THEN 'EARLY_EXIT'
    WHEN actual_points > predicted_points + 12 THEN 'EXPLOSION'
    WHEN ABS(minutes_played - expected_minutes) > 8 THEN 'MINUTES_MISS'
    ELSE 'EFFICIENCY_MISS'
  END as error_category,
  COUNT(*) as n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM prediction_errors_enriched
WHERE absolute_error > 10
GROUP BY 1;
```

**Value:** If 60% of big errors are EARLY_EXIT, focus on injury/blowout detection.

---

### 7. Weighted Ensemble by Confidence Tier

**Impact:** Medium-High
**Effort:** Medium

Instead of same weights for all predictions, weight systems differently based on how confident each is:

```python
def weighted_ensemble(predictions: dict, confidences: dict) -> float:
    """
    Weight each system by its confidence for this specific prediction.
    """
    weighted_sum = 0
    weight_total = 0

    for system, pred in predictions.items():
        conf = confidences[system]
        weighted_sum += pred * conf
        weight_total += conf

    return weighted_sum / weight_total
```

---

### 8. Recent Form Weighting

**Impact:** Medium
**Effort:** Medium (new feature in MLFS)

Recent games should matter more. Add exponential decay.

```python
# Current: Simple average of last N games
# Better: Exponentially weighted average

def recent_form_ewma(points_history: list, alpha: float = 0.3) -> float:
    """
    Exponentially weighted moving average.
    alpha=0.3 means most recent game has ~30% weight.
    """
    ewma = points_history[0]
    for pts in points_history[1:]:
        ewma = alpha * pts + (1 - alpha) * ewma
    return ewma
```

---

## Bigger Bets (Plan Carefully)

### 9. Per-Player Model Selection

Instead of one ensemble for all, pick the best model per player.

```sql
-- Find best model per player
SELECT
  player_lookup,
  ARRAY_AGG(STRUCT(system_id, mae) ORDER BY mae LIMIT 1)[OFFSET(0)] as best_system
FROM (
  SELECT
    player_lookup,
    system_id,
    AVG(absolute_error) as mae,
    COUNT(*) as n
  FROM prediction_accuracy
  WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
  HAVING n >= 10
)
GROUP BY 1;
```

**Complexity:** Need to store per-player model assignments, handle new players.

---

### 10. Injury/News Integration

**Impact:** High (game-time decisions are major error source)
**Effort:** High (need external data source)

Options:
- ESPN injury API
- Rotowire feeds
- Manual game-day checks

---

## Implementation Priority Matrix

| # | Quick Win | Impact | Effort | Priority |
|---|-----------|--------|--------|----------|
| 1 | System agreement confidence | High | Low | **P0** |
| 2 | Player predictability modifier | High | Low | **P0** |
| 3 | Minutes volatility guard | High | Low | **P0** |
| 4 | B2B flag in output | Medium | Very Low | **P0** |
| 5 | Blowout risk flag | Medium | Low | **P1** |
| 6 | Error pattern detection | High | Medium | **P1** |
| 7 | Confidence-weighted ensemble | Medium | Medium | **P2** |
| 8 | Recent form EWMA | Medium | Medium | **P2** |
| 9 | Per-player model | High | High | **P3** |
| 10 | Injury integration | High | High | **P3** |

---

## First Week Action Plan

After backfill completes:

### Day 1-2: Analysis
- Run system agreement analysis (Query from ADDITIONAL-ANGLES.md Section 4.3)
- Compute player predictability scores
- Run minutes variance analysis

### Day 3-4: Implement P0 Quick Wins
- Add system_spread to predictions table
- Create player_predictability table
- Add confidence modifiers based on spread + predictability

### Day 5: Validate
- Check if modified confidence correlates better with accuracy
- Measure impact on "high confidence" prediction accuracy

### Day 6-7: Deploy
- Update publishing to include new flags
- Update confidence calculation
- Document changes

---

## Success Metrics for Quick Wins

| Metric | Before | Target |
|--------|--------|--------|
| High-confidence (>70%) win rate | TBD | +3% |
| Catastrophic error rate (15+ pts off) | TBD | -20% |
| Confidence calibration score | TBD | Improve |
| User trust (qualitative) | - | Higher |
