---
name: spot-check-features
description: Validate feature store data quality before model training
---

# Spot Check Features Skill

Validate ML Feature Store data quality to ensure model training uses clean data.

## Trigger
- Before running `/model-experiment`
- User asks "is feature store data good?"
- User types `/spot-check-features`
- "Check feature quality", "Validate training data"

## Quick Start

```bash
# Check last 7 days of feature data
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNTIF(feature_quality_score >= 70 AND feature_quality_score < 85) as medium_quality,
  COUNTIF(feature_quality_score < 70) as low_quality,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  data_source,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas_line
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY game_date, data_source
ORDER BY game_date DESC"
```

## Validation Checks

### 1. Quality Score Distribution

**Healthy:** >80% records have quality_score >= 70

```sql
SELECT
  CASE
    WHEN feature_quality_score >= 85 THEN 'High (85+)'
    WHEN feature_quality_score >= 70 THEN 'Medium (70-84)'
    ELSE 'Low (<70)'
  END as quality_tier,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1
```

### 2. Vegas Line Coverage

**Healthy:** >90% records have Vegas lines for recent dates

```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1 DESC
```

### 3. Data Source Distribution

**Healthy:** <5% partial data, <10% early season data

```sql
SELECT
  data_source,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY records DESC
```

### 4. Feature Completeness

**Healthy:** All 37 features populated (feature_count = 37)

```sql
SELECT
  feature_count,
  COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1
```

### 5. Rolling Average Staleness

**Healthy:** points_avg_last_5 > 0 for most records

```sql
SELECT
  game_date,
  COUNTIF(features[OFFSET(0)] = 0) as missing_points_avg,
  COUNTIF(features[OFFSET(31)] = 0) as missing_minutes_avg,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1 DESC
```

### 6. Vegas Line Coverage by Player Tier (Session 103)

**Critical for training data quality.** Sportsbooks don't offer props for most bench players.
Training data should have balanced coverage or tier-aware model features.

```sql
-- Check Vegas line coverage by tier
SELECT
  CASE
    WHEN pgs.points >= 25 THEN 'star'
    WHEN pgs.points >= 15 THEN 'starter'
    WHEN pgs.points >= 5 THEN 'role'
    ELSE 'bench'
  END as tier,
  COUNT(*) as n,
  ROUND(AVG(CASE WHEN f.features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) * 100, 1) as pct_has_vegas,
  ROUND(AVG(CASE WHEN f.features[OFFSET(29)] > 0 THEN 1 ELSE 0 END) * 100, 1) as pct_has_matchup
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_analytics.player_game_summary pgs
  ON f.player_lookup = pgs.player_lookup AND f.game_date = pgs.game_date
WHERE f.game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY) AND DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND f.feature_count >= 33
GROUP BY 1
ORDER BY 1
```

**Expected (based on sportsbook behavior):**
| Tier | Vegas Coverage | Matchup Coverage |
|------|----------------|------------------|
| Star | ~95% | ~85% |
| Starter | ~90% | ~80% |
| Role | ~40% | ~30% |
| Bench | ~15% | ~10% |

**Why this matters:** If model trains mostly on players WITH vegas lines (stars), it learns
"vegas line → scoring" but can't generalize to players without lines. This causes
regression-to-mean bias.

### 7. Vegas Line Bias Check (Session 103)

**Vegas lines themselves are biased.** Sportsbooks set conservative lines.

```sql
-- Check if Vegas lines match actual scoring by tier
SELECT
  CASE
    WHEN pgs.points >= 25 THEN 'star'
    WHEN pgs.points >= 15 THEN 'starter'
    WHEN pgs.points >= 5 THEN 'role'
    ELSE 'bench'
  END as tier,
  COUNT(*) as n,
  ROUND(AVG(f.features[OFFSET(25)]), 1) as avg_vegas_line,
  ROUND(AVG(pgs.points), 1) as avg_actual,
  ROUND(AVG(f.features[OFFSET(25)]) - AVG(pgs.points), 1) as vegas_bias
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_analytics.player_game_summary pgs
  ON f.player_lookup = pgs.player_lookup AND f.game_date = pgs.game_date
WHERE f.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND f.features[OFFSET(25)] > 0
GROUP BY 1
ORDER BY 1
```

**Expected:** Vegas under-predicts stars by ~8 pts, over-predicts bench by ~5 pts.
This is intentional by sportsbooks but causes model bias if not accounted for.

## Quality Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Avg Quality Score | >= 80 | 70-79 | < 70 |
| High Quality % | >= 70% | 50-69% | < 50% |
| Vegas Coverage | >= 40% | 30-39% | < 30% |
| Partial Data % | < 5% | 5-10% | > 10% |
| Early Season % | < 10% | 10-20% | > 20% |

**Note on Vegas Coverage (Session 103):** 40% is realistic because sportsbooks don't
offer props for bench players. The key is ensuring BALANCED coverage by tier, not
forcing 90%+ overall coverage.

## Training Data Recommendations

Based on Session 103 investigation, model bias occurs when:
1. **Tier imbalance:** Stars have high Vegas coverage, bench has low → model learns "Vegas = high scorer"
2. **Vegas line following:** Model follows Vegas too closely instead of learning to diverge
3. **Missing data pattern:** Model can't distinguish "missing because bench player" vs "missing because data issue"

**Solutions:**
- Add `scoring_tier` as categorical training feature
- Filter training data to quality_score >= 70
- Consider separate models per tier or tier-aware weighting

## Pre-Training Checklist

Before running `/model-experiment`:

1. Run quality distribution check (target: >80% quality >= 70)
2. Check Vegas line coverage by tier (not overall - expect 40% for bench, 95% for stars)
3. Verify Vegas bias by tier (expect stars under-predicted ~8pts)
4. Check for unusual data source distribution (<5% partial)
5. Confirm model experiment includes tier bias analysis (built-in since Session 104)

## Example Output

```
=== Feature Store Quality Report ===
Date Range: 2026-01-20 to 2026-02-03

Quality Distribution:
  High (85+):   12,450 (78.2%)
  Medium (70-84): 2,890 (18.1%)
  Low (<70):      590 (3.7%)

Vegas Coverage: 94.2%
Partial Data: 0.5%
Early Season: 2.1%

Status: GOOD - Ready for model training
```

## Related Skills

- `/model-experiment` - Train challenger models
- `/validate-daily` - Full daily validation
- `/hit-rate-analysis` - Analyze model performance

## Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Has check_training_data_quality() |
| `data_processors/precompute/ml_feature_store/` | Feature store processor |

---
*Created: Session 104*
*Part of: Data Quality & Model Experiment Infrastructure*
