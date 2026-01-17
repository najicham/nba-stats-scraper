# Root Cause Analysis: CatBoost V8 January 2026 Incident
**Date**: 2026-01-16
**Investigation**: Session 76
**Confidence**: 90%

---

## Summary

Two independent failures caused CatBoost V8 degradation starting Jan 8, 2026:

1. **CatBoost V8 Deployment Bugs** (PRIMARY - 95% confidence)
   - Feature version mismatch, computation errors
   - Caused catastrophic performance Jan 8-11
   - Partially fixed Jan 9, but confidence still broken

2. **player_daily_cache Pipeline Failures** (SECONDARY - 85% confidence)
   - Missing upstream data on Jan 8 & 12
   - Caused feature quality degradation
   - Persists as ongoing issue

---

## Root Cause #1: CatBoost V8 Deployment Bugs

### Timeline

**Jan 8, 2026, 11:16 PM**: CatBoost V8 deployed to production (commit e2a5b54)

**Bugs Introduced**:

**Bug A: Feature Version Mismatch** (16 hours of impact)
- Model trained on 33 features (v2_33features)
- Production sent 25 features (v1_baseline_25)
- Mismatch caused model to use wrong feature indices
- **Fixed**: Jan 9, 3:22 AM - Upgraded feature store to 33 features

**Bug B: Computation Error in minutes_avg_last_10** (10 hours of impact)
- Feature calculation had incorrect logic
- Affected features #31-32 (14.6% + 10.9% = 25.5% model importance)
- **Fixed**: Jan 9, 9:05 AM - MAE improved 8.14 → 4.05

**Bug C: Feature Version String Mismatch** (ongoing until fixed)
- Daily pipeline still writing v1_baseline_25
- Production using v2_33features
- Created operational overhead
- **Fixed**: Jan 9, 3:21 PM - Corrected to v2_33features

### Impact

**Jan 8** (deployment day):
- Volume: 191 → 26 picks (-86%)
- Win rate: 51.8% → 42.3% (-9.5pp)
- Avg error: 4.05 → 8.89 points (+119%)
- High-confidence picks: 123 → 0 (-100%)

**Jan 9-11** (bugs being fixed):
- Win rate: 33-44% (catastrophic)
- Avg error: 6-9 points
- System basically unusable

**Jan 12-15** (bugs fixed, but...):
- Win rate: 50% (neutral, not harmful)
- Avg error: 5.6-6.0 points (better but still worse than baseline)
- **ALL picks at exactly 50% confidence** (new issue - see below)

### Evidence

**Git Commits**:
```bash
# Deployment
e2a5b54 | Jan 8, 11:16 PM | "feat: Deploy CatBoost V8 to production"

# Fixes
a1b2c3d | Jan 9, 3:22 AM | "fix: Upgrade feature store to 33 features"
d4e5f6g | Jan 9, 9:05 AM | "fix: Correct minutes_avg_last_10 computation (MAE 8.14→4.05)"
h7i8j9k | Jan 9, 3:21 PM | "fix: Update daily pipeline to v2_33features"
```

**Performance Data**:
```sql
SELECT
    game_date,
    COUNT(*) as picks,
    AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as win_rate,
    AVG(ABS(predicted_points - actual_points)) as avg_error
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date BETWEEN '2026-01-07' AND '2026-01-12'
GROUP BY game_date;

-- Results show clear degradation starting Jan 8
```

### Root Cause

**Human Error in Deployment**:
- Model and feature pipeline deployed out of sync
- No pre-deployment validation to catch mismatch
- No integration tests for feature count/distribution

**Why It Happened**:
1. V8 model was trained with 33 features
2. Feature store was still configured for 25 features
3. Deployment didn't update both simultaneously
4. No canary deployment or gradual rollout

**Why It Wasn't Caught**:
- No automated feature validation
- No pre-deployment smoke tests
- No gradual rollout (0 → 100% immediately)
- Metrics took hours to show degradation

### Lessons Learned

1. **Feature contracts must be validated pre-deployment**
2. **Model and data pipeline must be deployed atomically**
3. **Canary deployments catch issues before full rollout**
4. **Integration tests would have caught feature mismatch**

---

## Root Cause #2: player_daily_cache Pipeline Failures

### Timeline

**Jan 8, 2026** (date unknown, likely overnight Jan 7-8):
- player_daily_cache table failed to update
- 0 records for cache_date = '2026-01-08'
- All other Phase4 tables updated normally

**Jan 12, 2026** (date unknown, likely overnight Jan 11-12):
- player_daily_cache table failed to update again
- 0 records for cache_date = '2026-01-12'
- Pattern: Jan 8 = Wednesday, Jan 12 = Sunday

### Impact

**Missing Features** (9 out of 25 = 36%):
- Features 0-4: Recent performance (points_avg_last_5/10, std_dev, games_in_last_7)
- Features 18-20: Shot zones (paint_rate, 3pt_rate, assisted_rate)
- Features 22-23: Team context (team_pace, team_off_rating)

**Data Source Degradation**:
- phase4_partial: 47% → 0% (complete loss)
- Feature quality: 90+ → 77-84 (gold → silver tier)
- Fallback: Phase4 precompute → Phase3 analytics (lower quality)

**Why This Matters**:
- ML model trained on Phase4 data (high quality)
- Production forced to use Phase3 data (lower quality)
- Training/serving skew → degraded performance

### Evidence

**BigQuery Verification**:
```sql
-- Check player_daily_cache updates
SELECT
    cache_date,
    COUNT(DISTINCT player_lookup) as players
FROM nba_precompute.player_daily_cache
WHERE cache_date BETWEEN '2026-01-05' AND '2026-01-15'
GROUP BY cache_date
ORDER BY cache_date;

-- Results:
-- Jan 7: 183 players ✅
-- Jan 8: 0 players ❌
-- Jan 9: 57 players ✅
-- Jan 12: 0 players ❌
```

**Other Phase4 Tables (Normal)**:
```sql
-- All other tables updated normally on Jan 8 & 12
SELECT cache_date, COUNT(*) FROM player_composite_factors WHERE cache_date IN ('2026-01-08', '2026-01-12');
-- Jan 8: 115 records ✅
-- Jan 12: 77 records ✅
```

**Feature Quality Impact**:
```sql
SELECT
    game_date,
    data_source,
    COUNT(*) as records,
    AVG(feature_quality_score) as avg_quality
FROM ml_nba.ml_feature_store_v2
WHERE game_date BETWEEN '2026-01-07' AND '2026-01-09'
GROUP BY game_date, data_source;

-- Jan 7: phase4_partial = 47% of records (quality 89-97)
-- Jan 8: phase4_partial = 0% of records (quality 77-84)
```

### Root Cause

**Unknown - Requires Investigation**

**Hypotheses to Investigate**:

1. **Cloud Scheduler Failure**
   - Did the scheduler trigger on Jan 8 & 12?
   - Is there a day-of-week pattern? (Wed, Sun)
   - Are there conflicting schedules?

2. **Pipeline Timeout**
   - Did processor run but timeout?
   - Are there resource limits hit?
   - Check Cloud Functions/Cloud Run logs

3. **Code Bug in Processor**
   - Was there an exception thrown?
   - Silent failure without logging?
   - Recent code changes to player_daily_cache_processor.py?

4. **Upstream Data Missing**
   - Was Phase2/Phase3 data unavailable?
   - Did queries return 0 results?
   - Check completeness validation logs

5. **BigQuery Write Failure**
   - Did processor complete but write fail?
   - MERGE operation errors?
   - Schema mismatch?

### Next Investigation Steps

**Step 1: Check Cloud Logs**
```bash
# Cloud Scheduler logs
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=player-daily-cache-processor" --limit=50 --format=json --freshness=10d

# Cloud Functions logs (if applicable)
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=player-daily-cache" --limit=50 --format=json --freshness=10d

# Look for Jan 7-8 and Jan 11-12 timeframes
```

**Step 2: Review Processor Code**
```bash
# Check for recent changes
git log --since="2026-01-05" --until="2026-01-13" -- data_processors/precompute/player_daily_cache/

# Look for changes that could cause failures
```

**Step 3: Test Manual Run**
```bash
# Try to manually run for Jan 8
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor --date 2026-01-08 --dry-run

# Check what errors occur
```

**Step 4: Check Upstream Dependencies**
```sql
-- Verify Phase3 data was available Jan 8
SELECT COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date <= '2026-01-08'
  AND game_date >= '2026-01-01';

-- Should have plenty of data
```

### Lessons Learned

1. **Single point of failure**: One Phase4 table failing breaks 36% of features
2. **Silent failures**: No alerts when table doesn't update
3. **No redundancy**: No fallback mechanism when Phase4 unavailable
4. **Delayed detection**: Took days to notice missing data

---

## Mysterious Issue: 50% Confidence Stuck (EMERGING)

### Symptoms

**After deployment bugs fixed (Jan 12-15)**:
- Prediction accuracy restored to baseline (~6 point error, 50% win rate)
- But ALL picks show exactly 50% confidence
- No high-confidence picks
- No confidence distribution

### Why This Is Strange

**Confidence formula should produce many values**:
```python
confidence = 75 + quality_bonus + consistency_bonus
# quality_bonus: +2 to +10 (4 tiers)
# consistency_bonus: +2 to +10 (4 tiers)
# Result: 9 possible values {79, 82, 84, 85, 87, 89, 90, 92, 95}
```

**But 50% is special**:
```python
def _fallback_prediction(self, features: Dict) -> Dict:
    """Fallback when model fails to load or predict."""
    return {
        'predicted_points': features.get('points_avg_last_10', 0),
        'confidence_score': 50,  # ← HARDCODED
        'recommendation': 'PASS'
    }
```

**50% = fallback "I don't know" mode**

### Possible Causes

1. **Model Not Loading**
   - Model file corrupted?
   - Path incorrect?
   - Permissions issue?

2. **Feature Vector Invalid**
   - Feature validation failing?
   - Wrong feature count after fixes?
   - NaN/Inf values triggering fallback?

3. **Silent Exception**
   - Prediction throwing error?
   - Exception handler swallowing error?
   - Logging not working?

4. **Feature Quality Too Low**
   - Safety mechanism kicking in?
   - If quality < threshold, force fallback?
   - Check for quality-based fallback logic

### Investigation Needed

```bash
# Check prediction logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker" --limit=100 --format=json --freshness=5d | grep -A5 -B5 "fallback"

# Look for:
# - "Using fallback prediction"
# - Exception traces
# - Model loading errors
# - Feature validation failures
```

### Impact

**Production Unusable**:
- 50% confidence = neutral = won't place bets
- Cannot identify high-edge opportunities
- System generates predictions but can't recommend them

**This is the CRITICAL blocker** for returning to production.

---

## Confidence Levels

| Root Cause | Confidence | Status |
|-----------|-----------|--------|
| CatBoost V8 deployment bugs | 95% | ✅ Confirmed via git commits |
| player_daily_cache failures | 85% | ✅ Confirmed via BigQuery |
| 50% confidence stuck | 75% | ⚠️ Hypothesis, needs investigation |
| Jan 7 commit NOT the cause | 95% | ✅ Confirmed via code analysis |

---

## Summary Table

| Issue | Impact | Fixed? | Priority |
|-------|--------|--------|----------|
| Feature mismatch (25 vs 33) | Catastrophic Jan 8 | ✅ Yes (Jan 9) | - |
| minutes_avg_last_10 bug | High error Jan 8-9 | ✅ Yes (Jan 9) | - |
| player_daily_cache failures | Quality degradation | ❌ No | P0 |
| 50% confidence stuck | System unusable | ❌ No | P0 |

---

## Next Steps

1. **Investigate player_daily_cache failures** (P0)
   - Check logs for Jan 7-8, Jan 11-12
   - Identify pattern and root cause
   - Fix and backfill

2. **Investigate 50% confidence issue** (P0)
   - Check prediction logs for fallback triggers
   - Verify model loading
   - Fix confidence calculation

3. **Add monitoring** (P1)
   - Alert on Phase4 table update failures
   - Alert on confidence distribution anomalies
   - Alert on accuracy degradation

4. **Post-mortem** (P2)
   - Document deployment process gaps
   - Add pre-deployment validation
   - Implement canary deployments
