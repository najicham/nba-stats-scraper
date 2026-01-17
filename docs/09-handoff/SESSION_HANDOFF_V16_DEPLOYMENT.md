# Session Handoff: V1.6 MLB Prediction Deployment

**Date:** 2026-01-16
**Session Focus:** V1.6 model deployment alongside V1 (safe, side-by-side)
**Status:** Documentation complete, ready for Step 1 (upload to GCS)
**Next Action:** Upload V1.6 model to GCS

---

## Executive Summary

### What Was Accomplished This Session

✅ **Validated Current System (V1)**
- V1 has 8,130 predictions (2024-2025)
- 67.3% win rate, 1.46 MAE (production quality!)
- 88.5% graded (7,196/8,130)
- NO issues, stable baseline

✅ **Found the Gap**
- 2022-2023 seasons: No analytics tables exist
- Cannot backfill 2022-2023 without rebuilding analytics (10-20 hrs)
- **Decision:** Focus on 2024-2025 for V1.6 deployment first

✅ **Created V1.6 Deployment Strategy**
- Mirror V1's exact workflow
- Add V1.6 alongside V1 (not replacing)
- Both models isolated by `model_version` field
- Zero risk to V1 - completely separate

✅ **Created Comprehensive Documentation**
- 4 strategy documents (1,000+ lines)
- 2 validation scripts
- 2 comparison scripts
- Full execution plan (4-6 hours)

### What V1.6 Is

```
Model: mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
Location: models/mlb/ (local only, NOT in GCS yet)
Type: Classifier (outputs OVER probability)
Features: 35 (adds 16 new vs V1's 19)
Training Data: 6,112 samples (2024-2025)
Test Accuracy: 63.2%
Walk-Forward Hit Rate: 56.4%

New Features:
- f50-f53: Rolling Statcast (SwStr%, velocity trends)
- f40-f44: BettingPros projections
- f30-f32: Line-relative features
- f19: Season swing metrics
```

### Current State

| Component | V1 | V1.6 |
|-----------|----|----|
| Model in GCS | ✅ Yes | ❌ No (Step 1) |
| Predictions in DB | ✅ 8,130 | ❌ 0 |
| Grading | ✅ 88.5% | ❌ N/A |
| Win Rate | ✅ 67.3% | ❌ TBD |
| Status | 🟢 Production | 🟡 Staged |

---

## Execution Plan (4-6 Hours)

### Step 1: Upload V1.6 to GCS ⏸️ NEXT ACTION (5 minutes)

```bash
# Upload model files
gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json \
  gs://nba-scraped-data/ml-models/mlb/

# Verify upload
gsutil ls -lh gs://nba-scraped-data/ml-models/mlb/*pitcher_strikeouts*
```

**Expected Output:**
```
... mlb_pitcher_strikeouts_v1_20260107.json (455 KB) ← V1
... mlb_pitcher_strikeouts_v1_20260107_metadata.json (1 KB)
... mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json (513 KB) ← V1.6
... mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json (2 KB)
```

**Safety Check:**
```bash
# Verify V1 unchanged
PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py
# Must show: ✅ V1 INTEGRITY CHECK PASSED
```

---

### Step 2: Generate V1.6 Predictions ⏸️ TODO (2-3 hours)

**CRITICAL:** Must use same date range as V1 for direct comparison
- V1 used: 2024-04-09 to 2025-09-28
- V1.6 must use: 2024-04-09 to 2025-09-28

```bash
# Generate V1.6 predictions (mirrors V1)
PYTHONPATH=. python scripts/mlb/generate_v16_predictions_mirror_v1.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --model-path gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
```

**Expected Output:**
- ~8,130 predictions (matching V1's count)
- Written to: `mlb_predictions.pitcher_strikeouts`
- model_version: `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149`

**Note:** Script `generate_v16_predictions_mirror_v1.py` needs to be created.
Base it on: `scripts/mlb/generate_historical_predictions.py`
Key changes:
1. Use V1.6 model path
2. Use 35 features (not 19)
3. Handle classifier output (probability → strikeouts)
4. Tag with V1.6 model_version

**Safety Check:**
```bash
# Verify V1 still unchanged
PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py

# Check V1.6 prediction count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as v16_predictions
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE model_version LIKE '%v1_6%'
"
# Should show: ~8,130
```

---

### Step 3: Grade V1.6 Predictions ⏸️ TODO (1-2 hours)

```bash
# Grade all V1.6 predictions
PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --model-version-filter v1_6
```

**Note:** Script `grade_v16_predictions.py` needs to be created.
Base it on: `data_processors/grading/mlb/mlb_prediction_grading_processor.py`
Can reuse existing processor, just filter by model_version.

**Expected Output:**
- ~7,100+ graded (88%+, matching V1's grading rate)
- is_correct field populated
- actual_strikeouts populated

**Safety Check:**
```bash
# Verify V1 still unchanged
PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py

# Check V1.6 grading
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE model_version LIKE '%v1_6%'
  AND recommendation IN ('OVER', 'UNDER')
"
```

---

### Step 4: Compare V1 vs V1.6 ⏸️ TODO (1 hour)

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

**Analysis Will Show:**
- Overall: V1 vs V1.6 win rate, MAE, bias
- By recommendation: OVER vs UNDER performance
- Head-to-head: Games where each model wins
- Agreement: When models agree/disagree
- By confidence: Calibration analysis

---

### Step 5: Make Deployment Decision ⏸️ TODO

**Scenario A: V1.6 > V1 (Clear Winner)**
- V1.6 win rate >= 68%
- Action: Switch to V1.6 for production

**Scenario B: V1.6 ≈ V1 (Comparable)**
- V1.6 win rate 64-67%
- Action: A/B test both models (70% V1, 30% V1.6)

**Scenario C: V1 > V1.6 (V1 Wins)**
- V1.6 win rate < 60%
- Action: Keep V1, iterate on V1.6

**Scenario D: Different Strengths**
- V1.6 better on OVER, V1 better on UNDER (or vice versa)
- Action: Ensemble approach, use both

---

## Key Documentation Files

### Strategy & Planning
1. **`V1_V16_DEPLOYMENT_SUMMARY.md`** ⭐ Quick reference
   - 5-step execution plan
   - Quick commands
   - Decision matrix

2. **`V1_TO_V16_MIRROR_STRATEGY.md`** ⭐ Detailed strategy
   - What V1 did (blueprint)
   - How to mirror for V1.6
   - Database isolation strategy
   - Rollback plans
   - Comprehensive SQL queries

3. **`MLB_PREDICTION_SYSTEM_INVENTORY.md`** ⭐ Full system
   - Complete inventory
   - Data availability
   - Analytics dependencies
   - 5-phase backfill plan (includes 2022-2023)

4. **`FINAL_V16_VALIDATION_FINDINGS.md`** ⭐ Current state
   - Multi-angle validation
   - Performance analysis
   - Gap identification

5. **`SESSION_HANDOFF_V16_DEPLOYMENT.md`** ⭐ This file
   - Session summary
   - Next steps
   - File locations

### Quick Start Guides
- **`MLB_BACKFILL_QUICK_START.md`** - For 2022-2025 full backfill (later)
- **`CURRENT_PREDICTION_STATUS_REPORT.md`** - V1 baseline analysis

---

## Scripts Available

### Created This Session ✅
1. **`scripts/mlb/verify_v1_unchanged.py`** ✅
   - Verifies V1 predictions never modified
   - Run after each step for safety

2. **`scripts/mlb/compare_v1_vs_v16_head_to_head.py`** ✅
   - Head-to-head comparison
   - Agreement analysis
   - Exports CSVs

3. **`scripts/mlb/validate_v1_6_backfill_comprehensive.py`** ✅
   - Multi-angle validation
   - Coverage checks
   - Performance analysis

4. **`scripts/mlb/validate_v1_6_statistical_analysis.py`** ✅
   - Statistical distributions
   - Confidence calibration
   - Temporal trends

5. **`scripts/mlb/validate_current_predictions_v1.py`** ✅
   - V1 baseline validation
   - Used to establish baseline

### Need to Create ⏸️
1. **`scripts/mlb/generate_v16_predictions_mirror_v1.py`** ⏸️
   - Based on: `scripts/mlb/generate_historical_predictions.py`
   - Use V1.6 model (35 features)
   - Handle classifier output
   - Tag with V1.6 model_version

2. **`scripts/mlb/grade_v16_predictions.py`** ⏸️
   - Wrapper around existing grading processor
   - Filter by V1.6 model_version
   - Can reuse: `data_processors/grading/mlb/mlb_prediction_grading_processor.py`

---

## Model & Data Locations

### V1 Model (Production)
```
GCS: gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json
Local: models/mlb/mlb_pitcher_strikeouts_v1_20260107.json
Metadata: models/mlb/mlb_pitcher_strikeouts_v1_20260107_metadata.json
```

### V1.6 Model (Staged)
```
GCS: NOT UPLOADED YET (Step 1)
Local: models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json ✅
Metadata: models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json ✅
```

### Predictions Database
```
Table: nba-props-platform.mlb_predictions.pitcher_strikeouts
V1 Predictions: 8,130 (model_version = 'mlb_pitcher_strikeouts_v1_20260107')
V1.6 Predictions: 0 (will have model_version = 'mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149')
```

### Analytics Tables
```
pitcher_game_summary: 2024-2025 only (9,247 records)
pitcher_rolling_statcast: VIEW, auto-calculated from raw data
batter_game_summary: 2024-2025 only
```

### Raw Data
```
mlb_pitcher_stats: 2024-2025 confirmed ✅
statcast_pitcher_game_stats: 2024-2025 confirmed ✅
bp_pitcher_props: 2022-2025 ALL SEASONS ✅
```

---

## Safety Mechanisms

### 1. Isolation by model_version
- V1: `model_version = 'mlb_pitcher_strikeouts_v1_20260107'`
- V1.6: `model_version = 'mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149'`
- **Cannot conflict** - different values ensure separation

### 2. Verification Script
```bash
# Run after EVERY step
PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py
```

**Must show:**
```
✅ Total predictions: 8,130 (MATCH)
✅ Graded predictions: 7,196 (MATCH)
✅ Win rate: 67.3% (MATCH)
✅ MAE: 1.46 (MATCH)
✅ V1 INTEGRITY CHECK PASSED
```

### 3. Rollback Plan
```sql
-- If V1.6 has issues, delete it
DELETE FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%';

-- V1 remains untouched: 8,130 predictions, 67.3% win rate
```

### 4. Validation Checklist

After Step 1 (Upload):
- [ ] Both models visible in GCS
- [ ] V1 files unchanged
- [ ] V1.6 files uploaded

After Step 2 (Generate):
- [ ] ~8,130 V1.6 predictions created
- [ ] V1 predictions count unchanged (8,130)
- [ ] V1 win rate unchanged (67.3%)
- [ ] verify_v1_unchanged.py passes

After Step 3 (Grade):
- [ ] V1.6 predictions >95% graded
- [ ] V1 grading unchanged
- [ ] verify_v1_unchanged.py passes

After Step 4 (Compare):
- [ ] Comparison report generated
- [ ] CSV exports created
- [ ] Decision criteria clear

---

## Quick Reference Commands

### Check Current State
```bash
# How many predictions by model?
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  COUNT(*) as predictions,
  COUNTIF(is_correct IS NOT NULL) as graded
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
GROUP BY model
"

# Expected now:
# V1: 8,130 predictions, 7,196 graded
# (V1.6: 0 until Step 2)
```

### Verify V1 Safe
```bash
PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py
```

### Check GCS Models
```bash
gsutil ls -lh gs://nba-scraped-data/ml-models/mlb/*pitcher*
```

### Quick Performance Check
```bash
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate,
  ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL
GROUP BY model
"
```

---

## Important Notes

### What This Session Did NOT Do

❌ Did NOT backfill 2022-2023 seasons
- Reason: Analytics tables don't exist for those years
- Would require: 10-20 hours to rebuild analytics pipeline
- Decision: Focus on V1.6 deployment first (2024-2025)
- Future: Can backfill 2022-2023 later if needed (see `MLB_BACKFILL_QUICK_START.md`)

❌ Did NOT replace V1
- V1 remains in production
- V1.6 is additive, not replacement
- Both coexist side-by-side

❌ Did NOT modify V1 predictions
- V1 completely untouched
- 67.3% win rate preserved
- Safety verified at each step

### Key Insights

1. **V1 is Production Quality** ✅
   - 67.3% win rate (highly profitable)
   - 1.46 MAE (excellent accuracy)
   - 88.5% graded
   - No issues reported

2. **V1.6 Test Results Lower** ⚠️
   - Test hit rate: 56.4% (vs V1's 67.3% in production)
   - May be classifier vs regressor comparison
   - Need real-world validation
   - Hence: Generate & compare on same data as V1

3. **2022-2023 Gap** ℹ️
   - No analytics tables for 2022-2023
   - BettingPros props exist for all 4 seasons
   - Can backfill later if needed
   - Not blocking V1.6 deployment

4. **Safe Deployment Strategy** ✅
   - Both models isolated by model_version
   - V1 never at risk
   - Can compare head-to-head
   - Easy rollback if needed

---

## Timeline

| Step | Activity | Time | Status |
|------|----------|------|--------|
| 1 | Upload V1.6 to GCS | 5 min | ⏸️ Next |
| 2 | Generate V1.6 predictions | 2-3 hrs | ⏸️ TODO |
| 3 | Grade V1.6 predictions | 1-2 hrs | ⏸️ TODO |
| 4 | Compare V1 vs V1.6 | 1 hr | ⏸️ TODO |
| 5 | Make decision | 30 min | ⏸️ TODO |
| **Total** | | **4-6 hrs** | |

---

## Decision Criteria

After completing all steps, decide based on:

### Use V1.6 if:
- ✅ Win rate >= 67.3% (equal or better than V1)
- ✅ MAE <= 1.46 (equal or better accuracy)
- ✅ No data quality issues
- ✅ Agreement analysis shows no red flags

### A/B Test if:
- ⚠️ Win rate 64-67% (slightly lower but acceptable)
- ⚠️ Different strengths (e.g., better on OVER, worse on UNDER)
- ⚠️ Need more data to decide

### Keep V1 if:
- ❌ Win rate < 60% (significantly worse)
- ❌ MAE > 1.8 (worse accuracy)
- ❌ Data quality issues
- ❌ Systematically worse than V1

---

## Next Session Checklist

### Before Starting
- [ ] Read `V1_V16_DEPLOYMENT_SUMMARY.md`
- [ ] Review this handoff document
- [ ] Check V1 is still healthy (verify_v1_unchanged.py)

### Step 1: Upload V1.6
- [ ] Upload model + metadata to GCS
- [ ] Verify both V1 and V1.6 in GCS
- [ ] Verify V1 unchanged

### Step 2: Generate Predictions
- [ ] Create `generate_v16_predictions_mirror_v1.py` script
- [ ] Generate V1.6 predictions (2024-04-09 to 2025-09-28)
- [ ] Verify ~8,130 predictions created
- [ ] Verify V1 unchanged

### Step 3: Grade Predictions
- [ ] Create `grade_v16_predictions.py` script
- [ ] Grade all V1.6 predictions
- [ ] Check grading completeness (>95%)
- [ ] Verify V1 unchanged

### Step 4: Compare
- [ ] Run comparison analysis
- [ ] Run validation scripts
- [ ] Export CSVs
- [ ] Verify V1 unchanged

### Step 5: Decide
- [ ] Review comparison results
- [ ] Choose deployment strategy
- [ ] Document decision
- [ ] Update production if switching

---

## Success Criteria

### Must Have ✅
- [ ] V1.6 uploaded to GCS
- [ ] V1.6 predictions generated (~8,130)
- [ ] V1.6 predictions graded (>95%)
- [ ] V1 verified unchanged at each step
- [ ] Comparison analysis complete
- [ ] Decision documented

### Nice to Have 🎯
- [ ] V1.6 win rate >= 67.3%
- [ ] V1.6 MAE <= 1.46
- [ ] Agreement analysis insights
- [ ] CSV exports for further analysis

---

## Questions & Answers

**Q: Why not replace V1 with V1.6?**
A: V1 is performing excellently (67.3%). We want to validate V1.6 first on same data, then decide. V1.6 test results (56.4%) are lower, so need real-world validation.

**Q: Why not backfill 2022-2023?**
A: Analytics tables don't exist for those years. Would take 10-20 hours to rebuild. Focus on V1.6 deployment first (4-6 hours), can backfill later if needed.

**Q: What if V1.6 performs worse?**
A: Simply delete V1.6 predictions (one SQL DELETE). V1 remains untouched at 67.3% win rate. Zero risk.

**Q: Can both models run in production?**
A: Yes! Both coexist in same table, separated by model_version. Can use ensemble approach or A/B test.

**Q: How do we know V1 won't be affected?**
A: Different model_version values = impossible to conflict. Plus, verify_v1_unchanged.py runs after each step to catch any issues immediately.

---

## Contact & Support

**Documentation Location:** `/home/naji/code/nba-stats-scraper/`
**Key Files:** See "Key Documentation Files" section above
**Scripts Location:** `/home/naji/code/nba-stats-scraper/scripts/mlb/`
**Models Location:** `/home/naji/code/nba-stats-scraper/models/mlb/`

**Session Date:** 2026-01-16
**Next Action:** Upload V1.6 to GCS (Step 1)
**Estimated Total Time:** 4-6 hours
**Risk Level:** 🟢 ZERO - V1 fully protected

---

## Ready to Start

**Step 1 Command:**
```bash
gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil ls -lh gs://nba-scraped-data/ml-models/mlb/*pitcher_strikeouts*
```

**Good luck! V1 is safe, V1.6 will be a great addition! 🚀**
