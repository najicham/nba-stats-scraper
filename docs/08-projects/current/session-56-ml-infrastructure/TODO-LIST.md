# Session 56 TODO List

All ideas and improvements discussed during Session 56.

---

## COMPLETED THIS SESSION

- [x] **Performance Diagnostics System** - Unified monitoring for Vegas sharpness, model drift, data quality
- [x] **Experiment Registry** - BigQuery table + Python class for tracking ML experiments
- [x] **YAML Experiment Configs** - Schema and example for reproducible experiments
- [x] **Production-Equivalent Backtest Mode** - Added `--production-equivalent` flag to evaluate_model.py
- [x] **6 New Skills** - todays-predictions, yesterdays-grading, top-picks, model-health, player-lookup, experiment-tracker
- [x] **Investigated Production-Backtest Gap** - Found root causes (sample population, line contamination, missing dates)
- [x] **Deploy Schemas** - performance_diagnostics_daily and ml_experiments tables created

---

## HIGH PRIORITY (P0) - Do Next

### 1. Fix Feature Store Line Quality
**Problem**: 45% of `has_vegas_line=1.0` records have estimated (not real) Vegas lines.

**Tasks**:
- [ ] Add `line_is_actual` BOOLEAN column to ml_feature_store_v2
- [ ] Backfill: Set TRUE only when line ends in .5 or .0
- [ ] Update feature store processor to set this flag correctly
- [ ] Update backtest queries to filter on this flag

**Effort**: 1 session

### 2. Investigate Missing Production Dates
**Problem**: 8 dates in January have 0 graded predictions (Jan 19, 21-24, 29-30).

**Tasks**:
- [ ] Check coordinator logs for these dates
- [ ] Determine why predictions weren't generated or graded
- [ ] Add monitoring to detect future gaps
- [ ] Consider backfilling if data is available

**Effort**: 0.5 session

### 3. Automate Daily Performance Diagnostics
**Problem**: Diagnostics only run manually.

**Tasks**:
- [ ] Add `check_performance_diagnostics()` to data_quality_alerts Cloud Function
- [ ] Persist results to performance_diagnostics_daily table
- [ ] Add Slack alerting for WARNING/CRITICAL levels
- [ ] Create simple dashboard view in admin

**Effort**: 1 session

---

## MEDIUM PRIORITY (P1)

### 4. Implement Prediction Versioning/History
**Problem**: When predictions update throughout the day, old values are lost.

**Tasks**:
- [ ] Create `nba_predictions.prediction_history` table
- [ ] Modify BatchConsolidator to capture before-update values
- [ ] Add queries to track prediction drift
- [ ] Document in handoff

**Effort**: 2-3 sessions

### 5. Create Model Experiment Skill
**Problem**: No easy way to run experiments from Claude.

**Tasks**:
- [ ] Create `/model-experiment` skill
- [ ] Support specifying train/eval dates
- [ ] Reuse hit-rate-analysis groupings
- [ ] Output standardized results tables

**Effort**: 1-2 sessions

### 6. Vegas Sharpness Predictor
**Problem**: We know ~14% swing is predictable, but not automated.

**Tasks**:
- [ ] Create rule-based sharpness score calculator
- [ ] Add to prediction output (sharpness_score field)
- [ ] Adjust edge thresholds based on sharpness
- [ ] Monitor if this improves ROI

**Effort**: 2 sessions

### 7. Trajectory Features Experiment
**Problem**: V8 doesn't use trajectory features (pts_slope_10g, zscore, breakout_flag).

**Tasks**:
- [ ] Train model with 37 features (including trajectory)
- [ ] Evaluate using production-equivalent mode
- [ ] Compare to 33-feature baseline
- [ ] Decide if worth deploying

**Effort**: 1 session

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

### Already Answered (Session 55-56):
- [x] Why does model echo Vegas in January? → Shared information (both use recent stats)
- [x] Can we predict Vegas sharpness? → Yes, ~14% swing predictable
- [x] Is JAN_DEC better? → No, production V8 already at 57%
- [x] Why 57% vs 49% gap? → Sample population + line contamination

### Still Open:
- [ ] Why did coordinator not run on 8 January dates?
- [ ] Can we reduce Vegas feature weight without hurting performance?
- [ ] Would ensemble of recent + historical models help?
- [ ] Is there a seasonal January pattern we should model?

---

## DOCUMENTATION TO UPDATE

- [ ] Update CLAUDE.md with new skills
- [ ] Update troubleshooting-matrix.md with backtest methodology
- [ ] Create handoff doc at end of session
- [ ] Update experiment documentation with production-equivalent mode

---

## Quick Reference

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | Fix feature store line quality | 1 session | High |
| P0 | Investigate missing dates | 0.5 session | Medium |
| P0 | Automate daily diagnostics | 1 session | High |
| P1 | Prediction versioning | 2-3 sessions | Medium |
| P1 | Model experiment skill | 1-2 sessions | Medium |
| P1 | Vegas sharpness predictor | 2 sessions | High |
| P1 | Trajectory features experiment | 1 session | Medium |
| P2 | Monthly retraining pipeline | 2-3 sessions | High |
| P2 | Shared utilities | 1 session | Low |
| P2 | A/B shadow mode | 3-4 sessions | High |

---

*Created: 2026-01-31, Session 56*
