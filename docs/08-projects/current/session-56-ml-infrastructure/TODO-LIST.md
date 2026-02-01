# Session 56-57 TODO List

All ideas and improvements discussed during Sessions 56-57.

---

## COMPLETED (Sessions 56-57)

### Session 56
- [x] **Performance Diagnostics System** - Unified monitoring for Vegas sharpness, model drift, data quality
- [x] **Experiment Registry** - BigQuery table + Python class for tracking ML experiments
- [x] **YAML Experiment Configs** - Schema and example for reproducible experiments
- [x] **Production-Equivalent Backtest Mode** - Added `--production-equivalent` flag to evaluate_model.py
- [x] **6 New Skills** - todays-predictions, yesterdays-grading, top-picks, model-health, player-lookup, experiment-tracker
- [x] **Investigated Production-Backtest Gap** - Found root causes (sample population, line contamination, missing dates)
- [x] **Deploy Schemas** - performance_diagnostics_daily, ml_experiments, vegas_sharpness_daily tables created
- [x] **Fixed Line Contamination** - Changed feature_extractor.py from AVG() to picking single best line
- [x] **Vegas Sharpness Tracking Design** - Schema and dashboard design for tracking Vegas accuracy over time

### Session 57
- [x] **Investigate Missing Production Dates** - RESOLVED: Jan 8 had no Vegas lines (upstream issue), other dates working correctly
- [x] **Automate Daily Diagnostics** - Added to data-quality-alerts Cloud Function (needs shared module fix)
- [x] **Standardize Hit Rate Measurement** - Updated hit-rate-analysis skill with two standard filters
- [x] **Model Drift Investigation** - Confirmed MODEL_DRIFT (not Vegas sharpening): Week 1 84.5% → Week 4 46.2%
- [x] **Documentation Updates** - Added measurement guidance to CLAUDE.md

---

## HIGH PRIORITY (P0) - Do Next

### 1. Fix evaluate_model.py to Match Production ✅ DONE (Session 58)
**Problem**: Evaluation shows 50% hit rate, but production shows 78% for premium picks.

**Root Cause**: Evaluation includes ALL predictions, production only grades 92+ confidence.

**Tasks**:
- [x] Add `--confidence-threshold` parameter (default 0.92)
- [x] Filter predictions to only those meeting confidence threshold
- [x] Report results for both standard filters (Premium 92+/3+, High Edge 5+)
- [x] Add weekly breakdown to detect drift during evaluation

**Note**: Evaluation uses backfilled data, so results won't match production exactly.
Use for model comparison, not production forecasting.

### 2. Add "Find Best Filter" to hit-rate-analysis ✅ DONE (Session 58)
**Problem**: Need to test all filter combinations to find optimal trading strategy.

**Tasks**:
- [x] Add query to test all conf/edge combinations (Query 5 in skill)
- [x] Rank by hit rate with minimum sample size
- [x] Show which filter is currently performing best

### 3. Fix Cloud Function Shared Module ✅ DONE (Session 58)
**Problem**: data-quality-alerts can't import performance_diagnostics in production.

**Tasks**:
- [x] Fixed deploy.sh to cd into function directory before gcloud deploy
- [x] Created missing shared/__init__.py
- [ ] Test deployment (not yet tested in production)

---

## MEDIUM PRIORITY (P1)

### 4. Monthly Retraining Pipeline ✅ DONE (Session 58)
**Problem**: Model V8 is drifting - Week 1 hit 84%, Week 4 hit 46%.

**Solution Implemented**:
- `ml/experiments/quick_retrain.py` - Quick CLI tool for retraining
- `orchestration/cloud_functions/monthly_retrain/` - Cloud Function
- Runs on 1st of each month at 6 AM ET via Cloud Scheduler
- Trains on last 60 days, evaluates on last 7 days
- Compares to V8 baseline, sends Slack notification
- Stores models in GCS, registers in ml_experiments

**Usage**:
```bash
# CLI
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "FEB_MONTHLY"

# Deploy Cloud Function
cd orchestration/cloud_functions/monthly_retrain && ./deploy.sh
```

### 5. Create `/model-experiment` Skill ✅ DONE (Session 58)
**Problem**: No easy way to run experiments from Claude.

**Solution Implemented**:
- `.claude/skills/model-experiment/SKILL.md` - New skill
- `ml/experiments/quick_retrain.py` - Supporting script
- Defaults: 60 days training, 7 days eval
- Auto-compares to V8 baseline
- Registers in ml_experiments table

**Usage**: `/model-experiment` or direct script call

### 6. Test Trajectory Features ✅ TESTED (Session 58)
**Problem**: V8 doesn't use trajectory features that might help with drift.

**New Features Tested**:
- `pts_slope_10g` - 10-game scoring trend (importance: 5.97)
- `pts_vs_season_zscore` - Points z-score vs season average (importance: 4.92)
- `breakout_flag` - Recent breakout indicator (importance: 0.00)
- `dnp_rate` - DNP risk (importance: 0.89)

**Results** (Nov 2025 - Jan 2026 training data):
| Model | MAE | Hit Rate |
|-------|-----|----------|
| 33 features | 4.399 | 50.39% |
| 37 features | 4.430 | 49.61% |

**Conclusion**: Trajectory features did NOT improve model. They add noise.
Possible reasons:
- Only 3 months of training data
- Features may need tuning (window sizes, normalization)
- The signal may already be captured by existing features

**Script**: `ml/experiments/train_trajectory_test.py`

### 7. Implement Prediction Versioning/History
**Problem**: When predictions update throughout the day, old values are lost.

**Tasks**:
- [ ] Create `nba_predictions.prediction_history` table
- [ ] Modify BatchConsolidator to capture before-update values
- [ ] Add queries to track prediction drift
- [ ] Document in handoff

**Effort**: 2-3 sessions

### 8. Vegas Sharpness Dashboard (Design Complete)
**Purpose**: Track Vegas accuracy over time with graphs in admin dashboard.

**Schema**: DEPLOYED (`vegas_sharpness_daily` table)
**Design**: See `VEGAS-SHARPNESS-DASHBOARD.md`

**Remaining Tasks**:
- [ ] Create `VegasSharpnessProcessor` class to populate daily data
- [ ] Add to grading pipeline (run after prediction_accuracy updates)
- [ ] Backfill 90 days of historical data
- [ ] Create Flask blueprint with API endpoints (`/api/vegas-sharpness/*`)
- [ ] Create dashboard UI component with Chart.js charts
- [ ] Add to admin dashboard navigation

**Effort**: 2-3 sessions

### 7. Trajectory Features Experiment ✅ DONE (Session 58)
See #6 above - trajectory features tested, did not improve model.

---

## LOW PRIORITY (P2)

### 8. Monthly Retraining Pipeline
**Problem**: V8 is 18 months out of distribution.

**Tasks**:
- [ ] Create automated training pipeline
- [ ] Train on last 60-90 days of data
- [ ] Run monthly at start of each month
- [ ] Shadow mode before promotion

**Effort**: 2-3 sessions

### 9. Shared Backtest Filter Utility
**Problem**: Different scripts handle filtering differently.

**Tasks**:
- [ ] Create `shared/utils/backtest_filters.py`
- [ ] Move filter logic from evaluate_model.py
- [ ] Update tier_based_backtest.py to use shared utility
- [ ] Update other experiment scripts

**Effort**: 0.5 session

### 10. Standardized Betting Metrics Utility
**Problem**: Hit rate calculation varies slightly between scripts.

**Tasks**:
- [ ] Create `shared/utils/betting_metrics.py`
- [ ] Implement consistent hit_rate, ROI, Kelly calculations
- [ ] Handle pushes consistently
- [ ] Update all evaluation scripts to use

**Effort**: 0.5 session

### 11. Experiment Lineage Tracking
**Problem**: Hard to see which model derived from which.

**Tasks**:
- [ ] Add parent_experiment_id to registry
- [ ] Update training scripts to set parent
- [ ] Create lineage visualization query
- [ ] Add to experiment-tracker skill

**Effort**: 1 session

### 12. A/B Shadow Mode Pipeline
**Problem**: No automated way to test new models in production.

**Tasks**:
- [ ] Create shadow prediction system
- [ ] Log challenger predictions alongside champion
- [ ] Automated comparison after N days
- [ ] Promotion workflow with approval

**Effort**: 3-4 sessions

---

## RESEARCH QUESTIONS TO INVESTIGATE

### Already Answered (Sessions 55-57):
- [x] Why does model echo Vegas in January? → Shared information (both use recent stats)
- [x] Can we predict Vegas sharpness? → Yes, ~14% swing predictable
- [x] Is JAN_DEC better? → No, production V8 already at 57%
- [x] Why 57% vs 49% gap? → Sample population + line contamination
- [x] Why did coordinator not run on 8 January dates? → Jan 8 Vegas lines not fetched (upstream issue)
- [x] Is Week 4 drop due to Vegas sharpening? → NO, it's MODEL_DRIFT (model MAE 5.8→8.4, Vegas stable)
- [x] What's the best filter for trading? → Premium (92+ conf, 3+ edge) = 78.7% for full Jan

### Still Open:
- [ ] Can we reduce Vegas feature weight without hurting performance?
- [ ] Would ensemble of recent + historical models help?
- [ ] Is there a seasonal January pattern we should model?
- [ ] Would trajectory features (pts_slope, zscore) help combat drift?

---

## DOCUMENTATION UPDATED

- [x] Update CLAUDE.md with hit rate measurement guidance (Session 57)
- [x] Update hit-rate-analysis skill with standard filters (Session 57)
- [ ] Update troubleshooting-matrix.md with backtest methodology
- [x] Create handoff doc at end of session (Session 57)
- [ ] Update experiment documentation with production-equivalent mode

---

## Key Metrics (January 2026)

### Model Performance by Week
| Week | Premium (92+, 3+) | High Edge (5+) | Model MAE |
|------|-------------------|----------------|-----------|
| Week 1 | **84.5%** | **76.6%** | 5.80 |
| Week 2 | 78.6% | 55.6% | 7.88 |
| Week 3 | 70.6% | 54.7% | 9.54 |
| Week 4 | **46.2%** | **49.3%** | 8.44 |

### Standard Filters (Always Report Both)
| Filter | Definition | Jan Hit Rate |
|--------|------------|--------------|
| **Premium** | `conf >= 0.92 AND edge >= 3` | 78.7% (141 bets) |
| **High Edge** | `edge >= 5` (any conf) | 63.1% (398 bets) |

---

## Quick Reference

| Priority | Task | Effort | Impact | Status |
|----------|------|--------|--------|--------|
| P0 | Fix evaluate_model.py confidence filter | 30 min | High | ✅ DONE |
| P0 | Add "find best filter" to hit-rate skill | 15 min | Medium | ✅ DONE |
| P0 | Fix Cloud Function shared module | 30 min | Medium | ✅ DONE |
| P1 | **Monthly retraining pipeline** | 2-3 sessions | **CRITICAL** | ✅ DONE |
| P1 | Model experiment skill | 1-2 sessions | High | ✅ DONE |
| P1 | Trajectory features experiment | 1 session | Medium | ✅ DONE |
| P1 | Prediction versioning | 2-3 sessions | Medium | TODO |
| P1 | Vegas sharpness dashboard | 2-3 sessions | Medium | TODO |
| P2 | Shared utilities | 1 session | Low | TODO |
| P2 | A/B shadow mode | 3-4 sessions | High | TODO |

**Completed**:
| Task | Session |
|------|---------|
| Fix feature store line quality | 56 |
| Investigate missing dates | 57 |
| Automate daily diagnostics (partial) | 57 |
| Standardize hit rate measurement | 57 |
| Fix evaluate_model.py confidence filter | 58 |
| Add "find best filter" to hit-rate skill | 58 |
| Fix Cloud Function shared module | 58 |
| Test trajectory features | 58 |
| Monthly retraining pipeline | 58 |
| Model experiment skill | 58 |

---

*Created: 2026-01-31, Session 56*
*Updated: 2026-01-31, Session 57*
