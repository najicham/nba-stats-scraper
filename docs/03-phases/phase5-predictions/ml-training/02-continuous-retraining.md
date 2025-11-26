# Phase 5 Retraining & Continuous Improvement

**File:** `docs/predictions/ml-training/02-continuous-retraining.md`
**Created:** 2025-11-16
**Purpose:** Guide for when and how to retrain ML models, detect drift, and continuously improve prediction systems
**Status:** ✅ Current

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Understanding Model Staleness](#model-staleness)
3. [Retraining Triggers](#retraining-triggers)
4. [Retraining Process](#retraining-process)
5. [A/B Testing New Models](#ab-testing)
6. [Feature Importance Tracking](#feature-importance)
7. [Automated Workflows](#automated-workflows)
8. [Troubleshooting Performance Drops](#troubleshooting)
9. [Best Practices](#best-practices)
10. [Related Documentation](#related-docs)

---

## 🎯 Executive Summary {#executive-summary}

This guide teaches you when and how to retrain ML models, detect when they're becoming stale, and continuously improve your prediction systems through feedback loops.

### Core Goal

Keep models accurate as the NBA evolves. Don't let yesterday's patterns predict tomorrow's game incorrectly.

### Why Retraining Matters

- **NBA changes over time** (rules, playing style, pace)
- **Players age**, teams rebuild, strategies shift
- **Models trained on 2021 data** may not work well in 2025
- **Regular retraining** keeps predictions sharp

### What You'll Learn

- When to retrain (time triggers + performance triggers)
- How to detect concept drift (when patterns change)
- A/B testing new models safely
- Automated retraining workflows
- Feature importance tracking
- Troubleshooting performance drops

### Timeline

| Phase | Duration | Focus |
|-------|----------|-------|
| **Month 1** | 4 weeks | Manual monthly retraining |
| **Month 2-3** | 8 weeks | Add performance triggers |
| **Month 4+** | Ongoing | Semi-automated retraining |

---

## 📉 Understanding Model Staleness {#model-staleness}

### Why Models Go Stale

**Concept Drift:** The statistical properties of the target variable change over time.

**In NBA terms:**

```
2021: Average game pace was 99.2 possessions
2025: Average game pace is 102.5 possessions

→ Players get more shot attempts
→ Scoring patterns change
→ Old model predictions become less accurate
```

### Common Sources of Drift

| Source | Example | Impact |
|--------|---------|--------|
| **Rule Changes** | NBA changes foul rules | Different scoring patterns |
| **Playing Style** | League shoots more 3-pointers | Paint scoring decreases |
| **Roster Changes** | Star players traded/retired | Team dynamics shift |
| **Age Effects** | Players age | Performance changes |
| **Season Context** | Early season vs playoff push | Behavior patterns shift |

**Example of drift:**

```python
# Model trained on 2021-2023 data
# Learned: "Players average 24.5 points when fatigue_score < 40"

# Reality in 2025:
# Players now average 22.8 points in same situation
# (Load management became more aggressive)

# Result: Model overpredicts by ~1.7 points → Accuracy drops
```

### How to Detect Drift

#### Signal 1: Performance Degradation

Compare recent performance to validation metrics:

```python
# Your model's validation performance (when trained)
validation_mae = 4.1
validation_ou_accuracy = 58.3%

# Recent production performance (last 7 days)
production_mae = 5.2  # ⚠️ Worse by 1.1 points
production_ou_accuracy = 53.1%  # ⚠️ Down 5.2%

# Drift likely if:
# - MAE increases by 1.0+
# - O/U accuracy drops 5%+
```

#### Signal 2: Feature Importance Shift

Top features changed significantly:

```
# When trained (January 2025)
Top features:
1. points_avg_last_10 (18.3%)
2. points_avg_last_5 (15.7%)
3. current_points_line (12.1%)

# Now (April 2025)
Top features:
1. paint_mismatch_score (22.1%)  # ⚠️ Jumped to #1
2. opponent_pace (18.5%)  # ⚠️ New in top 3
3. points_avg_last_10 (14.2%)  # Dropped

# This suggests playing style changed
# Paint matchups now more important
```

#### Signal 3: Prediction Bias

Model consistently over or underpredicts:

```sql
-- Calculate bias
bias = AVG(predicted_points - actual_points)

-- When trained: bias ≈ 0.0 (unbiased)
-- Now: bias = +1.8  # ⚠️ Overpredicting by 1.8 points

-- Suggests systematic change in scoring
```

#### Signal 4: Feature Distribution Shift

Input data looks different than training data:

```python
# Training data (2021-2024)
avg_fatigue_score = 65.2
avg_opponent_def_rating = 112.8

# Recent data (last 30 days)
avg_fatigue_score = 58.3  # ⚠️ Much lower (more rest days?)
avg_opponent_def_rating = 110.5  # ⚠️ Better defense league-wide

# Model wasn't trained on these ranges
# Predictions may be unreliable
```

---

## 🔔 Retraining Triggers {#retraining-triggers}

### Strategy: Time-Based + Performance-Based

**Recommended approach:**

1. **Monthly retraining** (proactive, catches slow drift)
2. **Performance triggers** (reactive, catches sudden changes)
3. **Season boundaries** (major retraining at season start)

### Time-Based Retraining

**Schedule:**

```yaml
regular_retraining:
  frequency: monthly
  day_of_month: 1
  time: "02:00"

season_retraining:
  trigger: season_start  # October
  reason: "New rosters, new season patterns"

playoff_retraining:
  trigger: playoffs_start  # April
  reason: "Different effort levels, strategies"
```

**Why monthly?**

- NBA changes gradually
- Monthly captures trends without overreacting
- Enough new data to improve model

**Data window for retraining:**

```python
def get_training_window():
    """
    Get data range for retraining
    Rolling window approach (recommended)
    """
    end_date = date.today() - timedelta(days=1)

    # Use 3 seasons (1095 days)
    # Drop oldest data, add newest data
    start_date = end_date - timedelta(days=1095)

    return start_date, end_date

# Example:
# January 2025 training: Use Oct 2021 - Jan 2025
# February 2025 training: Use Nov 2021 - Feb 2025
```

**Why rolling window?**

- Recent data is most relevant
- Drops very old patterns
- Model stays current

### Performance-Based Retraining

**Trigger when any of these conditions met:**

#### Trigger 1: MAE Degradation

```python
# Compare production MAE vs validation MAE
trigger_mae_degradation = (
    production_mae_7_day > validation_mae + 1.0
)

# Example:
# Validation MAE: 4.1
# Production MAE (last 7 days): 5.3
# Difference: 1.2 → TRIGGER RETRAINING
```

#### Trigger 2: Accuracy Drop

```python
# Compare production accuracy vs validation
trigger_accuracy_drop = (
    production_ou_accuracy < validation_ou_accuracy - 0.05
)

# Example:
# Validation O/U accuracy: 58.3%
# Production O/U accuracy (last 7 days): 52.1%
# Difference: -6.2% → TRIGGER RETRAINING
```

#### Trigger 3: Consistent Underperformance

```python
# 3+ consecutive days below threshold
trigger_sustained_poor_performance = (
    days_below_threshold >= 3
    where daily_ou_accuracy < 52%
)
```

#### Trigger 4: Feature Distribution Shift

```python
# Features outside training range
trigger_feature_shift = (
    pct_features_out_of_range > 0.20  # 20% of features
)

# Example:
# 12 out of 46 features outside training range
# 12/46 = 26% → TRIGGER RETRAINING
```

### Retraining Decision Script

**Create:** `ml/retraining/check_retraining_triggers.py`

**Key methods:**

```python
class RetrainingChecker:
    def check_all_models(self):
        """Check all active ML models for retraining needs"""
        # Get active models
        # Check each for triggers
        # Send alerts if needed

    def check_model_triggers(self, model):
        """Check all retraining triggers for a model"""
        triggers = []

        # Trigger 1: Time-based (30 days since training)
        # Trigger 2: MAE degradation
        # Trigger 3: O/U accuracy drop
        # Trigger 4: Sustained poor performance
        # Trigger 5: Feature distribution shift

        return triggers

    def get_recent_mae(self, model_id, days=7):
        """Get recent production MAE"""

    def get_recent_accuracy(self, model_id, days=7):
        """Get recent O/U accuracy"""

    def send_retraining_alert(self, needs_retraining):
        """Send notification about models needing retraining"""
```

**Run daily:**

```bash
# Add to daily workflow (after monitoring)
python ml/retraining/check_retraining_triggers.py
```

---

## 🔄 Retraining Process {#retraining-process}

### Step-by-Step Retraining

When triggers fire, follow this process:

#### Step 1: Analyze Why Retraining Needed

Before blindly retraining, understand what changed:

```bash
# Generate feature importance comparison
python ml/analysis/compare_feature_importance.py

# Check for data quality issues
python ml/analysis/validate_recent_data.py

# Review prediction errors
python monitoring/failure_analysis.py --days 14
```

**Ask yourself:**

- Is this real drift or a data quality issue?
- Did something external change (new rule, injury to star)?
- Is it temporary (small sample) or sustained?

#### Step 2: Prepare Training Data

```bash
# Backfill ml_feature_store with recent data
python ml/features/backfill_features.py --days 30

# Verify data quality
python ml/features/validate_features.py
```

#### Step 3: Train New Model

```bash
# Train with updated data
python ml/training/train_model.py
```

This creates a new model version: `xgboost_universal_v1_20250220`

#### Step 4: Validate New Model

Compare new model vs current champion:

```python
# Validation on recent held-out data
new_model_mae = 4.0
current_model_mae = 4.6

new_model_ou_accuracy = 59.2%
current_model_ou_accuracy = 54.8%

# New model is better → proceed to A/B test
```

#### Step 5: A/B Test (7 Days)

Deploy new model as challenger, run alongside champion:

```bash
# Deploy challenger model
python ml/deployment/deploy_challenger.py \
  --model-id xgboost_universal_v1_20250220
```

Both models make predictions for 7 days, we compare results.

#### Step 6: Evaluate A/B Test

After 7 days:

```bash
# Compare champion vs challenger
python ml/analysis/compare_models.py \
  --champion xgboost_universal_v1_20250120 \
  --challenger xgboost_universal_v1_20250220 \
  --days 7
```

#### Step 7: Promote or Rollback

**If challenger wins** → promote to champion:

```bash
python ml/deployment/promote_to_champion.py \
  --model-id xgboost_universal_v1_20250220
```

**If challenger loses** → keep current champion:

```bash
# Challenger automatically disabled after test period
# Investigate why new model didn't improve
```

### Retraining Script

**Create:** `ml/retraining/retrain_model.py`

**Key function:**

```python
def retrain_model(reason="scheduled"):
    """
    Retrain model with latest data

    Args:
        reason: Why retraining ('scheduled', 'performance_trigger', 'drift_detected')
    """
    # Step 1: Load data (rolling 3-year window)
    # Step 2: Prepare features
    # Step 3: Create splits
    # Step 4: Train model
    # Step 5: Evaluate
    # Step 6: Compare to current champion
    # Step 7: Save model
    # Step 8: Send notification

    return {
        'success': True,
        'model_id': model_id,
        'is_better': is_better,
        'recommendation': deployment_recommendation
    }
```

---

## 🧪 A/B Testing New Models {#ab-testing}

### Why A/B Test?

**Problem:** New model looks better on test set, but will it work in production?

**Solution:** Run both models in parallel for 7 days, compare real-world performance.

**Benefits:**

- Catches issues test set didn't reveal
- Ensures improvements are real, not flukes
- Safe deployment (can rollback easily)

### A/B Testing Process

#### Step 1: Deploy Challenger

```python
def deploy_challenger(challenger_model_id):
    """
    Deploy new model as challenger (runs alongside champion)
    """
    # Register as challenger (not champion)
    # Both models will now generate predictions
    # Champion continues as primary recommendation
    # Challenger predictions stored for comparison
```

#### Step 2: Both Models Predict

For next 7 days, both models make predictions:

```python
# In daily prediction workflow
champion_prediction = champion_model.predict(features)
challenger_prediction = challenger_model.predict(features)

# Store both
store_prediction(champion_prediction, is_champion=True)
store_prediction(challenger_prediction, is_champion=False)

# Use champion for actual recommendations
return champion_prediction
```

#### Step 3: Compare After 7 Days

```python
def compare_ab_test(champion_id, challenger_id, days=7):
    """
    Compare champion vs challenger over test period
    """
    # Query performance metrics for both models
    # Calculate O/U accuracy, MAE for each
    # Determine statistical significance

    accuracy_diff = challenger['ou_accuracy'] - champion['ou_accuracy']
    mae_diff = champion['mae'] - challenger['mae']  # Lower MAE is better

    # Decision criteria
    should_promote = (
        accuracy_diff > 0.02 and  # At least 2% better
        mae_diff > 0.2  # At least 0.2 points better MAE
    )

    return should_promote
```

#### Step 4: Promote or Rollback

**If challenger wins:**

```bash
python ml/deployment/promote_to_champion.py \
  --model-id xgboost_universal_v1_20250220
```

This:
- Sets challenger as new champion (`is_champion = TRUE`)
- Demotes old champion (`is_champion = FALSE`)
- Sends notification

**If challenger loses:**

```bash
python ml/deployment/disable_challenger.py \
  --model-id xgboost_universal_v1_20250220
```

---

## 📊 Feature Importance Tracking {#feature-importance}

### Why Track Feature Importance?

#### Reason 1: Detect Drift

```
# January 2025 training
Top feature: points_avg_last_10 (18.3%)

# April 2025 training
Top feature: paint_mismatch_score (24.1%)

# Analysis: Playing style shifted
# Paint matchups became more important
# This is concept drift!
```

#### Reason 2: Understand Model

```
# If model suddenly performs worse
# Check what features changed importance

Old model: fatigue_score 8.9% importance
New model: fatigue_score 2.1% importance

# Why? Did fatigue become less predictive?
# Or is data quality issue?
```

#### Reason 3: Data Collection Priority

```
# Features with high importance need perfect data
# Features with low importance can have some errors

Top 5 features = 65% of model decisions
→ Focus data quality efforts here
```

### Feature Importance Comparison

**Create:** `ml/analysis/compare_feature_importance.py`

```python
def compare_feature_importance(model_id_1, model_id_2):
    """
    Compare feature importance between two models
    """
    # Get feature importance for both models
    # Create comparison dataframe
    # Print biggest increases/decreases
    # Analyze changes

    # Output:
    # - Top 10 features with biggest increases
    # - Top 10 features with biggest decreases
    # - Analysis of significant changes
```

**Run after retraining:**

```bash
python ml/analysis/compare_feature_importance.py \
  --model1 xgboost_universal_v1_20250120 \
  --model2 xgboost_universal_v1_20250220
```

---

## 🤖 Automated Workflows {#automated-workflows}

### Monthly Automation

Set up Cloud Scheduler to trigger monthly retraining:

```bash
# Create Cloud Scheduler job
gcloud scheduler jobs create http ml-monthly-retraining \
  --location us-central1 \
  --schedule "0 2 1 * *" \
  --time-zone "America/Los_Angeles" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/ml-retraining-job:run" \
  --http-method POST \
  --oauth-service-account-email nba-props-sa@nba-props-platform.iam.gserviceaccount.com

# Runs 1st of every month at 2 AM
```

### Daily Trigger Check Automation

Run retraining check daily:

```bash
# Create Cloud Scheduler job for daily checks
gcloud scheduler jobs create http ml-daily-retraining-check \
  --location us-central1 \
  --schedule "0 3 * * *" \
  --time-zone "America/Los_Angeles" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/ml-retraining-check:run" \
  --http-method POST \
  --oauth-service-account-email nba-props-sa@nba-props-platform.iam.gserviceaccount.com

# Runs daily at 3 AM
```

This checks triggers and sends alert if retraining needed.

---

## 🔧 Troubleshooting Performance Drops {#troubleshooting}

### Issue: Model Performance Suddenly Drops

**Symptom:**

```
Yesterday: 58% O/U accuracy
Today: 48% O/U accuracy
```

**Diagnosis Steps:**

#### 1. Check Sample Size

```sql
-- Was today just a small/unlucky sample?
SELECT
  game_date,
  COUNT(*) as predictions,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM prediction_results
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC

-- If today had only 5 games, might just be bad luck
-- If today had 40 games, real issue
```

#### 2. Check Data Quality

```sql
-- Are features missing or corrupted?
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN fatigue_score IS NULL THEN 1 ELSE 0 END) as missing_fatigue,
  SUM(CASE WHEN opponent_def_rating_last_10 IS NULL THEN 1 ELSE 0 END) as missing_def
FROM ml_feature_store
WHERE game_date = CURRENT_DATE()
```

#### 3. Check for Outliers

```sql
-- Were there unusual games today?
SELECT
  player_lookup,
  actual_points,
  predicted_points,
  prediction_error
FROM prediction_results
WHERE game_date = CURRENT_DATE()
ORDER BY prediction_error DESC
LIMIT 10

-- Did star players get injured mid-game?
-- Was there overtime? (more possessions = unusual)
```

#### 4. Check Feature Distribution

```sql
-- Did input features look unusual today?
SELECT
  AVG(fatigue_score) as avg_fatigue,
  AVG(opponent_def_rating_last_10) as avg_def_rating,
  AVG(days_rest) as avg_rest
FROM ml_feature_store
WHERE game_date = CURRENT_DATE()

-- Compare to historical averages
-- If very different, that's why predictions were off
```

### Issue: New Model Worse Than Old Model

**Symptom:**

```
Old model: 58% accuracy, 4.1 MAE
New model: 54% accuracy, 4.8 MAE
```

**Possible Causes:**

#### 1. Overfitting to Recent Data

```
# New model trained on 2022-2025 data
# Old model trained on 2021-2024 data

# Recent data (2025) might have been unusual
# New model learned patterns that don't generalize

Solution: Use longer training window (4 years vs 3 years)
```

#### 2. Hyperparameters Too Aggressive

```yaml
# New model config
max_depth: 8  # Too deep
learning_rate: 0.2  # Too fast

# Makes model overfit

Solution: Use more conservative hyperparameters
max_depth: 6
learning_rate: 0.1
```

#### 3. Data Quality Degraded

```
# Recent data has more missing values
# Or new data collection bug

Solution: Fix data quality issues before retraining
```

#### 4. Concept Drift Was Temporary

```
# Performance dropped due to short-term anomaly
# (e.g., shortened season due to event)
# Retraining on anomaly made model worse

Solution: Wait for more data, ensure drift is sustained
```

---

## ✅ Best Practices {#best-practices}

### Retraining Cadence

**Recommended Schedule:**

| Phase | Cadence | Purpose |
|-------|---------|---------|
| **Months 1-3** | Monthly | Build intuition, learn triggers |
| **Months 4-6** | Bi-weekly | More responsive to changes |
| **Months 7+** | Weekly + triggers | Automated with alerts |

### Versioning Strategy

**Naming convention:**

```
xgboost_universal_v{major}_{date}

Examples:
xgboost_universal_v1_20250120  (version 1, Jan 20)
xgboost_universal_v1_20250220  (version 1, Feb 20)
xgboost_universal_v2_20250320  (version 2, Mar 20) ← Major change
```

**Version history:**

```sql
-- Keep all model versions for analysis
SELECT
  model_id,
  trained_on_date,
  test_mae,
  production_ready,
  active
FROM ml_models
ORDER BY trained_on_date DESC
```

### Documentation After Retraining

After each retraining, document:

- **Why retrained** - Which triggers fired?
- **Data window used** - Which dates?
- **Performance change** - Better or worse?
- **Feature importance changes** - What shifted?
- **Deployment decision** - Promoted or not? Why?

**Create:** `retraining_log.md`

```markdown
# Retraining Log

## 2025-02-20 Retraining
**Trigger:** Monthly scheduled + MAE degradation
**Data Window:** 2022-02-20 to 2025-02-19 (3 years)
**Old Model:** xgboost_universal_v1_20250120
**New Model:** xgboost_universal_v1_20250220

**Performance Comparison:**
| Metric | Old | New | Change |
|--------|-----|-----|--------|
| Test MAE | 4.6 | 4.0 | -0.6 ✅ |
| Test O/U Acc | 54.8% | 59.2% | +4.4% ✅ |

**Feature Importance Changes:**
- paint_mismatch_score: 12.1% → 18.3% (+6.2%)
- fatigue_score: 8.9% → 6.1% (-2.8%)

**Analysis:**
Paint matchups became more important as league shifted to more interior scoring.

**Decision:** Deployed as challenger, ran A/B test for 7 days.
**Outcome:** Promoted to champion on 2025-02-27. Improvement sustained.
```

### Monthly Review Checklist

**First Monday of each month:**

- [ ] Review last month's performance
  - Overall accuracy trend
  - Best/worst performing systems
  - Confidence calibration

- [ ] Check for drift signals
  - Feature importance shifts
  - Prediction bias
  - Feature distribution changes

- [ ] Analyze failure patterns
  - Which players are hard to predict?
  - Which situations cause errors?
  - Are there systematic biases?

- [ ] Plan improvements
  - New features to add?
  - Hyperparameters to tune?
  - Data quality to fix?

- [ ] Retrain if needed
  - Follow retraining process
  - Document results

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 ML Documentation:**

- **Initial Training:** `01-initial-model-training.md` - How to train your first model
- **Feature Strategy:** `03-feature-development-strategy.md` - Why 25 features and how to grow systematically
- **Confidence Scoring:** `../algorithms/02-confidence-scoring-framework.md` - Confidence calculation
- **Composite Factors:** `../algorithms/01-composite-factor-calculations.md` - Feature engineering

**Phase 5 Operations:**

- **Worker Deep-Dive:** `../operations/04-worker-deepdive.md` - Model loading in production
- **Troubleshooting:** `../operations/03-troubleshooting.md` - Operational issues

**Monitoring:**

- **Performance Monitoring:** See Phase 5 monitoring documentation for dashboards and alerts

---

**Last Updated:** 2025-11-16
**Next Steps:** Set up automated retraining checks, establish monthly review cadence
**Status:** ✅ Current

---

## Quick Reference

**Check if retraining needed:**

```bash
python ml/retraining/check_retraining_triggers.py
```

**Retrain model:**

```bash
python ml/retraining/retrain_model.py --reason "performance_drop"
```

**Compare models:**

```bash
python ml/analysis/compare_models.py \
  --champion old_model_id \
  --challenger new_model_id \
  --days 7
```

**Retraining triggers:**

- ⏰ 30+ days since last training
- 📉 MAE increased by 1.0+
- 📊 O/U accuracy dropped 5%+
- 🔄 Feature distribution shifted 20%+
