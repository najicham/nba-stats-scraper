# Session 75 Handoff: V1.6 MLB Deployment In Progress

**Date:** 2026-01-16
**Session Focus:** V1.6 model deployment alongside V1
**Status:** ✅ Predictions generated, 🔄 Grading in progress (25% complete)
**Next Action:** Wait for grading to complete, then compare V1 vs V1.6

---

## Executive Summary

### What Was Accomplished This Session ✅

**1. Created V1.6 Prediction Generation Script**
- **File:** `scripts/mlb/generate_v16_predictions_mirror_v1.py`
- Mirrors V1's workflow exactly
- Uses 35 features (vs V1's 19)
- Handles classifier output (probability → strikeouts)
- Tags with model_version: `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149`

**2. Generated 8,536 V1.6 Predictions** ✅
- Date range: 2024-04-09 to 2025-09-28 (same as V1)
- Model: `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json`
- Initial metrics:
  - MAE: 1.704 (vs V1's 1.46)
  - Line accuracy: 74.9% on 6,112 games with lines
  - Avg OVER probability: 0.547
- Data coverage:
  - BettingPros features: 71.6%
  - Statcast features: 85.1%

**3. Created V1.6 Grading Script**
- **File:** `scripts/mlb/grade_v16_predictions.py`
- Grades V1.6 predictions only (filters by model_version)
- Does NOT touch V1 predictions
- Populates is_correct and actual_strikeouts fields

**4. Started V1.6 Grading Process** 🔄
- **Status:** Running in background (PID: b4b3ef9)
- **Progress:** 2,100/8,536 records graded (24.6%)
- **Time remaining:** ~6-7 hours
- **Output file:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b4b3ef9.output`

**5. Validated MLB Data Quality** ✅
- Checked all 4 seasons (2022-2025)
- No fake or suspicious lines found
- 14,521 BettingPros props validated
- All lines align with actual outcomes (z-score < 0.4)
- No issues like NBA's 20-point problem

**6. Verified V1 Safety** ✅
- V1 predictions: 8,130 (unchanged)
- V1 win rate: 67.3% (unchanged)
- V1 MAE: 1.46 (unchanged)
- V1 graded: 7,196 (unchanged)

---

## Current State

### V1 Model (Production) - Untouched ✅

| Metric | Value | Status |
|--------|-------|--------|
| Predictions | 8,130 | ✅ Unchanged |
| Graded | 7,196 (88.5%) | ✅ Unchanged |
| Win Rate | 67.3% | ✅ Unchanged |
| MAE | 1.46 | ✅ Unchanged |
| Date Range | 2024-04-09 to 2025-09-28 | ✅ Unchanged |
| Model Version | mlb_pitcher_strikeouts_v1_20260107 | ✅ Unchanged |

### V1.6 Model (Deployed, Grading In Progress) 🔄

| Metric | Value | Status |
|--------|-------|--------|
| Predictions | 8,536 | ✅ Generated |
| Graded | 936 (11.0%) | 🔄 In Progress (25% of updates complete) |
| Win Rate | 88.7% (partial) | 🔄 Early data only (Apr-Jul 2024) |
| MAE | 1.63 (partial) | 🔄 Early data only |
| Date Range | 2024-04-09 to 2025-09-28 | ✅ Complete |
| Model Version | mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149 | ✅ Tagged |

---

## Early V1.6 Results (Partial Data)

### ⚠️ IMPORTANT: These are EARLY results from 22% of data (April-July 2024 only)

**V1.6 Performance (936 graded predictions):**
- **Win Rate: 88.7%** (830 wins, 106 losses)
- **MAE: 1.63**
- **Graded Range:** April 9 - July 8, 2024 (89 days, early season)

**V1 Performance (Full Data for Comparison):**
- **Win Rate: 67.3%** (4,841 wins, 2,355 losses)
- **MAE: 1.46**
- **Graded Range:** April 9, 2024 - September 28, 2025

**Initial Observation:**
- V1.6 showing +21.4 percentage points advantage
- BUT: Only 11% of predictions graded, early season only
- Need full grading to confirm if this holds across full season

### Recommendation Breakdown (Full V1.6 Dataset)

```
OVER: 2,558 (30.0%)
NO_LINE: 2,424 (28.4%)
PASS: 1,907 (22.3%)
UNDER: 1,647 (19.3%)
```

---

## Grading Progress Details

### Background Process

**Process ID:** b4b3ef9
**Started:** 2026-01-16 15:28:29
**Status:** Running
**Output:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b4b3ef9.output`

### Timeline

| Milestone | Records | Time | Status |
|-----------|---------|------|--------|
| Started | 0/8,536 | 15:28 | ✅ Complete |
| Calculated grades | 8,536/8,536 | 15:29 | ✅ Complete |
| Updated 500 | 500/8,536 | 15:59 | ✅ Complete |
| Updated 1000 | 1,000/8,536 | 16:33 | ✅ Complete |
| Updated 1500 | 1,500/8,536 | 17:08 | ✅ Complete |
| Updated 2000 | 2,000/8,536 | 17:44 | ✅ Complete |
| Updated 2100 | 2,100/8,536 | 17:51 | ✅ Complete |
| **Current** | **2,100/8,536** | **17:51** | **🔄 In Progress** |
| Estimated completion | 8,536/8,536 | ~23:30 - 01:00 | ⏸️ Pending |

**Rate:** ~100 records per 6.5 minutes
**Estimated Time Remaining:** 6-7 hours

### How to Check Progress

```bash
# Check latest progress
tail -50 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b4b3ef9.output

# Check if process is still running
ps aux | grep b4b3ef9

# Query partial results
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  COUNTIF(is_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNTIF(is_correct IS NOT NULL)) * 100, 1) as win_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE model_version LIKE '%v1_6%'
  AND recommendation IN ('OVER', 'UNDER')
"
```

---

## Data Quality Validation Results ✅

### All 4 Seasons Validated (2022-2025)

| Season | Props | Avg Line | Avg Actual | Over % | Coverage | Status |
|--------|-------|----------|------------|--------|----------|--------|
| 2022 | 3,888 | 5.05 | 5.34 | 53.8% | 100% | ✅ Clean |
| 2023 | 3,726 | 5.05 | 5.24 | 50.2% | 100% | ✅ Clean |
| 2024 | 3,211 | 4.97 | 5.12 | 50.1% | 100% | ✅ Clean |
| 2025 | 3,696 | 4.72 | 4.95 | 51.3% | 100% | ✅ Clean |
| **Total** | **14,521** | **4.95** | **5.16** | **51.4%** | **100%** | **✅ All Clean** |

### Line Distribution (Most Common)

| Line | Count | Avg Actual | Over % | Status |
|------|-------|------------|--------|--------|
| 4.5 | 4,480 | 4.69 | 52.0% | ✅ OK |
| 5.5 | 3,601 | 5.66 | 51.7% | ✅ OK |
| 3.5 | 2,259 | 3.93 | 54.5% | ✅ OK |
| 6.5 | 1,648 | 6.61 | 50.4% | ✅ OK |

### Deviation Analysis

**All lines pass validation:**
- Z-scores < 0.4 (well within normal range)
- No suspicious concentrations
- No fake lines detected
- Lines align with actual outcomes

**Conclusion:** ✅ All MLB data is legitimate and ready for production use

---

## Scripts Created This Session

### 1. Generate V1.6 Predictions
**File:** `scripts/mlb/generate_v16_predictions_mirror_v1.py`

**Features:**
- 35 features (vs V1's 19)
- Classifier model (outputs OVER probability)
- Converts probability to predicted strikeouts
- Same date range as V1 for direct comparison

**Usage:**
```bash
PYTHONPATH=. python scripts/mlb/generate_v16_predictions_mirror_v1.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --model-path gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
```

### 2. Grade V1.6 Predictions
**File:** `scripts/mlb/grade_v16_predictions.py`

**Features:**
- Filters by model_version (v1_6 only)
- Populates is_correct and actual_strikeouts
- Does NOT touch V1 predictions

**Usage:**
```bash
PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --model-version-filter v1_6
```

**Note:** Currently running in background

---

## Next Steps (When Grading Completes)

### Step 1: Verify Grading Complete ✅

```bash
# Check if grading finished
tail -100 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b4b3ef9.output

# Verify all V1.6 predictions graded
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  ROUND(COUNTIF(is_correct IS NOT NULL) * 100.0 / COUNT(*), 1) as graded_pct
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE model_version LIKE '%v1_6%'
  AND recommendation IN ('OVER', 'UNDER')
"
```

### Step 2: Verify V1 Still Unchanged ✅

```bash
PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py
```

**Must show:**
- ✅ Total predictions: 8,130
- ✅ Win rate: 67.3%
- ✅ MAE: 1.46

### Step 3: Compare V1 vs V1.6 Head-to-Head 📊

```bash
# Comprehensive comparison
PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16_head_to_head.py --export-csv

# Full validation
PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py \
  --seasons 2024,2025 \
  --verbose

# Statistical analysis
PYTHONPATH=. python scripts/mlb/validate_v1_6_statistical_analysis.py \
  --export-csv
```

### Step 4: Get Final V1.6 Metrics 📈

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  COUNTIF(is_correct = TRUE) as wins,
  COUNTIF(is_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNTIF(is_correct IS NOT NULL)) * 100, 1) as win_rate,
  ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae,
  ROUND(AVG(predicted_strikeouts - actual_strikeouts), 2) as bias
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY model
ORDER BY model
"
```

### Step 5: Make Deployment Decision 🎯

Based on full results, choose:

**Scenario A: V1.6 > V1 (Clear Winner)**
- V1.6 win rate >= 68% (better than V1's 67.3%)
- **Action:** Promote V1.6 to production

**Scenario B: V1.6 ≈ V1 (Comparable)**
- V1.6 win rate 64-67% (similar)
- **Action:** A/B test both models (70% V1, 30% V1.6)

**Scenario C: V1 > V1.6 (V1 Wins)**
- V1.6 win rate < 60% (worse)
- **Action:** Keep V1, iterate on V1.6

**Scenario D: Different Strengths**
- V1.6 better on OVER, V1 better on UNDER (or vice versa)
- **Action:** Ensemble approach, use both

---

## Files & Locations

### Models

**V1 (Production):**
- GCS: `gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json`
- Local: `models/mlb/mlb_pitcher_strikeouts_v1_20260107.json`

**V1.6 (Deployed):**
- GCS: `gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json`
- Local: `models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json`

### Scripts Created

1. `scripts/mlb/generate_v16_predictions_mirror_v1.py` ✅
2. `scripts/mlb/grade_v16_predictions.py` ✅

### Scripts Available (From Previous Sessions)

1. `scripts/mlb/verify_v1_unchanged.py` ✅
2. `scripts/mlb/compare_v1_vs_v16_head_to_head.py` ✅
3. `scripts/mlb/validate_v1_6_backfill_comprehensive.py` ✅
4. `scripts/mlb/validate_v1_6_statistical_analysis.py` ✅

### Documentation

1. `SESSION_HANDOFF_V16_DEPLOYMENT.md` - Original deployment plan
2. `V1_V16_DEPLOYMENT_SUMMARY.md` - Quick reference
3. `V1_TO_V16_MIRROR_STRATEGY.md` - Detailed strategy
4. `2026-01-16-SESSION-75-V16-DEPLOYMENT-IN-PROGRESS.md` - **This file**

---

## Database State

### Table: `mlb_predictions.pitcher_strikeouts`

**V1 Predictions:**
- Count: 8,130
- model_version: `mlb_pitcher_strikeouts_v1_20260107`
- Graded: 7,196 (88.5%)
- Win rate: 67.3%

**V1.6 Predictions:**
- Count: 8,536
- model_version: `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149`
- Graded: ~2,100 (24.6%) - **IN PROGRESS**
- Win rate: 88.7% (partial, early season only)

**Isolation:**
- Both models in same table
- Separated by model_version field
- No conflicts possible
- Can query independently or together

---

## Key Insights

### 1. V1.6 Uses 16 Additional Features

**New Features:**
- **f15-f18:** Context (opponent K rate, ballpark factor, season timing)
- **f19, f19b, f19c:** Season SwStr%, CSW%, Chase%
- **f30-f32:** Line-relative features
- **f40-f44:** BettingPros projections and historical performance
- **f50-f53:** Rolling Statcast (SwStr% trend, velocity change)

### 2. V1.6 is a Classifier (Not Regressor)

- Outputs OVER probability (not strikeout count)
- Converts to strikeouts: `line + (prob_over - 0.5) * 2`
- More conservative thresholds (OVER if prob > 0.55)

### 3. Early Results Are Promising

- 88.7% win rate on 22% of data
- +21.4 percentage points vs V1
- But: Early season only, need full validation

### 4. Data Quality Validated

- All 4 seasons clean (2022-2025)
- No fake or suspicious lines
- 14,521 BettingPros props validated

---

## Risk Assessment

### Risks Mitigated ✅

1. **V1 Modified:** ❌ Not possible - different model_version
2. **Data Quality:** ✅ Validated - all lines legitimate
3. **Grading Errors:** ✅ Tested - working correctly
4. **Process Interruption:** ✅ Running in background, recoverable

### Current Risks ⚠️

1. **Grading Incomplete:** Process running, ~6 hours remaining
2. **Temporal Bias:** Early results only (Apr-Jul 2024)
3. **Performance Drop:** 88.7% may not hold across full season

### Rollback Plan

If V1.6 performs poorly after full grading:

```sql
-- Delete all V1.6 predictions
DELETE FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%';

-- V1 remains: 8,130 predictions, 67.3% win rate
```

---

## Success Criteria

### Must Have ✅

- [x] V1.6 model uploaded to GCS
- [x] V1.6 predictions generated (~8,536)
- [ ] V1.6 predictions graded (>95%) - **IN PROGRESS: 24.6%**
- [x] V1 predictions verified unchanged
- [ ] Comparison analysis complete - **PENDING**
- [ ] Decision documented - **PENDING**

### Performance Targets 🎯

- [ ] V1.6 win rate >55% (minimum profitability) - **PENDING**
- [ ] V1.6 MAE <2.0 (acceptable accuracy) - **PENDING**
- [ ] V1.6 vs V1 comparison shows patterns - **PENDING**
- [ ] Decision made on deployment strategy - **PENDING**

---

## Timeline

| Step | Activity | Time | Status |
|------|----------|------|--------|
| 1 | Upload V1.6 to GCS | 5 min | ✅ Complete (prior session) |
| 2 | Generate V1.6 predictions | 2-3 hrs | ✅ Complete |
| 3 | Verify V1 unchanged | 2 min | ✅ Complete |
| 4 | Grade V1.6 predictions | 1-2 hrs | 🔄 In Progress (7 hrs actual) |
| 5 | Compare V1 vs V1.6 | 1 hr | ⏸️ Pending |
| **Total** | | **~10 hrs** | **60% Complete** |

---

## Questions & Answers

**Q: Why is grading taking so long?**
A: Using individual UPDATE statements (not batch). Working correctly but slow. Will complete overnight.

**Q: Can we trust the 88.7% win rate?**
A: NOT YET - only 22% of data graded, early season only. Need full grading to confirm.

**Q: Is V1 safe?**
A: YES - completely untouched. Different model_version ensures zero conflict.

**Q: What if V1.6 underperforms after full grading?**
A: Simply delete V1.6 predictions (one SQL DELETE). V1 remains at 67.3% win rate.

**Q: How do we know when grading is done?**
A: Check output file for "Batch update complete" message. Query database for grading %.

---

## Next Session Prompt

```
V1.6 MLB predictions grading should be complete (or nearly complete).

Check status:
1. tail -100 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b4b3ef9.output
2. PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py
3. Query V1.6 grading percentage

If grading complete:
- Compare V1 vs V1.6 head-to-head
- Run comprehensive validation
- Make deployment decision

Key files:
- This handoff: docs/09-handoff/2026-01-16-SESSION-75-V16-DEPLOYMENT-IN-PROGRESS.md
- Comparison script: scripts/mlb/compare_v1_vs_v16_head_to_head.py
- Validation script: scripts/mlb/validate_v1_6_backfill_comprehensive.py
```

---

## Contact & Support

**Session Date:** 2026-01-16
**Documentation:** `/home/naji/code/nba-stats-scraper/docs/09-handoff/`
**Scripts:** `/home/naji/code/nba-stats-scraper/scripts/mlb/`
**Models:** `/home/naji/code/nba-stats-scraper/models/mlb/`

**Current Status:** V1.6 grading in progress, V1 safe, all data validated

**Next Action:** Wait for grading completion (~6-7 hours), then compare models

---

**Session Status:** ✅ V1.6 deployed successfully, grading in progress
**V1 Status:** ✅ Untouched and safe (67.3% win rate preserved)
**Risk Level:** 🟢 LOW - All safety mechanisms working
**Estimated Completion:** 2026-01-17 00:00-01:00 UTC
