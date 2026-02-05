# Session 125B Handoff - Breakout Detection & Quality Filters

**Date:** 2026-02-05 (Evening)
**Duration:** ~3 hours
**Status:** Infrastructure complete, deployment needed, model training pending

---

## Quick Start for Next Session

```bash
# 1. Deploy the latest changes (3 new filters)
./bin/deploy-service.sh prediction-worker

# 2. Verify deployment
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Should show: 3e8f35ef

# 3. (Optional) Train breakout classifier
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_V1" \
    --train-start 2025-11-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-04

# 4. Check filter performance (after games complete)
bq query --use_legacy_sql=false "
SELECT filter_reason, COUNT(*) as filtered,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as would_have_hit
FROM nba_predictions.prediction_accuracy
WHERE is_actionable = false
  AND filter_reason IS NOT NULL
  AND game_date >= CURRENT_DATE() - 3
GROUP BY 1"
```

---

## What Was Done

### 1. Three New UNDER Filters Implemented

| Filter | Condition | Hit Rate Without Filter |
|--------|-----------|------------------------|
| `role_player_under_low_edge` | Role (8-16 PPG) + UNDER + edge < 5 | 42% |
| `hot_streak_under_risk` | L5 > season + 3 + UNDER | **14%** |
| `low_data_quality` | quality_score < 80 | 39% |

### 2. Quality Propagation to Grading
- `feature_quality_score` now flows to `prediction_accuracy` table
- New `data_quality_tier` field: 'HIGH', 'MEDIUM', 'LOW'
- Enables hit rate analysis by quality tier

### 3. Breakout Classifier Infrastructure
- Training script: `ml/experiments/train_breakout_classifier.py`
- 10 features including computed `explosion_ratio` and `days_since_breakout`
- CatBoost binary classifier with class weights
- Experiment skill updated with `--model-type breakout`

### 4. Monitoring Queries
- 6 comprehensive queries in `validation/queries/monitoring/breakout_filter_monitoring.sql`
- Daily filter performance, player profiles, opponent analysis

---

## Key Data Findings

### Role Player UNDER by Edge
```
Edge 3-5:  42.3% hit rate  ← FILTER THIS
Edge 5+:   55-67% hit rate ← KEEP
```

### Hot Streak Impact
```
L5 > season + 3:  14.3% hit rate  ← FILTER THIS
Normal:           49.2% hit rate
```

### High-Breakout Opponents
```
UTA: 38%, POR: 37%, MEM: 37%, LAL: 35%, DEN: 35%
```

---

## Files Changed

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | +3 filters (role player, hot streak, quality) |
| `data_processors/grading/.../prediction_accuracy_processor.py` | Quality propagation |
| `ml/experiments/train_breakout_classifier.py` | NEW - breakout model training |
| `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py` | NEW - breakout risk score |
| `tests/processors/precompute/.../test_breakout_risk_calculator.py` | NEW - 30 unit tests |
| `.claude/skills/model-experiment/SKILL.md` | Added breakout classifier docs |
| `validation/queries/monitoring/breakout_filter_monitoring.sql` | NEW - 6 queries |
| `docs/08-projects/current/breakout-detection-design/` | NEW - design docs |
| `docs/08-projects/current/breakout-risk-score/` | NEW - risk score design |

---

## Commits (Not Yet Deployed)

```
f59e4c37 - feat: Add quality filters and propagate quality to grading
95bcc254 - feat: Strengthen role player UNDER filter and add breakout monitoring
6e8f7079 - feat: Add hot streak UNDER filter and breakout classifier infrastructure
6189e0a5 - docs: Add Session 125B implementation docs and handoff
3e8f35ef - feat: Add breakout_risk_score calculator with tests and design docs
```

**IMPORTANT:** These commits need deployment. Run:
```bash
./bin/deploy-service.sh prediction-worker
```

---

## Priority Actions for Next Session

### P1: Deploy Changes
```bash
./bin/deploy-service.sh prediction-worker
```

### P2: Train Breakout Classifier (Optional)
```bash
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_V1" \
    --train-start 2025-11-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-04
```
Target: AUC >= 0.65, then integrate as filter or prediction adjustment.

### P3: Monitor Filter Performance
After 2-3 days, run monitoring queries to validate filters.

---

## Breakout Classifier Design

### Target
```python
is_breakout = 1 if actual_points >= season_avg * 1.5 else 0
```

### Features (10)
1. `pts_vs_season_zscore` - Hot streak indicator
2. `points_std_last_10` - Volatility
3. `explosion_ratio` - max(L5) / season_avg (computed)
4. `days_since_breakout` - Recency (computed)
5. `opponent_def_rating` - Defense weakness
6. `home_away` - Home court
7. `back_to_back` - Fatigue
8. `points_avg_last_5` - Recent form
9. `points_avg_season` - Baseline
10. `minutes_avg_last_10` - Playing time

### Integration Plan
1. **Shadow mode:** Log breakout predictions without affecting bets
2. **Signal enhancement:** Boost confidence or create breakout bets
3. **Full integration:** New `breakout_predictions` table

---

## Documentation Created

| Document | Location |
|----------|----------|
| Implementation Details | `docs/08-projects/current/breakout-detection-design/SESSION-125-IMPLEMENTATION.md` |
| Design Document | `docs/08-projects/current/breakout-detection-design/BREAKOUT-DETECTION-DESIGN.md` |
| Monitoring Queries | `validation/queries/monitoring/breakout_filter_monitoring.sql` |

---

## Opus Agent Findings

### Role Player Analysis
- Skip ALL role player UNDERs improves ROI by +5.3%
- L5 hot streak is strongest breakout predictor
- Simple edge-based filter more effective than complex model

### Breakout Classifier Design
- 10-feature model design complete
- Recommend shadow mode integration first
- Target AUC >= 0.65

---

## Known Issues

1. **breakout_flag is too rare** - Only triggers 0.4% (threshold too high)
2. **Need more games** for opponent pattern validation

---

*Session 125B - Breakout Detection & Quality Filters*
