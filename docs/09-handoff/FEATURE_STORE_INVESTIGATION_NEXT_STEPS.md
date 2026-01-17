# Feature Store Investigation - Next Steps

**Investigation Date:** 2026-01-16
**Root Cause Identified:** phase4_partial pipeline stopped on Jan 8, 2026

---

## What We Found

The comprehensive BigQuery analysis revealed a **complete loss of the phase4_partial data source** on January 8, 2026:

- **Before Jan 8:** 783 phase4_partial records (47% of data) providing quality scores 89.8-97
- **After Jan 8:** 0 phase4_partial records (0% of data) - pipeline completely stopped
- **Impact:** Models lost access to high-quality features they were likely trained on

---

## Immediate Action Items

### 1. Investigate Phase4 Pipeline Failure (P0 - URGENT)

**Questions to answer:**
- Was the phase4_partial pipeline intentionally deprecated?
- Or did it fail unexpectedly?
- What is "phase4_partial" vs "mixed" data source?
- Where is the code that generates these two sources?

**Where to look:**
```bash
# Search for phase4_partial in codebase
cd /home/naji/code/nba-stats-scraper
grep -r "phase4_partial" . --include="*.py" --include="*.sql"
grep -r "data_source.*phase4" . --include="*.py" --include="*.sql"

# Check for feature generation code
find scripts -name "*feature*" -type f
find src -name "*feature*" -type f

# Check Cloud Functions/Workers
find . -name "*worker*" -o -name "*function*" | grep -v node_modules
```

**Check Cloud Logs:**
```bash
# Check logs around Jan 7-8 transition
gcloud logging read "
  resource.type=cloud_function
  timestamp>='2026-01-07T00:00:00Z'
  timestamp<='2026-01-08T23:59:59Z'
  (jsonPayload.message=~'phase4' OR textPayload=~'phase4' OR jsonPayload.message=~'feature')
" --limit=100 --format=json --project=nba-props-platform
```

### 2. Check Feature Generation Worker Status (P0)

**Queries to run:**
```sql
-- Check prediction_worker_runs table for failures
SELECT
    run_date,
    success,
    COUNT(*) as run_count,
    COUNT(DISTINCT player_lookup) as unique_players,
    AVG(execution_time_ms) as avg_execution_time
FROM `nba-props-platform.nba_predictions.prediction_worker_runs`
WHERE run_date BETWEEN '2026-01-06' AND '2026-01-10'
GROUP BY run_date, success
ORDER BY run_date, success;

-- Check for error messages
SELECT
    run_date,
    player_lookup,
    error_message,
    execution_time_ms
FROM `nba-props-platform.nba_predictions.prediction_worker_runs`
WHERE run_date BETWEEN '2026-01-06' AND '2026-01-10'
  AND success = false
LIMIT 50;
```

### 3. Compare Feature Generation Code Versions (P0)

**Check git history around Jan 7-8:**
```bash
# Check commits around the transition
git log --since="2026-01-06" --until="2026-01-09" --oneline --all

# Look for changes to feature generation
git log --since="2026-01-06" --until="2026-01-09" --all -- "*feature*"

# Check for changes to worker/prediction code
git log --since="2026-01-06" --until="2026-01-09" --all -- "*worker*" "*prediction*"
```

### 4. Identify Model Training Data Source (P1)

**Questions:**
- What data source were the current models trained on?
- When were they last retrained?
- Do we have model metadata showing training data characteristics?

**Check:**
```sql
-- Check ML model registry
SELECT
    model_id,
    model_version,
    training_date,
    feature_version,
    training_data_source,  -- if this field exists
    training_records,
    validation_accuracy,
    notes
FROM `nba-props-platform.nba_predictions.ml_model_registry`
ORDER BY training_date DESC
LIMIT 10;
```

---

## Analysis Queries Already Run

All query results are saved in `/tmp/q*.json`:

1. ✅ `q1_feature_quality_over_time.json` - Daily quality trends
2. ✅ `q2_data_source_distribution.json` - Data source breakdown
3. ✅ `q3_feature_completeness.json` - NULL checking (all NULL)
4. ✅ `q4a_sample_jan7.json` - Sample features from Jan 7
5. ✅ `q4b_sample_jan8.json` - Sample features from Jan 8
6. ✅ `q5_feature_version.json` - Feature version distribution
7. ✅ `q6_before_after_comparison.json` - Before/after stats
8. ✅ `q7_transition_window.json` - Jan 6-10 detailed view
9. ✅ `q8a-d_feature_values_*.json` - Actual feature value samples
10. ✅ `q9_feature_array_health.json` - Feature array validation
11. ✅ `q10_quality_score_distribution.json` - Exact quality buckets

---

## Decision Tree

```
Is phase4_partial pipeline supposed to be running?
│
├─ YES (pipeline failed unexpectedly)
│  ├─ ACTION: Fix the pipeline
│  ├─ ACTION: Restore phase4_partial data generation
│  └─ RESULT: Model performance should recover
│
└─ NO (pipeline was intentionally deprecated)
   ├─ ACTION: Retrain models on mixed-only data
   ├─ ACTION: Update feature expectations
   └─ RESULT: New models adapted to current data distribution
```

---

## Code to Review

### Priority 1: Feature Generation
```
scripts/nba/generate_ml_features.py  (if exists)
src/nba/features/  (if exists)
cloud_functions/nba/features/  (if exists)
workers/nba/prediction_worker.py  (if exists)
```

### Priority 2: Data Pipelines
```
scripts/nba/precompute/  (likely location)
src/nba/pipelines/  (if exists)
airflow/dags/nba_feature_generation.py  (if exists)
```

### Priority 3: Model Training
```
scripts/nba/train_model.py  (if exists)
src/nba/ml/training/  (if exists)
notebooks/nba/model_training/  (if exists)
```

---

## Questions for Domain Experts

1. **What is "phase4_partial"?**
   - Is it a specific data enrichment step?
   - Does it refer to a 4th phase of data collection?
   - Why is it called "partial"?

2. **What is "mixed" data source?**
   - Does it mix multiple data sources?
   - Is it a fallback when primary sources fail?
   - Why does it have lower quality scores?

3. **When were current models trained?**
   - What data range was used for training?
   - What was the data_source distribution in training data?
   - Are models retrained regularly or static?

4. **Is there a runbook for feature pipeline failures?**
   - Who owns the feature generation pipeline?
   - Is there monitoring/alerting for this?
   - What's the recovery procedure?

---

## Monitoring to Add (Future)

### 1. Data Source Distribution Alert
```sql
-- Alert if phase4_partial drops to 0
-- Alert if data_source distribution changes >20% day-over-day
```

### 2. Feature Quality Alert
```sql
-- Alert if avg quality < 75 for a day
-- Alert if max quality < 90 for a day (indicates no high-quality features)
-- Alert if stddev < 5 (indicates lack of variance)
```

### 3. Feature Pipeline Health
```sql
-- Alert if prediction_worker_runs success rate < 95%
-- Alert if feature_count != 33 for any record
-- Alert if >5% of features are NULL/zero
```

### 4. Model Performance Correlation
```sql
-- Track correlation between feature_quality_score and prediction accuracy
-- Alert if accuracy drops when quality drops
```

---

## Files Generated by This Analysis

1. **FEATURE_STORE_JAN_7_8_COMPREHENSIVE_ANALYSIS.md**
   - Full detailed analysis with all findings
   - Tables, charts, observations
   - Root cause analysis

2. **analyze_feature_store_jan7_8.py**
   - Python script to visualize the query results
   - Can be re-run with updated data
   - Generates formatted reports

3. **FEATURE_STORE_INVESTIGATION_NEXT_STEPS.md** (this file)
   - Action items and decision tree
   - Code locations to investigate
   - Queries to run next

4. **Query result files in /tmp/**
   - q1 through q10 JSON files
   - Can be re-analyzed or shared

---

## Summary

**Root Cause:** phase4_partial pipeline stopped producing features on Jan 8, 2026

**Evidence:**
- 783 phase4_partial records before Jan 8 → 0 after Jan 8 (100% loss)
- Quality 90+ records dropped 46% → 25% (-36% reduction)
- No high-quality features (97.0) on Jan 8 itself

**Next Critical Step:**
Determine if phase4_partial loss was intentional or a bug. This dictates whether to:
- Fix the pipeline (if bug)
- Retrain models (if intentional deprecation)

**Who Should Investigate:**
- Platform/DevOps: Check pipeline health, logs, deployments around Jan 7-8
- ML Team: Confirm training data source and retraining requirements
- Data Engineering: Explain phase4_partial vs mixed data sources
