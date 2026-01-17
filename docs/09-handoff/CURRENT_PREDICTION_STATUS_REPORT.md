# MLB Prediction System - Current Status Report

**Date:** 2026-01-16
**Scope:** Past 4 MLB seasons (2022-2025)
**Model Version:** V1 (mlb_pitcher_strikeouts_v1_20260107)

---

## Executive Summary

✅ **Current predictions are high quality** (67.3% win rate, 1.46K MAE)
❌ **Missing 2022-2023 seasons completely** (0 predictions)
⚠️ **V1.6 model trained but not deployed** (model exists locally, not in GCS/database)

---

## Current Database State (V1 Model)

### Overall Statistics
- **Total Predictions:** 8,130
- **Unique Pitchers:** 340
- **Date Range:** 2024-04-09 to 2025-09-28
- **Grading Status:** 88.5% graded (7,196/8,130)
- **Win Rate:** **67.3%** (4,841 wins / 7,196 graded) 🟢
- **MAE:** 1.46K (excellent accuracy) 🟢
- **Avg Prediction:** 5.09K
- **Avg Actual:** 5.07K (well-calibrated!)

### Coverage by Season

| Season | Games Available | Predictions | Coverage | Graded | Win Rate |
|--------|----------------|-------------|----------|--------|----------|
| 2022   | 0 (N/A)        | **0**       | **0%**   | N/A    | N/A      |
| 2023   | 0 (N/A)        | **0**       | **0%**   | N/A    | N/A      |
| 2024   | 4,543          | 3,760       | 82.8%    | 82.0%  | **71.3%** |
| 2025   | 4,573          | 4,365       | 95.5%    | 94.2%  | **64.3%** |

🔴 **Critical Gap:** 2022-2023 seasons have ZERO predictions

### Performance by Recommendation Type

| Recommendation | Bets  | Wins  | Losses | Win Rate | Avg Confidence |
|----------------|-------|-------|--------|----------|----------------|
| OVER           | 4,313 | 2,822 | 1,491  | **65.4%** | 0.8 |
| UNDER          | 2,883 | 2,019 | 864    | **70.0%** | 0.8 |
| PASS           | N/A   | N/A   | N/A    | N/A       | N/A |

🟢 **Strong Performance:** Both OVER and UNDER bets are profitable

### Grading Status
- ✅ **7,196 predictions graded** (88.5%)
- ✅ **934 pass recommendations** (not applicable for grading)
- ✅ **0 old ungraded predictions** (>2 days old)

---

## V1.6 Model Status

### Model Training ✅
- **Model ID:** mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149
- **Trained:** 2026-01-15 13:11:49
- **Type:** Classifier (outputs probability of OVER)
- **Training Samples:** 6,112
- **Test Accuracy:** 63.2%
- **Test AUC:** 0.682
- **Walk-Forward Results:**
  - Overall hit rate: 56.4%
  - Very high OVER hit rate: 63.6%
  - High confidence OVER hit rate: 61.5%

### New Features in V1.6 🆕
V1.6 adds 4 rolling Statcast features:
- `f50_swstr_pct_last_3`: Per-game SwStr% (last 3 starts)
- `f51_fb_velocity_last_3`: Fastball velocity (last 3 starts)
- `f52_swstr_trend`: SwStr% trend (recent - season baseline)
- `f53_velocity_change`: Velocity change (season - recent)

### Deployment Status ❌
- ❌ **Model NOT uploaded to GCS yet**
- ❌ **No V1.6 predictions in database**
- ❌ **No V1.6 grading completed**
- ✅ Model files exist locally in `models/mlb/`

---

## Gap Analysis

### Missing Data

| Category | Status | Details |
|----------|--------|---------|
| 2022 Season Predictions | ❌ Missing | 0 predictions (need ~4,500) |
| 2023 Season Predictions | ❌ Missing | 0 predictions (need ~4,500) |
| 2024 Season V1.6 Predictions | ❌ Missing | Have V1, need V1.6 (~3,760) |
| 2025 Season V1.6 Predictions | ❌ Missing | Have V1, need V1.6 (~4,365) |

**Total Missing Predictions:** ~17,125

### Feature Availability for V1.6

To generate V1.6 predictions, we need:
1. ✅ `mlb_analytics.pitcher_game_summary` (core stats)
2. ✅ `mlb_analytics.pitcher_rolling_statcast` (V1.6 features)
3. ✅ `mlb_raw.bp_pitcher_props` (BettingPros data)
4. ✅ `mlb_raw.mlb_game_lineups` (lineup data for V1.4 features)

**Feature Coverage Check Needed:**
- Validate `pitcher_rolling_statcast` exists for 2022-2023 ⚠️
- Validate BettingPros props exist for 2022-2023 ⚠️

---

## Validation Approach - Multiple Angles

We validated from these different perspectives:

### 1. **Existence Validation** ✅
- Checked prediction counts vs game counts
- Identified missing seasons (2022-2023)
- Confirmed V1.6 model not deployed

### 2. **Coverage Validation** ✅
- 2024: 82.8% coverage (782 missing games)
- 2025: 95.5% coverage (208 missing games)
- Date gaps: None within covered seasons

### 3. **Grading Validation** ✅
- 88.5% of predictions graded
- No stale ungraded predictions (>2 days)
- Grading is current and complete

### 4. **Quality Validation** ✅
- MAE: 1.46K (excellent for pitcher strikeouts)
- Bias: +0.02K (nearly perfect calibration)
- Win rate: 67.3% (highly profitable)

### 5. **Model Version Validation** ✅
- Only 1 model version in database (V1 Jan 7)
- V1.6 model exists locally but not deployed
- Confirmed need for V1.6 backfill

### 6. **Statistical Distribution Validation** (pending)
- Need to run statistical analysis script
- Check confidence calibration
- Analyze edge value distributions

---

## Action Items for V1.6 Deployment

### Phase 1: Upload Model to GCS ⏸️
```bash
# Upload v1.6 model files
gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json \
  gs://nba-scraped-data/ml-models/mlb/
```

### Phase 2: Validate Feature Availability ⏸️
```bash
# Check if rolling statcast features exist for 2022-2023
PYTHONPATH=. python scripts/mlb/check_v16_feature_coverage.py --seasons 2022,2023
```

### Phase 3: Generate Historical Predictions ⏸️
```bash
# Generate V1.6 predictions for all 4 seasons
PYTHONPATH=. python scripts/mlb/generate_v16_historical_predictions.py \
  --start-date 2022-04-07 \
  --end-date 2025-09-28 \
  --model-version v1.6

# Expected output: ~17,125 predictions
```

### Phase 4: Grade Predictions ⏸️
```bash
# Grade all V1.6 predictions
PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py \
  --start-date 2022-04-07 \
  --end-date 2025-09-28
```

### Phase 5: Validate Results ⏸️
```bash
# Run comprehensive validation
PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py --seasons 2022,2023,2024,2025

# Run statistical analysis
PYTHONPATH=. python scripts/mlb/validate_v1_6_statistical_analysis.py --export-csv
```

---

## Key Questions to Resolve

1. **Do we have rolling Statcast data for 2022-2023?**
   - Need to query `mlb_analytics.pitcher_rolling_statcast` for those seasons
   - V1.6 requires `swstr_pct_last_3`, `fb_velocity_last_3`, etc.

2. **Do we have BettingPros props for 2022-2023?**
   - Need to query `mlb_raw.bp_pitcher_props` for those seasons
   - V1.6 uses `projection_value`, `perf_last_5_pct`, etc.

3. **Should we keep V1 predictions or replace with V1.6?**
   - Option A: Keep V1, add V1.6 as separate model_version (recommended)
   - Option B: Replace V1 with V1.6 (loses V1 comparison)

4. **What's the priority order?**
   - Option A: Fill 2022-2023 gap first (highest priority)
   - Option B: Upgrade 2024-2025 to V1.6 first (test on known data)

---

## Recommendations

### Immediate Actions (Priority 1)
1. ✅ **Validate current state** (COMPLETED - this report)
2. ⏸️ **Check feature availability** for 2022-2023
3. ⏸️ **Upload V1.6 model to GCS**

### Short-term Actions (Priority 2)
4. ⏸️ **Generate V1.6 predictions for 2024-2025** (validate against V1)
5. ⏸️ **Compare V1 vs V1.6 performance** on 2024-2025
6. ⏸️ **Backfill 2022-2023** if features available

### Long-term Actions (Priority 3)
7. ⏸️ **Set up automated V1.6 prediction pipeline** for 2026 season
8. ⏸️ **Monitor V1.6 performance** vs V1 in production
9. ⏸️ **Update prediction export/monitoring** to use V1.6

---

## Success Criteria

✅ **Backfill complete when:**
- [ ] V1.6 model uploaded to GCS
- [ ] ~17,125 V1.6 predictions generated (2022-2025)
- [ ] >95% of predictions graded
- [ ] Coverage >90% for each season
- [ ] Win rate >55% (maintaining profitability)
- [ ] MAE <2.0 (maintaining accuracy)
- [ ] All validation scripts pass

---

## Files Created for Validation

1. ✅ `scripts/mlb/validate_v1_6_backfill_comprehensive.py`
   - Checks existence, grading, coverage, quality
   - Multi-angle validation approach

2. ✅ `scripts/mlb/validate_v1_6_statistical_analysis.py`
   - Statistical distributions
   - Confidence calibration
   - Edge value analysis
   - Temporal trends

3. ✅ `scripts/mlb/validate_current_predictions_v1.py`
   - Validates existing V1 predictions
   - Identified 2022-2023 gap
   - Confirmed V1 performance

---

## Conclusion

**Current System Status:** 🟡 Partial
- V1 predictions for 2024-2025: **Excellent quality** (67.3% win rate)
- 2022-2023 predictions: **Missing entirely**
- V1.6 model: **Ready but not deployed**

**Next Steps:**
1. Validate feature availability for 2022-2023
2. Upload V1.6 model to GCS
3. Generate and grade historical predictions
4. Run comprehensive validation

**Estimated Effort:**
- Feature validation: 30 minutes
- Model upload: 15 minutes
- Prediction generation: 2-4 hours (depending on data volume)
- Grading: 1-2 hours
- Validation: 30 minutes

**Total:** ~5-8 hours to complete full V1.6 backfill and validation
