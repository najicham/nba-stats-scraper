---
name: hit-rate-analysis
description: Analyze prediction hit rates with consistent groupings by confidence, edge, tier, and time
---

# Hit Rate Analysis Skill

Provides consistent, standardized hit rate analysis across confidence levels, edge thresholds, player tiers, and time periods.

## Quick Reference

### Key Concepts

| Metric | Definition | How Calculated | Good Value |
|--------|------------|----------------|------------|
| **Confidence** | Model's certainty in prediction | `confidence_score` from prediction table (0-1) | ≥0.90 |
| **Edge** | Disagreement with Vegas | `ABS(predicted_points - line_value)` | ≥3 pts |
| **Hit Rate** | % of correct over/under calls | `prediction_correct = TRUE` / total | ≥52.4% (breakeven) |
| **Tier** | Player scoring category | Based on season avg points | Star/Starter/Rotation/Bench |

### Tier Definitions

| Tier | Points Avg | Description |
|------|------------|-------------|
| Star | ≥22 ppg | High-usage scorers |
| Starter | 14-22 ppg | Regular starters |
| Rotation | 6-14 ppg | Rotation players |
| Bench | <6 ppg | Limited minutes |

## Usage

When the user asks for hit rate analysis, use the following standardized queries.

### Basic Hit Rate by Confidence and Edge

```sql
-- Standard hit rate breakdown
SELECT
  -- Confidence bucket
  CASE
    WHEN confidence_score >= 0.90 THEN '90+'
    WHEN confidence_score >= 0.85 THEN '85-89'
    WHEN confidence_score >= 0.80 THEN '80-84'
    WHEN confidence_score >= 0.75 THEN '75-79'
    ELSE '<75'
  END as confidence,

  -- Edge bucket
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN '5+'
    WHEN ABS(predicted_points - line_value) >= 3 THEN '3-5'
    WHEN ABS(predicted_points - line_value) >= 2 THEN '2-3'
    WHEN ABS(predicted_points - line_value) >= 1 THEN '1-2'
    ELSE '<1'
  END as edge,

  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae

FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND line_value IS NOT NULL
GROUP BY 1, 2
HAVING bets >= 10
ORDER BY
  CASE confidence WHEN '90+' THEN 1 WHEN '85-89' THEN 2 WHEN '80-84' THEN 3 WHEN '75-79' THEN 4 ELSE 5 END,
  CASE edge WHEN '5+' THEN 1 WHEN '3-5' THEN 2 WHEN '2-3' THEN 3 WHEN '1-2' THEN 4 ELSE 5 END
```

### Hit Rate by Player Tier

```sql
WITH player_tiers AS (
  SELECT
    player_lookup,
    CASE
      WHEN AVG(points) >= 22 THEN 'Star'
      WHEN AVG(points) >= 14 THEN 'Starter'
      WHEN AVG(points) >= 6 THEN 'Rotation'
      ELSE 'Bench'
    END as tier
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND minutes_played > 10
  GROUP BY 1
)
SELECT
  pt.tier,
  CASE
    WHEN confidence_score >= 0.90 THEN '90+'
    WHEN confidence_score >= 0.85 THEN '85-89'
    ELSE '<85'
  END as confidence,
  CASE
    WHEN ABS(pa.predicted_points - pa.line_value) >= 3 THEN '3+'
    ELSE '<3'
  END as edge,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate

FROM nba_predictions.prediction_accuracy pa
LEFT JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
WHERE pa.system_id = 'catboost_v8'
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND pa.line_value IS NOT NULL
GROUP BY 1, 2, 3
HAVING bets >= 10
ORDER BY
  CASE tier WHEN 'Star' THEN 1 WHEN 'Starter' THEN 2 WHEN 'Rotation' THEN 3 ELSE 4 END,
  confidence, edge
```

### Hit Rate Over Time (Weekly Trend)

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,

  -- Overall
  COUNT(*) as total_bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as overall_hit,

  -- High confidence (90+) with 3+ edge
  COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 3) as hc_bets,
  ROUND(100.0 * COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
        NULLIF(COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 3), 0), 1) as hc_hit,

  -- MAE
  ROUND(AVG(absolute_error), 2) as mae

FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC
```

### Hit Rate by Month

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,

  -- By confidence level
  ROUND(100.0 * COUNTIF(confidence_score >= 0.90 AND prediction_correct) /
        NULLIF(COUNTIF(confidence_score >= 0.90), 0), 1) as hit_90plus,
  COUNTIF(confidence_score >= 0.90) as bets_90plus,

  ROUND(100.0 * COUNTIF(confidence_score >= 0.85 AND confidence_score < 0.90 AND prediction_correct) /
        NULLIF(COUNTIF(confidence_score >= 0.85 AND confidence_score < 0.90), 0), 1) as hit_85_89,
  COUNTIF(confidence_score >= 0.85 AND confidence_score < 0.90) as bets_85_89,

  -- Overall
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as overall_hit

FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2025-10-01'
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1
```

### Compare Systems

```sql
SELECT
  system_id,
  COUNT(*) as predictions,

  -- High confidence picks
  COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 3) as hc_bets,
  ROUND(100.0 * COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
        NULLIF(COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 3), 0), 1) as hc_hit_rate,

  -- Overall
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as overall_hit,
  ROUND(AVG(absolute_error), 2) as mae

FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND line_value IS NOT NULL
GROUP BY 1
HAVING predictions >= 50
ORDER BY hc_hit_rate DESC NULLS LAST
```

## Interactive Mode

When user invokes `/hit-rate` or asks about hit rate, ask clarifying questions:

```
Question 1: "What time period?"
Options:
  - "Last 7 days"
  - "Last 30 days" (Recommended)
  - "Last 3 months"
  - "Specific date range"

Question 2: "What groupings?"
Options:
  - "Confidence + Edge (Recommended)" - Standard breakdown
  - "Player Tier" - Star/Starter/Rotation/Bench
  - "Weekly Trend" - Performance over time
  - "All groupings" - Comprehensive analysis

Question 3: "Which system?"
Options:
  - "catboost_v8 (Production)" (Recommended)
  - "All systems" - Compare all
  - "Specific system" - Custom
```

## Output Format

Always present results in this consistent format:

```
## Hit Rate Analysis - [System] - [Date Range]

### Summary
- **Best Filter**: [confidence] + [edge] = [hit_rate]% ([bets] bets)
- **Breakeven**: 52.4% (need this to profit with -110 odds)
- **Status**: [PROFITABLE/UNPROFITABLE]

### By Confidence and Edge

| Confidence | Edge | Hit Rate | Bets | Status |
|------------|------|----------|------|--------|
| 90+ | 5+ | XX.X% | XXX | ✅/❌ |
| 90+ | 3-5 | XX.X% | XXX | ✅/❌ |
| ... | ... | ... | ... | ... |

### By Player Tier (3+ Edge)

| Tier | 90+ Conf | 85-89 Conf | <85 Conf |
|------|----------|------------|----------|
| Star | XX.X% (XX) | XX.X% (XX) | XX.X% (XX) |
| Starter | XX.X% (XX) | XX.X% (XX) | XX.X% (XX) |
| Rotation | XX.X% (XX) | XX.X% (XX) | XX.X% (XX) |
| Bench | XX.X% (XX) | XX.X% (XX) | XX.X% (XX) |

### Weekly Trend

| Week | Overall | High-Conf (90+, 3+) | MAE |
|------|---------|---------------------|-----|
| 2026-01-27 | XX.X% | XX.X% (XX bets) | X.XX |
| ... | ... | ... | ... |

### Recommendations
1. [Specific actionable recommendation based on data]
2. [Filter recommendation if applicable]
```

## Key Thresholds

| Metric | Excellent | Good | Warning | Critical |
|--------|-----------|------|---------|----------|
| Hit Rate | ≥65% | 55-65% | 52.4-55% | <52.4% |
| High-Conf Hit | ≥75% | 65-75% | 55-65% | <55% |
| Sample Size | ≥200 | 100-200 | 50-100 | <50 |

## Common Patterns

### Pattern 1: High Confidence Works, Low Doesn't
```
90+ conf, 3+ edge: 77% ✅
85-89 conf, 3+ edge: 49% ❌
```
**Interpretation**: Model confidence is well-calibrated. Only trade high confidence.

### Pattern 2: Edge Matters More Than Confidence
```
Any conf, 5+ edge: 65% ✅
90+ conf, <2 edge: 52% ❌
```
**Interpretation**: Model needs to disagree with Vegas to add value.

### Pattern 3: Tier-Specific Performance
```
Star tier: 55%
Rotation tier: 63%
```
**Interpretation**: Model better at role players. Consider tier-based filtering.

### Pattern 4: Performance Degradation Over Time
```
Week 1: 65%
Week 2: 58%
Week 3: 51%
```
**Interpretation**: Model drift detected. Consider retraining.

## Related Skills and Tools

- `/validate-daily` - Check overall pipeline health
- `bin/monitoring/model_drift_detection.py` - Comprehensive drift analysis
- `bin/monitoring/vegas_sharpness_monitor.py` - Vegas line accuracy tracking

## Table Reference

| Table | Key Columns |
|-------|-------------|
| `nba_predictions.prediction_accuracy` | player_lookup, game_date, system_id, predicted_points, line_value, actual_points, prediction_correct, confidence_score, absolute_error |
| `nba_analytics.player_game_summary` | player_lookup, game_date, points, minutes_played |

---

*Skill created: Session 55*
