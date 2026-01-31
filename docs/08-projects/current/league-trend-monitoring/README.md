# League Trend Monitoring System

**Created:** 2026-01-30
**Status:** In Progress
**Purpose:** Early warning system for model drift by tracking league-wide and cohort-level trends

## Problem Statement

The CatBoost v8 model experienced a significant performance decline (67% → 48% hit rate) from January 5-26, 2026. Post-mortem analysis revealed:

1. **League-wide scoring dropped** from ~14 to ~12 points per player
2. **OVER predictions failed badly** (68% → 40% hit rate)
3. **Model confidence calibration collapsed** (90%+ confidence went from 77% to 43% hit rate)
4. **High scorers underperformed** their lines more than low scorers

These trends were observable weeks before the hit rate crashed, but we had no systematic monitoring to detect them.

## Goals

1. **Early Warning**: Detect scoring environment changes before they impact model performance
2. **Cohort Analysis**: Track star players, starters, bench players separately
3. **Model Health**: Monitor confidence calibration, prediction bias, and recommendation balance
4. **Seasonal Patterns**: Understand recurring patterns (All-Star break, playoff push, etc.)
5. **Actionable Alerts**: Know when to trigger model retraining evaluation

## Architecture

### Data Flow

```
BigQuery Tables → Trend Views → Admin Dashboard → Alerts
     ↓                ↓              ↓
prediction_accuracy   Weekly         Chart.js
player_game_summary   aggregates     visualizations
ml_feature_store_v2   by cohort      HTMX updates
```

### Components

1. **BigQuery Views** (`schemas/bigquery/monitoring/league_trend_views.sql`)
   - `league_scoring_trends` - Weekly scoring environment metrics
   - `cohort_performance_trends` - Star/starter/bench breakdowns
   - `model_health_trends` - Confidence calibration, bias tracking
   - `recommendation_performance` - OVER/UNDER/PASS hit rates

2. **Admin Dashboard Blueprint** (`services/admin_dashboard/blueprints/league_trends.py`)
   - API endpoints for trend data
   - Time-range filtering (7/14/30/60/90 days)

3. **Dashboard UI** (`services/admin_dashboard/templates/components/league_trends.html`)
   - Interactive charts for all trend categories
   - Cohort comparison tables
   - Alert threshold indicators

4. **Validation Skill** (`.claude/skills/trend-check/`)
   - Quick CLI access to trend data
   - Identifies concerning patterns

## Trend Categories

### 1. Scoring Environment Trends

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `avg_points_per_player` | Weekly average | ±10% from 4-week baseline |
| `scoring_volatility` | Std dev of points | ±25% change |
| `high_scorer_avg` | Avg for 20+ line players | ±15% change |
| `low_scorer_avg` | Avg for <10 line players | ±15% change |
| `pct_overs_hitting` | % of overs that hit | <45% or >55% |

### 2. Player Cohort Trends

| Cohort | Definition | Tracked Metrics |
|--------|------------|-----------------|
| **Star Players** | line_value >= 20 | Avg points, hit rate, bias |
| **Starters** | starter_flag = TRUE or line >= 15 | Avg points, hit rate, bias |
| **Bench Players** | line_value < 10 | Avg points, hit rate, bias |
| **High Usage** | usage_rate > 25% | Performance vs prediction |
| **Rest Situations** | days_rest >= 3 | Scoring boost/decline |

### 3. Model Health Indicators

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `prediction_bias` | Avg(predicted - actual) | ±2 points |
| `over_recommendation_bias` | Bias for OVER picks | ±3 points |
| `confidence_90_hit_rate` | Hit rate when conf >= 90% | <60% |
| `confidence_calibration_error` | |conf - hit_rate| | >15% |
| `recommendation_balance` | % OVER vs UNDER | >60% either way |

### 4. Line Market Trends

| Metric | Description | Significance |
|--------|-------------|--------------|
| `line_mae` | How accurate are lines? | Lines getting sharper = harder edge |
| `line_vs_actual_bias` | Are lines biased high/low? | Market sentiment indicator |
| `model_vs_line_agreement` | How often model agrees with line | Divergence = potential edge or drift |

### 5. Seasonal Patterns

| Period | Expected Pattern |
|--------|------------------|
| Nov-Dec | Higher scoring (fresh legs) |
| Jan-Feb | Load management increases |
| Pre All-Star | Rest, lower intensity |
| Post All-Star | Playoff push begins |
| Mar-Apr | Intensity peaks, injuries increase |

## Implementation Plan

### Phase 1: BigQuery Views (Priority: HIGH)
- [ ] Create `league_scoring_trends` view
- [ ] Create `cohort_performance_trends` view
- [ ] Create `model_health_trends` view
- [ ] Create `recommendation_performance` view
- [ ] Add player classification logic (star/starter/bench)

### Phase 2: Admin Dashboard Integration
- [ ] Create `league_trends.py` blueprint
- [ ] Add `/api/league-trends/*` endpoints
- [ ] Create trend visualization components
- [ ] Add to dashboard navigation

### Phase 3: Alerting & Skills
- [ ] Define alert thresholds in config
- [ ] Create `/trend-check` skill
- [ ] Add trend checks to `/validate-daily`
- [ ] Slack alerts for threshold breaches

### Phase 4: Historical Analysis
- [ ] Backfill trend data for 2025-2026 season
- [ ] Identify seasonal patterns
- [ ] Document normal ranges by month

## Usage

### Admin Dashboard
Navigate to **League Trends** tab to see:
- Scoring environment charts
- Cohort comparison tables
- Model health gauges
- Alert status indicators

### CLI Skill
```bash
/trend-check              # Quick summary
/trend-check --detailed   # Full breakdown
/trend-check --cohort star  # Star player focus
```

### Validation Integration
The `/validate-daily` skill will include trend checks:
- Scoring environment within normal range
- Confidence calibration healthy
- No cohort showing extreme bias

## Files

| File | Purpose |
|------|---------|
| `schemas/bigquery/monitoring/league_trend_views.sql` | BigQuery view definitions |
| `services/admin_dashboard/blueprints/league_trends.py` | API endpoints |
| `services/admin_dashboard/templates/components/league_trends.html` | UI components |
| `.claude/skills/trend-check/SKILL.md` | CLI skill definition |
| `docs/08-projects/current/league-trend-monitoring/` | Project documentation |

## Success Criteria

1. Dashboard shows all trend categories with 7/14/30/60/90 day views
2. Alert thresholds fire when trends breach limits
3. `/trend-check` skill provides quick access to key metrics
4. Can detect the Jan 2026 performance decline 1-2 weeks earlier
5. Seasonal patterns documented for future reference

## Related

- [Model Drift Investigation (Session 42)](../../09-handoff/2026-01-30-SESSION-42-RETRY-FIX-COMPLETE-HANDOFF.md)
- [Admin Dashboard Documentation](../../07-admin-dashboard/README.md)
- [Feature Drift Detector](../../../../shared/validation/feature_drift_detector.py)
