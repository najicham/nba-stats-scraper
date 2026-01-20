# Future Work Options - Prediction System Optimization
**Created:** 2026-01-18 (Session 98 afternoon)
**Purpose:** Document valuable work options for future sessions
**Status:** 📋 Planned - Execute after Track E complete and Track A monitoring period

---

## 🎯 Overview

This document captures high-value work options identified during Session 98 planning. These are productive tasks that can be executed when:
- Track A monitoring completes (after Jan 23)
- Track B is ready to start (XGBoost V1 V2 validated)
- We have 1-4 hour blocks of time
- We want to improve operational excellence

---

## 🛠️ Option 2: Prepare Track B (Ensemble Retraining)

**Status:** 🚫 Blocked (need 5 days of XGBoost V1 V2 data first)
**Priority:** HIGH (but wait until Jan 23+)
**Time Required:** 2-3 hours preparation, then 8-10 hours execution
**Value:** Speeds up Track B execution when ready

### Why This Is Valuable

- Track B is our highest priority next track (85% likely path)
- Preparation makes execution much faster
- Understanding current ensemble reduces risk
- Could start immediately on Day 6 (Jan 24)

### What We Can Do (Preparation Phase)

#### 1. Review Current Ensemble Code (45 min)
```bash
# Read and understand ensemble training script
# Likely locations:
- models/ensemble/train_ensemble.py
- models/ensemble/ensemble_predictor.py
- predictions/worker/ensemble_v1.py
```

**Questions to Answer:**
- Where are individual model weights/predictions loaded?
- How is ensemble currently weighted?
- What training data is used?
- How are predictions combined?
- What hyperparameters exist?

**Deliverable:** Code architecture diagram + notes

---

#### 2. Analyze Current Ensemble Performance (45 min)
```sql
-- Compare ensemble to individual systems (last 30 days)
SELECT
  system_id,
  COUNT(*) as total_graded,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate_pct,
  ROUND(STDDEV(absolute_error), 2) as mae_stddev
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id IN ('ensemble_v1', 'catboost_v8', 'xgboost_v1')
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY system_id
ORDER BY mae ASC
```

**Questions to Answer:**
- Is ensemble currently better than CatBoost V8?
- Is ensemble using old XGBoost V1 weights?
- What's the performance gap we're trying to close?
- Which predictions does ensemble excel at?

**Deliverable:** Performance analysis document

---

#### 3. Design Retraining Strategy (45 min)

**Plan Considerations:**
1. **Training Data Window**
   - How many days of historical data?
   - Include XGBoost V1 V2 predictions (from Jan 18+)
   - Balance recency vs sample size

2. **Model Architecture**
   - Keep current architecture or redesign?
   - Which systems to include? (all 6 or subset?)
   - How to weight systems? (equal, performance-based, learned)

3. **Validation Strategy**
   - Hold-out set (last N days?)
   - Cross-validation approach?
   - Success criteria (MAE < 3.40 to beat CatBoost?)

4. **Deployment Plan**
   - Deploy as ensemble_v2 (new system)?
   - Replace ensemble_v1?
   - A/B test period?

**Deliverable:** Detailed retraining plan document

---

#### 4. Prepare Training Environment (30 min)

**Setup Tasks:**
- Verify Python dependencies for training
- Test training data extraction query
- Check compute resources (local vs Cloud?)
- Prepare training script template
- Set up model versioning strategy
- Plan artifact storage (where to save trained model?)

**Training Data Query Template:**
```sql
-- Extract training data for ensemble
SELECT
  pa.game_date,
  pa.game_id,
  pa.player_lookup,
  pa.line,
  pa.actual_points,
  -- Get predictions from each system
  MAX(IF(pa.system_id = 'xgboost_v1', pa.predicted_points, NULL)) as xgb_pred,
  MAX(IF(pa.system_id = 'catboost_v8', pa.predicted_points, NULL)) as cat_pred,
  MAX(IF(pa.system_id = 'similarity_balanced_v1', pa.predicted_points, NULL)) as sim_pred,
  MAX(IF(pa.system_id = 'zone_matchup_v1', pa.predicted_points, NULL)) as zone_pred,
  MAX(IF(pa.system_id = 'moving_average', pa.predicted_points, NULL)) as ma_pred
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
WHERE pa.game_date BETWEEN 'START_DATE' AND 'END_DATE'
  AND pa.recommendation IN ('OVER', 'UNDER')
  AND pa.has_prop_line = TRUE
GROUP BY pa.game_date, pa.game_id, pa.player_lookup, pa.line, pa.actual_points
HAVING COUNT(DISTINCT pa.system_id) >= 5  -- Ensure we have most systems
```

**Deliverable:** Ready-to-execute training environment

---

### Success Criteria for Track B

**Must Achieve:**
- Ensemble MAE ≤ 3.40 (match or beat CatBoost V8)
- Win rate ≥ 52%
- Validation performance stable across different date ranges

**Stretch Goals:**
- Ensemble MAE < 3.35 (beat CatBoost by 0.05)
- Improved calibration (confidence matches actual performance)
- Better performance on specific player types

---

### Estimated Timeline

**Preparation (can do before Jan 23):** 2-3 hours
**Execution (after Jan 23):** 8-10 hours
- Training data prep: 1 hour
- Model training experiments: 3-4 hours
- Validation analysis: 1-2 hours
- Deployment prep: 1 hour
- Testing: 2-3 hours

**Total:** 10-13 hours end-to-end

---

## 📊 Option 3: Track C - Infrastructure Monitoring

**Status:** 📋 Planned
**Priority:** MEDIUM (operational excellence)
**Time Required:** 3-4 hours
**Value:** Catch issues before they become problems

### Why This Is Valuable

- Proactive issue detection
- Professional production setup
- Reduces MTTR (mean time to recovery)
- Improves operational confidence
- Could alert us during Track A monitoring period

---

### What We Can Do

#### 1. Cloud Monitoring Alerts (90 min)

**Critical Alerts to Create:**

**Alert 1: Prediction Coordinator Failure**
```
Resource: Cloud Run service prediction-coordinator
Condition: Error rate > 5% over 5 minutes
Notification: Email/Slack
Severity: CRITICAL
```

**Alert 2: Grading Processor Failure**
```
Resource: Cloud Run service grading-processor
Condition: No successful executions in 24 hours
Notification: Email/Slack
Severity: HIGH
```

**Alert 3: Model Serving Errors**
```
Resource: Cloud Run service prediction-worker
Condition: 5xx errors > 10 in 10 minutes
Notification: Email/Slack
Severity: HIGH
```

**Alert 4: Feature Store Staleness**
```
Query: Check max(game_date) in feature store
Condition: No new data in 36 hours
Notification: Email/Slack
Severity: MEDIUM
```

**Alert 5: BigQuery Quota**
```
Resource: BigQuery project
Condition: Query quota > 80% of daily limit
Notification: Email/Slack
Severity: MEDIUM
```

**Alert 6: Low Prediction Volume**
```
Query: Count predictions per day
Condition: < 200 predictions generated today
Notification: Email/Slack
Severity: HIGH
```

**Implementation Commands:**
```bash
# Create alerts using gcloud
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Prediction Coordinator Failure" \
  --condition-display-name="High error rate" \
  --condition-threshold-value=5 \
  --condition-threshold-duration=300s
# ... (repeat for each alert)
```

**Deliverable:** 6 production alerts configured

---

#### 2. Monitoring Dashboard (60 min)

**Dashboard Panels:**

1. **Prediction Volume (All 6 Systems)**
   - Time series: predictions per day by system_id
   - Last 30 days
   - Stacked area chart

2. **Grading Coverage**
   - Time series: % of predictions graded
   - By system_id
   - Line chart with 70% threshold line

3. **MAE Trends**
   - Time series: MAE by system_id
   - Last 30 days
   - Line chart with target thresholds

4. **Win Rate Trends**
   - Time series: Win % by system_id
   - Last 30 days
   - Line chart

5. **Coordinator Performance**
   - Time series: execution duration
   - 95th percentile, median
   - Last 7 days

6. **Error Rates**
   - Time series: errors by service
   - Prediction coordinator, grading processor, worker
   - Last 7 days

**Implementation:**
- Use Google Cloud Monitoring Dashboards
- Or Looker Studio connected to BigQuery
- Or custom dashboard (Grafana, etc.)

**Deliverable:** Production dashboard URL

---

#### 3. Log-Based Metrics (45 min)

**Custom Metrics to Create:**

**Metric 1: Batch Loading Duration**
```
# Extract from logs: "Batch loaded X in Y seconds"
# Create metric: batch_load_duration_seconds
# Aggregate: p50, p95, p99
```

**Metric 2: Circuit Breaker Trips**
```
# Extract from logs: "Circuit breaker triggered for system_id"
# Create metric: circuit_breaker_trips_count
# Aggregate: count by system_id
```

**Metric 3: Feature Store Cache Hits**
```
# Extract from logs: "Cache hit/miss"
# Create metric: feature_store_cache_hit_rate
# Aggregate: hit rate %
```

**Metric 4: Model Inference Latency**
```
# Extract from logs: model inference timing
# Create metric: model_inference_duration_ms
# Aggregate: p50, p95, p99 by system_id
```

**Implementation:**
```bash
# Create log-based metric
gcloud logging metrics create batch_load_duration \
  --description="Batch loading duration in seconds" \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-coordinator"
    AND jsonPayload.message=~"Batch loaded .* in .* seconds"'
```

**Deliverable:** 4 custom log-based metrics

---

#### 4. Runbook Creation (30 min)

**Runbook Sections:**

1. **Common Failure Scenarios**
   - Prediction coordinator timeout
   - Grading processor failure
   - Feature store staleness
   - Model serving errors
   - Low prediction volume

2. **Troubleshooting Steps**
   - How to check logs
   - How to check BigQuery tables
   - How to check Firestore state
   - How to verify service health

3. **Recovery Procedures**
   - Restart Cloud Run service
   - Clear Firestore state
   - Trigger manual execution
   - Rollback deployment

4. **On-Call Guidance**
   - Severity definitions
   - Escalation paths
   - Response time SLAs
   - Communication templates

**Deliverable:** Runbook markdown document

---

### Success Criteria for Track C

**Must Achieve:**
- All 6 critical alerts configured and tested
- Dashboard showing key metrics
- Runbook documented
- Tested alert notifications

**Stretch Goals:**
- Automated remediation for common issues
- SLO/SLI definitions
- Incident retrospective template

---

## 🔬 Option 4: Deep Model Analysis

**Status:** 📋 Planned
**Priority:** MEDIUM (nice to have, informs Track B)
**Time Required:** 1-2 hours
**Value:** Better understanding of model characteristics

### Why This Is Valuable

- Understand XGBoost V1 V2 vs CatBoost V8 differences
- Identify feature importance
- Inform ensemble retraining strategy
- Could discover insights for future optimization
- Better intuition about model behavior

---

### What We Can Do

#### 1. Feature Importance Analysis (45 min)

**XGBoost V1 V2 Analysis:**
```python
# Load model and extract feature importance
import joblib
import pandas as pd

# Assuming model is stored in GCS or local
model = joblib.load('models/xgboost_v1_v2_33features_20260118.pkl')

# Get feature importance
importance = model.get_booster().get_score(importance_type='gain')
importance_df = pd.DataFrame([
    {'feature': k, 'importance': v}
    for k, v in importance.items()
]).sort_values('importance', ascending=False)

print(importance_df.head(20))  # Top 20 features
```

**Questions to Answer:**
- Which features drive predictions most?
- Are pace features (if added) likely to help?
- Any surprising feature importance?
- Are there underutilized features?

**Deliverable:** Feature importance report

---

#### 2. Validation Set Deep Dive (45 min)

**Performance by Player Type:**
```sql
-- Analyze MAE by player characteristics
WITH player_stats AS (
  SELECT
    pa.player_lookup,
    pa.system_id,
    AVG(pa.line) as avg_line,
    AVG(pa.absolute_error) as avg_mae,
    COUNT(*) as predictions
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  WHERE pa.system_id IN ('xgboost_v1', 'catboost_v8')
    AND pa.game_date >= '2026-01-01'
    AND pa.recommendation IN ('OVER', 'UNDER')
  GROUP BY pa.player_lookup, pa.system_id
)
SELECT
  system_id,
  CASE
    WHEN avg_line < 15 THEN 'Low scorers (<15)'
    WHEN avg_line < 25 THEN 'Medium scorers (15-25)'
    ELSE 'High scorers (25+)'
  END as player_type,
  COUNT(*) as players,
  ROUND(AVG(avg_mae), 2) as avg_mae,
  ROUND(MIN(avg_mae), 2) as best_mae,
  ROUND(MAX(avg_mae), 2) as worst_mae
FROM player_stats
GROUP BY system_id, player_type
ORDER BY system_id, player_type
```

**Performance by Line Value:**
```sql
-- Analyze MAE by line value range
SELECT
  system_id,
  CASE
    WHEN line < 15 THEN '<15'
    WHEN line < 20 THEN '15-20'
    WHEN line < 25 THEN '20-25'
    WHEN line < 30 THEN '25-30'
    ELSE '30+'
  END as line_range,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNT(*)) * 100, 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id IN ('xgboost_v1', 'catboost_v8')
  AND game_date >= '2026-01-01'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY system_id, line_range
ORDER BY system_id, line_range
```

**Questions to Answer:**
- Does XGBoost V1 V2 excel at certain player types?
- Are there systematic biases by line value?
- Where does each model struggle?
- Are there complementary strengths? (good for ensemble!)

**Deliverable:** Performance breakdown analysis

---

#### 3. Confidence Calibration Analysis (30 min)

**Check if confidence matches actual performance:**
```sql
-- Analyze if high confidence = better performance
SELECT
  system_id,
  CASE
    WHEN confidence < 0.6 THEN 'Low (<0.6)'
    WHEN confidence < 0.7 THEN 'Medium (0.6-0.7)'
    WHEN confidence < 0.8 THEN 'High (0.7-0.8)'
    ELSE 'Very High (0.8+)'
  END as confidence_bucket,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNT(*)) * 100, 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id IN ('xgboost_v1', 'catboost_v8')
  AND game_date >= '2026-01-01'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY system_id, confidence_bucket
ORDER BY system_id, confidence_bucket
```

**Questions to Answer:**
- Is confidence well-calibrated? (high conf = low MAE?)
- Can we trust confidence scores for filtering?
- Should we adjust confidence thresholds?

**Deliverable:** Confidence calibration report

---

### Success Criteria for Option 4

**Must Achieve:**
- Feature importance documented
- Performance by player type analyzed
- Confidence calibration understood

**Value:**
- Better intuition about models
- Informs ensemble design
- Identifies optimization opportunities

---

## ⚡ Quick Wins (1 hour)

**If you have limited time but want to make progress:**

### Quick Win 1: Critical Alerts (30 min)
Set up just the 3 most critical alerts:
1. Prediction coordinator failure
2. Grading processor failure
3. Low prediction volume

### Quick Win 2: Simple Dashboard (30 min)
Create basic Looker Studio dashboard with:
1. Prediction volume by system (last 30 days)
2. MAE trends by system (last 30 days)
3. Win rate by system (last 30 days)

### Quick Win 3: Deployment Documentation (30 min)
Document:
1. How to deploy coordinator changes
2. How to deploy worker changes
3. How to rollback
4. Where models are stored

---

## 📅 Recommended Execution Order

**After Track E Complete (today):**
1. ✅ Track A monitoring starts tomorrow (Jan 19-23)
2. Wait for monitoring results

**After Track A Monitoring (Jan 23+):**

**If MAE ≤ 4.0 (Track B ready):**
1. Execute Option 2 prep (2-3h) → Then start Track B
2. While Track B running: Execute Option 3 (alerts/monitoring)

**If MAE 4.0-4.5 (Track E first):**
1. Complete remaining Track E scenarios
2. Execute Option 3 (infrastructure monitoring)
3. Then start Track B

**If MAE > 4.5 (investigate):**
1. Execute Option 4 (model analysis) to understand issues
2. Debug model problems
3. Reassess Track B timeline

**Anytime (operational excellence):**
- Quick Wins can be done in any 30-min block
- Track C improves operations regardless of Track B timing

---

## 📊 Priority Matrix

```
High Value + Soon Needed:
- Option 2 (Track B prep) - Do before Jan 24

High Value + Can Wait:
- Option 3 (Monitoring) - Do when have 3-4h block
- Option 4 (Model analysis) - Do before Track B

Medium Value + Quick:
- Quick Wins - Do anytime in 30-min blocks
```

---

## 📝 Notes

**Created:** 2026-01-18 during Session 98 afternoon planning
**Context:** After completing Track E to 60%, identified other valuable work options
**Purpose:** Don't lose these ideas - come back to them when ready
**Next Review:** After Jan 23 (Track A monitoring complete)

---

**✅ Document complete - These options are preserved for future sessions!**
