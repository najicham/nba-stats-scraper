# Prediction Quality Analysis

This directory contains analysis of prediction model performance and quality metrics.

## Documents

### [SESSION-81-DEEP-DIVE.md](./SESSION-81-DEEP-DIVE.md)
**Date:** Feb 2, 2026
**Topic:** Root cause analysis of 33% vs 79% hit rate mystery

**Key Findings:**
- 39% of "predictions" were PASS (non-bets), included in original hit rate calculation
- 73% of actual bets have edge < 3 and lose money (~50% hit rate)
- Only 27% of bets (edge >= 3) are profitable (65% hit rate, +24% ROI)
- Confidence score doesn't predict profitability - edge is everything

**Recommendations:**
1. ✅ Implement edge >= 3 filter (+43% more profit)
2. ✅ Stop using confidence-based filters (don't work)
3. ✅ Always exclude PASS from hit rate calculations
4. ✅ Update monitoring to show edge-based tiers

**Impact:** +43% profit improvement available by filtering edge < 3 bets

---

## Quick Reference

### Profitable Bet Criteria (catboost_v9)

| Tier | Edge | Hit Rate | ROI | Volume | Recommendation |
|------|------|----------|-----|--------|----------------|
| High Quality | >= 5 | 79.0% | +50.9% | ~5 bets/day | Best ROI, selective |
| Medium Quality | >= 3 | 65.0% | +24.0% | ~17 bets/day | **OPTIMAL** - best profit |
| Low Quality | < 3 | 50.9% | -2.5% | ~50 bets/day | ❌ Loses money, filter out |

### Correct Hit Rate Query

```sql
-- ALWAYS use this pattern for hit rate queries
SELECT
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND recommendation IN ('OVER', 'UNDER')  -- Exclude PASS (non-bets)
  AND ABS(predicted_points - line_value) >= 3  -- Edge filter
  AND prediction_correct IS NOT NULL
```

### Why Confidence Doesn't Work

- Model can be 95% confident predicting 18.2 when Vegas says 18.5 (low edge)
- 92% of high-confidence (0.92+) predictions have edge < 3 and lose money
- High confidence ≠ High edge ≠ Profitability

**Conclusion:** Use edge-based filters only. Ignore confidence for bet selection.

---

## Related Documentation

- `CLAUDE.md` - Updated hit rate measurement section (Session 81)
- `docs/09-handoff/2026-02-02-SESSION-80-HANDOFF.md` - Monitoring improvements
- `docs/08-projects/current/ml-challenger-experiments/` - Model training documentation

---

**Last Updated:** Feb 2, 2026 (Session 81)
