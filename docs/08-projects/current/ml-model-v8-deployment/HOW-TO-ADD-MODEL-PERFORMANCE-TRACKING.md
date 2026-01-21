# How to Add Performance Tracking for New Models

**Created:** 2026-01-17
**Purpose:** Step-by-step template for adding performance tracking when deploying new prediction models
**Template Version:** 1.0

---

## Overview

This guide provides a standardized process for creating performance tracking documentation and queries when deploying new prediction models. Following this process ensures consistent monitoring across all models and enables easy comparison.

**Use this template when:**
- Deploying a new ML model (e.g., LightGBM, Neural Network)
- Creating a new version of an existing model (e.g., CatBoost V9)
- Adding a new prediction system (e.g., Rule-based V2)

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step-by-Step Process](#step-by-step-process)
3. [Documentation Template](#documentation-template)
4. [Required Queries](#required-queries)
5. [Testing Checklist](#testing-checklist)
6. [Examples](#examples)

---

## Prerequisites

Before adding performance tracking, ensure:

1. ✅ **Model is trained** and validated
   - Training MAE documented
   - Validation MAE documented
   - Feature importance analyzed

2. ✅ **Model is deployed** to production
   - Uploaded to GCS
   - Environment variable configured
   - Worker service redeployed
   - Health check passing

3. ✅ **System ID is unique**
   - Defined in prediction system code
   - Used consistently in database
   - No conflicts with existing models

4. ✅ **Predictions are being generated**
   - Verify predictions exist in `player_prop_predictions` table
   - Check `system_id` column matches

5. ✅ **Grading pipeline works**
   - Predictions are being graded in `prediction_accuracy` table
   - `system_id` is preserved in graded results

---

## Step-by-Step Process

### Step 1: Gather Model Metadata

Collect the following information about your model:

**Model Information:**
- [ ] Model ID (filename/identifier)
- [ ] System ID (used in database)
- [ ] Model type (XGBoost, CatBoost, LightGBM, etc.)
- [ ] Training date range
- [ ] Number of training samples
- [ ] Number of features
- [ ] Feature names and types
- [ ] Hyperparameters used
- [ ] Framework version

**Performance Baselines:**
- [ ] Training MAE
- [ ] Training RMSE
- [ ] Validation MAE
- [ ] Validation RMSE
- [ ] Within-N-points accuracy (3 pts, 5 pts)
- [ ] Best iteration (if using early stopping)
- [ ] Feature importance rankings (top 15)

**Deployment Information:**
- [ ] GCS model path
- [ ] Deployment date/time
- [ ] Worker revision ID
- [ ] Environment variable name
- [ ] Comparison to baseline models

**Template:**
```markdown
### Model Metadata

| Metric | Value |
|--------|-------|
| Model ID | {model_filename} |
| System ID | `{system_id}` |
| Training Samples | {training_count} |
| Training Date Range | {start_date} to {end_date} |
| Features | {feature_count} ({feature_version}) |
| Framework | {framework} {version} |
| **Validation MAE** | **{val_mae} points** |
| Training MAE | {train_mae} points |
| Model Path | {gcs_path} |
| Deployed | {deployment_datetime} UTC |
```

---

### Step 2: Create Performance Guide Document

Create a new file: `docs/08-projects/current/ml-model-v8-deployment/{MODEL_NAME}-PERFORMANCE-GUIDE.md`

**Naming Convention:**
- XGBoost V1 → `XGBOOST-V1-PERFORMANCE-GUIDE.md`
- CatBoost V9 → `CATBOOST-V9-PERFORMANCE-GUIDE.md`
- LightGBM V1 → `LIGHTGBM-V1-PERFORMANCE-GUIDE.md`

**Document Structure:** (See template below)

1. Quick Reference
2. Model Information
3. Performance Tracking Queries
4. Head-to-Head Comparison (vs existing models)
5. Confidence Tier Analysis
6. Feature Performance
7. Troubleshooting
8. Monitoring Recommendations
9. Retraining Triggers

---

### Step 3: Customize Core Queries

Replace `{SYSTEM_ID}` and `{DEPLOYMENT_DATE}` in all queries:

**Find/Replace:**
- `{SYSTEM_ID}` → Your model's system_id (e.g., `'xgboost_v1'`, `'catboost_v9'`)
- `{DEPLOYMENT_DATE}` → Deployment date (e.g., `'2026-01-17'`)
- `{CHAMPION_MODEL}` → Current best model to compare against (e.g., `'catboost_v8'`)

---

### Step 4: Test All Queries

Before finalizing documentation, test each query:

```bash
# Test basic performance query
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = '{SYSTEM_ID}'
  AND game_date >= '{DEPLOYMENT_DATE}'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
"
```

**Expected Results:**
- Query runs without errors
- Returns meaningful data (if predictions/grading exist)
- MAE is reasonable (within 1-2 points of validation MAE)

---

### Step 5: Add Head-to-Head Comparison

Create queries comparing your new model to the current champion:

**Template Query:**
```sql
WITH new_model_performance AS (
  SELECT
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    ROUND(AVG(absolute_error), 2) as mae,
    '{MODEL_NAME}' as model
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '{DEPLOYMENT_DATE}'
    AND system_id = '{SYSTEM_ID}'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
),
champion_performance AS (
  SELECT
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    ROUND(AVG(absolute_error), 2) as mae,
    '{CHAMPION_NAME}' as model
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '{DEPLOYMENT_DATE}'
    AND system_id = '{CHAMPION_SYSTEM_ID}'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  model,
  picks,
  wins,
  ROUND(SAFE_DIVIDE(wins, picks) * 100, 1) as win_rate,
  mae
FROM new_model_performance
UNION ALL
SELECT
  model,
  picks,
  wins,
  ROUND(SAFE_DIVIDE(wins, picks) * 100, 1) as win_rate,
  mae
FROM champion_performance
ORDER BY mae ASC
```

---

### Step 6: Document Monitoring Strategy

**Define alert thresholds based on validation performance:**

| Alert Level | Condition | Action |
|-------------|-----------|--------|
| WARNING | Production MAE > validation MAE + 0.5 for 3+ days | Investigate data quality |
| CRITICAL | Production MAE > validation MAE + 1.0 for 7+ days | Consider rollback |
| WARNING | Win rate < 50% for 7+ days | Review confidence calibration |
| CRITICAL | Placeholders appearing | Immediate fix required |
| INFO | Daily prediction volume drops >20% | Check feature availability |

**Add to your performance guide:**
```markdown
## Monitoring Recommendations

### Alert Thresholds

**Production MAE:**
- Target: ~{validation_mae} ± 0.5 points
- Warning: > {validation_mae + 0.5} for 3+ days
- Critical: > {validation_mae + 1.0} for 7+ days

**Win Rate:**
- Target: ≥ 52.4% (breakeven)
- Warning: < 50% for 7+ days
- Critical: < 45% for 14+ days
```

---

### Step 7: Add Retraining Guidelines

**Define when to retrain the model:**

```markdown
## Retraining Triggers

Consider retraining {MODEL_NAME} if:

1. **Performance Degradation**
   - Production MAE > {validation_mae + 1.0} for 14+ consecutive days
   - Win rate < 50% for 30+ consecutive days

2. **Seasonal Updates**
   - Quarterly retraining (every 3 months)
   - Add most recent season data

3. **Distribution Shift**
   - Significant rule changes (e.g., play-in tournament format)
   - Major meta shifts (e.g., pace changes league-wide)
   - Feature importance drift (top features change significantly)

**Retraining Process:**
```bash
# Step 1: Train new model with updated date range
PYTHONPATH=. python3 ml_models/nba/train_{model_script}.py \
  --start-date {original_start} \
  --end-date {new_end_date} \
  --upload-gcs

# Step 2: Compare metrics
# - Validation MAE should be ≤ {current_validation_mae}
# - Feature importance should be similar
# - No major regressions

# Step 3: Deploy if improvement
export {ENV_VAR_NAME}="gs://path/to/new/model.extension"
./bin/predictions/deploy/deploy_prediction_worker.sh prod

# Step 4: Monitor for 7-14 days
# - Compare production MAE to old model
# - Check for improvements
# - Validate no regressions
```
```

---

### Step 8: Update Index Documentation

Add your new model to the main performance tracking index:

**File:** `docs/08-projects/current/ml-model-v8-deployment/README.md`

Add entry:
```markdown
### Active Models

| Model | System ID | Guide | Deployed | Status |
|-------|-----------|-------|----------|--------|
| CatBoost V8 | catboost_v8 | [PERFORMANCE-ANALYSIS-GUIDE.md](PERFORMANCE-ANALYSIS-GUIDE.md) | 2024-11-XX | ✅ Champion |
| XGBoost V1 | xgboost_v1 | [XGBOOST-V1-PERFORMANCE-GUIDE.md](XGBOOST-V1-PERFORMANCE-GUIDE.md) | 2026-01-17 | ✅ Active |
| {Your Model} | {system_id} | [{GUIDE_NAME}]({GUIDE_NAME}) | {date} | ✅ Active |
```

---

## Documentation Template

**File:** `docs/08-projects/current/ml-model-v8-deployment/{MODEL_NAME}-PERFORMANCE-GUIDE.md`

### Minimum Sections Required

```markdown
# {Model Name} Performance Analysis Guide

**Created:** {date}
**Model:** {Model Name} ({description})
**Purpose:** Track {model} performance, compare to {champion}, and identify optimization opportunities

---

## Quick Reference

### Model Metadata
[Table with all model info]

### Baseline Performance (Validation Set)
[Table with MAE, RMSE, etc.]

### Quick Status Check
```bash
# Latest graded predictions
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as latest_graded, COUNT(*) as total_graded
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = '{SYSTEM_ID}'
"
```

---

## Model Information

### Training Configuration
[Hyperparameters, training setup]

### Feature Importance (Top 15)
[Table of most important features]

---

## Performance Tracking Queries

### Overall Production Performance
[Query for season summary]

### Daily Performance Trend
[Query for daily tracking]

### OVER vs UNDER Performance
[Query for directional analysis]

---

## Head-to-Head Comparison

### {Your Model} vs {Champion Model}
[Side-by-side comparison query]

### Same-Game Head-to-Head
[Query for overlapping picks]

---

## Confidence Tier Analysis

### Performance by Confidence Band
[Query to track calibration]

---

## Troubleshooting

### Low Production Performance
[Debugging steps]

### Missing Predictions
[Check prediction volume]

### Placeholders Appearing
[Validation gate check]

---

## Monitoring Recommendations

### Daily Checks (Automated)
[Alert thresholds]

### Weekly Reviews
[Manual analysis tasks]

### Monthly Analysis
[Long-term trends]

---

## Retraining Triggers

[When and how to retrain]

---

## Related Documentation

- Training Guide: {link}
- Model Metadata: {link}
- Deployment Guide: {link}
- Champion Model: {link}
```

---

## Required Queries

Every model performance guide MUST include these queries:

### 1. Overall Performance
```sql
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = '{SYSTEM_ID}'
  AND game_date >= '{DEPLOYMENT_DATE}'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
```

### 2. Daily Trend
```sql
SELECT
  game_date,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = '{SYSTEM_ID}'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date DESC
```

### 3. Confidence Tiers
```sql
WITH picks_with_tier AS (
  SELECT
    *,
    CASE
      WHEN confidence_score >= 0.90 THEN 'VERY HIGH (90%+)'
      WHEN confidence_score >= 0.70 THEN 'HIGH (70-90%)'
      WHEN confidence_score >= 0.55 THEN 'MEDIUM (55-70%)'
      ELSE 'LOW (<55%)'
    END as confidence_tier
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = '{SYSTEM_ID}'
    AND game_date >= '{DEPLOYMENT_DATE}'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  confidence_tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM picks_with_tier
GROUP BY confidence_tier
ORDER BY
  CASE confidence_tier
    WHEN 'VERY HIGH (90%+)' THEN 1
    WHEN 'HIGH (70-90%)' THEN 2
    WHEN 'MEDIUM (55-70%)' THEN 3
    ELSE 4
  END
```

### 4. OVER vs UNDER
```sql
SELECT
  recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = '{SYSTEM_ID}'
  AND game_date >= '{DEPLOYMENT_DATE}'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY recommendation
```

### 5. Head-to-Head vs Champion
```sql
-- (See Step 5 for full template)
```

---

## Testing Checklist

Before finalizing your performance guide:

### Pre-Deployment Testing
- [ ] Model training completed successfully
- [ ] Validation MAE meets target
- [ ] Model uploaded to GCS
- [ ] Environment variable configured
- [ ] Worker redeployed
- [ ] Health check passes
- [ ] System ID is unique

### Post-Deployment Testing
- [ ] Predictions appearing in `player_prop_predictions` table
- [ ] System ID matches in database
- [ ] Predictions being graded in `prediction_accuracy` table
- [ ] All required queries run without errors
- [ ] Query results make sense (MAE near validation)
- [ ] Head-to-head comparison query works
- [ ] Confidence tier query shows expected distribution

### Documentation Testing
- [ ] All placeholders replaced (`{SYSTEM_ID}`, `{DEPLOYMENT_DATE}`, etc.)
- [ ] Model metadata table complete
- [ ] Feature importance table accurate
- [ ] All code blocks have proper syntax highlighting
- [ ] Links to related documents work
- [ ] Troubleshooting section covers common issues
- [ ] Monitoring thresholds are reasonable

### Integration Testing
- [ ] Added to model index (`README.md`)
- [ ] Cross-referenced in related guides
- [ ] Mentioned in deployment documentation
- [ ] Linked from training script comments

---

## Examples

### Example 1: XGBoost V1 (Reference Implementation)

**Files:**
- Guide: `docs/08-projects/current/ml-model-v8-deployment/XGBOOST-V1-PERFORMANCE-GUIDE.md`
- Training: `ml_models/nba/train_xgboost_v1.py`
- System: `predictions/worker/prediction_systems/xgboost_v1.py`

**Key Details:**
- System ID: `xgboost_v1`
- Deployment Date: `2026-01-17`
- Validation MAE: 3.98
- Champion Comparison: vs CatBoost V8 (3.40 MAE)

**Use this as a template!**

### Example 2: CatBoost V8 (Original)

**Files:**
- Guide: `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`
- System: `predictions/worker/prediction_systems/catboost_v8.py`

**Key Details:**
- System ID: `catboost_v8`
- Validation MAE: 3.40
- Status: Current champion

---

## Quick Start: New Model Checklist

When deploying a new model, follow this checklist:

**Day 0: Pre-Deployment**
- [ ] Train model, document validation MAE
- [ ] Upload model to GCS
- [ ] Create system implementation
- [ ] Choose unique system_id

**Day 1: Deployment**
- [ ] Configure environment variable
- [ ] Deploy worker
- [ ] Verify predictions generating
- [ ] Confirm system_id in database

**Day 2: Documentation**
- [ ] Create performance guide (use template)
- [ ] Customize all queries
- [ ] Test all queries
- [ ] Add to model index

**Week 1: Monitoring**
- [ ] Run daily performance query
- [ ] Compare to validation MAE
- [ ] Check confidence calibration
- [ ] Review head-to-head vs champion

**Week 2: Validation**
- [ ] Confirm production MAE stable
- [ ] Review any problem tiers
- [ ] Analyze OVER vs UNDER performance
- [ ] Document any issues

**Month 1: Analysis**
- [ ] Monthly performance review
- [ ] Compare to champion model
- [ ] Evaluate for champion status
- [ ] Plan any improvements/retraining

---

## FAQ

**Q: Do I need a separate guide for each model version?**
A: Yes. Each major version (V1, V2, etc.) should have its own guide. Minor updates can be documented in the existing guide.

**Q: What if my model doesn't have confidence scores?**
A: Skip the confidence tier analysis section, but add a note explaining why.

**Q: How do I know if my model should be the new champion?**
A: After 30+ days, if production MAE < current champion's MAE consistently, consider promoting.

**Q: Can I combine multiple models in one guide?**
A: No. Each model gets its own guide for clarity and independent tracking.

**Q: What if validation MAE doesn't match production MAE?**
A: Document the discrepancy, investigate causes (distribution shift, data quality), and consider retraining.

---

## Related Documentation

- **CatBoost V8 Guide:** `PERFORMANCE-ANALYSIS-GUIDE.md` (original template)
- **XGBoost V1 Guide:** `XGBOOST-V1-PERFORMANCE-GUIDE.md` (reference implementation)
- **Champion-Challenger Framework:** `CHAMPION-CHALLENGER-FRAMEWORK.md`
- **Deployment Roadmap:** `docs/04-deployment/IMPLEMENTATION-ROADMAP.md`

---

**Template Version:** 1.0
**Last Updated:** 2026-01-17
**Status:** ✅ Active Template
