# Trend Check Skill

Check league trends and model health for early warning of model drift.

## Usage

```
/trend-check              # Quick summary with alerts
/trend-check detailed     # Full breakdown by category
/trend-check cohorts      # Player cohort comparison
/trend-check stars        # Star player performance
```

## Instructions

When the user invokes `/trend-check`, run the appropriate trend analysis based on the argument.

### Default (No Arguments) - Quick Summary

Run this query to get the current trend status:

```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform "
WITH latest_scoring AS (
  SELECT * FROM (
    SELECT
      week_start,
      avg_points,
      pct_overs_hitting,
      scoring_alert
    FROM \`nba_trend_monitoring.league_scoring_trends\`
    ORDER BY week_start DESC
    LIMIT 2
  )
),
latest_health AS (
  SELECT * FROM (
    SELECT
      week_start,
      overall_hit_rate,
      overall_bias,
      conf_90_hit_rate,
      over_hit_rate,
      under_hit_rate,
      calibration_alert,
      bias_alert
    FROM \`nba_trend_monitoring.model_health_trends\`
    ORDER BY week_start DESC
    LIMIT 2
  )
),
alerts AS (
  SELECT category, severity, description
  FROM \`nba_trend_monitoring.trend_alerts_summary\`
)
SELECT 'SCORING' as section, * FROM latest_scoring
UNION ALL
SELECT 'HEALTH' as section, * FROM latest_health
UNION ALL
SELECT 'ALERTS' as section, * FROM alerts
"
```

Then summarize the results in a clear format showing:
1. Current vs previous week scoring environment
2. Model health indicators
3. Active alerts (CRITICAL first, then WARNING)
4. Overall status recommendation

### `detailed` Argument - Full Breakdown

Query each view for the last 4 weeks:

```bash
# Scoring trends
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT
  week_start,
  avg_points,
  scoring_volatility,
  pct_overs_hitting,
  zero_point_pct,
  scoring_alert
FROM \`nba_trend_monitoring.league_scoring_trends\`
WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
ORDER BY week_start DESC"

# Model health
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT
  week_start,
  overall_hit_rate,
  overall_bias,
  conf_90_hit_rate,
  over_hit_rate,
  under_hit_rate,
  mae,
  calibration_alert,
  bias_alert
FROM \`nba_trend_monitoring.model_health_trends\`
WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
ORDER BY week_start DESC"
```

Present as tables showing week-over-week changes.

### `cohorts` Argument - Player Cohort Comparison

```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT
  week_start,
  player_cohort,
  predictions,
  hit_rate,
  prediction_bias,
  over_hit_rate,
  under_hit_rate
FROM \`nba_trend_monitoring.cohort_performance_trends\`
WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
ORDER BY week_start DESC, player_cohort"
```

Show side-by-side comparison of star/starter/rotation/bench performance.

### `stars` Argument - Star Player Performance

```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT
  player_lookup,
  SUM(games) as total_games,
  ROUND(AVG(avg_actual), 1) as avg_actual,
  ROUND(AVG(avg_predicted), 1) as avg_predicted,
  ROUND(AVG(prediction_bias), 2) as avg_bias,
  ROUND(AVG(hit_rate), 1) as avg_hit_rate,
  SUM(dnp_games) as total_dnp
FROM \`nba_trend_monitoring.star_player_trends\`
WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY player_lookup
HAVING SUM(games) >= 4
ORDER BY avg_bias DESC
LIMIT 20"
```

Show which star players are being over/under-predicted.

## Alert Thresholds

When presenting results, highlight these thresholds:

| Metric | WARNING | CRITICAL |
|--------|---------|----------|
| Scoring change | ±10% from baseline | ±15% from baseline |
| Overs hitting | <45% or >55% | <40% or >60% |
| Prediction bias | ±2 points | ±3 points |
| 90%+ conf hit rate | <70% | <60% |
| OVER vs UNDER gap | >20% difference | >30% difference |

### ⚠️ Session 101 Update: Tier-Specific Bias

**CRITICAL**: The overall bias threshold (±3 pts) may miss tier-specific issues!

Session 101 discovered model had:
- **Stars (25+ pts)**: -9.3 bias (massive under-prediction)
- **Bench (<5 pts)**: +5.6 bias (over-prediction)
- **Overall**: ~0 bias (cancels out!)

**New Tier Thresholds**:

| Tier | WARNING | CRITICAL |
|------|---------|----------|
| Star (25+) | < -3 bias | < -5 bias |
| Bench (<5) | > +3 bias | > +5 bias |

**If cohort analysis shows bias > ±5 for any tier**: Check `/model-health` and see `MODEL-BIAS-INVESTIGATION.md`.

## Output Format

Use tables for data presentation:

```
## Trend Status: [OK/WARNING/CRITICAL]

### Scoring Environment
| Week | Avg Points | Overs Hitting | Alert |
|------|------------|---------------|-------|
| Jan 26 | 12.3 | 48.5% | WARNING |
| Jan 19 | 13.1 | 52.1% | OK |

### Model Health
| Week | Hit Rate | Bias | 90%+ Conf | Alert |
|------|----------|------|-----------|-------|
| Jan 26 | 48.3% | +2.1 | 43.2% | CRITICAL |
| Jan 19 | 58.1% | +0.9 | 58.0% | WARNING |

### Active Alerts
- CRITICAL: Confidence calibration - 90%+ conf hitting at 43.2%
- WARNING: Scoring environment - Avg 12.3 pts (baseline 13.5)

### Recommendations
1. Consider model retraining - confidence calibration has collapsed
2. Monitor star player load management patterns
```

## Related

- Admin Dashboard: League Trends tab shows interactive charts
- `/validate-daily` includes trend checks in comprehensive mode
- BigQuery views: `nba_trend_monitoring.league_scoring_trends`, etc.
