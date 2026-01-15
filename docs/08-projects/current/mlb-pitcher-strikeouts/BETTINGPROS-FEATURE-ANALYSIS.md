# BettingPros Feature Analysis for Pitcher Strikeouts

**Date**: 2026-01-15
**Data Source**: `mlb_raw.bp_pitcher_props` (market_id = 285)
**Sample Size**: 14,521 graded props

---

## Key Findings

### 1. Projection Accuracy

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Projection MAE | 1.88 | BP projections off by ~1.88 Ks |
| Line MAE | 1.83 | Lines slightly better than projections |
| Projection Hit Rate | **52%** | Barely above random |

**Conclusion:** BettingPros projections are NOT significantly better than the betting line.

---

### 2. Performance Trend Features (STRONGEST SIGNAL)

| Scenario | Over Rate | Sample Size | Edge vs Baseline |
|----------|-----------|-------------|------------------|
| Trending Over (4+ of last 5) | **60.9%** | 3,296 | +9.5% |
| Trending Under (≤1 of last 5) | **42.5%** | 3,748 | -8.9% |
| Baseline | 51.4% | 14,521 | 0% |

**This is an 18.4 percentage point spread** - highly actionable!

---

### 3. Combined Signal Strength

When both perf_last_5 and projection agree:

| Signal Combo | Over Rate | Count | Edge |
|--------------|-----------|-------|------|
| Both favor over | **62.2%** | 2,344 | +10.8% |
| Trend over, proj under | 57.6% | 952 | +6.2% |
| Mixed signals | 51.7% | 7,477 | +0.3% |
| Trend under, proj over | 42.1% | 1,731 | -9.3% |
| Both favor under | **42.9%** | 2,017 | -8.5% |

**When both signals agree: 19.3pp spread (62.2% vs 42.9%)**

---

### 4. Line Bucket Analysis

| Line Range | Over Rate | MAE | Count |
|------------|-----------|-----|-------|
| Low (<4 Ks) | 54.5% | 1.64 | 2,690 |
| Medium-Low (4-4.5) | 50.9% | 1.78 | 5,012 |
| Medium (5-5.5) | 50.7% | 1.90 | 4,129 |
| Medium-High (6-6.5) | 50.1% | 2.04 | 1,954 |
| High (7+) | 51.1% | 2.04 | 736 |

**Lower lines are easier to beat** - 54.5% over rate at <4 Ks.

---

## Feature Recommendations for V1.5

### High Value Features

1. **f43_perf_last_5_over_pct** - Recent O/U performance (18pp edge)
2. **f46_combined_signal** - When trend and projection agree
3. **f40_betting_line** - The line itself (market baseline)

### Medium Value Features

4. **f44_perf_last_10_over_pct** - Longer trend window
5. **f42_projection_diff** - Projection minus line
6. **f47_over_implied_prob** - Market odds

### Low Value Features

7. **f41_bp_projection** - Only marginally better than line
8. **f45_perf_season_over_pct** - Too noisy

---

## SQL Queries Used

### Projection Accuracy
```sql
SELECT
  AVG(ABS(projection_value - actual_value)) as projection_mae,
  AVG(ABS(over_line - actual_value)) as line_mae,
  AVG(CASE WHEN (projection_value > over_line AND actual_value > over_line) OR
            (projection_value < over_line AND actual_value <= over_line)
      THEN 1.0 ELSE 0.0 END) as projection_hit_rate
FROM `mlb_raw.bp_pitcher_props`
WHERE market_id = 285 AND actual_value IS NOT NULL
```

### Performance Trend Analysis
```sql
SELECT
  AVG(CASE WHEN perf_last_5_over >= 4 THEN
    CASE WHEN actual_value > over_line THEN 1.0 ELSE 0.0 END
  END) as over_rate_when_trending_over,
  AVG(CASE WHEN perf_last_5_over <= 1 THEN
    CASE WHEN actual_value > over_line THEN 1.0 ELSE 0.0 END
  END) as over_rate_when_trending_under
FROM `mlb_raw.bp_pitcher_props`
WHERE market_id = 285 AND actual_value IS NOT NULL
```
