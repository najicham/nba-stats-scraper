# Pre-Game Signals Strategy

**Created**: February 1, 2026
**Status**: EXPERIMENTAL
**Owner**: ML Team

---

## Overview

This project documents pre-game signals that may predict daily prediction performance. The goal is to identify warning signs before games start so betting strategy can be adjusted.

## Discovery Context

During Session 70 analysis of V9 performance (Jan 20-31, 2026), we discovered that certain pre-game characteristics correlate with worse high-edge hit rates.

---

## Signal 1: Over/Under Skew (pct_over)

### Definition

`pct_over` = Percentage of predictions recommending OVER vs UNDER

```sql
pct_over = 100.0 * COUNT(recommendation = 'OVER') / COUNT(*)
```

### Correlation Found

| pct_over Range | Typical Hit Rate | Classification |
|----------------|------------------|----------------|
| 28-39% | 60-100% | GOOD |
| 25-28% | 50-60% | OK |
| < 25% | 33-50% | WARNING |

### Historical Data (Jan 20-31, V9 High-Edge)

| Date | pct_over | High-Edge Hit Rate | Quality |
|------|----------|-------------------|---------|
| Jan 31 | 19.6% | 40.0% | BAD |
| Jan 30 | 24.6% | 75.0% | GOOD |
| Jan 29 | 19.7% | 50.0% | OK |
| Jan 28 | 28.9% | 100.0% | GOOD |
| Jan 27 | 21.8% | 33.3% | BAD |
| Jan 26 | 35.5% | 85.7% | GOOD |
| Jan 25 | 29.0% | 100.0% | GOOD |
| Jan 24 | 28.2% | 50.0% | OK |
| Jan 23 | 38.7% | 100.0% | GOOD |
| Jan 22 | 30.6% | 100.0% | GOOD |
| Jan 21 | 27.9% | 57.1% | OK |
| Jan 20 | 30.4% | 100.0% | GOOD |

### Interpretation

When the model heavily favors UNDER predictions (< 25% over), it may indicate:
1. Model uncertainty manifesting as directional bias
2. Market conditions the model doesn't handle well
3. Potential overfitting to recent trends

### Caveats

- **Small sample size**: Only 12 days analyzed
- **Correlation not causation**: May be coincidental
- **Confounding factors**: Game slate, injuries, etc. not controlled

---

## Signal 2: Number of High-Edge Picks

### Definition

High-edge picks = predictions where `|predicted_points - line| >= 5`

### Observation

Days with very few high-edge picks (1-3) show extreme variance:

| Date | High-Edge Picks | Hit Rate |
|------|-----------------|----------|
| Jan 28 | 1 | 100% |
| Jan 25 | 2 | 100% |
| Jan 27 | 3 | 33% |

### Interpretation

With < 4 high-edge picks, a single wrong prediction can swing hit rate by 25-50%. These days are essentially coin flips and should not be used to evaluate model performance.

### Recommendation

- **< 4 picks**: Reduce bet sizing or skip
- **4-7 picks**: Normal confidence
- **8+ picks**: Higher confidence in daily signal

---

## Signal 3: Average Edge Magnitude

### Definition

`avg_edge` = Average of `|predicted_points - line|` for high-edge picks

### Observation

Higher average edge doesn't guarantee better performance:

| Date | Avg Edge | Hit Rate |
|------|----------|----------|
| Jan 30 | 10.6 | 75% |
| Jan 27 | 8.0 | 33% |
| Jan 31 | 6.9 | 40% |
| Jan 26 | 6.7 | 86% |

### Interpretation

Edge magnitude alone is not predictive. A 10-point edge that's wrong is still wrong.

### Recommendation

Do not use avg_edge as a standalone signal.

---

## Daily Pre-Game Diagnostic

### SQL Query

Run this each morning before betting:

```sql
SELECT
  game_date,
  COUNT(*) as total_picks,
  SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) as high_edge_picks,
  ROUND(AVG(confidence_score), 2) as avg_confidence,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  -- Warning flags
  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
    THEN 'WARNING: HEAVY UNDER SKEW'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 40
    THEN 'WARNING: HEAVY OVER SKEW'
    ELSE 'BALANCED'
  END as skew_signal,
  CASE
    WHEN SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) < 4
    THEN 'WARNING: LOW PICK COUNT'
    ELSE 'OK'
  END as volume_signal
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND current_points_line IS NOT NULL
GROUP BY 1
```

### Output Interpretation

| Signal | Value | Action |
|--------|-------|--------|
| skew_signal | BALANCED | Normal betting |
| skew_signal | WARNING: HEAVY UNDER/OVER SKEW | Reduce bet sizing 25-50% |
| volume_signal | OK | Normal betting |
| volume_signal | WARNING: LOW PICK COUNT | Consider skipping or minimal bets |

---

## Recommended Betting Strategy

### Tier 1: Green Light (Full Confidence)
- pct_over: 28-39%
- high_edge_picks: 5+
- Action: Normal bet sizing

### Tier 2: Yellow Light (Reduced Confidence)
- pct_over: 20-28% OR 39-45%
- high_edge_picks: 3-4
- Action: Reduce bet sizing by 25-50%

### Tier 3: Red Light (High Caution)
- pct_over: < 20% OR > 45%
- high_edge_picks: < 3
- Action: Minimal bets or skip

---

## Validation Plan

### Phase 1: Observation (Current)
- Track signals daily for 2 weeks
- Record actual hit rates
- Build larger sample size

### Phase 2: Statistical Validation
- Calculate correlation coefficients
- Test statistical significance
- Control for confounding factors (game count, back-to-backs, etc.)

### Phase 3: Implementation
- If validated, add to daily dashboard
- Create automated alerts for warning conditions
- Integrate into bet recommendation system

---

## Example: Feb 1, 2026 Analysis

### Pre-Game Signal

| Metric | Value | Benchmark | Status |
|--------|-------|-----------|--------|
| total_picks | 170 | - | - |
| high_edge_picks | 4 | 5-8 | Borderline |
| avg_confidence | 84.0 | 86-89 | Low |
| pct_over | **10.6%** | 28-39% | **RED FLAG** |

### Assessment

Feb 1 shows **extreme UNDER skew** (10.6%) - the worst we've seen. Based on historical patterns, this suggests higher risk of poor performance.

### Recommendation

- Reduce bet sizing by 50%
- Focus only on highest-edge picks (7+ points)
- Set stop-loss limits

---

## Files

| File | Purpose |
|------|---------|
| `README.md` | This document |
| `daily-diagnostic.sql` | SQL query for daily checks |
| `historical-analysis.sql` | Queries used for discovery |
| `validation-tracker.md` | Ongoing validation results |

---

## Related Documents

- `docs/09-handoff/2026-02-01-SESSION-70-V9-PERFORMANCE-ANALYSIS.md` - Discovery session
- `docs/08-projects/current/catboost-v9-experiments/` - V9 model documentation

---

## Open Questions

1. **Is pct_over causally related to performance?**
   - Or is it a proxy for something else (market conditions, game types)?

2. **Should we retrain V9 to be more balanced?**
   - Current model seems biased toward UNDER predictions

3. **Are there game-level signals?**
   - Back-to-back games, rivalry games, playoff implications?

4. **Can we predict pct_over before predictions are generated?**
   - If so, we could flag problematic days earlier

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-01 | Initial creation based on Session 70 analysis |
