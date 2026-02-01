# Session 69 Handoff - Monthly Retraining Infrastructure

**Date:** February 1, 2026
**Session:** 69
**Focus:** Model management strategy, monthly retraining infrastructure, multi-model deployment
**Status:** COMPLETE

---

## Executive Summary

This session established a comprehensive monthly model retraining infrastructure:

1. **Cloud Scheduler:** Auto-retrain on 1st of each month at 6 AM ET
2. **Multi-Model Architecture:** Run multiple CatBoost versions in parallel
3. **February Model Deployed:** `catboost_v9_2026_02` running alongside `catboost_v9`
4. **Pre-Game Signal Validated:** pct_over correlates with high-edge hit rate (p=0.0065)

---

## Part 1: Monthly Retraining Strategy

### Infrastructure Created

| Component | Status | Location |
|-----------|--------|----------|
| Cloud Scheduler | ✅ Active | `monthly-retrain-job` |
| Cloud Function | ✅ Deployed | `monthly-retrain-f7p3g7f6ya-wl.a.run.app` |
| Quick Retrain Script | ✅ Enhanced | `ml/experiments/quick_retrain.py` |
| Multi-Model System | ✅ Deployed | `predictions/worker/prediction_systems/catboost_monthly.py` |

### Training Window Strategy

**Decision:** Use expanding window from season start (Nov 2)

| Month | Training Window | Rationale |
|-------|-----------------|-----------|
| Feb | Nov 2 → Jan 24 | Full season so far |
| Mar | Nov 2 → Feb 28 | Expanding window |
| Apr | Nov 2 → Mar 31 | More data = better |

### Window Experiments Results

| Window | MAE | High-Edge HR | Winner? |
|--------|-----|--------------|---------|
| 30-day | 4.97 | 45.5% | ❌ Poor HR |
| 45-day | 5.04 | 62.5% | - |
| 60-day | 5.01 | 61.1% | - |
| 90-day | 5.08 | **68.8%** | ✅ Best HR |
| Full season | 5.08 | **68.8%** | ✅ Best HR |

**Conclusion:** Longer windows = better hit rate. Stick with full season.

---

## Part 2: February Model Deployment

### Model Details

| Property | Value |
|----------|-------|
| System ID | `catboost_v9_2026_02` |
| Training | Nov 2, 2025 → Jan 24, 2026 |
| Samples | 12,477 |
| MAE | 5.08 |
| High-Edge HR | 68.75% (on Jan 25-31) |

### Apples-to-Apples Comparison (Jan 25-31)

| Model | High-Edge Picks | Hit Rate |
|-------|-----------------|----------|
| catboost_v9 | 28 | 65.4% |
| catboost_v9_2026_02 | 16 | **68.75%** |

The February model slightly outperforms on the same evaluation period.

### Deployment Status

```
Revision: prediction-worker-00058-jfz
Commit: 288f07b2
Status: ✅ Deployed and serving
```

Both models now run in parallel and make predictions with separate system_ids.

---

## Part 3: Script Enhancements

### New Arguments Added to quick_retrain.py

| Argument | Purpose | Example |
|----------|---------|---------|
| `--half-life` | Recency weighting | `--half-life 60` |
| `--depth` | Tree depth | `--depth 8` |
| `--learning-rate` | Learning rate | `--learning-rate 0.03` |
| `--l2-reg` | L2 regularization | `--l2-reg 5.0` |
| `--feature-set` | Feature subset | `--feature-set core` |

### Feature Sets Available

| Set | Features | Use Case |
|-----|----------|----------|
| `all` | 33 | Default |
| `no_vegas` | 29 | Test without Vegas lines |
| `core` | 15 | Reduce overfitting |
| `stats_only` | 13 | Pure player stats |

---

## Part 4: Pre-Game Signal Validation

### Session 70 Finding Validated

The `pct_over` signal (% of predictions recommending OVER) correlates with performance:

| pct_over | Days | Picks | Hit Rate |
|----------|------|-------|----------|
| <25% (Under-heavy) | 7 | 26 | **53.8%** |
| >=25% (Balanced) | 15 | 61 | **82.0%** |

**Statistical Test:**
- Z-statistic: 2.72
- P-value: **0.0065** (significant at p < 0.01)

**Implication:** When V9 heavily favors UNDER (<25% pct_over), reduce confidence in high-edge picks.

---

## Part 5: Documentation Created

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/ml-monthly-retraining/README.md` | Overview |
| `docs/08-projects/current/ml-monthly-retraining/STRATEGY.md` | Full strategy |
| `docs/08-projects/current/ml-monthly-retraining/QUICK-START.md` | How to add new models |
| `docs/08-projects/current/ml-monthly-retraining/MONTHLY-MODEL-ARCHITECTURE.md` | Technical details |
| `docs/08-projects/current/pre-game-signals-strategy/README.md` | pct_over signal |

---

## Part 6: Commits Made

| Commit | Description |
|--------|-------------|
| `3585f8d7` | feat: Add monthly model retraining infrastructure |
| `129d6fce` | docs: Update hit-rate-analysis skill for monthly models |

---

## Part 7: Models in Production

| Model | System ID | Training | Status |
|-------|-----------|----------|--------|
| V9 Original | `catboost_v9` | Nov 2 → Jan 8 | ✅ Running |
| V9 Feb 2026 | `catboost_v9_2026_02` | Nov 2 → Jan 24 | ✅ Running |

The new model will start making predictions on Feb 2 games (today's predictions were generated before deployment).

---

## Part 8: Next Steps

### Immediate (Tomorrow)

1. Verify both models making predictions:
   ```sql
   SELECT system_id, COUNT(*) 
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-02-02' AND system_id LIKE 'catboost%'
   GROUP BY 1
   ```

2. Check pct_over for Feb 1 predictions (was flagged as UNDER_HEAVY in Session 70)

### This Week

1. Monitor side-by-side performance of v9 vs v9_2026_02
2. Consider adding pct_over warning to /top-picks skill

### March 1

1. Cloud Scheduler will auto-trigger monthly retrain
2. Review results, add to MONTHLY_MODELS, deploy

---

## Key Learnings

1. **Data Leakage Risk:** Initial Feb retrain had overlapping train/eval dates (caught and fixed)
2. **Window Size Matters:** Full season training gives best high-edge hit rate (68.8% vs 45.5% for 30-day)
3. **pct_over Signal:** Under-heavy days (<25%) have 28-point lower hit rate (statistically significant)
4. **Multi-Model Works:** Architecture supports running multiple CatBoost versions in parallel

---

## Files Changed

### Created
- `docs/08-projects/current/ml-monthly-retraining/` (7 files)
- `docs/08-projects/current/pre-game-signals-strategy/README.md`
- `predictions/worker/prediction_systems/catboost_monthly.py`
- `verify_monthly_models.py`
- `models/catboost_v9_2026_02.cbm`

### Modified
- `predictions/worker/worker.py` (multi-model support)
- `.claude/skills/hit-rate-analysis/SKILL.md` (monthly model support)

---

## Validation Commands

### Check Models Running
```bash
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-01' AND system_id LIKE 'catboost%'
GROUP BY 1"
```

### Check pct_over Signal
```bash
bq query --use_legacy_sql=false "
SELECT game_date,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1 DESC"
```

### Compare Model Performance
```bash
bq query --use_legacy_sql=false "
SELECT system_id, game_date,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-01' AND system_id LIKE 'catboost%'
GROUP BY 1, 2 ORDER BY 2, 1"
```

---

**Session Complete**
**Duration:** ~3 hours
**Next Session:** Monitor multi-model performance, consider pct_over skill integration

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
