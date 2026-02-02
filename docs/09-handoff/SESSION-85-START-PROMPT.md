# Session 85 Start Prompt - Model Attribution Validation

**Date**: Feb 2 (Evening) or Feb 3, 2026 (Morning)
**Previous**: Session 84 (Built model attribution tracking system)
**Priority**: Validate NEW V9 model + Verify model attribution working
**Status**: Code deployed, awaiting validation

---

## 🎯 Your Mission

### CRITICAL Priority 1: Validate NEW V9 Model Performance

**Context**: Session 82 deployed NEW V9 model (`catboost_v9_feb_02_retrain.cbm`), but we haven't validated it's actually working yet. Feb 2 was the FIRST day with predictions from this model.

**Check if Feb 2 games finished**:
```bash
bq query --use_legacy_sql=false "
SELECT game_status, COUNT(*)
FROM nba_reference.nba_schedule
WHERE game_date = DATE('2026-02-02')
GROUP BY 1"
```

**If game_status = 3 (Final), validate performance**:
```bash
./bin/validate-feb2-model-performance.sh
```

**What to look for**:
- ✅ catboost_v9 MAE ~4.12? → NEW model working
- ⚠️ catboost_v9 MAE >5.0? → OLD model or issue
- ✅ catboost_v9 High-edge HR ~74.6%? → NEW model working
- ⚠️ catboost_v9 High-edge HR ~50%? → OLD model or issue

**Important**: Feb 2 was a RED signal day (79.5% UNDER bias). Hit rate may be lower than expected even if model is working correctly.

---

### Priority 2: Verify Model Attribution System Working

**Context**: Session 84 deployed model attribution tracking at 3:22 PM PST on Feb 2. The system adds 6 new fields to every prediction to track which exact model file generated it.

**Check if Feb 3 predictions exist**:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-03')
  AND system_id = 'catboost_v9'"
```

**If predictions exist (count > 100), verify attribution**:
```bash
./bin/verify-model-attribution.sh
```

**Expected output (Success)**:
```
CatBoost V9 Coverage: 100.0%
✅ PASS: Model attribution is working correctly
```

**Expected output (Failure)**:
```
CatBoost V9 Coverage: 0.0%
❌ FAIL: Model attribution is not working
```

**If failure**: Check `docs/09-handoff/2026-02-02-SESSION-84-HANDOFF.md` troubleshooting section.

---

### Priority 3: Answer Session 83 Question

**Question**: Which model version produced the 75.9% historical hit rate for v9_top5 subset?

**Background**: Session 83 reported "v9_top5 has 75.9% historical hit rate" but we couldn't determine if this was from the OLD model (MAE 5.08) or NEW model (MAE 4.12) because there was no model tracking.

**Query** (run after verifying attribution is working):
```sql
-- Historical performance by model file
SELECT
  model_file_name,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL  -- Only predictions with attribution
  AND ABS(predicted_points - line_value) >= 5  -- High-edge picks (v9_top5 filter)
GROUP BY model_file_name
ORDER BY last_game DESC;
```

**Expected result**:
```
catboost_v9_feb_02_retrain.cbm  | 1,245 | 75.9% | 4.12 | 2026-02-03 | 2026-02-03
catboost_v9_2026_02.cbm         |   832 | 50.8% | 5.08 | 2026-01-09 | 2026-02-02
```

**Note**: Feb 2 predictions won't have model attribution (generated at 1:38 PM before deployment at 3:22 PM). Attribution starts with Feb 3 predictions.

---

### Priority 4 (Optional): Analyze RED Signal Day Impact

**Context**: Feb 2 had extreme UNDER bias (79.5% UNDER, only 2.5% OVER) - a RED signal day.

**Hypothesis** (from Session 83): RED signal days have lower hit rate than GREEN days.

**Query** (after Feb 2 grading completes):
```sql
-- Feb 2 performance by recommendation
SELECT
  recommendation,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id = 'catboost_v9'
  AND ABS(predicted_points - line_value) >= 5  -- High-edge
  AND prediction_correct IS NOT NULL
GROUP BY recommendation;
```

**What to look for**: Did UNDER recommendations perform worse on this extreme UNDER-bias day?

---

## 📚 Context from Session 84

### What Was Built

Session 84 built a comprehensive model attribution tracking system to solve the "which model generated which predictions?" problem.

**Schema Changes**:
- Added 6 fields to `player_prop_predictions` table:
  - `model_file_name` - "catboost_v9_feb_02_retrain.cbm"
  - `model_training_start_date` - 2025-11-02
  - `model_training_end_date` - 2026-01-31
  - `model_expected_mae` - 4.12
  - `model_expected_hit_rate` - 74.6
  - `model_trained_at` - Timestamp

**Code Changes**:
- `catboost_v9.py` - Tracks model file name, emits metadata
- `worker.py` - Extracts and stores model attribution
- `verify-model-attribution.sh` - Verification script

**Documentation**:
- `docs/08-projects/current/model-attribution-tracking/` - Complete project docs
- `docs/09-handoff/2026-02-02-SESSION-84-HANDOFF.md` - Detailed handoff

### Deployment Timeline (Feb 2, 2026)

| Time (PST) | Event | Model Attribution Status |
|------------|-------|--------------------------|
| 1:38 PM | Feb 2 predictions generated | ❌ NO attribution (before deployment) |
| 3:22 PM | Model attribution deployed | ✅ Code ready |
| ~10:00 PM | Feb 2 games finish (estimated) | Games in progress |
| ~11:00 PM (Feb 2) / 2:30 AM ET (Feb 3) | Early predictions for Feb 3 | ✅ WILL have attribution |

**Key Point**: Feb 2 predictions do NOT have model attribution. Feb 3 predictions WILL have attribution.

### Current State

**Schema**: ✅ Applied to BigQuery
**Code**: ✅ Deployed (commit 5002a7d1, revision prediction-worker-00078-2wt)
**Verification**: ⏳ Pending (awaiting Feb 3 predictions)

---

## 🔍 Validation Checklist

Run these in order:

### Step 1: Check Game Status
```bash
bq query --use_legacy_sql=false "
SELECT game_status,
  CASE game_status
    WHEN 1 THEN 'Scheduled'
    WHEN 2 THEN 'In Progress'
    WHEN 3 THEN 'Final'
  END as status_text,
  COUNT(*) as game_count
FROM nba_reference.nba_schedule
WHERE game_date = DATE('2026-02-02')
GROUP BY 1, 2"
```

- ✅ All games status = 3? → Proceed to Step 2
- ⏳ Games in progress or scheduled? → Wait

### Step 2: Validate Feb 2 Model Performance
```bash
./bin/validate-feb2-model-performance.sh
```

Expected output includes:
- Overall catboost_v9 performance (MAE, hit rate, bias)
- Comparison vs catboost_v9_2026_02 (OLD model)
- Performance by confidence/edge tier
- UNDER vs OVER recommendation breakdown

**Success criteria**:
- catboost_v9 MAE between 4.0-4.5
- catboost_v9 high-edge HR between 70-80%
- catboost_v9 outperforms catboost_v9_2026_02

### Step 3: Check Feb 3 Predictions
```bash
bq query --use_legacy_sql=false "
SELECT game_date, system_id, COUNT(*) as predictions,
  MIN(created_at) as first_created,
  MAX(created_at) as last_created
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-03')
GROUP BY 1, 2
ORDER BY 1, 2"
```

- ✅ catboost_v9 count > 100? → Predictions exist, proceed to Step 4
- ⏳ Count = 0? → Wait for prediction run (2:30 AM or 7:00 AM ET)

### Step 4: Verify Model Attribution
```bash
./bin/verify-model-attribution.sh
```

This will check:
- Coverage percentage (should be 100% for Feb 3+)
- Model file distribution
- GCS bucket verification
- Sample predictions with full attribution

**Success criteria**: Coverage = 100.0%

### Step 5: Answer Historical Question
```sql
-- Run the query from Priority 3 above
SELECT model_file_name, COUNT(*), hit_rate, mae
FROM prediction_accuracy
WHERE model_file_name IS NOT NULL
  AND ABS(predicted_points - line_value) >= 5
GROUP BY model_file_name;
```

**Success criteria**: Can distinguish OLD vs NEW model performance

---

## 🔧 If Things Go Wrong

### Issue: Feb 2 Games Haven't Finished

**Symptom**: game_status = 1 or 2 (not 3)

**Action**: Wait. Games typically finish by midnight ET (9 PM PT).

**Check again**: In 1-2 hours

---

### Issue: Feb 2 Performance Doesn't Match Expectations

**Symptom**: catboost_v9 MAE >5.0 or HR <60%

**Possible causes**:
1. **RED signal day effect** - Feb 2 had extreme UNDER bias, may lower HR
2. **OLD model still running** - Session 82 deployment failed
3. **Small sample size** - Only 4 games on Feb 2

**Diagnosis**:
```bash
# Compare to OLD model
bq query --use_legacy_sql=false "
SELECT system_id,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id IN ('catboost_v9', 'catboost_v9_2026_02')
GROUP BY 1"
```

**Action**:
- If catboost_v9 ≈ catboost_v9_2026_02: May be using same model (bug)
- If catboost_v9 < catboost_v9_2026_02: NEW model working, just RED day effect
- If small sample: Don't over-interpret, wait for more data

---

### Issue: Model Attribution Coverage <100%

**Symptom**: `verify-model-attribution.sh` shows coverage 50% or 0%

**Diagnosis**:
```bash
# Check deployment
./bin/check-deployment-drift.sh --verbose

# Check commit
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Should be: 5002a7d1
```

**Action**:
1. If wrong commit → Redeploy:
   ```bash
   ./bin/deploy-service.sh prediction-worker
   ```

2. If correct commit → Check worker logs:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision"
     AND resource.labels.service_name="prediction-worker"
     AND timestamp>="2026-02-03T00:00:00Z"' --limit=20
   ```

3. See full troubleshooting guide in Session 84 handoff

---

### Issue: No Feb 3 Predictions Yet

**Symptom**: Query returns 0 predictions for Feb 3

**Cause**: Prediction run hasn't happened yet

**Prediction schedule**:
- 2:30 AM ET (11:30 PM PT) - Early predictions
- 7:00 AM ET (4:00 AM PT) - Overnight predictions
- 11:30 AM ET (8:30 AM PT) - Same-day predictions

**Action**: Wait for next scheduled run, then re-check

---

## 📖 Documentation Reference

### Session 84 Handoff (MUST READ)
**File**: `docs/09-handoff/2026-02-02-SESSION-84-HANDOFF.md`

This has:
- Complete deployment details
- Troubleshooting guide
- Known issues
- All context you need

### Project Documentation
**Directory**: `docs/08-projects/current/model-attribution-tracking/`

Files:
- `README.md` - Overview, use cases, quick start
- `DESIGN.md` - Architecture, data model, decisions
- `IMPLEMENTATION.md` - Deployment guide, verification queries

### Code Files
- `predictions/worker/prediction_systems/catboost_v9.py` - Model system
- `predictions/worker/worker.py` - Worker formatter (lines 1811-1827)
- `bin/verify-model-attribution.sh` - Verification script

---

## 🎯 Success Criteria

By end of this session, you should have:

1. ✅ **Validated NEW V9 model performance**
   - Confirmed MAE ~4.12
   - Confirmed high-edge HR ~70-80%
   - Understood RED signal day impact (if applicable)

2. ✅ **Verified model attribution working**
   - 100% coverage for Feb 3+ predictions
   - Can see exact model file names
   - All 6 fields populated correctly

3. ✅ **Answered Session 83 question**
   - Identified which model = 75.9% HR
   - Distinguished OLD vs NEW performance
   - Can show model file provenance

4. ✅ **Updated documentation**
   - Added findings to session handoff
   - Updated CLAUDE.md if needed

**Bonus**:
- 📋 Enhanced notifications with model metadata (Task #4 from Session 83)
- 📋 Analyzed RED signal hypothesis
- 📋 Compared Feb 2 vs Feb 3 performance

---

## 💡 Key Context

### The Problem We're Solving

**Session 83 Finding**: "v9_top5 subset has 75.9% historical hit rate"

**Question**: Which model version produced this?
- OLD model (`catboost_v9_2026_02.cbm`)? Expected MAE 5.08, HR 50.84%
- NEW model (`catboost_v9_feb_02_retrain.cbm`)? Expected MAE 4.12, HR 74.6%

**Before Session 84**: UNKNOWN - no way to tell!

**After Session 84**: Can query `model_file_name` field to know exactly which model generated which predictions.

### Why This Matters

1. **Model debugging** - When HR changes, we can identify if it's due to model changes or data changes
2. **A/B testing** - Can compare model versions with confidence
3. **Compliance** - Full audit trail for all predictions
4. **Rollback decisions** - Can identify which model to rollback to
5. **Historical analysis** - Can analyze performance by model version

---

## 🚀 Quick Start

**If you're starting fresh**, run these commands in order:

```bash
# 1. Read the handoff
cat docs/09-handoff/2026-02-02-SESSION-84-HANDOFF.md

# 2. Check if Feb 2 games finished
bq query --use_legacy_sql=false "
SELECT game_status, COUNT(*)
FROM nba_reference.nba_schedule
WHERE game_date = DATE('2026-02-02')
GROUP BY 1"

# 3. If games finished, validate Feb 2 performance
./bin/validate-feb2-model-performance.sh

# 4. Check if Feb 3 predictions exist
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-03') AND system_id = 'catboost_v9'"

# 5. If predictions exist, verify attribution
./bin/verify-model-attribution.sh

# 6. If attribution working, answer historical question
# (See Priority 3 query above)
```

---

## 📅 Timeline Reference

### Feb 2, 2026
- **1:38 PM PST**: Predictions generated (no attribution)
- **3:22 PM PST**: Model attribution deployed
- **~10:00 PM PST**: Games finish (estimated)
- **~11:30 PM PST**: Grading runs

### Feb 3, 2026
- **2:30 AM ET (11:30 PM PT Feb 2)**: Early predictions (WITH attribution)
- **7:00 AM ET (4:00 AM PT)**: Overnight predictions (WITH attribution)

---

## ❓ Questions to Ask User

1. **What time is it?** - Determines which tasks are ready
2. **Have Feb 2 games finished?** - Check game_status in schedule
3. **Do Feb 3 predictions exist?** - Check prediction count
4. **What's the priority?** - Validation, analysis, or enhancements?

---

## 🎓 Expected Learning Outcomes

By end of this session, you'll understand:

1. How to validate ML model deployments
2. How to verify new database fields are being populated
3. How to distinguish between model versions in historical data
4. How to troubleshoot deployment issues
5. How RED/GREEN signal days affect performance

---

**TL;DR**:
1. Validate Feb 2 model performance (after games finish)
2. Verify model attribution working (after Feb 3 predictions)
3. Answer "which model = 75.9% HR?" question
4. Document findings

**Start here**: Check if Feb 2 games finished, then run validation script.

**Need help?**: Read `docs/09-handoff/2026-02-02-SESSION-84-HANDOFF.md`
