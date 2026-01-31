# Session 43 Start Prompt

Copy and paste this to start a new chat:

---

Continue work on NBA stats scraper pipeline. Session 42 fixed a Phase 3 retry loop and built a league trend monitoring system.

Read the handoff document first:
```bash
cat docs/09-handoff/2026-01-30-SESSION-42-FINAL-HANDOFF.md
```

## Current State
- Pipeline: Healthy (retry loop fixed)
- Model: CRITICAL - 48% hit rate, needs retraining
- Trend Monitoring: Deployed to `nba_trend_monitoring` dataset
- Latest commit: 761a5e6a

## Key Findings from Session 42
The CatBoost v8 model drifted badly:
- Hit rate: 67% → 48% over 4 weeks
- OVER predictions: 68% → 40%
- 90%+ confidence: 77% → 43% (calibration collapsed)
- Root cause: Model using stale rolling averages, didn't adapt to mid-season scoring decline

## Priority Tasks for This Session

### Priority 1: Model Retraining (CRITICAL)
Create a challenger model (catboost_v9) rather than replacing v8:
1. Review experiments framework in `ml/experiments/`
2. Train new model with recent data
3. Add recency weighting to rolling averages
4. A/B test before deploying

### Priority 2: Deploy Extended Trend Views
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform --location=us-west2 < schemas/bigquery/monitoring/extended_trend_views.sql
```
This adds: starter_bench_trends, usage_rate_trends, underperforming_stars, player_streaks, etc.

### Priority 3: Dashboard UI for Trends
Create `templates/components/league_trends.html` and add to dashboard navigation.

### Priority 4: Clean Up Uncommitted Changes
```bash
git status  # Several files have uncommitted changes
```

## Quick Validation
```bash
# Check trend status
/trend-check

# Check model health
bq query --use_legacy_sql=false --project_id=nba-props-platform --location=us-west2 "
SELECT week_start, overall_hit_rate, conf_90_hit_rate, calibration_alert
FROM nba_trend_monitoring.model_health_trends
ORDER BY week_start DESC LIMIT 4"

# Daily validation
/validate-daily
```

## Key Files
- `docs/08-projects/current/league-trend-monitoring/` - Project docs
- `schemas/bigquery/monitoring/league_trend_views.sql` - Deployed views
- `schemas/bigquery/monitoring/extended_trend_views.sql` - Views to deploy
- `ml/experiments/` - Experiments framework for challenger models

---
