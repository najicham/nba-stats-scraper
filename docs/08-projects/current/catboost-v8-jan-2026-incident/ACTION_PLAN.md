# Action Plan: Fixing CatBoost V8 January 2026 Incident
**Created**: 2026-01-16
**Priority**: P0 CRITICAL
**Estimated Time**: 4-8 hours total

---

## 🎯 Objectives

1. ✅ Restore player_daily_cache pipeline reliability
2. ✅ Fix 50% confidence stuck issue
3. ✅ Backfill missing historical data
4. ✅ Add monitoring to prevent recurrence
5. ✅ Verify system health for 3+ days

---

## 📋 Investigation Phase (2-4 hours)

### Task 1: Investigate player_daily_cache Pipeline Failure ⚠️ P0

**Goal**: Understand why player_daily_cache failed to update on Jan 8 & 12

**Steps**:

1. **Check Cloud Scheduler Configuration**
   ```bash
   # List all scheduler jobs
   gcloud scheduler jobs list --project=nba-props-platform

   # Get player_daily_cache job details
   gcloud scheduler jobs describe player-daily-cache-processor \
     --location=us-central1 \
     --project=nba-props-platform

   # Check schedule (looking for day-of-week pattern)
   # Jan 8 = Wednesday, Jan 12 = Sunday
   ```

2. **Review Cloud Logs for Jan 7-8, Jan 11-12**
   ```bash
   # Scheduler execution logs
   gcloud logging read \
     "resource.type=cloud_scheduler_job AND
      resource.labels.job_id=player-daily-cache-processor AND
      timestamp>=\"2026-01-07T00:00:00Z\" AND
      timestamp<=\"2026-01-13T00:00:00Z\"" \
     --limit=50 \
     --format=json \
     --project=nba-props-platform

   # Cloud Function/Run logs (if it triggered)
   gcloud logging read \
     "resource.type=cloud_function AND
      resource.labels.function_name=player-daily-cache AND
      timestamp>=\"2026-01-07T00:00:00Z\" AND
      timestamp<=\"2026-01-13T00:00:00Z\"" \
     --limit=50 \
     --format=json \
     --project=nba-props-platform

   # Look for:
   # - Did scheduler trigger?
   # - Did function execute?
   # - Any errors/timeouts?
   # - Completion status?
   ```

3. **Check Processor Code for Recent Changes**
   ```bash
   # Git history around the failure dates
   git log --since="2026-01-05" --until="2026-01-13" \
     -- data_processors/precompute/player_daily_cache/

   # Show diffs for any changes found
   git show <commit-hash>
   ```

4. **Manual Test Run**
   ```bash
   # Try to reproduce the failure
   cd /home/naji/code/nba-stats-scraper

   # Run for Jan 8 in dry-run mode
   python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
     --date 2026-01-08 \
     --dry-run

   # Check what errors occur
   # If successful in dry-run, try actual run to backfill
   ```

5. **Verify Upstream Data Availability**
   ```sql
   -- Check if Phase3 data was available for Jan 8
   SELECT
       game_date,
       COUNT(DISTINCT player_lookup) as players,
       COUNT(*) as records
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date BETWEEN '2026-01-01' AND '2026-01-08'
   GROUP BY game_date
   ORDER BY game_date;

   -- Should have plenty of data for Jan 8
   ```

**Expected Findings**:
- Scheduler didn't trigger (config issue)
- Function timed out (resource limit)
- Code exception (bug)
- Upstream data missing (dependency failure)
- BigQuery write failed (MERGE error)

**Document**: Save logs and findings to `investigation-findings/player-daily-cache-failure.md`

---

### Task 2: Investigate 50% Confidence Stuck Issue ⚠️ P0

**Goal**: Understand why ALL predictions show exactly 50% confidence after fixes

**Steps**:

1. **Check Prediction Logs (Jan 12-15)**
   ```bash
   # Look for fallback triggers
   gcloud logging read \
     "resource.type=cloud_run_revision AND
      resource.labels.service_name=prediction-worker AND
      timestamp>=\"2026-01-12T00:00:00Z\" AND
      timestamp<=\"2026-01-16T00:00:00Z\"" \
     --limit=200 \
     --format=json \
     --project=nba-props-platform | grep -i "fallback"

   # Look for:
   # - "Using fallback prediction"
   # - Exception traces
   # - "Model failed to load"
   # - "Invalid feature vector"
   ```

2. **Verify Model Loading**
   ```python
   # Test script to check model loading
   import sys
   sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

   from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8PredictionSystem

   system = CatBoostV8PredictionSystem()
   print(f"Model loaded: {system.model is not None}")
   print(f"Model path: {system.model_path if hasattr(system, 'model_path') else 'N/A'}")

   # Try a test prediction
   sample_features = {
       'feature_quality_score': 85,
       'points_std_last_10': 5.2,
       # ... other features
   }

   import numpy as np
   feature_vector = np.array([20.5] * 33)  # Dummy 33 features

   confidence = system._calculate_confidence(sample_features, feature_vector)
   print(f"Calculated confidence: {confidence}")

   # Should be around 75 + 7 + 7 = 89, NOT 50
   ```

3. **Check Feature Vector Validation**
   ```bash
   # Read catboost_v8.py to find validation logic
   grep -n "feature_vector" predictions/worker/prediction_systems/catboost_v8.py
   grep -n "fallback" predictions/worker/prediction_systems/catboost_v8.py

   # Look for:
   # - Feature count checks (must be 33)
   # - NaN/Inf validation
   # - Quality score thresholds
   # - Any conditions that trigger fallback
   ```

4. **Review Recent Changes to Confidence Logic**
   ```bash
   # Check if confidence calculation changed
   git log --since="2026-01-08" --until="2026-01-16" \
     -- predictions/worker/prediction_systems/catboost_v8.py

   # If changes found, review them
   ```

5. **Test Confidence Calculation Locally**
   ```python
   # Create test script: test_confidence.py
   from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8PredictionSystem
   import numpy as np

   system = CatBoostV8PredictionSystem()

   # Test various quality scores
   test_cases = [
       {'feature_quality_score': 95, 'points_std_last_10': 3.5},  # Should be 95
       {'feature_quality_score': 85, 'points_std_last_10': 5.0},  # Should be 89
       {'feature_quality_score': 75, 'points_std_last_10': 7.0},  # Should be 85
   ]

   for features in test_cases:
       confidence = system._calculate_confidence(features, np.array([20.0] * 33))
       print(f"Quality: {features['feature_quality_score']}, "
             f"Std: {features['points_std_last_10']}, "
             f"Confidence: {confidence}")
   ```

**Expected Findings**:
- Model file not loading properly
- Feature validation failing (triggering fallback)
- Silent exception in prediction code
- Quality score below some threshold
- Recent code change introduced bug

**Document**: Save findings to `investigation-findings/50-percent-confidence-issue.md`

---

## 🔧 Fix Phase (1-2 hours)

### Task 3: Fix player_daily_cache Pipeline ⚠️ P0

**Based on investigation findings, apply appropriate fix**:

**If scheduler issue**:
```bash
# Update scheduler configuration
gcloud scheduler jobs update http player-daily-cache-processor \
  --schedule="0 23 * * *" \  # Adjust as needed
  --location=us-central1 \
  --project=nba-props-platform
```

**If timeout issue**:
```python
# Update function timeout in config
# Or optimize processor query performance
```

**If code bug**:
```bash
# Fix the bug, test locally, deploy
git add data_processors/precompute/player_daily_cache/
git commit -m "fix: Fix player_daily_cache pipeline failure"
# Deploy to production
```

**If upstream data issue**:
```bash
# Fix dependency ordering in orchestration
# Or add retry logic for transient failures
```

**Verification**:
```bash
# Manual run for current date
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --date $(date +%Y-%m-%d)

# Check BigQuery
bq query --use_legacy_sql=false \
  "SELECT cache_date, COUNT(*) as records
   FROM nba_precompute.player_daily_cache
   WHERE cache_date = CURRENT_DATE()
   GROUP BY cache_date"

# Should show records
```

---

### Task 4: Fix 50% Confidence Issue ⚠️ P0

**Based on investigation findings, apply appropriate fix**:

**If model not loading**:
```python
# Check model file path, permissions, existence
# Redeploy model if corrupted
# Update path if incorrect
```

**If feature validation failing**:
```python
# Review validation logic in catboost_v8.py
# Adjust thresholds or fix validation bug
# Test with real feature vectors
```

**If silent exception**:
```python
# Add proper logging to catch exceptions
# Don't swallow errors in exception handlers
# Make fallback logging more visible
```

**If quality threshold**:
```python
# Review if there's a quality-based fallback
# Adjust threshold if too strict
# Or accept that low quality should use fallback
```

**Verification**:
```python
# Test locally with real data
from predictions.worker import worker

result = worker.predict(
    player_lookup='lebron_james',
    game_date='2026-01-16',
    system_id='catboost_v8'
)

print(f"Confidence: {result['confidence_score']}")
# Should NOT be 50% for all predictions
```

---

### Task 5: Backfill Missing Data ⚠️ P0

**Goal**: Restore historical data for Jan 8 and Jan 12

**Steps**:

1. **Backfill player_daily_cache**
   ```bash
   # Jan 8
   python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
     --date 2026-01-08

   # Verify
   bq query --use_legacy_sql=false \
     "SELECT COUNT(*) FROM nba_precompute.player_daily_cache
      WHERE cache_date = '2026-01-08'"

   # Jan 12
   python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
     --date 2026-01-12

   # Verify
   bq query --use_legacy_sql=false \
     "SELECT COUNT(*) FROM nba_precompute.player_daily_cache
      WHERE cache_date = '2026-01-12'"
   ```

2. **Regenerate ML Feature Store for affected dates**
   ```bash
   # Jan 8
   python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
     --date 2026-01-08

   # Jan 12
   python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
     --date 2026-01-12
   ```

3. **Verify feature quality restored**
   ```sql
   -- Check feature quality for backfilled dates
   SELECT
       game_date,
       data_source,
       COUNT(*) as records,
       AVG(feature_quality_score) as avg_quality
   FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
   WHERE game_date IN ('2026-01-08', '2026-01-12')
   GROUP BY game_date, data_source;

   -- Expected:
   -- phase4_partial should reappear
   -- avg_quality should be 90+
   ```

---

## 📊 Monitoring Phase (1-2 hours)

### Task 6: Add Critical Monitoring ⚠️ P1

**Goal**: Prevent future incidents through early detection

**1. Player Daily Cache Update Alert**

```python
# Location: monitoring/alerts/data_pipeline_alerts.py

def check_player_daily_cache_freshness():
    """Alert if player_daily_cache hasn't updated in 24 hours."""
    from google.cloud import bigquery

    client = bigquery.Client()
    query = """
        SELECT MAX(cache_date) as latest_date
        FROM `nba-props-platform.nba_precompute.player_daily_cache`
    """

    result = list(client.query(query))[0]
    latest_date = result.latest_date

    # Check if older than 24 hours
    from datetime import datetime, timedelta
    if datetime.now().date() - latest_date > timedelta(days=1):
        send_alert(
            severity='CRITICAL',
            title='player_daily_cache Not Updated',
            message=f'Latest cache_date is {latest_date}, expected {datetime.now().date()}'
        )
```

**2. Feature Quality Alert**

```python
def check_feature_quality_degradation():
    """Alert if feature quality drops significantly."""
    from google.cloud import bigquery

    client = bigquery.Client()
    query = """
        SELECT
            AVG(feature_quality_score) as avg_quality,
            COUNTIF(data_source = 'phase4_partial') / COUNT(*) as phase4_partial_pct
        FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
        WHERE game_date = CURRENT_DATE()
    """

    result = list(client.query(query))[0]

    if result.avg_quality < 85:
        send_alert(
            severity='WARNING',
            title='Feature Quality Degraded',
            message=f'Average quality: {result.avg_quality} (expected >85)'
        )

    if result.phase4_partial_pct < 0.30:
        send_alert(
            severity='WARNING',
            title='Phase4 Partial Data Low',
            message=f'Phase4_partial: {result.phase4_partial_pct*100:.1f}% (expected >40%)'
        )
```

**3. Confidence Distribution Alert**

```python
def check_confidence_distribution():
    """Alert if confidence clustered at single value."""
    from google.cloud import bigquery

    client = bigquery.Client()
    query = """
        SELECT
            confidence_score,
            COUNT(*) as picks
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
          AND game_date = CURRENT_DATE()
        GROUP BY confidence_score
    """

    results = list(client.query(query))

    # Check if >80% at single value
    total_picks = sum(r.picks for r in results)
    max_picks = max(r.picks for r in results) if results else 0

    if max_picks / total_picks > 0.80:
        send_alert(
            severity='CRITICAL',
            title='Confidence Clustering Detected',
            message=f'{max_picks/total_picks*100:.1f}% picks at single confidence value'
        )
```

**4. Accuracy Degradation Alert**

```python
def check_prediction_accuracy():
    """Alert if prediction accuracy degrades significantly."""
    from google.cloud import bigquery

    client = bigquery.Client()
    query = """
        SELECT
            AVG(ABS(predicted_points - actual_points)) as avg_error,
            AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as win_rate
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
          AND game_date = CURRENT_DATE()
    """

    result = list(client.query(query))[0]

    if result.avg_error > 5.5:  # Baseline is ~4.2
        send_alert(
            severity='WARNING',
            title='Prediction Error Increased',
            message=f'Average error: {result.avg_error:.2f} points (expected <5.0)'
        )

    if result.win_rate < 0.50:
        send_alert(
            severity='CRITICAL',
            title='Win Rate Below 50%',
            message=f'Win rate: {result.win_rate*100:.1f}% (below breakeven)'
        )
```

**Deploy Alerts**:
```bash
# Add to Cloud Scheduler
gcloud scheduler jobs create http data-quality-alerts \
  --schedule="0 */4 * * *" \  # Every 4 hours
  --uri="https://your-function-url/check-data-quality" \
  --http-method=POST \
  --location=us-central1 \
  --project=nba-props-platform
```

---

## ✅ Verification Phase (30 minutes)

### Task 7: Verify System Health ⚠️ P0

**Run validation queries**:

```sql
-- 1. Check player_daily_cache updating
SELECT
    cache_date,
    COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= CURRENT_DATE() - 3
GROUP BY cache_date
ORDER BY cache_date DESC;

-- Expected: 50-200 players per day


-- 2. Check feature quality restored
SELECT
    game_date,
    data_source,
    COUNT(*) as records,
    AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date, data_source
ORDER BY game_date DESC, data_source;

-- Expected: phase4_partial >40%, avg_quality >90


-- 3. Check confidence distribution
SELECT
    ROUND(confidence_score * 100) as confidence_pct,
    COUNT(*) as picks,
    AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as win_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8'
  AND game_date >= CURRENT_DATE() - 3
GROUP BY confidence_pct
ORDER BY confidence_pct DESC;

-- Expected: Many different confidence values, not just 50%


-- 4. Check prediction performance
SELECT
    game_date,
    COUNT(*) as picks,
    AVG(confidence_score) as avg_confidence,
    AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as win_rate,
    AVG(ABS(predicted_points - actual_points)) as avg_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8'
  AND game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC;

-- Expected: win_rate >53%, avg_error <5.0
```

**Success Criteria**:
- ✅ player_daily_cache updates daily (50+ players)
- ✅ phase4_partial ≥40% of features
- ✅ Average quality score ≥90
- ✅ Confidence shows distribution (not just 50%)
- ✅ Win rate ≥53%
- ✅ Average error ≤5.0 points

---

## 📝 Documentation Phase (30 minutes)

### Task 8: Document Resolution ⚠️ P1

**Create**: `RESOLUTION_SUMMARY.md`

Include:
- What was fixed
- How it was fixed
- Verification results
- Monitoring added
- Lessons learned
- Prevention measures

**Update**: Session handoff document with resolution status

---

## 🕐 Timeline

### Day 1 (Today)
- [ ] Task 1: Investigate player_daily_cache (1-2 hours)
- [ ] Task 2: Investigate 50% confidence (1-2 hours)
- [ ] Document findings

### Day 2
- [ ] Task 3: Fix player_daily_cache (30 min - 1 hour)
- [ ] Task 4: Fix 50% confidence (30 min - 1 hour)
- [ ] Task 5: Backfill data (30 minutes)
- [ ] Task 7: Verify health (30 minutes)

### Day 3
- [ ] Task 6: Add monitoring (1-2 hours)
- [ ] Task 8: Documentation (30 minutes)
- [ ] Final verification

### Days 4-6
- [ ] Monitor daily for stability
- [ ] Ensure no regressions
- [ ] Collect 3 days of healthy data

---

## 🚨 Escalation

**If stuck or blocked**:
1. Document what you tried
2. Document what failed
3. Post findings to incident channel
4. Consider alternative approaches
5. Ask for help if needed after 2 hours on single task

**Red flags**:
- Cannot reproduce failures locally
- Fixes don't work in production
- New issues emerge after fixes
- Monitoring shows continued degradation

---

## 📋 Checklist

### Investigation Complete When:
- [ ] player_daily_cache failure root cause identified
- [ ] 50% confidence issue root cause identified
- [ ] Findings documented in markdown files
- [ ] Next steps clear

### Fixes Complete When:
- [ ] player_daily_cache pipeline running reliably
- [ ] Confidence showing distribution (not stuck at 50%)
- [ ] Backfills successful for Jan 8 & 12
- [ ] All verification queries passing

### Monitoring Complete When:
- [ ] 4 critical alerts configured
- [ ] Alerts tested with sample data
- [ ] Alert delivery confirmed (Slack/email)
- [ ] Documentation updated with runbooks

### Incident Resolved When:
- [ ] All fixes deployed and verified
- [ ] 3+ consecutive days of healthy metrics
- [ ] Monitoring active and tested
- [ ] Documentation complete
- [ ] Post-mortem scheduled

---

**Last Updated**: 2026-01-16
**Next Review**: After investigation phase complete
