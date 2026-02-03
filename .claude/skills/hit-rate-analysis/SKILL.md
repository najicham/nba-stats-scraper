---
name: hit-rate-analysis
description: Analyze prediction hit rates with consistent groupings by confidence, edge, tier, and time
---

# Hit Rate Analysis Skill

Provides consistent, standardized hit rate analysis across confidence levels, edge thresholds, player tiers, and time periods.

## 🚨 SESSION 81 CRITICAL UPDATE (Feb 2, 2026)

**BREAKING DISCOVERY**: Confidence-based filters DON'T WORK!

**Key Findings:**
- 39% of predictions are PASS (non-bets) - MUST exclude from hit rate calculations
- Confidence score does NOT predict profitability
- Edge is the ONLY filter that matters
- 73% of predictions have edge < 3 and lose money

**NEW Standard Filters (Edge-Based):**

| Filter Name | Definition | Performance | Use Case |
|-------------|------------|-------------|----------|
| **Medium Quality** | `edge >= 3` + exclude PASS | 65.0% hit rate, +24.0% ROI | **RECOMMENDED** - Best profit/volume |
| **High Quality** | `edge >= 5` + exclude PASS | 79.0% hit rate, +50.9% ROI | Best ROI, lower volume |

**CRITICAL**: Always add `AND recommendation IN ('OVER', 'UNDER')` to exclude PASS recommendations!

**OLD Filters (DEPRECATED - Don't Use):**
- ❌ "Premium (92+ conf, 3+ edge)" - Confidence doesn't help, small sample
- ❌ Any confidence-based filter - Model can be 95% confident in low-edge losing bets

**See**: `docs/08-projects/current/prediction-quality-analysis/SESSION-81-DEEP-DIVE.md`

---

## IMPORTANT: Standard Filters (PRE-SESSION 81 - DEPRECATED)

**⚠️ WARNING: These filters are OUTDATED. Use edge-based filters above instead.**

| Filter Name | Definition | Use Case |
|-------------|------------|----------|
| **Premium Picks** | `confidence >= 0.92 AND edge >= 3` | DEPRECATED - confidence doesn't predict profitability |
| **High Edge Picks** | `edge >= 5` (any confidence) | Still valid but should exclude PASS |

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

### Data Quality Filters (Session 99)

| Filter | Definition | Purpose |
|--------|------------|---------|
| **Complete Data** | `matchup_data_status = 'COMPLETE'` | Only predictions with full matchup data |
| **Exclude Degraded** | `matchup_data_status != 'MATCHUP_UNAVAILABLE'` | Exclude defaulted matchup factors |
| **High Quality** | `feature_quality_score >= 85` | Above threshold quality score |

**Why filter by data quality?**
- Predictions with `MATCHUP_UNAVAILABLE` used neutral defaults (0.0) for matchup-specific factors
- These predictions may be less accurate since shot_zone_mismatch and pace_score are missing
- Use these filters to analyze whether data quality affects hit rate

**Example: Compare hit rate by data quality:**
```sql
SELECT
  COALESCE(matchup_data_status, 'LEGACY') as data_status,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND system_id = 'catboost_v9'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY data_status
ORDER BY predictions DESC;
```

## Standard Queries

| Query # | Name | Purpose |
|---------|------|---------|
| 0 | **Daily Model Comparison** | Compare all models day-by-day (quick check) |
| 1 | Best Performing Picks | Compare standard filters (run first) |
| 2 | Weekly Trend | Detect drift over time |
| 3 | Confidence x Edge Matrix | Full breakdown |
| 4 | Model Beats Vegas | Compare to Vegas accuracy |
| 5 | **Find Best Filter** | Optimize filter for current conditions |
| 6 | Player Tier Analysis | Performance by player scoring tier |
| 7 | **Signal Context** | Correlate with RED/GREEN pre-game signals |

### Query 0: Daily Model Comparison (Quick Check)

**Use this to quickly see how all models performed each day.**

```sql
-- Daily comparison of all CatBoost models
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  COUNTIF(ABS(predicted_points - line_value) >= 5) as high_edge,
  ROUND(100.0 * COUNTIF(
    ABS(predicted_points - line_value) >= 5 AND prediction_correct
  ) / NULLIF(COUNTIF(
    ABS(predicted_points - line_value) >= 5 AND prediction_correct IS NOT NULL
  ), 0), 1) as high_edge_hr,
  ROUND(100.0 * COUNTIF(prediction_correct) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as overall_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND system_id LIKE 'catboost%'
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id
```

**Interpretation**:
- Compare `catboost_v9` vs `catboost_v9_2026_02` on the same days
- Look for patterns where one model outperforms the other
- Note: New monthly models only have data from their deployment date forward

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
- `catboost_v9` is the original V9 model (trained Nov 2 - Jan 8)
- `catboost_v9_2026_02` is the February 2026 monthly retrain (trained Nov 2 - Jan 24)
- `catboost_v9_2026_XX` are monthly retrained models (added each month)
- `catboost_v8` is the historical model (legacy, has data leakage issues)
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

### Query 6B: Model Bias by Tier (Session 101 - NEW)

**Purpose**: Detect regression-to-mean bias that causes systematic under/over-prediction.

**Why this matters**: Session 101 discovered that V9 was under-predicting stars by -9 points and over-predicting bench by +6 points. This caused 78% UNDER recommendations and 0/7 high-edge pick failures. Detecting this early prevents prolonged losses.

**When to use**:
- After RED signal detected (heavy UNDER skew)
- After high-edge picks lose consistently
- Weekly as part of model health check

```sql
-- Model Bias by Scoring Tier (Session 101)
-- Expected: Bias < ±3 for all tiers
SELECT
  system_id,
  CASE
    WHEN actual_points >= 25 THEN '1_Stars (25+)'
    WHEN actual_points >= 15 THEN '2_Starters (15-24)'
    WHEN actual_points >= 5 THEN '3_Role (5-14)'
    ELSE '4_Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points - actual_points), 1) as bias,
  CASE
    WHEN ABS(AVG(predicted_points - actual_points)) > 5 THEN '🔴 CRITICAL'
    WHEN ABS(AVG(predicted_points - actual_points)) > 3 THEN '🟡 WARNING'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND actual_points IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')  -- Exclude PASS
GROUP BY 1, 2
ORDER BY 1, 2
```

**Interpretation**:

| Tier | Expected Bias | Session 101 Finding |
|------|---------------|---------------------|
| Stars (25+) | ~0 | **-9.3** (massive under-prediction) |
| Starters (15-24) | ~0 | **-2.8** (moderate under-prediction) |
| Role (5-14) | ~0 | +1.5 (slight over-prediction) |
| Bench (<5) | ~0 | **+5.6** (large over-prediction) |

**Root Cause**: Model learns to shrink predictions toward training mean (~13 pts), regardless of actual player scoring tier.

**If CRITICAL bias detected**:
1. Check `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`
2. Options: Recalibrate predictions by tier, retrain with tier features, or switch to quantile regression

### Query 7: Signal Context Analysis (Session 85)

**Purpose**: Correlate hit rates with pre-game signal (RED/GREEN days).

**Why this matters**: Session 70 discovered that RED signal days (heavy UNDER skew, pct_over < 25%) have historically 54% hit rate vs 82% on balanced GREEN days. This query validates and tracks that correlation.

```sql
-- Performance by pre-game signal type
SELECT
  dps.daily_signal,
  dps.skew_category,
  COUNT(*) as bets,
  COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate,
  -- High-edge subset
  COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5) as high_edge_bets,
  ROUND(100.0 * COUNTIF(
    ABS(pa.predicted_points - pa.line_value) >= 5 AND pa.prediction_correct
  ) / NULLIF(COUNTIF(
    ABS(pa.predicted_points - pa.line_value) >= 5 AND pa.prediction_correct IS NOT NULL
  ), 0), 1) as high_edge_hr
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.daily_prediction_signals dps
  ON pa.game_date = dps.game_date AND pa.system_id = dps.system_id
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= @start_date AND pa.game_date <= @end_date
  AND pa.prediction_correct IS NOT NULL
GROUP BY dps.daily_signal, dps.skew_category
ORDER BY
  CASE dps.daily_signal WHEN 'GREEN' THEN 1 WHEN 'YELLOW' THEN 2 WHEN 'RED' THEN 3 END
```

**Interpretation**:
- **GREEN days**: Expected ~82% high-edge hit rate (balanced predictions)
- **RED days**: Expected ~54% high-edge hit rate (heavy UNDER skew)
- Use this to validate the signal's predictive power over time

**Daily breakdown with signal**:
```sql
-- Daily performance with signal context
SELECT
  pa.game_date,
  dps.daily_signal,
  ROUND(dps.pct_over, 1) as pct_over,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate,
  COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5) as high_edge
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.daily_prediction_signals dps
  ON pa.game_date = dps.game_date AND pa.system_id = dps.system_id
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pa.prediction_correct IS NOT NULL
GROUP BY pa.game_date, dps.daily_signal, dps.pct_over
ORDER BY pa.game_date DESC
```

## Output Format

**Always present results in this format (grouped by model):**

```
## Hit Rate Analysis - ALL MODELS - [Date Range]

### Model Summary

| Model | Total Predictions | Active Date Range | Notes |
|-------|-------------------|-------------------|-------|
| catboost_v9 | XXX | Jan 9+ | Original V9 (trained Nov-Jan 8) |
| catboost_v9_2026_02 | XXX | Feb 1+ | Feb monthly (trained Nov-Jan 24) |
| catboost_v8 | XXX | Jan 18-28 | LEGACY (data leakage issues) |
| ensemble_v1_1 | XXX | Jan 20+ | Ensemble model |

### Best Performing Picks (by Model)

**catboost_v9** (Current Production Model):
| Filter | Hit Rate | Bets | Status |
|--------|----------|------|--------|
| Premium (92+ conf, 3+ edge) | XX.X% | XXX | ✅/❌ |
| High Edge (5+ pts) | XX.X% | XXX | ✅/❌ |
| All 3+ Edge | XX.X% | XXX | ✅/❌ |
| All Picks | XX.X% | XXX | ✅/❌ |

**catboost_v8** (Historical):
| Filter | Hit Rate | Bets | Status |
|--------|----------|------|--------|
| Premium (92+ conf, 3+ edge) | XX.X% | XXX | ✅/❌ |
| High Edge (5+ pts) | XX.X% | XXX | ✅/❌ |

**ensemble_v1_1**:
| Filter | Hit Rate | Bets | Status |
|--------|----------|------|--------|
| Premium (92+ conf, 3+ edge) | XX.X% | XXX | ✅/❌ |
| High Edge (5+ pts) | XX.X% | XXX | ✅/❌ |

### Weekly Trend (Grouped by Model)

Show side-by-side comparison of models over time to detect drift and compare performance.

### Key Findings
1. [Which model is performing best currently]
2. [Model comparison insights (V9 vs V8 vs ensemble)]
3. [Any drift detected in weekly trend]
4. [Confidence vs edge - which matters more for each model]

### Recommendations
1. [Which model to use for trading based on current performance]
2. [Optimal filter settings for the recommended model]
3. [When to switch between models based on conditions]
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

### Issue 4: Unknown Model Version (Session 84/87)
**Example**: "V9 has 75% hit rate" but which V9 model file?
**Cause**: Multiple model retrains exist, unclear which generated the predictions
**Solution**: Use model attribution fields (Session 84) to track:

```sql
-- Check which model version generated predictions
SELECT
  model_file_name,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY model_file_name
ORDER BY MIN(game_date);
```

**Note**: If `model_file_name` is NULL, predictions were generated before Session 84 deployment. Check deployment status: `./bin/whats-deployed.sh prediction-worker`

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
*Updated: Session 69 - Added daily model comparison, support for monthly models (catboost_v9_2026_XX)*
*Updated: Session 87 - Added Issue 4 for model version tracking via model_file_name field*
