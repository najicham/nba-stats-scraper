---
name: hit-rate-analysis
description: Analyze prediction hit rates with consistent groupings by confidence, edge, tier, and time
---

# Hit Rate Analysis Skill

Provides consistent, standardized hit rate analysis across confidence levels, edge thresholds, player tiers, and time periods.

## IMPORTANT: Standard Filters

**Always report BOTH of these filters for consistency:**

| Filter Name | Definition | Use Case |
|-------------|------------|----------|
| **Premium Picks** | `confidence >= 0.92 AND edge >= 3` | Highest hit rate, fewer bets |
| **High Edge Picks** | `edge >= 5` (any confidence) | Larger sample, still profitable |

This prevents confusion when comparing analyses across sessions.

## Quick Reference

### Key Metrics (Don't Confuse These!)

| Metric | Definition | How Calculated | Good Value |
|--------|------------|----------------|------------|
| **Hit Rate** | % of correct OVER/UNDER calls | `prediction_correct = TRUE` / total | ≥52.4% (breakeven) |
| **Model Beats Vegas** | % where model closer to actual than Vegas | `\|pred - actual\| < \|line - actual\|` | ≥50% |
| **Edge** | Disagreement with Vegas | `ABS(predicted_points - line_value)` | ≥3 pts |
| **Confidence** | Model's certainty | `confidence_score` (0-1) | ≥0.92 for premium |

**WARNING**: Hit Rate and Model Beats Vegas are DIFFERENT metrics. A 78% hit rate with 40% model-beats-vegas is possible.

### Confidence Thresholds (Based on Actual Data)

| Tier | Confidence Score | Performance |
|------|------------------|-------------|
| **Premium** | ≥0.92 | Best hit rates (78%+ with 3+ edge) |
| High | 0.90-0.91 | Good performance |
| Medium | 0.87-0.89 | Mixed results |
| Low | <0.87 | Often below breakeven |

### Edge Thresholds

| Tier | Edge (points) | Description |
|------|---------------|-------------|
| **High Edge** | ≥5 | Strong disagreement with Vegas |
| Medium Edge | 3-5 | Moderate disagreement |
| Low Edge | <3 | Close to Vegas line |

## Standard Queries

| Query # | Name | Purpose |
|---------|------|---------|
| 1 | Best Performing Picks | Compare standard filters (run first) |
| 2 | Weekly Trend | Detect drift over time |
| 3 | Confidence x Edge Matrix | Full breakdown |
| 4 | Model Beats Vegas | Compare to Vegas accuracy |
| 5 | **Find Best Filter** | Optimize filter for current conditions |
| 6 | Player Tier Analysis | Performance by player scoring tier |

### Query 1: Best Performing Picks Summary (ALWAYS RUN THIS FIRST)

**IMPORTANT**: This query now checks ALL active models and groups results by model.

```sql
-- Standard filters comparison - RUN THIS FIRST (ALL MODELS)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @start_date AND game_date <= @end_date
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  filter_name,
  bets,
  hits,
  ROUND(100.0 * hits / bets, 1) as hit_rate,
  CASE WHEN ROUND(100.0 * hits / bets, 1) >= 52.4 THEN '✅' ELSE '❌' END as profitable
FROM (
  -- Premium Picks: 92+ conf, 3+ edge
  SELECT system_id,
         'Premium (92+ conf, 3+ edge)' as filter_name,
         COUNT(*) as bets,
         COUNTIF(prediction_correct) as hits
  FROM nba_predictions.prediction_accuracy
  WHERE system_id IN (SELECT system_id FROM active_models)
    AND game_date >= @start_date AND game_date <= @end_date
    AND confidence_score >= 0.92
    AND ABS(predicted_points - line_value) >= 3
    AND prediction_correct IS NOT NULL
  GROUP BY system_id

  UNION ALL

  -- High Edge: 5+ edge (any confidence)
  SELECT system_id,
         'High Edge (5+ pts, any conf)' as filter_name,
         COUNT(*) as bets,
         COUNTIF(prediction_correct) as hits
  FROM nba_predictions.prediction_accuracy
  WHERE system_id IN (SELECT system_id FROM active_models)
    AND game_date >= @start_date AND game_date <= @end_date
    AND ABS(predicted_points - line_value) >= 5
    AND prediction_correct IS NOT NULL
  GROUP BY system_id

  UNION ALL

  -- All 3+ edge picks
  SELECT system_id,
         'All 3+ Edge' as filter_name,
         COUNT(*) as bets,
         COUNTIF(prediction_correct) as hits
  FROM nba_predictions.prediction_accuracy
  WHERE system_id IN (SELECT system_id FROM active_models)
    AND game_date >= @start_date AND game_date <= @end_date
    AND ABS(predicted_points - line_value) >= 3
    AND prediction_correct IS NOT NULL
  GROUP BY system_id

  UNION ALL

  -- All picks (baseline)
  SELECT system_id,
         'All Picks (baseline)' as filter_name,
         COUNT(*) as bets,
         COUNTIF(prediction_correct) as hits
  FROM nba_predictions.prediction_accuracy
  WHERE system_id IN (SELECT system_id FROM active_models)
    AND game_date >= @start_date AND game_date <= @end_date
    AND prediction_correct IS NOT NULL
  GROUP BY system_id
)
ORDER BY system_id, hit_rate DESC
```

**Usage Notes**:
- Results are grouped by `system_id` to compare model performance side-by-side
- `catboost_v9` is the current production model (Jan 31+ predictions)
- `catboost_v8` is the historical model (Jan 18-28, 2026)
- `ensemble_v1_1` is an active ensemble model for comparison

### Query 2: Weekly Trend (Detect Drift)

**IMPORTANT**: This query shows weekly trends for ALL active models to compare performance over time.

```sql
-- Weekly breakdown with BOTH standard filters (ALL MODELS)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @start_date AND game_date <= @end_date
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  FORMAT_DATE('%Y-%m-%d', DATE_TRUNC(game_date, WEEK(MONDAY))) as week_start,

  -- Premium Picks (92+ conf, 3+ edge)
  COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3) as premium_bets,
  ROUND(100.0 * COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
        NULLIF(COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL), 0), 1) as premium_hit_rate,

  -- High Edge (5+ pts)
  COUNTIF(ABS(predicted_points - line_value) >= 5) as high_edge_bets,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 5 AND prediction_correct) /
        NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 5 AND prediction_correct IS NOT NULL), 0), 1) as high_edge_hit_rate,

  -- Overall
  COUNT(*) as total_bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as overall_hit_rate,

  -- Model Beats Vegas (secondary metric)
  ROUND(100.0 * COUNTIF(ABS(predicted_points - actual_points) < ABS(line_value - actual_points)) / COUNT(*), 1) as model_beats_vegas_pct

FROM nba_predictions.prediction_accuracy
WHERE system_id IN (SELECT system_id FROM active_models)
  AND game_date >= @start_date AND game_date <= @end_date
  AND line_value IS NOT NULL
  AND prediction_correct IS NOT NULL
GROUP BY system_id, week_start
ORDER BY system_id, week_start
```

### Query 3: Full Confidence x Edge Matrix

**IMPORTANT**: This query breaks down performance by confidence AND edge for ALL active models.

```sql
-- Detailed breakdown by confidence AND edge (ALL MODELS)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @start_date AND game_date <= @end_date
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 0.92 THEN '92+'
    WHEN confidence_score >= 0.90 THEN '90-91'
    WHEN confidence_score >= 0.87 THEN '87-89'
    ELSE '<87'
  END as confidence,
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN '5+'
    WHEN ABS(predicted_points - line_value) >= 3 THEN '3-5'
    WHEN ABS(predicted_points - line_value) >= 2 THEN '2-3'
    ELSE '<2'
  END as edge,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  CASE WHEN ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) >= 52.4 THEN '✅' ELSE '❌' END as profitable
FROM nba_predictions.prediction_accuracy
WHERE system_id IN (SELECT system_id FROM active_models)
  AND game_date >= @start_date AND game_date <= @end_date
  AND line_value IS NOT NULL
  AND prediction_correct IS NOT NULL
GROUP BY system_id, confidence, edge
HAVING bets >= 10
ORDER BY
  system_id,
  CASE confidence WHEN '92+' THEN 1 WHEN '90-91' THEN 2 WHEN '87-89' THEN 3 ELSE 4 END,
  CASE edge WHEN '5+' THEN 1 WHEN '3-5' THEN 2 WHEN '2-3' THEN 3 ELSE 4 END
```

### Query 4: Model Beats Vegas Analysis

**IMPORTANT**: This query compares hit rate vs model-beats-vegas for ALL active models.

```sql
-- Compare hit rate vs model beats vegas (they're different!) - ALL MODELS
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @start_date AND game_date <= @end_date
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3 THEN 'Premium'
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'High Edge'
    ELSE 'Other'
  END as filter_group,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - actual_points) < ABS(line_value - actual_points)) / COUNT(*), 1) as model_beats_vegas,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as model_mae
FROM nba_predictions.prediction_accuracy
WHERE system_id IN (SELECT system_id FROM active_models)
  AND game_date >= @start_date AND game_date <= @end_date
  AND actual_points IS NOT NULL
GROUP BY system_id, filter_group
ORDER BY system_id, filter_group
```

### Query 5: Find Best Filter (Optimization)

**IMPORTANT**: This query finds the optimal filter for EACH active model separately.

```sql
-- Test ALL confidence/edge combinations and rank by hit rate (ALL MODELS)
-- Use this to find the optimal filter for current market conditions
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @start_date AND game_date <= @end_date
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
),
filter_results AS (
  SELECT
    system_id,
    conf_threshold,
    edge_threshold,
    COUNT(*) as bets,
    COUNTIF(prediction_correct) as hits,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) - 52.4 as edge_over_breakeven
  FROM (
    SELECT *,
      CASE
        WHEN confidence_score >= 0.95 THEN 95
        WHEN confidence_score >= 0.92 THEN 92
        WHEN confidence_score >= 0.90 THEN 90
        WHEN confidence_score >= 0.87 THEN 87
        ELSE 80
      END as conf_threshold,
      CASE
        WHEN ABS(predicted_points - line_value) >= 7 THEN 7
        WHEN ABS(predicted_points - line_value) >= 5 THEN 5
        WHEN ABS(predicted_points - line_value) >= 4 THEN 4
        WHEN ABS(predicted_points - line_value) >= 3 THEN 3
        WHEN ABS(predicted_points - line_value) >= 2 THEN 2
        ELSE 1
      END as edge_threshold
    FROM nba_predictions.prediction_accuracy
    WHERE system_id IN (SELECT system_id FROM active_models)
      AND game_date >= @start_date AND game_date <= @end_date
      AND prediction_correct IS NOT NULL
  )
  GROUP BY system_id, conf_threshold, edge_threshold
  HAVING bets >= 20  -- Minimum sample size for statistical significance
)
SELECT
  system_id,
  CONCAT(CAST(conf_threshold AS STRING), '+ conf, ', CAST(edge_threshold AS STRING), '+ edge') as filter,
  bets,
  hits,
  hit_rate,
  edge_over_breakeven,
  CASE
    WHEN hit_rate >= 70 THEN '🏆 Excellent'
    WHEN hit_rate >= 60 THEN '✅ Good'
    WHEN hit_rate >= 52.4 THEN '⚠️ Marginal'
    ELSE '❌ Unprofitable'
  END as quality
FROM filter_results
ORDER BY system_id, hit_rate DESC
LIMIT 50
```

**Interpretation**:
- The top filter is your best trading strategy for the current period
- Compare to the standard filters (92+/3+ and 5+) to see if optimization helps
- If optimized filter differs significantly from standard, investigate why

### Query 6: Player Tier Analysis

**IMPORTANT**: This query breaks down performance by player tier for ALL active models.

```sql
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @start_date AND game_date <= @end_date
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
),
player_tiers AS (
  SELECT
    player_lookup,
    CASE
      WHEN AVG(points) >= 22 THEN 'Star'
      WHEN AVG(points) >= 14 THEN 'Starter'
      WHEN AVG(points) >= 6 THEN 'Rotation'
      ELSE 'Bench'
    END as tier
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(@end_date, INTERVAL 60 DAY)
    AND minutes_played > 10
  GROUP BY 1
)
SELECT
  pa.system_id,
  COALESCE(pt.tier, 'Unknown') as tier,
  COUNT(*) as bets,

  -- Premium filter
  COUNTIF(pa.confidence_score >= 0.92 AND ABS(pa.predicted_points - pa.line_value) >= 3) as premium_bets,
  ROUND(100.0 * COUNTIF(pa.confidence_score >= 0.92 AND ABS(pa.predicted_points - pa.line_value) >= 3 AND pa.prediction_correct) /
        NULLIF(COUNTIF(pa.confidence_score >= 0.92 AND ABS(pa.predicted_points - pa.line_value) >= 3 AND pa.prediction_correct IS NOT NULL), 0), 1) as premium_hit,

  -- High edge filter
  COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5) as high_edge_bets,
  ROUND(100.0 * COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5 AND pa.prediction_correct) /
        NULLIF(COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5 AND pa.prediction_correct IS NOT NULL), 0), 1) as high_edge_hit

FROM nba_predictions.prediction_accuracy pa
LEFT JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
WHERE pa.system_id IN (SELECT system_id FROM active_models)
  AND pa.game_date >= @start_date AND pa.game_date <= @end_date
  AND pa.line_value IS NOT NULL
GROUP BY pa.system_id, tier
HAVING bets >= 20
ORDER BY
  pa.system_id,
  CASE tier WHEN 'Star' THEN 1 WHEN 'Starter' THEN 2 WHEN 'Rotation' THEN 3 WHEN 'Bench' THEN 4 ELSE 5 END
```

## Output Format

**Always present results in this format:**

```
## Hit Rate Analysis - catboost_v8 - [Date Range]

### Best Performing Picks

| Filter | Hit Rate | Bets | Status |
|--------|----------|------|--------|
| Premium (92+ conf, 3+ edge) | XX.X% | XXX | ✅/❌ |
| High Edge (5+ pts) | XX.X% | XXX | ✅/❌ |
| All 3+ Edge | XX.X% | XXX | ✅/❌ |
| All Picks | XX.X% | XXX | ✅/❌ |

### Weekly Trend

| Week | Premium Hit | Premium Bets | High Edge Hit | High Edge Bets | Model Beats Vegas |
|------|-------------|--------------|---------------|----------------|-------------------|
| Jan 1 | XX.X% | XX | XX.X% | XX | XX.X% |
| ... | ... | ... | ... | ... | ... |

### Confidence x Edge Matrix

| Confidence | Edge | Hit Rate | Bets | Status |
|------------|------|----------|------|--------|
| 92+ | 5+ | XX.X% | XX | ✅ |
| 92+ | 3-5 | XX.X% | XX | ✅ |
| ... | ... | ... | ... | ... |

### Key Findings
1. [Which filter is performing best]
2. [Any drift detected in weekly trend]
3. [Confidence vs edge - which matters more]

### Recommendations
1. [Specific actionable recommendation]
2. [Filter to use for trading]
```

## Key Thresholds

| Metric | Excellent | Good | Warning | Critical |
|--------|-----------|------|---------|----------|
| Premium Hit Rate | ≥75% | 65-75% | 55-65% | <55% |
| High Edge Hit Rate | ≥65% | 55-65% | 52.4-55% | <52.4% |
| Model Beats Vegas | ≥55% | 50-55% | 45-50% | <45% |
| Weekly Trend | Stable | -5% drop | -10% drop | >-10% drop |

## Common Issues to Watch For

### Issue 1: Different Filters Give Different Numbers
**Example**: "78% hit rate" vs "50% hit rate"
**Cause**: Different confidence/edge filters applied
**Solution**: Always specify the filter used, report both standard filters

### Issue 2: Monthly vs Weekly Numbers Differ
**Example**: "78% for the month" but "46% last week"
**Cause**: Good early weeks can mask recent degradation
**Solution**: Always show weekly trend to detect drift

### Issue 3: Hit Rate vs Model Beats Vegas Confusion
**Example**: "78% hit rate but only 40% beats Vegas"
**Cause**: Different metrics measuring different things
**Solution**: Report both, explain the difference

## Related Skills

- `/model-health` - Performance diagnostics with root cause
- `/validate-daily` - Overall pipeline health
- `/top-picks` - Today's best trading opportunities

## Table Reference

| Table | Key Columns |
|-------|-------------|
| `nba_predictions.prediction_accuracy` | player_lookup, game_date, system_id, predicted_points, line_value, actual_points, prediction_correct, confidence_score, absolute_error |
| `nba_analytics.player_game_summary` | player_lookup, game_date, points, minutes_played |

---

*Skill created: Session 55*
*Updated: Session 57 - Added standard filters, clarified metrics confusion*
*Updated: Session 58 - Added "Find Best Filter" query for filter optimization*
