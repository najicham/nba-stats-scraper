# Trend Categories Reference

Complete list of all tracked trends and their use cases.

## Core Trend Views

### 1. League Scoring Trends (`league_scoring_trends`)
**Purpose:** Detect league-wide scoring environment changes

| Metric | Description | Why It Matters |
|--------|-------------|----------------|
| `avg_points` | Weekly average points per player | Scoring environment shift |
| `scoring_volatility` | Standard deviation of points | Predictability indicator |
| `line_mae` | How accurate are sportsbook lines | Market efficiency |
| `line_bias` | Are lines systematically high/low | Market sentiment |
| `pct_overs_hitting` | % of overs that hit | Market balance |
| `zero_point_pct` | DNP/injury rate | Load management indicator |

**Alerts:**
- Scoring ±10% from 4-week baseline → WARNING
- Scoring ±15% from baseline → CRITICAL
- Overs <45% or >55% → WARNING
- Overs <40% or >60% → CRITICAL

---

### 2. Cohort Performance Trends (`cohort_performance_trends`)
**Purpose:** Compare star, starter, rotation, and bench players

| Cohort | Definition | Key Metrics |
|--------|------------|-------------|
| **Star** | line_value >= 20 | High-value players, most prediction impact |
| **Starter** | line_value 12-20 | Regular rotation players |
| **Rotation** | line_value 7-12 | Bench contributors |
| **Bench** | line_value < 7 | Limited minutes players |

**Tracked per cohort:**
- Hit rate overall, OVER, UNDER
- Prediction bias
- Vs line performance
- Recommendation balance

**Use Case:** If star players are underperforming predictions but bench players are fine, suggests model is overweighting historical data for high-usage players.

---

### 3. Model Health Trends (`model_health_trends`)
**Purpose:** Monitor prediction quality and confidence calibration

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `overall_hit_rate` | Weekly accuracy | Track trend |
| `overall_bias` | Avg(pred - actual) | ±2 pts WARNING, ±3 pts CRITICAL |
| `over_bias` / `under_bias` | Bias by recommendation | Identify systematic errors |
| `conf_90_hit_rate` | 90%+ confidence accuracy | <70% WARNING, <60% CRITICAL |
| `conf_85_90_hit_rate` | 85-90% confidence accuracy | Calibration check |
| `mae` | Mean absolute error | Prediction quality |

**Key Insight:** If `conf_90_hit_rate` drops significantly below 90%, confidence calibration has failed.

---

### 4. Daily Trend Summary (`daily_trend_summary`)
**Purpose:** Quick daily health check

- Daily hit rate, bias, confidence
- OVER vs UNDER performance
- DNP count tracking

---

### 5. Trend Alerts Summary (`trend_alerts_summary`)
**Purpose:** Aggregated alert status

Shows all active alerts from all trend categories with severity and description.

---

## Extended Trend Views

### 6. Star Player Trends (`star_player_trends`)
**Purpose:** Track individual star player performance

| Metric | Description |
|--------|-------------|
| `avg_actual` vs `avg_predicted` | Per-player bias |
| `vs_line` | Performance vs sportsbook line |
| `times_over` / `times_under` | Streak tracking |
| `dnp_games` | Injury/rest frequency |

**Use Case:** Identify which star players are consistently over/under-predicted.

---

### 7. Rest Impact Trends (`rest_impact_trends`)
**Purpose:** How rest affects performance

| Rest Category | Definition |
|---------------|------------|
| `back_to_back` | 0 days rest |
| `one_day_rest` | 1 day rest |
| `two_days_rest` | 2 days rest |
| `extended_rest` | 3+ days rest |

**Expected Pattern:** Extended rest should correlate with higher scoring.

---

### 8. Starter vs Bench Trends (`starter_bench_trends`)
**Purpose:** Direct comparison of starters vs bench players

Uses `starter_flag` from `player_game_summary` when available, otherwise infers from line value.

| Role | Inference | Key Question |
|------|-----------|--------------|
| Starter | starter_flag OR line >= 12 | Are starters underperforming more? |
| Bench | !starter_flag AND line < 12 | Is bench predictability different? |

---

### 9. Usage Rate Trends (`usage_rate_trends`)
**Purpose:** How ball-dominant vs low-usage players perform

| Tier | Usage Rate | Typical Players |
|------|------------|-----------------|
| High | >= 28% | Primary scorers |
| Medium | 20-28% | Secondary options |
| Low | 12-20% | Role players |
| Minimal | < 12% | Limited touches |

**Hypothesis:** High-usage players may have more variance in scoring.

---

### 10. Home vs Away Trends (`home_away_trends`)
**Purpose:** Home court advantage impact

Track if predictions are systematically biased for home or away games.

---

### 11. Underperforming Stars (`underperforming_stars`)
**Purpose:** Flag star players consistently missing predictions

| Metric | Description |
|--------|-------------|
| `avg_over_prediction` | How much model overestimates |
| `recent_bias` vs `older_bias` | Is bias getting worse? |
| `dnp_games` | Injury/rest frequency |

**Use Case:** Identify load management or injury-related prediction failures.

---

### 12. Player Streaks (`player_streaks`)
**Purpose:** Identify hot/cold players

| Status | Definition |
|--------|------------|
| `HOT_STREAK` | >= 75% overs in last 14 days |
| `COLD_STREAK` | <= 25% overs in last 14 days |
| `OUTPERFORMING` | Avg +3 pts vs line |
| `UNDERPERFORMING` | Avg -3 pts vs line |

**Use Case:** Consider recent form when validating predictions.

---

### 13. Trend Change Detection (`trend_changes`)
**Purpose:** Highlight significant week-over-week changes

Flags changes as SIGNIFICANT, NOTABLE, or NORMAL for:
- Points change (>=1.5 pts = significant)
- Hit rate change (>=10% = significant)
- Bias change (>=2 pts = significant)

---

### 14. Monthly Baselines (`monthly_baselines`)
**Purpose:** Establish seasonal expectations

| Month | Expected Pattern |
|-------|------------------|
| Nov-Dec | Higher scoring (fresh legs) |
| Jan-Feb | Load management increases |
| Mar-Apr | Playoff push, intensity peaks |

**Use Case:** Compare current trends to historical monthly norms.

---

## Trend Correlation Matrix

| If This Changes... | Check These... |
|--------------------|----------------|
| League avg points drops | Star player bias, OVER hit rate |
| OVER hit rate drops | Star/starter cohorts, bias |
| Confidence calibration fails | All cohorts, recommendation balance |
| Star players underperform | Usage rate trends, rest patterns |
| High bias on OVERs | Scoring environment, star tracker |

---

## Alert Priority

1. **CRITICAL** - Requires immediate attention, likely model retraining
2. **WARNING** - Monitor closely, may need intervention soon
3. **OK** - Within normal ranges

---

## Dashboard Integration

All views power the Admin Dashboard's **League Trends** tab:

1. **Scoring Environment** - Line charts showing weekly trends
2. **Cohort Comparison** - Side-by-side tables
3. **Model Health** - Confidence calibration gauges
4. **Alert Status** - Real-time alert feed
5. **Star Player Tracker** - Individual player breakdown

---

## CLI Access

```bash
/trend-check              # Quick summary with alerts
/trend-check detailed     # Full breakdown
/trend-check cohorts      # Cohort comparison
/trend-check stars        # Star player focus
```

---

## Future Enhancements

1. **Position-based trends** - PG/SG/SF/PF/C breakdowns
2. **Team context trends** - Pace, defensive efficiency impact
3. **Injury correlation** - Teammates out = more/less scoring?
4. **Referee trends** - Some refs favor higher/lower totals
5. **Betting line movement** - Track line movement patterns
6. **Weather/travel** - Back-to-back road games, altitude, etc.
