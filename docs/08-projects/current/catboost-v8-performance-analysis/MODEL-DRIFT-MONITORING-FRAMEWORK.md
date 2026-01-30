# Model Drift Monitoring Framework

**Purpose:** Detect model degradation early and trigger retraining before significant profit loss.

---

## Monitoring Tiers

### Tier 1: Daily Health Checks (Automated)

Run automatically after daily grading completes.

```sql
-- Daily performance snapshot
SELECT
  game_date,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date = CURRENT_DATE() - 1
GROUP BY 1;
```

**Thresholds:**
| Metric | Warning | Critical |
|--------|---------|----------|
| Hit Rate | < 55% | < 50% |
| MAE | > 6.0 | > 7.0 |
| Bias | > |3.0| | > |5.0| |

### Tier 2: Weekly Trend Analysis (Scheduled)

Run every Monday for the previous week.

```sql
-- Weekly rolling metrics with trend
WITH weekly_metrics AS (
  SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    COUNT(*) as predictions,
    ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
    ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
    ROUND(AVG(predicted_points - actual_points), 2) as bias
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v8'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  GROUP BY 1
)
SELECT
  week,
  predictions,
  hit_rate,
  LAG(hit_rate) OVER (ORDER BY week) as prev_week_hit_rate,
  hit_rate - LAG(hit_rate) OVER (ORDER BY week) as hit_rate_change,
  mae,
  bias
FROM weekly_metrics
ORDER BY week DESC;
```

**Alert Conditions:**
- Hit rate dropped > 5% week-over-week
- Hit rate < 60% for 2 consecutive weeks
- MAE increased > 1.0 point from baseline

### Tier 3: Player Tier Analysis (Weekly)

Detects if specific player segments are failing.

```sql
-- Performance by player scoring tier
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  CASE
    WHEN actual_points >= 25 THEN '1_stars_25+'
    WHEN actual_points >= 15 THEN '2_starters_15-25'
    WHEN actual_points >= 5 THEN '3_rotation_5-15'
    ELSE '4_bench_<5'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

**Alert Conditions:**
- Star player hit rate < 65%
- Tier hit rate divergence > 20% (e.g., stars at 55%, bench at 75%)
- Any tier bias > |5| points

### Tier 4: Model vs Vegas Comparison (Weekly)

Tracks if our edge over Vegas is eroding.

```sql
-- Our MAE vs Vegas MAE
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as our_edge
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

**Alert Conditions:**
- Our edge is negative (Vegas is more accurate) for 2+ weeks
- Edge degraded by > 1.0 point from 4-week baseline

---

## Retraining Triggers

### Automatic Retraining Criteria

Trigger retraining when ANY of these conditions persist for 2+ weeks:

| Condition | Threshold | Priority |
|-----------|-----------|----------|
| Overall hit rate | < 55% | P0 |
| Star tier hit rate | < 60% | P0 |
| Star tier bias | > |6| points | P1 |
| MAE vs baseline | > +1.5 points | P1 |
| Edge vs Vegas | < -1.0 points | P2 |

### Manual Review Triggers

Flag for human review when:
- Sudden performance drop (> 10% in one week)
- New player emergence (rookie breakout)
- Trade deadline activity
- Injury to major star

---

## Dashboard Metrics

### Primary Dashboard (Daily)

| Metric | Source | Update Frequency |
|--------|--------|------------------|
| Yesterday's Hit Rate | prediction_accuracy | Daily |
| 7-Day Rolling Hit Rate | prediction_accuracy | Daily |
| 7-Day Rolling MAE | prediction_accuracy | Daily |
| High-Confidence Hit Rate | prediction_accuracy | Daily |

### Secondary Dashboard (Weekly)

| Metric | Source | Update Frequency |
|--------|--------|------------------|
| Hit Rate by Player Tier | prediction_accuracy | Weekly |
| Hit Rate by OVER/UNDER | prediction_accuracy | Weekly |
| Prediction Bias by Tier | prediction_accuracy | Weekly |
| Our Edge vs Vegas | prediction_accuracy | Weekly |

### Trend Dashboard (Monthly)

| Metric | Source | Update Frequency |
|--------|--------|------------------|
| Monthly Hit Rate Trend | prediction_accuracy | Monthly |
| Model Age (days since training) | model metadata | Daily |
| Feature Drift Score | feature_store | Weekly |

---

## Implementation Checklist

### Phase 1: Core Monitoring (Week 1)

- [ ] Add Tier 1 queries to daily validation skill
- [ ] Create BigQuery scheduled query for weekly metrics
- [ ] Set up Slack alerts for critical thresholds
- [ ] Add hit rate to daily orchestration completion message

### Phase 2: Advanced Monitoring (Week 2)

- [ ] Create Looker/DataStudio dashboard
- [ ] Add player tier breakdown to weekly report
- [ ] Implement Vegas comparison tracking
- [ ] Add trend detection (week-over-week changes)

### Phase 3: Automated Response (Week 3-4)

- [ ] Build automated retraining pipeline
- [ ] Add retraining trigger logic
- [ ] Create model versioning system
- [ ] Implement A/B testing for new models

---

## Alert Escalation

| Level | Condition | Action | Owner |
|-------|-----------|--------|-------|
| Info | Hit rate < 60% (1 day) | Log only | Automated |
| Warning | Hit rate < 55% (3 days) | Slack alert | On-call |
| Critical | Hit rate < 50% (1 week) | Investigate immediately | Team |
| Emergency | Hit rate < 45% (any period) | Pause predictions | Team lead |

---

## Historical Baseline Reference

Based on 2024-25 season performance:

| Metric | Baseline | Good | Concerning | Critical |
|--------|----------|------|------------|----------|
| Hit Rate | 70-74% | 65-70% | 55-65% | < 55% |
| MAE | 4.0-4.5 | 4.5-5.5 | 5.5-6.5 | > 6.5 |
| Bias | ±1.0 | ±2.0 | ±3.0 | > ±5.0 |
| High-Conf HR | 80-85% | 75-80% | 65-75% | < 65% |

---

*Framework created 2026-01-30*
*Ready for implementation*
