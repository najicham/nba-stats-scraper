# Model Drift Investigation Findings

**Date:** 2026-01-30
**Session:** 42
**Investigator:** Claude Opus 4.5

## Executive Summary

CatBoost v8 model experienced a significant performance decline from 67% → 48% hit rate between December 2025 and January 2026. This investigation identified the root causes and early warning signals that were missed.

## Performance Timeline

| Week | Hit Rate | Key Observation |
|------|----------|-----------------|
| Dec 29 | 66.5% | Baseline - model performing well |
| Jan 5 | 61.1% | First decline signal |
| Jan 12 | 49.7% | **Major drop** - calibration collapsed |
| Jan 19 | 58.1% | Partial recovery |
| Jan 26 | 48.3% | Continued poor performance |

## Root Causes Identified

### 1. OVER Prediction Failure

OVER recommendations experienced catastrophic decline:

| Week | OVER Hit Rate | UNDER Hit Rate |
|------|---------------|----------------|
| Dec 29 | 68.5% | 64.0% |
| Jan 5 | 57.1% | 64.3% |
| Jan 12 | 46.5% | 53.5% |
| Jan 26 | **40.2%** | 53.5% |

**Finding:** OVER hit rate dropped 28 percentage points while UNDER remained relatively stable.

### 2. Systematic Over-Prediction Bias

For OVER recommendations, the model's prediction bias grew dramatically:

| Week | Avg Bias (pred - actual) |
|------|--------------------------|
| Dec 22 | -0.08 pts (nearly perfect) |
| Dec 29 | +0.87 pts |
| Jan 5 | +2.42 pts |
| Jan 12 | +2.97 pts |
| Jan 19 | +3.66 pts |
| Jan 26 | **+4.98 pts** |

**Finding:** Model was predicting 5 points too high for OVER picks by late January.

### 3. Confidence Calibration Collapse

High-confidence predictions became unreliable:

| Week | 90%+ Conf Hit Rate | Expected |
|------|--------------------| ---------|
| Dec 22 | 76.9% | ~90% |
| Jan 5 | 70.8% | ~90% |
| Jan 12 | 57.7% | ~90% |
| Jan 26 | **43.2%** | ~90% |

**Finding:** 90%+ confidence predictions went from 77% to 43% - worse than coin flips.

### 4. Star Player Underperformance

Players with lines ≥20 points (stars) showed worst decline:

| Week | Star Hit Rate | Star vs Line |
|------|---------------|--------------|
| Dec 22 | 67.5% | -0.19 pts |
| Jan 5 | 60.9% | **-4.06 pts** |
| Jan 12 | 61.8% | -2.26 pts |
| Jan 26 | **36.6%** | -1.29 pts |

**Finding:** Star players were consistently scoring below their lines, likely due to load management or mid-season fatigue.

### 5. Prediction-Actual Correlation Degraded

| Week | Pred-Actual Corr | Line-Actual Corr |
|------|------------------|------------------|
| Dec 22 | 0.779 | 0.608 |
| Jan 5 | 0.717 | 0.715 |
| Jan 12 | **0.544** | 0.660 |
| Jan 26 | 0.565 | 0.704 |

**Finding:** Model correlation dropped 30% while sportsbook lines improved. The market adapted better than our model.

### 6. League-Wide Scoring Decline

| Week | Avg Points | Overs Hitting |
|------|------------|---------------|
| Dec 15 | 14.22 | 54.5% |
| Jan 5 | 12.55 | 43.9% |
| Jan 26 | 12.26 | 43.9% |

**Finding:** League-wide scoring dropped ~15% (14.2 → 12.3 pts), but model didn't adapt.

## Early Warning Signals (Missed)

These signals appeared 2-3 weeks before the hit rate crashed:

1. **Week of Jan 5:** Star players -4.06 vs line (WARNING)
2. **Week of Jan 5:** Overs hitting at 43.9% (WARNING)
3. **Week of Jan 12:** Confidence calibration 57.7% (CRITICAL)
4. **Week of Jan 12:** Prediction-actual correlation 0.544 (CRITICAL)
5. **Week of Jan 12:** OVER bias +2.97 points (WARNING)

## Why The Model Drifted

### Primary Cause: Stale Rolling Averages

The model uses rolling averages (L5, L10) that captured high-scoring December games. When scoring dropped in January:
- Rolling averages remained elevated
- Model predicted high (based on December scoring)
- Actuals came in lower
- OVER predictions failed systematically

### Contributing Factors

1. **Mid-season fatigue** - Players scoring less as season progresses
2. **Load management** - Stars resting more (increased DNP games)
3. **Market adaptation** - Sportsbooks adjusted lines, model didn't
4. **No recency weighting** - Old games weighted same as recent games

## Recommendations

### Immediate Actions

1. **Retrain model** with recent data (use challenger model approach)
2. **Add recency bias** to rolling average calculations
3. **Monitor confidence calibration** weekly

### Trend Monitoring (Implemented)

The following views were created in `nba_trend_monitoring` dataset:
- `league_scoring_trends` - Detects scoring environment shifts
- `cohort_performance_trends` - Tracks star/starter/bench separately
- `model_health_trends` - Monitors calibration and bias
- `daily_trend_summary` - Quick daily health checks

### Future Model Improvements

1. **Dynamic recency weighting** - Weight recent games more heavily
2. **Seasonal adjustment factors** - Account for mid-season patterns
3. **Market correlation tracking** - Alert when lines beat model
4. **Star player fatigue model** - Specific handling for high-usage players

## Data Queries Used

All queries used `nba_predictions.prediction_accuracy` table with `system_id = 'catboost_v8'`.

Key analysis dimensions:
- Weekly aggregation (`DATE_TRUNC(game_date, WEEK(MONDAY))`)
- Cohort classification (`line_value >= 20` = star, etc.)
- Recommendation type (`OVER`, `UNDER`, `PASS`)
- Confidence buckets (90+, 85-90, 80-85)

## Files Created

| File | Purpose |
|------|---------|
| `schemas/bigquery/monitoring/league_trend_views.sql` | Core trend views |
| `schemas/bigquery/monitoring/extended_trend_views.sql` | Additional analysis views |
| `services/admin_dashboard/blueprints/league_trends.py` | Dashboard API |
| `.claude/skills/trend-check/SKILL.md` | CLI skill |
| `docs/08-projects/current/league-trend-monitoring/` | Project docs |

## Conclusion

The model drift was predictable and detectable 2-3 weeks in advance using the trend monitoring system now in place. The key insight is that **confidence calibration** is the most reliable early warning indicator - when 90%+ confidence predictions drop below 70%, the model needs evaluation regardless of overall hit rate.
