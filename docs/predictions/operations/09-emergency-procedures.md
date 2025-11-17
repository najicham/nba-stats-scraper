# Phase 5: Emergency Procedures & Advanced Troubleshooting

**File:** `docs/predictions/operations/09-emergency-procedures.md`
**Created:** 2025-11-16
**Purpose:** Emergency response procedures and advanced troubleshooting for Phase 5 prediction services - critical incidents, performance issues, system failures
**Status:** ✅ Production Ready

---

## 📋 Table of Contents

1. [Emergency Response Overview](#overview)
2. [Critical Emergencies (P0)](#critical-emergencies)
3. [High Priority Issues (P1)](#high-priority)
4. [Performance Issues](#performance-issues)
5. [System Issues](#system-issues)
6. [Data Issues](#data-issues)
7. [Confidence Issues](#confidence-issues)
8. [Escalation Paths](#escalation)
9. [Related Documentation](#related-docs)

---

## 🚨 Emergency Response Overview {#overview}

### Incident Priority Levels

| Priority | Impact | Response Time | Examples |
|----------|--------|---------------|----------|
| **P0 - Critical** | No predictions generated | Immediate (<1 hour) | Service down, complete failure |
| **P1 - High** | Predictions losing money | Immediate (<2 hours) | Accuracy <45%, systematic errors |
| **P2 - Medium** | Degraded performance | Within 24 hours | Accuracy 52-54%, 1-2 systems down |
| **P3 - Low** | Minor issues | Within week | Confidence miscalibration, warnings |

### How to Use This Guide

1. **Find your symptom** in the table of contents
2. **Follow diagnosis steps** in order
3. **Apply the solution** that matches your situation
4. **Document what worked** for future reference

---

## 🔴 Critical Emergencies (P0) {#critical-emergencies}

### P0-1: No Predictions Generated

**Impact:** No bets can be placed today
**Response Time:** Immediate (within 1 hour)

#### Diagnosis

**Step 1: Check Coordinator**

```bash
# Check if coordinator ran
gcloud logging read \
  "resource.labels.service_name='predictions-coordinator' AND \
   timestamp>=\"$(date -u '+%Y-%m-%dT00:00:00')Z\"" \
  --limit=20
```

**Look for:**
- Did coordinator start?
- Any error messages?
- Did it publish to Pub/Sub?

**Step 2: Check Worker Status**

```bash
# Check worker instances
gcloud run services describe predictions-worker \
  --region=us-central1 \
  --format='value(status.conditions)'
```

**Step 3: Check Pub/Sub Queue**

```bash
# Check if messages were published
gcloud pubsub topics describe phase5-player-prediction-tasks

# Check subscription
gcloud pubsub subscriptions describe phase5-worker-subscription
```

---

#### Solutions

**Solution A: Coordinator Didn't Run**

```bash
# Check Cloud Scheduler
gcloud scheduler jobs list | grep coordinator

# If scheduler paused, resume:
gcloud scheduler jobs resume coordinator-daily-6am

# If scheduler OK, manually trigger:
URL=$(gcloud run services describe predictions-coordinator \
  --region=us-central1 --format='value(status.url)')

curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $URL
```

**Solution B: Pub/Sub Issue**

```bash
# Check subscription configuration
gcloud pubsub subscriptions describe phase5-worker-subscription

# If messages stuck, check ack deadline:
gcloud pubsub subscriptions update phase5-worker-subscription \
  --ack-deadline=300

# Purge and retry if needed (CAUTION: loses queued messages)
gcloud pubsub subscriptions seek phase5-worker-subscription \
  --time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
```

**Solution C: Worker Deployment Issue**

```bash
# Check worker service status
gcloud run services describe predictions-worker \
  --region=us-central1

# If unhealthy, check recent deployments
gcloud run revisions list \
  --service=predictions-worker \
  --region=us-central1 \
  --limit=5

# Rollback to previous revision if needed
gcloud run services update-traffic predictions-worker \
  --region=us-central1 \
  --to-revisions=[PREVIOUS-REVISION]=100
```

**Solution D: Fallback - Use Previous Day's Predictions**

If cannot fix within 2 hours:

```sql
-- Copy yesterday's predictions with adjusted lines
INSERT INTO `nba-props-platform.nba_predictions.player_prop_predictions`
SELECT
  player_lookup,
  CURRENT_DATE() as game_date,
  predicted_points,
  current_points_line + (today_line - yesterday_line) as adjusted_line,
  -- ... other fields with adjustments
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
```

**Note:** This is emergency fallback only. Predictions will be less accurate.

---

### P0-2: Cloud Run Service Down

**Impact:** Varies by service
**Response Time:** Immediate

#### Diagnosis

```bash
# Check all services status
gcloud run services list \
  --platform=managed \
  --project=nba-props-platform \
  --region=us-central1
```

#### Solutions

**Solution A: Restart Service**

```bash
# Deploy new revision (triggers restart)
gcloud run services update [SERVICE-NAME] \
  --region=us-central1 \
  --no-traffic  # Don't route traffic yet

# If new revision healthy, route traffic
gcloud run services update-traffic [SERVICE-NAME] \
  --region=us-central1 \
  --to-latest
```

**Solution B: Rollback to Previous Revision**

```bash
# List recent revisions
gcloud run revisions list \
  --service=[SERVICE-NAME] \
  --region=us-central1 \
  --limit=5

# Rollback to last working revision
gcloud run services update-traffic [SERVICE-NAME] \
  --region=us-central1 \
  --to-revisions=[PREVIOUS-REVISION]=100
```

**Solution C: Check GCP Status**

If service down >1 hour and no solution found:

1. Check GCP status: https://status.cloud.google.com
2. Review recent deployments (possible bad deploy)
3. Alert stakeholders
4. Enable fallback procedures

---

## 🔶 High Priority Issues (P1) {#high-priority}

### P1-1: Accuracy <45% (Catastrophic)

**Impact:** Losing money rapidly
**Response Time:** Immediate, pause betting

#### Step 1: Disable Recommendations

```sql
-- Temporarily disable ensemble predictions
UPDATE `nba-props-platform.nba_predictions.system_config`
SET is_active = FALSE
WHERE system_id = 'meta_ensemble_v1';
```

#### Step 2: Investigate Root Cause

**Check data quality:**

```bash
# Validate features
python ml/features/validate_features.py --date yesterday
```

**Check for model corruption:**

```bash
# List current model
gsutil ls -l gs://nba-props-ml-models/xgboost_v1_current.json

# Compare to backup
gsutil ls -l gs://nba-props-ml-models/xgboost_v1_[PREVIOUS_DATE].json
```

**Check for NBA rule changes or external factors:**
- All-Star break?
- Trade deadline?
- Playoffs starting?
- Major injury news affecting features?

#### Step 3: Rollback to Previous Model

```bash
# Copy previous working model to current
gsutil cp \
  gs://nba-props-ml-models/xgboost_v1_PREVIOUS.json \
  gs://nba-props-ml-models/xgboost_v1_current.json
```

#### Step 4: Re-enable Once Fixed

```sql
-- Re-enable ensemble after fix confirmed
UPDATE `nba-props-platform.nba_predictions.system_config`
SET is_active = TRUE
WHERE system_id = 'meta_ensemble_v1';
```

---

### P1-2: Performance Degrading (52-54%)

**Impact:** Barely profitable, may start losing
**Response Time:** Within 24 hours

#### Step 1: Run Diagnostics

**Check if specific to player type:**

```sql
SELECT
  player_position,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_results` r
JOIN `nba-props-platform.nba_analytics.player_game_summary` p
  ON r.player_lookup = p.player_lookup
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY player_position;
```

**If specific position affected:**
- Guards low: Check perimeter defense features
- Centers low: Check paint matchup calculations
- All positions: System-wide issue

#### Step 2: Check Feature Drift

Compare feature distributions now vs training time:

```sql
SELECT
  'fatigue_score' as feature,
  AVG(fatigue_score) as current_avg,
  STDDEV(fatigue_score) as current_stddev
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Compare to training period averages
-- If >10% shift, feature drift detected
```

#### Step 3: Consider Early Retraining

If degradation continues >3 days:

```bash
# Trigger manual retraining (don't wait for monthly)
gcloud run jobs execute predictions-ml-training \
  --region=us-central1 \
  --args="--reason=performance_decline"
```

Follow [retraining process](../../ml-training/02-continuous-retraining.md) for A/B testing.

---

## 📉 Performance Issues {#performance-issues}

### Issue: Accuracy Suddenly Drops

**Symptom:** Yesterday 58%, today 47%

#### Diagnosis

**Step 1: Check Sample Size**

```python
# Quick sample size check
from google.cloud import bigquery

client = bigquery.Client()
query = """
  SELECT COUNT(*) as predictions
  FROM `nba-props-platform.nba_predictions.prediction_results`
  WHERE game_date = CURRENT_DATE() - 1
"""
result = list(client.query(query))[0]
print(f'Predictions: {result.predictions}')
```

**Interpretation:**
- **<10 predictions:** Likely small sample / bad luck → Monitor tomorrow
- **10-30 predictions:** Borderline → Check for anomalies
- **>30 predictions:** Real issue → Continue investigation

**Step 2: Check Data Quality**

```bash
# Validate feature quality
python ml/features/validate_features.py --date yesterday
```

**Look for:**
- Missing features (>5% NULL values)
- Unusual values (fatigue_score < 0, impossible values)
- Data source issues (Phase 4 not running properly)

**Step 3: Review Specific Failures**

```bash
# Run failure analysis
python monitoring/failure_analysis.py --date yesterday
```

**Common patterns:**

**Pattern 1: All errors on one team**
```
Lakers: 8/8 predictions wrong
Other teams: Normal accuracy

Likely: Lakers roster change, injury, data issue
Solution: Check if star player injured. Disable predictions for affected team temporarily.
```

**Pattern 2: All errors in overtime games**
```
OT games: 0/5 correct
Regulation: Normal accuracy

Likely: Model doesn't account for extra possessions
Solution: This is expected. Note for future feature engineering (add OT flag).
```

**Pattern 3: All errors on back-to-backs**
```
B2B games: 2/12 correct
Normal rest: Normal accuracy

Likely: Fatigue model needs tuning
Solution: Check fatigue scoring. May need weight adjustment.
```

**Step 4: Check for External Events**

**Questions to ask:**
- Trade deadline? (roster changes)
- All-Star break? (rest affects patterns)
- Playoffs starting? (effort levels change)
- Rule change announced? (league-wide shift)

**If yes to any:**
- This is **concept drift**
- Schedule retraining immediately
- See [Continuous Retraining](../../ml-training/02-continuous-retraining.md)

---

### Issue: Accuracy Gradually Declining

**Symptom:**
```
Week 1: 58% accuracy
Week 2: 56% accuracy
Week 3: 54% accuracy
Week 4: 52% accuracy ⚠️
```

This is classic **concept drift** - NBA patterns changing, model getting stale.

#### Step 1: Confirm Trend is Real

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
  AND system_id = (SELECT system_id FROM prediction_systems WHERE is_champion = TRUE)
GROUP BY week
ORDER BY week;
```

**If clear downward trend:** Continue to Step 2
**If fluctuating:** Might be normal variance, monitor

#### Step 2: Check Feature Importance Shifts

```bash
# Compare current to 2 months ago
python ml/analysis/compare_feature_importance.py \
  --model1 current_champion \
  --model2 model_from_2_months_ago
```

**Look for >5% change in importance:**
```
Features with >5% change:
  - paint_mismatch_score: 12% → 19% (+7%)
  - fatigue_score: 15% → 8% (-7%)

Indicates playing style shifted (more paint-focused)
```

#### Solution: Retrain Model

```bash
# Immediate retraining recommended
python ml/retraining/retrain_model.py --reason "performance_decline"

# Follow retraining process
# A/B test for 7 days
# Should see accuracy improve back to 56-58%
```

See [Continuous Retraining](../../ml-training/02-continuous-retraining.md) for full process.

---

### Issue: MAE Increasing

**Symptom:**
```
Training MAE: 4.1
Current MAE: 5.3 🔴
```

#### Diagnosis

**Step 1: Decompose Error Sources**

```sql
-- Where is the error coming from?
SELECT
  CASE
    WHEN ABS(predicted_points - actual_points) <= 2 THEN 'Very Close (0-2)'
    WHEN ABS(predicted_points - actual_points) <= 5 THEN 'Close (3-5)'
    WHEN ABS(predicted_points - actual_points) <= 8 THEN 'Far (6-8)'
    ELSE 'Very Far (9+)'
  END as error_category,
  COUNT(*) as count,
  AVG(prediction_error) as avg_error
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY error_category
ORDER BY avg_error;
```

**If many "Very Far" errors:** Something systematically wrong
**If evenly distributed:** Model losing precision overall

**Step 2: Check for Bias**

```sql
-- Are we consistently over or underpredicting?
SELECT
  AVG(predicted_points - actual_points) as bias
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

**Interpretation:**
- **Bias near 0:** Not biased, just imprecise
- **Bias >1.0:** Overpredicting (predicting too high)
- **Bias <-1.0:** Underpredicting (predicting too low)

#### Solutions

**Solution for Bias:**

If overpredicting (+1.5 bias):
```
Likely cause: Scoring decreased league-wide
Examples:
  - Pace slowed down
  - Defense improved
  - Foul calling stricter

Solution: Retrain with recent data
```

If underpredicting (-1.5 bias):
```
Likely cause: Scoring increased league-wide
Examples:
  - Pace increased
  - More 3-pointers
  - Foul calling looser

Solution: Retrain with recent data
```

**Solution for High Variance (no bias):**

1. Check data quality first
2. If data is good, model needs improvement:
   - Retrain with more data (4 years instead of 3)
   - Tune hyperparameters (increase regularization)
   - Add new features (better predictors)
   - Ensemble multiple models (reduce variance)

---

### Issue: Predictions All Wrong on One Day

**Symptom:**
```
Date: 2025-01-15
Accuracy: 15% 🔴 (disastrous)
All predictions off by 8-12 points
```

**This is almost always a data issue, not a model issue.**

#### Diagnosis

**Step 1: Check if Predictions Ran**

```sql
SELECT COUNT(*)
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2025-01-15';
```

**If 0:** Predictions never generated → See [P0-1: No Predictions Generated](#p0-1-no-predictions-generated)
**If >0:** Continue to Step 2

**Step 2: Check Feature Values**

```sql
-- Look at features used for that day
SELECT
  player_lookup,
  fatigue_score,
  opponent_def_rating_last_10,
  points_avg_last_5,
  current_points_line
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = '2025-01-15'
LIMIT 10;
```

**Suspicious patterns:**
- All fatigue_score = 0 (should be 30-90)
- All opponent_def_rating = NULL
- current_points_line all wrong (mismatched data?)

**If features look wrong:** Data pipeline issue

**Step 3: Identify Pipeline Failure**

```bash
# Check processor logs
gcloud logging read \
  "resource.type=cloud_run_job AND \
   timestamp>='2025-01-14T00:00:00Z' AND \
   severity>=WARNING" \
  --limit=100
```

**Look for:**
- Scraper failures
- Processor timeouts
- BigQuery write errors

#### Solution

**Fix and Regenerate:**

```bash
# Step 1: Fix source data
python scrapers/scrape_historical.py --date 2025-01-15

# Step 2: Rerun processors
python processors/process_analytics.py --date 2025-01-15
python processors/process_precompute.py --date 2025-01-15

# Step 3: Regenerate predictions
python ml/prediction/predict.py --date 2025-01-15

# Step 4: Verify
python monitoring/performance_monitor.py --date 2025-01-15
```

**Step 5: Update Results**

```sql
-- Mark old predictions as inactive
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET is_active = FALSE
WHERE game_date = '2025-01-15'
  AND created_at < (SELECT MAX(created_at)
                    FROM player_prop_predictions
                    WHERE game_date = '2025-01-15');
```

---

## ⚙️ System Issues {#system-issues}

### Issue: Model Training Fails

**Symptom:**
```bash
python ml/training/train_model.py
# Error: [various errors]
```

#### Common Errors & Solutions

**Error: "MemoryError" or "Killed"**

Cause: Not enough RAM to train model

Solutions:
1. **Reduce data size:**
   ```python
   # In ml/training/train_model.py
   start_date = end_date - timedelta(days=1095)  # 3 years instead of 4
   ```

2. **Increase memory:**
   ```bash
   # Update Cloud Run job to use more memory (16Gi)
   ```

3. **Sample data:**
   ```python
   # Train on 75% of data
   df = df.sample(frac=0.75, random_state=42)
   ```

**Error: "No data in date range"**

Cause: Feature store empty for training period

Solution:
```bash
# Backfill feature store
python ml/features/backfill_features.py \
  --start-date 2021-10-01 \
  --end-date 2025-01-20

# This may take 30-60 minutes
# Then retry training
```

**Error: "Feature X not found"**

Cause: Model config references feature that doesn't exist

Solution:
```bash
# Check feature_store schema vs model config
# Option 1: Add missing feature to feature_store
# Option 2: Remove feature from model config
```

---

## 📊 Data Issues {#data-issues}

### Issue: Missing Features

**Symptom:**
```sql
SELECT COUNT(*) as total,
  SUM(CASE WHEN fatigue_score IS NULL THEN 1 ELSE 0 END) as missing
FROM ml_feature_store_v2
WHERE game_date = '2025-01-19';

-- Result: 50% missing fatigue scores
```

#### Diagnosis

**Identify scope:**
```sql
-- Which features are missing?
SELECT
  SUM(CASE WHEN fatigue_score IS NULL THEN 1 ELSE 0 END) as missing_fatigue,
  SUM(CASE WHEN opponent_def_rating_last_10 IS NULL THEN 1 ELSE 0 END) as missing_def,
  SUM(CASE WHEN paint_rate_last_10 IS NULL THEN 1 ELSE 0 END) as missing_paint
FROM ml_feature_store_v2
WHERE game_date = '2025-01-19';
```

**If one feature:** Specific calculation issue
**If many features:** Upstream data issue

**Check upstream:**
```sql
-- Does source data exist?
SELECT COUNT(*)
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = '2025-01-19';

-- If 0: Precompute didn't run
-- If >0: Feature engineering issue
```

#### Solutions

**If precompute missing:**
```bash
# Run precompute manually
python data_processors/precompute/composite_factors_calculator.py \
  --date 2025-01-19

# Then regenerate features
python ml/features/feature_engineering.py --date 2025-01-19
```

**If feature calculation broken:**
```bash
# Check logs
gcloud logging read "severity>=ERROR"

# Fix calculation logic
# Rerun feature engineering
```

---

## 🎯 Confidence Issues {#confidence-issues}

### Issue: Confidence Not Calibrated

**Symptom:**
```
High Confidence (85+): 54% accuracy
Medium Confidence (70-84): 56% accuracy
Low Confidence (<70): 55% accuracy

Problem: High confidence NOT better than low
```

#### Diagnosis

```sql
SELECT
  CASE
    WHEN confidence_score >= 85 THEN 'HIGH'
    WHEN confidence_score >= 70 THEN 'MEDIUM'
    ELSE 'LOW'
  END as tier,
  COUNT(*) as predictions,
  AVG(confidence_score) as avg_confidence,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM prediction_results
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY tier;
```

#### Solutions

**Option 1: Fix Confidence Logic**

```python
# Update calculate_confidence() in xgboost_predictor.py

def calculate_confidence(self, X, predictions):
    base_confidence = 75

    # Adjust for feature completeness
    missing_pct = X.isnull().sum().sum() / (X.shape[0] * X.shape[1])
    base_confidence -= missing_pct * 30

    # Adjust for prediction extremes
    if predictions < 15 or predictions > 40:
        base_confidence -= 10

    return max(40, min(95, base_confidence))
```

**Option 2: Adjust Thresholds**

```yaml
# In config file
confidence_thresholds:
  high: 90       # Increase from 85 (be more strict)
  medium: 80     # Increase from 70
  low: 65        # Increase from 55
```

See [Confidence Scoring Framework](../../algorithms/02-confidence-scoring-framework.md) for details.

---

## 🆘 Escalation Paths {#escalation}

### Level 1: Check This Guide
- Find symptom
- Follow diagnosis steps
- Try solutions

### Level 2: Check Related Docs
- [Performance Monitoring](./06-performance-monitoring.md)
- [Continuous Retraining](../../ml-training/02-continuous-retraining.md)
- [Troubleshooting](../operations/03-troubleshooting.md)

### Level 3: Deep Investigation
- Check logs systematically
- Query BigQuery directly
- Review recent code changes
- Check external factors (NBA schedule, rules)

### Level 4: Emergency Actions
1. **Disable affected systems**
   ```sql
   UPDATE system_config SET is_active = FALSE WHERE system_id = '[PROBLEM_SYSTEM]';
   ```

2. **Fall back to working systems**
   - Use only systems with >55% accuracy
   - Reduce prediction volume if needed

3. **Fix root cause**
   - Don't rush the fix
   - Test thoroughly before re-enabling

4. **Validate before re-enabling**
   - Run on historical data first
   - Shadow mode for 1 day
   - Monitor closely after re-enable

---

## 🔗 Related Documentation {#related-docs}

### Operations
- **[Daily Operations Checklist](./05-daily-operations-checklist.md)** - Daily routine
- **[Performance Monitoring](./06-performance-monitoring.md)** - Monitoring tools
- **[Weekly Maintenance](./07-weekly-maintenance.md)** - Weekly reviews
- **[Monthly Maintenance](./08-monthly-maintenance.md)** - Model retraining
- **[Troubleshooting](../operations/03-troubleshooting.md)** - Common issues (basic)

### ML Training
- **[Initial Model Training](../../ml-training/01-initial-model-training.md)** - Training procedures
- **[Continuous Retraining](../../ml-training/02-continuous-retraining.md)** - Drift detection, retraining triggers

### Tutorials
- **[Operations Command Reference](../../tutorials/04-operations-command-reference.md)** - Quick command lookup
- **[Getting Started](../../tutorials/01-getting-started.md)** - Onboarding

---

## 📝 Prevention Checklist

### Daily Prevention
- [ ] Run monitoring script every morning
- [ ] Check for alerts in Slack
- [ ] Verify predictions generated

### Weekly Prevention
- [ ] Review performance trends
- [ ] Check data quality dashboard
- [ ] Verify all pipeline jobs running

### Monthly Prevention
- [ ] Retrain models on schedule
- [ ] Review and update documentation
- [ ] Check GCS storage costs
- [ ] Validate backups exist

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Platform Operations Team
