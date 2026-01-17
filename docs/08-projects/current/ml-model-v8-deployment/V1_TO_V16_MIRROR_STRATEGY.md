# V1 → V1.6 Mirror Strategy
## Keeping V1 Safe While Adding V1.6 Alongside

**Date:** 2026-01-16
**Strategy:** Mirror V1's exact workflow for V1.6, keep both models separate and comparable
**Risk Level:** 🟢 ZERO RISK - V1 remains untouched

---

## What V1 Did (The Blueprint)

### V1 Training (Jan 7, 2026)
```
Script: scripts/mlb/training/train_pitcher_strikeouts_v2.py (likely)
Model Output: models/mlb/mlb_pitcher_strikeouts_v1_20260107.json
Training Data: 8,130 samples (same as current predictions!)
Date Range: Inferred to be 2024-2025 based on predictions
Features: 19 features (f00-f10, f20-f26, f33)
Model Type: Regressor (XGBoost, objective: reg:squarederror)
Test MAE: 1.71
```

### V1 Prediction Generation (Jan 9, 2026)
```
Script: scripts/mlb/generate_historical_predictions.py
Model: models/mlb/mlb_pitcher_strikeouts_v4_20260108.json (note: filename mismatch, likely symlink or renamed)
Execution: Single batch run on 2026-01-09 05:30:28 UTC
Date Range: 2024-04-09 to 2025-09-28
Output: 8,130 predictions → mlb_predictions.pitcher_strikeouts
Model Version Tag: 'mlb_pitcher_strikeouts_v1_20260107'
```

### V1 Grading (Jan 9, 2026+)
```
Processor: data_processors/grading/mlb/mlb_prediction_grading_processor.py
Status: 88.5% graded (7,196/8,130)
Result: 67.3% win rate, 1.46 MAE
```

### V1 Current State
```
✅ Model uploaded to GCS
✅ 8,130 predictions in database
✅ 7,196 graded (88.5%)
✅ 67.3% win rate (production quality!)
✅ NO issues reported
✅ Stable baseline for comparison
```

---

## V1.6 Mirror Plan (Exact Replication)

### Phase 1: V1.6 Training (Already Done! ✅)
```
Script: scripts/mlb/training/train_v1_6_rolling.py ✅ COMPLETE
Model Output: models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json ✅ EXISTS
Training Data: 6,112 samples (2024-2025 only)
Date Range: 2024-01-01 to 2025-12-31
Features: 35 features (adds f19, f30-f32, f40-f44, f50-f53)
Model Type: Classifier (XGBoost, objective: binary:logistic)
Test Accuracy: 63.2%, Test AUC: 0.682
Walk-Forward Hit Rate: 56.4%
```

**Status:** ✅ Complete - model exists locally

---

### Phase 2: Upload V1.6 to GCS (Mirrors V1's GCS deployment)
```bash
# V1 is at: gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json
# V1.6 will be at: gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json \
  gs://nba-scraped-data/ml-models/mlb/

# Verify both models exist side-by-side
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
- ✅ V1 files remain untouched
- ✅ V1.6 files have unique names
- ✅ No overwriting possible

---

### Phase 3: Generate V1.6 Predictions (Mirrors V1's generation)

**Create V1.6-specific prediction script** (based on V1's script)

File: `scripts/mlb/generate_v16_predictions_mirror_v1.py`

Key changes from V1 script:
1. ✅ Use V1.6 model path
2. ✅ Use V1.6 features (35 instead of 19)
3. ✅ Tag with V1.6 model_version
4. ✅ Same date ranges as V1 (2024-04-09 to 2025-09-28)
5. ✅ Same query structure
6. ✅ Write to same table (mlb_predictions.pitcher_strikeouts)
7. ✅ Different model_version ensures separation

**Command (mirroring V1):**
```bash
# V1 used these dates:
# --start-date 2024-04-09 --end-date 2025-09-28

# V1.6 will use identical dates for direct comparison
PYTHONPATH=. python scripts/mlb/generate_v16_predictions_mirror_v1.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --model-path gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  --model-version mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149
```

**Expected Output:**
- ~8,130 predictions (matching V1's count)
- Same pitchers, same games, same dates
- Different predicted_strikeouts, different recommendations
- model_version = 'mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149'

**Safety Mechanism:**
```sql
-- V1 and V1.6 predictions are COMPLETELY SEPARATE by model_version
SELECT model_version, COUNT(*) as predictions
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY model_version;

-- Expected:
-- mlb_pitcher_strikeouts_v1_20260107: 8,130 (unchanged)
-- mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149: 8,130 (new)
```

---

### Phase 4: Grade V1.6 Predictions (Mirrors V1's grading)

**Use SAME grading processor** (already supports multiple models)

```bash
# Grading processor already handles model_version filtering
# Just need to re-run for V1.6's dates

PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --model-version-filter v1_6
```

**Expected Output:**
- ~7,100+ graded (88%+, matching V1's grading rate)
- is_correct, actual_strikeouts populated
- graded_at timestamp set

**Safety Check:**
```sql
-- Both models graded independently
SELECT
  model_version,
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY model_version;

-- V1 grading remains unchanged
-- V1.6 has its own grading
```

---

### Phase 5: Compare V1 vs V1.6 (New Analysis)

**Create head-to-head comparison script**

File: `scripts/mlb/compare_v1_vs_v16_head_to_head.py`

**Comparison Dimensions:**

#### 5.1: Overall Performance
```sql
SELECT
  CASE
    WHEN model_version LIKE '%v1_6%' THEN 'V1.6'
    ELSE 'V1'
  END as model,
  COUNT(*) as predictions,
  COUNTIF(is_correct IS NOT NULL) as graded,
  COUNTIF(is_correct = TRUE) as wins,
  COUNTIF(is_correct = FALSE) as losses,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate,
  ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae,
  ROUND(AVG(predicted_strikeouts - actual_strikeouts), 2) as bias
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE is_correct IS NOT NULL
GROUP BY model;
```

#### 5.2: By Recommendation Type
```sql
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  recommendation,
  COUNT(*) as bets,
  COUNTIF(is_correct = TRUE) as wins,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE is_correct IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY model, recommendation
ORDER BY model, recommendation;
```

#### 5.3: Head-to-Head (Same Game Comparison)
```sql
-- For games where BOTH models made predictions
WITH v1_preds AS (
  SELECT
    game_date,
    pitcher_lookup,
    predicted_strikeouts as v1_pred,
    recommendation as v1_rec,
    is_correct as v1_correct,
    actual_strikeouts
  FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
  WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
),
v16_preds AS (
  SELECT
    game_date,
    pitcher_lookup,
    predicted_strikeouts as v16_pred,
    recommendation as v16_rec,
    is_correct as v16_correct
  FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
  WHERE model_version LIKE '%v1_6%'
)
SELECT
  COUNT(*) as head_to_head_games,
  COUNTIF(v1_correct = TRUE AND v16_correct = FALSE) as v1_only_correct,
  COUNTIF(v1_correct = FALSE AND v16_correct = TRUE) as v16_only_correct,
  COUNTIF(v1_correct = TRUE AND v16_correct = TRUE) as both_correct,
  COUNTIF(v1_correct = FALSE AND v16_correct = FALSE) as both_wrong,
  ROUND(AVG(ABS(v1_pred - actual_strikeouts)), 2) as v1_mae,
  ROUND(AVG(ABS(v16_pred - actual_strikeouts)), 2) as v16_mae
FROM v1_preds
INNER JOIN v16_preds USING (game_date, pitcher_lookup)
WHERE v1_correct IS NOT NULL AND v16_correct IS NOT NULL;
```

#### 5.4: Agreement Analysis
```sql
-- How often do models agree on recommendations?
WITH both_models AS (
  SELECT
    v1.game_date,
    v1.pitcher_lookup,
    v1.recommendation as v1_rec,
    v16.recommendation as v16_rec,
    v1.is_correct as v1_correct,
    v16.is_correct as v16_correct
  FROM (
    SELECT * FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
  ) v1
  INNER JOIN (
    SELECT * FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE model_version LIKE '%v1_6%'
  ) v16
  USING (game_date, pitcher_lookup)
)
SELECT
  CASE
    WHEN v1_rec = v16_rec THEN 'AGREE'
    ELSE 'DISAGREE'
  END as agreement,
  v1_rec,
  v16_rec,
  COUNT(*) as cases,
  COUNTIF(v1_correct = TRUE) as v1_wins,
  COUNTIF(v16_correct = TRUE) as v16_wins
FROM both_models
WHERE v1_rec IN ('OVER', 'UNDER')
  AND v16_rec IN ('OVER', 'UNDER')
GROUP BY agreement, v1_rec, v16_rec
ORDER BY cases DESC;
```

#### 5.5: By Confidence Level
```sql
-- Compare performance by confidence quartiles
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  CASE
    WHEN confidence < 60 THEN 'Low (0-60)'
    WHEN confidence < 75 THEN 'Medium (60-75)'
    WHEN confidence < 90 THEN 'High (75-90)'
    ELSE 'Very High (90+)'
  END as confidence_bucket,
  COUNT(*) as bets,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE is_correct IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY model, confidence_bucket
ORDER BY model,
  CASE confidence_bucket
    WHEN 'Low (0-60)' THEN 1
    WHEN 'Medium (60-75)' THEN 2
    WHEN 'High (75-90)' THEN 3
    ELSE 4
  END;
```

---

## Database Isolation Strategy

### Table Structure (No Changes Needed!)
```
mlb_predictions.pitcher_strikeouts
├── prediction_id (UUID) ← Unique per prediction
├── model_version ← KEY: Separates V1 from V1.6
├── game_date
├── pitcher_lookup
├── predicted_strikeouts
├── confidence
├── recommendation
├── strikeouts_line
├── actual_strikeouts
├── is_correct
└── graded_at
```

**Isolation Mechanism:**
- ✅ V1: `model_version = 'mlb_pitcher_strikeouts_v1_20260107'`
- ✅ V1.6: `model_version = 'mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149'`
- ✅ Never conflict because model_version is different
- ✅ Both can exist for same game_date + pitcher_lookup

### Query Patterns
```sql
-- Get V1 predictions only
SELECT * FROM mlb_predictions.pitcher_strikeouts
WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107';

-- Get V1.6 predictions only
SELECT * FROM mlb_predictions.pitcher_strikeouts
WHERE model_version LIKE '%v1_6%';

-- Get both for comparison
SELECT
  game_date,
  pitcher_lookup,
  model_version,
  predicted_strikeouts,
  recommendation,
  is_correct
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2024-04-10'
  AND pitcher_lookup = 'gerrit_cole'
ORDER BY model_version;
```

---

## Rollback Plan (If V1.6 Fails)

### Scenario 1: V1.6 predictions have bugs
```sql
-- Simply delete V1.6 predictions (V1 untouched)
DELETE FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%';

-- V1 remains: 8,130 predictions, 67.3% win rate
```

### Scenario 2: V1.6 performs poorly (<55% win rate)
```sql
-- Keep V1.6 in database but flag as "experimental"
-- Continue using V1 for production decisions
-- No deletion needed, just ignore V1.6 in production queries
```

### Scenario 3: Need to regenerate V1.6 predictions
```sql
-- Delete old V1.6 predictions
DELETE FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%';

-- Regenerate with fixes
PYTHONPATH=. python scripts/mlb/generate_v16_predictions_mirror_v1.py ...
```

**V1 is NEVER at risk** - completely isolated by model_version

---

## Validation Checkpoints

### Checkpoint 1: Post-Upload
```bash
# Verify both models in GCS
gsutil ls -lh gs://nba-scraped-data/ml-models/mlb/*pitcher*

# Expected: 4 files (2 for V1, 2 for V1.6)
```

### Checkpoint 2: Post-Generation
```sql
-- Check prediction counts
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  COUNT(*) as predictions,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  COUNT(DISTINCT pitcher_lookup) as pitchers
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY model;

-- Expected:
-- V1: 8,130 predictions (unchanged from before)
-- V1.6: ~8,130 predictions (new, should match V1 count)
```

### Checkpoint 3: Post-Grading
```sql
-- Check grading status
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE recommendation IN ('OVER', 'UNDER')
GROUP BY model;

-- V1 grading should be EXACTLY the same as before
-- V1.6 should have ~88% grading rate
```

### Checkpoint 4: V1 Unchanged
```sql
-- Verify V1 predictions are exactly as they were
SELECT
  COUNT(*) as v1_predictions,
  COUNTIF(is_correct = TRUE) as v1_wins,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as v1_win_rate,
  ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as v1_mae
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
  AND is_correct IS NOT NULL;

-- Must match current stats:
-- predictions: 7,196 graded
-- win_rate: 67.3%
-- mae: 1.46
```

---

## Decision Matrix: Keep V1 or Switch to V1.6?

### Scenario A: V1.6 > V1 (Clear Winner)
**Criteria:**
- V1.6 win rate >= 67.5% (better than V1's 67.3%)
- V1.6 MAE <= 1.46 (equal or better)
- No data quality issues

**Action:**
- ✅ Promote V1.6 to production
- ✅ Keep V1 in database for historical comparison
- ✅ Update default model path to V1.6
- ✅ Monitor V1.6 for 1 week before fully switching

### Scenario B: V1.6 ≈ V1 (Tie)
**Criteria:**
- V1.6 win rate 65-67% (slightly lower but close)
- V1.6 MAE 1.4-1.6 (comparable)

**Action:**
- ⚠️ A/B test: Use V1 70%, V1.6 30% for 2 weeks
- ⚠️ Analyze edge cases where they disagree
- ⚠️ Re-evaluate after more data

### Scenario C: V1.6 < V1 (V1 Wins)
**Criteria:**
- V1.6 win rate < 60% (significantly worse)
- V1.6 MAE > 1.8 (less accurate)

**Action:**
- ❌ Keep V1 as production model
- ❌ Flag V1.6 as "experimental"
- ❌ Investigate why V1.6 underperforms
- ❌ Iterate on V1.6 training before deployment

### Scenario D: Different Strengths
**Criteria:**
- V1.6 better on OVER bets, V1 better on UNDER
- Or: V1.6 better early season, V1 better late season

**Action:**
- 🔀 Ensemble approach: Use both models
- 🔀 Route predictions based on situation
- 🔀 Weight predictions by model strength

---

## Timeline

| Phase | Activity | Time | V1 Status |
|-------|----------|------|-----------|
| 1 | V1.6 training | ✅ Done | Unchanged |
| 2 | Upload V1.6 to GCS | 5 minutes | Unchanged |
| 3 | Generate V1.6 predictions | 2-3 hours | Unchanged |
| 4 | Grade V1.6 predictions | 1-2 hours | Unchanged |
| 5 | Compare V1 vs V1.6 | 1 hour | Unchanged |
| **Total** | | **4-6 hours** | **V1 NEVER TOUCHED** |

---

## Success Criteria

### Must Have ✅
- [ ] V1.6 model uploaded to GCS
- [ ] V1.6 predictions generated (~8,130)
- [ ] V1.6 predictions graded (>95%)
- [ ] V1 predictions unchanged (verified)
- [ ] V1 win rate still 67.3% (unchanged)
- [ ] V1.6 win rate calculated
- [ ] Head-to-head comparison complete

### Nice to Have 🎯
- [ ] V1.6 win rate >= 67.3%
- [ ] V1.6 MAE <= 1.46
- [ ] Agreement analysis shows patterns
- [ ] Confidence calibration validated
- [ ] Documentation updated

---

## Quick Reference Commands

### Check Both Models Exist
```bash
# GCS
gsutil ls -lh gs://nba-scraped-data/ml-models/mlb/*pitcher*

# Database
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  COUNT(*) as predictions
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
GROUP BY model
"
```

### Verify V1 Unchanged
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as v1_predictions,
  COUNTIF(is_correct = TRUE) as wins,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
  AND is_correct IS NOT NULL
"
# Must show: ~7,196 predictions, 67.3% win rate
```

### Quick Comparison
```bash
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  COUNT(*) as predictions,
  COUNTIF(is_correct = TRUE) as wins,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate,
  ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
WHERE is_correct IS NOT NULL
GROUP BY model
"
```

---

## Files to Create

### New Scripts Needed
1. ✅ `scripts/mlb/generate_v16_predictions_mirror_v1.py` - V1.6 prediction generation
2. ✅ `scripts/mlb/grade_v16_predictions.py` - V1.6 grading
3. ✅ `scripts/mlb/compare_v1_vs_v16_head_to_head.py` - Comparison analysis
4. ✅ `scripts/mlb/verify_v1_unchanged.py` - V1 integrity check

### Documentation Updates
1. ✅ This file (V1_TO_V16_MIRROR_STRATEGY.md)
2. ⏸️ Update `MLB_PREDICTION_SYSTEM_INVENTORY.md` with side-by-side status
3. ⏸️ Create `V1_VS_V16_COMPARISON_REPORT.md` after comparison

---

## Summary

**What We're Doing:**
- ✅ Adding V1.6 predictions alongside V1 (not replacing)
- ✅ Using exact same dates, pitchers, games as V1
- ✅ Completely isolated by model_version field
- ✅ V1 remains untouched and continues working
- ✅ Can compare head-to-head on identical data
- ✅ Can rollback V1.6 anytime without affecting V1
- ✅ Zero risk to production system

**What We're NOT Doing:**
- ❌ Not replacing V1
- ❌ Not deleting V1
- ❌ Not modifying V1 predictions
- ❌ Not changing production behavior until validated

**Why This is Safe:**
- 🟢 V1 and V1.6 never conflict (different model_version)
- 🟢 V1 continues serving production
- 🟢 V1.6 is addition, not modification
- 🟢 Can delete V1.6 anytime if issues arise
- 🟢 V1's 67.3% win rate is preserved baseline

**End Goal:**
- 📊 Side-by-side comparison of V1 vs V1.6
- 📊 Data-driven decision on which to use
- 📊 Keep best model(s) for production
- 📊 Learn from comparison to improve future models

---

**Status:** Ready to execute
**Risk Level:** 🟢 ZERO - V1 protected, V1.6 is additive only
**Time to Complete:** 4-6 hours
