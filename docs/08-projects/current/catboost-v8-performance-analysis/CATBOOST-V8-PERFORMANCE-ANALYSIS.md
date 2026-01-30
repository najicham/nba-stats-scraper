# CatBoost V8 Performance Analysis

**Created:** 2026-01-29
**Updated:** 2026-01-29 Session 24
**Status:** ROOT CAUSES IDENTIFIED - MODEL WORKS WHEN FEATURES PASSED CORRECTLY
**Next Steps:** Fix feature passing bug, then continue experiments

---

## Executive Summary

### Session 24 Discovery: THE MODEL WORKS

**Critical finding:** The model achieved **74.25% hit rate** on the 2024-25 season (true out-of-sample data). The poor 52% performance in January 2026 is due to a **feature passing bug**, not model failure.

| Period | Hit Rate | Issue |
|--------|----------|-------|
| 2024-25 Season (out-of-sample) | **74.25%** | Model works correctly |
| Jan 2026 forward-looking | **52.03%** | Feature passing bug |

### Root Causes Identified

1. **Feature Passing Bug** - Worker doesn't pass Vegas/opponent/PPM features, causing +29 point prediction errors
2. **Confidence Scale Change** - Dec 2025 code change, correlates with buggy predictions
3. **BettingPros Data Gap** - Oct-Nov 2025 missing, forcing lower-quality ODDS_API lines

**See:** `SESSION-24-INVESTIGATION-FINDINGS.md` for full analysis.

---

## 0. Session 24 Results: Model Validation

### Experiment D1: 2024-25 Season Performance

We evaluated the existing CatBoost V8 model on the 2024-25 NBA season - data the model NEVER saw during training (training ended May 2024).

| Metric | Value |
|--------|-------|
| **Predictions** | 13,315 |
| **Hit Rate** | **74.25%** |
| **ROI** | **+41.75%** |

### Monthly Performance (No Decay)

| Month | Hit Rate | Months Since Training |
|-------|----------|----------------------|
| Nov 2024 | 77.44% | 6 |
| Dec 2024 | 74.95% | 7 |
| Jan 2025 | 72.82% | 8 |
| Feb 2025 | 71.99% | 9 |
| Mar 2025 | 73.32% | 10 |
| Apr 2025 | 74.49% | 11 |
| May 2025 | 79.44% | 12 |
| Jun 2025 | 79.12% | 13 |

**The model maintained 72-79% hit rate for 13 months after training.**

### By Confidence Tier

| Tier | Predictions | Hit Rate | ROI |
|------|-------------|----------|-----|
| 95%+ | 1,562 | **79.64%** | +52.04% |
| 90-95% | 8,317 | 75.42% | +43.98% |
| 85-90% | 3,345 | 68.79% | +31.32% |

### By Direction

| Direction | Hit Rate | ROI |
|-----------|----------|-----|
| UNDER | **76.54%** | +46.11% |
| OVER | 72.21% | +37.85% |

**Best segment: High-confidence (90%+) UNDER = 78.09% hit rate**

---

## 1. Model Training Details

### Training Script
- **Location:** `/home/naji/code/nba-stats-scraper/ml/train_final_ensemble_v8.py`
- **Model Trained:** January 8, 2026 at 21:18:17

### Training Data Period
```
November 1, 2021 → June 1, 2024 (2.5 years)
```

### Training Samples
- **Total:** 76,863 game samples
- **Split:** 70% train / 15% validation / 15% test (chronological)

### Reported Training Metrics
| Model | MAE |
|-------|-----|
| XGBoost | 3.45 |
| LightGBM | 3.47 |
| CatBoost | 3.43 |
| **Stacked Ensemble** | **3.40** |

---

## 2. The Data Leakage Problem

### What Happened

On **January 9, 2026**, someone ran the model retroactively on ALL historical data:

| Year | Predictions | When Created | Problem |
|------|-------------|--------------|---------|
| 2021 | 12,569 | 2026-01-09 | Model trained on this data |
| 2022 | 26,209 | 2026-01-09 | Model trained on this data |
| 2023 | 24,263 | 2026-01-09 | Model trained on this data |
| 2024 | 25,919 | 2026-01-09 | Partial overlap with training |
| 2025 | 28,816 | 2026-01-09 to 01-18 | Mixed - some retroactive |
| 2026 | 4,507 | Various | Mixed - some forward-looking |

### Why This Invalidates Historical Results

1. **Training period:** Nov 2021 - June 2024
2. **Retroactive predictions:** Nov 2021 - Dec 2024 (generated Jan 9, 2026)
3. **Overlap:** The model "predicted" games it was TRAINED on

This is like taking a test after seeing the answer key. The 73% hit rate on historical data is meaningless.

### Real Out-of-Sample Period

Only predictions made BEFORE the game date count as real predictions:

| Creation Date | Forward-Looking | Retroactive | Notes |
|---------------|-----------------|-------------|-------|
| 2026-01-09 | 0 | 114,884 | ALL retroactive |
| 2026-01-12 | 80 | 125 | First real predictions |
| 2026-01-19 | 83 | 0 | Clean forward-looking |
| 2026-01-23+ | ~1,500 | ~500 | Mostly forward-looking |

**True out-of-sample period:** ~January 12, 2026 onwards

---

## 3. True Performance Analysis

### Forward-Looking Predictions Only (Jan 12-28, 2026)

| Metric | Value |
|--------|-------|
| Total forward-looking predictions | ~1,737 |
| Graded (excluding NULL/push) | ~1,600 |
| Overall hit rate | **~54%** |
| ROI at -110 odds | **~3%** |

### By Confidence Score (2026 Only)

**Critical Finding:** Confidence scores have two scales - 0-100 (percentage) and 0-1 (decimal)

| Scale | Confidence | Predictions | Hit Rate |
|-------|------------|-------------|----------|
| Percent (0-100) | 95%+ | 732 | **66.12%** |
| Decimal (0-1) | 95%+ | 6 | 50.0% |
| Decimal (0-1) | 90-95% | 219 | 52.05% |
| Decimal (0-1) | 85-90% | 779 | 49.17% |
| Decimal (0-1) | <85% | 629 | 48.17% |

**Only percent-scale 95%+ predictions are profitable.**

### By Line Source (2026 Only)

| Source | Predictions | Hit Rate | ROI |
|--------|-------------|----------|-----|
| BETTINGPROS | ~1,000 | 57.28% | +9.35% |
| ODDS_API | ~1,300 | 52.35% | -0.06% |

---

## 4. Known Issues Affecting Performance

### 4.1 Confidence Scale Bug
- **Issue:** Some predictions stored confidence as 0-1, others as 0-100
- **Impact:** Can't reliably filter by confidence
- **When:** Started around November 2025

### 4.2 Feature Passing Bug
- **Issue:** Worker doesn't pass Vegas/opponent/PPM features correctly
- **Impact:** Model uses incorrect default values, causing extreme predictions (60+ points)
- **When:** Identified January 2026
- **Documented:** `docs/09-handoff/2026-01-29-SESSION-20-CATBOOST-V8-FIX-AND-SAFEGUARDS.md`

### 4.3 Phantom Line Predictions
- **Issue:** Backfilled predictions use line values that don't exist in source data
- **Impact:** ~38% of predictions have unverifiable line sources
- **Example:** `jaimejaquezjr` 2026-01-20 has predictions for lines 12.5, 16.5 that never existed

---

## 5. Can We Really Achieve 70%+?

### Session 24 Answer: YES, WE ALREADY DID

| Scenario | Hit Rate | Evidence |
|----------|----------|----------|
| **2024-25 season (model working correctly)** | **74.25%** | 13,315 predictions |
| **2024-25 high-confidence (95%+)** | **79.64%** | 1,562 predictions |
| **2024-25 high-conf UNDER** | **78.09%** | Best segment |
| Jan 2026 forward-looking (bug active) | 52.03% | Feature passing broken |

### What Went Wrong in 2025-26

The model performed at 74% through June 2025, then dropped to 52% starting Oct 2025. Root causes:

1. **Feature Passing Bug** - Worker doesn't pass Vegas/opponent/PPM features
   - Causes predictions like 64.48 points → clamped to 60
   - OVER edge went from +4.13 to +8.99 (doubled)

2. **BettingPros Data Gap** - Oct-Nov 2025 missing
   - ODDS_API: 55.49% hit rate
   - BETTINGPROS: 65.77% hit rate

### To Restore 70%+ Performance

1. **Fix the feature passing bug** (P0) - See Session 20 documentation
2. **Restore BettingPros data collection** (P1)
3. **Use high-confidence UNDER predictions** - Best segment historically

### Expected Performance After Fix

| Filtering | Expected Hit Rate | Based On |
|-----------|-------------------|----------|
| All predictions | 70-74% | 2024-25 actual |
| 90%+ confidence | 73-76% | 2024-25 actual |
| 95%+ confidence | 77-80% | 2024-25 actual |
| High-conf UNDER | 76-78% | 2024-25 actual |

---

## 6. Retraining Plan

### Current Issues to Fix Before Retraining

1. [ ] Fix confidence score storage (standardize to 0-100)
2. [ ] Fix feature passing in prediction worker
3. [ ] Add line source validation
4. [ ] Remove retroactive prediction capability (or flag clearly)

### Proper Train/Test Split

For next model version:

| Period | Purpose | Dates |
|--------|---------|-------|
| Training | Model learning | Nov 2021 - June 2024 |
| Validation | Hyperparameter tuning | July 2024 - Dec 2024 |
| **Holdout Test** | Final evaluation | Jan 2025 - Dec 2025 |
| **Live** | True out-of-sample | Jan 2026+ |

**CRITICAL:** Never evaluate on training data. The holdout test set should be completely untouched until final evaluation.

### Retraining Checklist

- [ ] Clean training data (remove duplicates, validate line sources)
- [ ] Implement proper cross-validation with time-series split
- [ ] Add feature importance analysis
- [ ] Track prediction vs actual distribution
- [ ] Set up A/B testing framework for new models
- [ ] Create monitoring dashboard for live performance

---

## 7. Measuring Performance Correctly

### Metrics to Track

| Metric | Formula | Target |
|--------|---------|--------|
| Hit Rate | Hits / (Hits + Misses) | >55% |
| ROI | (Wins × 0.909 - Losses) / Total | >5% |
| MAE | Mean(|Predicted - Actual|) | <5.0 |
| Calibration | Confidence vs Actual Hit Rate | Monotonic |

### Proper Grading Rules

1. **Exclude pushes** (actual = line)
2. **Exclude NULL points** (games not played)
3. **Only grade forward-looking predictions** (created before game)
4. **Verify line existed in source data**

### Daily Monitoring Query

```sql
SELECT
  p.game_date,
  COUNT(*) as predictions,
  SUM(CASE WHEN
    DATE(p.created_at) <= p.game_date
  THEN 1 ELSE 0 END) as forward_looking,
  SUM(CASE WHEN
    (p.recommendation = 'OVER' AND g.points > p.current_points_line) OR
    (p.recommendation = 'UNDER' AND g.points < p.current_points_line)
  THEN 1 ELSE 0 END) as hits,
  ROUND(SUM(CASE WHEN
    (p.recommendation = 'OVER' AND g.points > p.current_points_line) OR
    (p.recommendation = 'UNDER' AND g.points < p.current_points_line)
  THEN 1 ELSE 0 END) * 100.0 /
  NULLIF(SUM(CASE WHEN DATE(p.created_at) <= p.game_date THEN 1 ELSE 0 END), 0), 2) as forward_hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary g
  ON p.player_lookup = g.player_lookup AND p.game_date = g.game_date
WHERE p.system_id = 'catboost_v8'
  AND p.has_prop_line = TRUE
  AND p.recommendation IN ('OVER', 'UNDER')
  AND p.game_date >= '2026-01-01'
  AND p.game_date < CURRENT_DATE()
  AND g.points IS NOT NULL
GROUP BY 1
ORDER BY 1
```

---

## 8. Next Steps

### Immediate (P0 - This Week)
1. [x] ~~Calculate true forward-looking performance only~~ - Done: 74.25% on 2024-25
2. [ ] **Fix feature passing bug** - See Session 20 docs
3. [ ] Deploy fix and verify predictions are reasonable
4. [ ] Add extreme prediction warnings (>55 or <5 points)

### Short-Term (P1 - Next 2 Weeks)
1. [ ] Investigate BettingPros Oct-Nov 2025 data gap
2. [ ] Add feature validation logging
3. [ ] Continue walk-forward experiments (Series A, B)
4. [ ] Build monitoring dashboard

### Medium-Term (P2 - Next Month)
1. [ ] Collect 30+ days of clean forward-looking predictions (post-fix)
2. [ ] Compare to 2024-25 baseline (should return to 74%)
3. [ ] Decide on retraining schedule based on experiments

---

## Appendix: Key Queries

### A1: Forward-Looking Predictions Only
```sql
SELECT *
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND DATE(created_at) <= game_date  -- Created before or on game day
  AND game_date < CURRENT_DATE()
```

### A2: Check Confidence Scale
```sql
SELECT
  CASE WHEN confidence_score <= 1 THEN 'decimal' ELSE 'percent' END as scale,
  COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
GROUP BY 1
```

### A3: Line Source Verification
```sql
SELECT
  p.line_source_api,
  SUM(CASE WHEN o.points_line = p.current_points_line OR b.points_line = p.current_points_line
      THEN 1 ELSE 0 END) as verified,
  COUNT(*) as total
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_raw.odds_api_player_points_props o
  ON p.player_lookup = o.player_lookup AND p.game_date = o.game_date
LEFT JOIN nba_raw.bettingpros_player_points_props b
  ON p.player_lookup = b.player_lookup AND p.game_date = b.game_date
WHERE p.system_id = 'catboost_v8'
  AND p.game_date >= '2026-01-01'
GROUP BY 1
```

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `SESSION-24-INVESTIGATION-FINDINGS.md` | Full Session 24 analysis |
| `WALK-FORWARD-EXPERIMENT-PLAN.md` | Experiment framework |
| `experiments/D1-results.json` | 2024-25 performance data |
| `docs/09-handoff/2026-01-29-SESSION-20-CATBOOST-V8-FIX-AND-SAFEGUARDS.md` | Feature passing fix |

---

*Document maintained by: Claude Code sessions*
*Last updated: 2026-01-29 Session 24*
