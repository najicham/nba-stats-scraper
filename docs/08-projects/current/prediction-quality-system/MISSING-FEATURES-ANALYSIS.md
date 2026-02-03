# Missing Features Impact Analysis

**Session 95 - 2026-02-03**

## Summary

When ML features are missing (low quality score < 85%), the model **underpredicts** player scoring by 0.45 points on average. This creates artificially large edges that look like good bets but are actually unreliable.

---

## Key Findings

### 1. Low Quality = Underprediction

| Quality Tier | Avg Predicted | Avg Actual | Error |
|--------------|---------------|------------|-------|
| High (85%+) | 13.0 | 12.9 | +0.05 (slight overprediction) |
| Medium (80-85%) | 13.0 | 13.2 | -0.13 |
| **Low (<80%)** | **12.4** | **12.8** | **-0.45 (underprediction)** |

When BDB shot zone features are missing, the model predicts lower scores because:
- Shot zone data (pct_paint, pct_mid_range, pct_three) default to 0
- The model interprets this as "player doesn't shoot from any zone"
- Result: Conservative (low) predictions

### 2. Low Quality Creates False High-Edge Picks

| Quality | Edge Tier | Rec | Picks | Hit Rate | Avg Predicted | Avg Actual |
|---------|-----------|-----|-------|----------|---------------|------------|
| High | Medium (3-5) | UNDER | 101 | **60.4%** | 13.9 | 15.8 |
| **Low** | Medium (3-5) | **UNDER** | 10 | **40.0%** | **13.6** | **19.5** |

Low quality UNDER picks:
- Model predicted 13.6 points
- Players actually scored 19.5 points
- **Underprediction of 5.9 points on average**

This is exactly what happened on Feb 2:

| Player | Quality | Predicted | Line | Actual | Edge | Result |
|--------|---------|-----------|------|--------|------|--------|
| Trey Murphy III | 82.73% | 11.1 | 22.5 | 27 | 11.4 | MISS |
| Jaren Jackson Jr | 82.73% | 13.8 | 22.5 | 30 | 8.7 | MISS |
| Jabari Smith Jr | 82.73% | 9.4 | 17.5 | 19 | 8.1 | MISS |

### 3. RED Signal is Valid (Not Just Detecting Low Quality)

The RED signal is **NOT** caused by low quality features. It's a valid market signal:

| Signal | Quality | Edge 3+ Hit Rate |
|--------|---------|------------------|
| GREEN | High (85%+) | **66.9%** |
| YELLOW | High (85%+) | **81.7%** |
| RED | High (85%+) | **54.8%** |

Even with perfect high-quality features:
- GREEN days: 66.9% hit rate
- RED days: 54.8% hit rate (12% lower)

The signal correctly identifies days when the model is less reliable.

### 4. Worst Case: RED Signal + Low Quality

| Signal | Quality | Hit Rate |
|--------|---------|----------|
| GREEN | High | 66.9% |
| GREEN | Low | 61.1% |
| RED | High | 54.8% |
| **RED** | **Low** | **45.5%** |

The combination of RED signal + low quality features is the worst case scenario:
- Only 45.5% hit rate
- Worse than random

---

## Why This Happens

### Feature Quality Score Calculation

The quality score is calculated as a weighted average of source quality:
- Phase 4 data: 100 points
- Phase 3 data: 87 points
- Default values: 40 points

When BDB shot zone data is missing, features like `pct_paint`, `pct_mid_range`, `pct_three` default to 0, which:
1. Lowers the quality score
2. Causes the model to predict lower scoring (conservative)

### The Chain Reaction

```
Missing BDB data
     │
     ▼
Features default to 0
     │
     ▼
Quality score drops (65-82%)
     │
     ▼
Model predicts LOW (conservative)
     │
     ▼
Creates artificial "high edge" for UNDER
     │
     ▼
Player performs normally
     │
     ▼
UNDER pick MISSES
```

---

## Implications for Betting Strategy

### 1. Don't Trust High-Edge Picks Without Checking Quality

A pick with edge > 5 might look great, but if quality < 85%, the edge is likely artificial.

### 2. RED Signal Days Require Extra Caution

Even with high-quality features, RED days have 12% lower hit rate. Combined with low quality, hit rate drops to 45%.

### 3. The Quality Filter is Essential

The new quality filter (min 85% for top picks) prevents these false high-edge picks from being exported.

---

## Monitoring Queries

### Check Daily Quality Distribution

```sql
SELECT
  game_date,
  COUNT(*) as players,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNTIF(feature_quality_score < 80) as low_quality,
  ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

### Check Hit Rate by Quality on RED Days

```sql
SELECT
  CASE WHEN f.feature_quality_score >= 85 THEN 'High'
       ELSE 'Not High' END as quality,
  COUNT(*) as picks,
  COUNTIF(a.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(a.prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy a
  ON p.player_lookup = a.player_lookup
  AND p.game_date = a.game_date
JOIN nba_predictions.ml_feature_store_v2 f
  ON p.player_lookup = f.player_lookup
  AND p.game_date = f.game_date
JOIN nba_predictions.daily_prediction_signals s
  ON p.game_date = s.game_date
WHERE s.daily_signal = 'RED'
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 3
GROUP BY quality;
```

---

## Conclusions

1. **Low quality features cause underprediction** (avg -0.45 points)
2. **This creates false high-edge UNDER picks** that miss at 40% rate
3. **RED signal is valid even with good features** (54.8% vs 66.9% hit rate)
4. **RED + low quality is worst case** (45.5% hit rate)
5. **Quality filter (85% threshold) is essential** for export
