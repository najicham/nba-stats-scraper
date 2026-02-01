# Session 57 Comprehensive Handoff

**Date:** 2026-01-31
**Focus:** Hit Rate Measurement Standardization, Model Drift Investigation, Evaluation Infrastructure
**Status:** Investigation complete, improvements identified, ready for implementation

---

## Start Here

### Quick Context
- **Model V8 is drifting**: Week 1 hit 76-84%, Week 4 collapsed to 46-49%
- **Root cause**: MODEL_DRIFT (not Vegas sharpening) - model MAE degraded from 5.8 to 8.4
- **Key finding**: Must use consistent filters when measuring hit rates
- **Immediate need**: Update evaluation infrastructure to match production

### Key Documents
1. **This handoff** - Full context for continuation
2. **Session 56 handoff** - `docs/09-handoff/2026-01-31-SESSION-56-HANDOFF.md`
3. **TODO list** - `docs/08-projects/current/session-56-ml-infrastructure/TODO-LIST.md`
4. **Hit rate skill** - `.claude/skills/hit-rate-analysis/SKILL.md` (updated this session)

---

## Critical Findings This Session

### 1. Model Drift Confirmed

| Week | Premium (92+, 3+) | High Edge (5+) | Model MAE | Vegas MAE |
|------|-------------------|----------------|-----------|-----------|
| Week 1 (Jan 1-7) | **84.5%** | **76.6%** | 5.80 | 7.02 |
| Week 2 (Jan 8-14) | 78.6% | 55.6% | 7.88 | 4.93 |
| Week 3 (Jan 15-21) | 70.6% | 54.7% | 9.54 | 6.35 |
| Week 4 (Jan 22-28) | **46.2%** | **49.3%** | 8.44 | 5.56 |

**Vegas MAE stayed stable (4.9-7.0), Model MAE degraded (5.8 → 8.4-9.5)**

### 2. Hit Rate Measurement Confusion Resolved

**Problem**: Different analyses showed different numbers (78% vs 50% vs 40%)

**Cause**: Three different metrics were being confused:

| Metric | What It Measures | January Value |
|--------|------------------|---------------|
| **Hit Rate (Premium filter)** | 92+ conf, 3+ edge correct calls | 78.7% |
| **Hit Rate (all picks)** | All correct calls | 57.4% |
| **Model Beats Vegas** | Model closer to actual than Vegas | 40-45% |

**Solution**: Always report BOTH standard filters:
- **Premium Picks**: `confidence >= 0.92 AND edge >= 3`
- **High Edge Picks**: `edge >= 5` (any confidence)

### 3. Evaluation Script Gap

**Problem**: `evaluate_model.py --production-equivalent` shows 50.24% hit rate, but production shows 78.7% for premium picks.

**Cause**: Evaluation script includes ALL predictions, but production only grades 92+ confidence predictions.

**Fix Needed**: Add confidence filtering to match production.

---

## What Was Completed This Session

### 1. Automated Daily Diagnostics (P0 - DONE)
- Added `check_model_performance()` to data-quality-alerts Cloud Function
- Uses `PerformanceDiagnostics` for root cause attribution
- Persists to `nba_orchestration.performance_diagnostics_daily`
- **Deployed** to Cloud Function (but shared module import issue - needs fix)

### 2. Missing Dates Investigation (P0 - DONE)
- Jan 8: All predictions had `line_source = 'NO_PROP_LINE'` (Vegas lines not fetched)
- Other dates: Working correctly, just fewer predictions with valid lines
- Backfill timing issue: Jan 8 predictions made on Jan 12 (4 days late)

### 3. Hit Rate Skill Updated
- Added two standard filters (Premium, High Edge)
- Clarified Hit Rate vs Model Beats Vegas difference
- Added weekly trend detection
- Updated CLAUDE.md with measurement guidance

### 4. Documentation Updated
- `CLAUDE.md` - Added "Hit Rate Measurement (IMPORTANT)" section
- `.claude/skills/hit-rate-analysis/SKILL.md` - Complete rewrite

---

## TODO List (Prioritized)

### P0 - Immediate (Do First)

| Task | Effort | Notes |
|------|--------|-------|
| **Fix evaluate_model.py to match production** | 30 min | Add 92+ confidence filter, report standard filters |
| **Add "find best filter" to hit-rate-analysis** | 15 min | Rank all filter combinations by hit rate |
| **Fix Cloud Function shared module** | 30 min | Copy performance_diagnostics.py properly or inline |

### P1 - High Priority

| Task | Effort | Notes |
|------|--------|-------|
| **Create `/model-experiment` skill** | 1 session | Easy challenger model testing |
| **Test trajectory features** | 1 session | Add pts_slope_10g, zscore to see if it helps |
| **Monthly retraining pipeline** | 2-3 sessions | CRITICAL - model is stale and drifting |
| **Vegas sharpness dashboard** | 2-3 sessions | Schema deployed, need processor + UI |

### P2 - Later

| Task | Effort | Notes |
|------|--------|-------|
| Prediction versioning/history | 2-3 sessions | Track when predictions change |
| Backfill feature store lines | 1 session | Fix historical averaged lines |
| A/B shadow mode pipeline | 3-4 sessions | Test new models in production |

---

## Key Commands

### Check Current Performance
```bash
# Full hit rate analysis with standard filters
bq query --use_legacy_sql=false "
SELECT
  'Premium (92+ conf, 3+ edge)' as filter,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND confidence_score >= 0.92
  AND ABS(predicted_points - line_value) >= 3
  AND prediction_correct IS NOT NULL
UNION ALL
SELECT 'High Edge (5+ pts)', COUNT(*), ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1)
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ABS(predicted_points - line_value) >= 5
  AND prediction_correct IS NOT NULL
ORDER BY 1"
```

### Run Model Evaluation
```bash
# Production-equivalent evaluation
PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path models/catboost_v8_33features_20260108_211817.cbm \
    --eval-start 2026-01-01 \
    --eval-end 2026-01-28 \
    --experiment-id V8_JAN \
    --production-equivalent
```

### Check Diagnostics
```bash
# View recent diagnostics
bq query --use_legacy_sql=false "
SELECT game_date, alert_level, primary_cause, hit_rate_7d, model_beats_vegas_pct
FROM nba_orchestration.performance_diagnostics_daily
ORDER BY game_date DESC LIMIT 5"
```

---

## Files Changed This Session

| File | Change |
|------|--------|
| `orchestration/cloud_functions/data_quality_alerts/main.py` | Added model_performance check |
| `orchestration/cloud_functions/data_quality_alerts/deploy.sh` | Added shared module copy |
| `shared/utils/performance_diagnostics.py` | Fixed TABLE_ID and to_dict() |
| `.claude/skills/hit-rate-analysis/SKILL.md` | Rewrote with standard filters |
| `CLAUDE.md` | Added hit rate measurement section |
| `docs/09-handoff/2026-01-31-SESSION-57-HANDOFF.md` | Initial handoff |

---

## Implementation Plan for Next Session

### Step 1: Fix evaluate_model.py (30 min)

Update `ml/experiments/evaluate_model.py` to:
1. Add `--confidence-threshold` parameter (default 0.92)
2. Filter predictions to only those meeting confidence threshold
3. Report results for both standard filters (Premium, High Edge)
4. Add weekly breakdown option

```python
# Add to evaluation output
"by_standard_filter": {
    "premium_92_edge3": {"hit_rate": X, "bets": Y},
    "high_edge_5": {"hit_rate": X, "bets": Y}
}
```

### Step 2: Add "Find Best Filter" Query (15 min)

Add to hit-rate-analysis skill:
```sql
-- Test all filter combinations and rank by hit rate
WITH filter_results AS (
  SELECT
    conf_threshold,
    edge_threshold,
    COUNT(*) as bets,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
  FROM (
    SELECT *,
      CASE WHEN confidence_score >= 0.95 THEN 95
           WHEN confidence_score >= 0.92 THEN 92
           WHEN confidence_score >= 0.90 THEN 90
           ELSE 87 END as conf_threshold,
      CASE WHEN ABS(predicted_points - line_value) >= 5 THEN 5
           WHEN ABS(predicted_points - line_value) >= 3 THEN 3
           ELSE 1 END as edge_threshold
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v8' AND game_date >= @start_date
  )
  GROUP BY 1, 2
  HAVING bets >= 20
)
SELECT * FROM filter_results ORDER BY hit_rate DESC
```

### Step 3: Create /model-experiment Skill (1 session)

Skill that makes it easy to:
- Train a new model with specified date range
- Evaluate with production-equivalent mode
- Compare to current V8 baseline
- Store results in ml_experiments table

### Step 4: Test Trajectory Features (1 session)

Add to feature list:
- `pts_slope_10g` - 10-game scoring trend
- `pts_zscore_season` - Points z-score vs season average
- `breakout_flag` - Recent breakout indicator

Train model with 37 features, compare to 33-feature V8.

---

## Model Status Summary

| Model | Features | Training Period | Current Status |
|-------|----------|-----------------|----------------|
| **catboost_v8** | 33 | Historical (2021-2025) | PRODUCTION (drifting) |
| catboost_v9 | 36 | Historical | Not deployed |
| catboost_v10 | 33 | Jan 2026 only | Tested, not deployed |

**Recommendation**: Train new model on Dec 2025 - Jan 2026 data with 37 features.

---

## Questions for Next Session

1. Should we add trajectory features (pts_slope, zscore) to next model?
2. What training window is optimal? (60 days? 90 days? Full season?)
3. Should we deploy a quick retrain or wait for proper monthly pipeline?

---

## Commits This Session

```
45244ea9 docs: Standardize hit rate measurement with two filters
2f5d3781 feat: Automate daily performance diagnostics in data-quality-alerts
```

---

*Session 57 Complete*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
