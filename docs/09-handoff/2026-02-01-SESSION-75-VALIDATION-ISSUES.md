# Session 75 - Daily Validation Issues - Feb 1, 2026

## Executive Summary

**Date**: 2026-02-01 21:00 PST
**Validation Target**: Friday, Jan 31, 2026 (yesterday's games)
**Validation Type**: Comprehensive (all priorities)
**Overall Status**: 🟡 **SIGNIFICANT ISSUES DETECTED**

This validation uncovered **3 P1 CRITICAL issues** and **3 P2 HIGH issues** requiring immediate attention:

1. 🔴 **BigQuery quota exceeded** - blocking writes
2. 🔴 **Phase 3 incomplete** - only 3/5 processors ran, missing `player_game_summary`
3. 🔴 **Feature store Vegas line coverage 40%** - expected ≥80%, directly impacts prediction quality
4. 🟡 Incomplete grading coverage for ensemble models
5. 🟡 catboost_v9 hit rate degradation (51.6% this week)
6. 🟡 Historical scraped data gaps (Jan 26-27)

**Good News**: Data quality itself is excellent (100% spot check accuracy), raw data is complete, and DNP handling is correct. Issues are primarily pipeline completeness and configuration, not data correctness.

---

## Validation Context

### Timeline
- **Game Date**: 2026-01-31 (Friday) - 6 NBA games played
- **Processing Date**: 2026-02-01 (Saturday) - overnight scrapers ran after midnight
- **Validation Run**: 2026-02-01 21:00 PST (Sunday night)

### Scope
- Phase 0: Proactive health checks (quota, heartbeat, grading, orchestrator)
- Phase 1: Critical checks (box scores, grading, scrapers)
- Phase 2: Pipeline completeness (analytics, cache, BDB, feature store, model drift)
- Phase 3: Quality verification (spot checks, accuracy)

---

## Critical Issues (P1)

### Issue 1: BigQuery Quota Exceeded (Rate Limits)

**Severity**: 🔴 P1 CRITICAL
**Discovered**: Phase 0 proactive quota check
**Impact**: Blocks BigQuery writes, can cause cascading processor failures

#### Evidence
```
Timestamp: 2026-02-01T16:47:22.291574Z
Error: Exceeded rate limits: too many table dml insert operations for this table
Frequency: 5 errors in 1 minute (16:46-16:47 UTC)
```

#### Root Cause
Too many single-row INSERT operations to a partitioned BigQuery table, most likely:
- `nba_orchestration.run_history` table
- `pipeline_logger` writing individual events instead of batching
- Known issue from Session 59 - fix committed (c07d5433) but may not be deployed

#### Analysis
This is a **deployment drift issue** (Session 58 pattern):
1. Fix was committed for batching writes
2. Fix may not have been deployed to all services
3. Services continue using old code with single-row inserts
4. Quota accumulates and hits limit

#### Recommended Actions

**Immediate (Next 15 Minutes)**:
```bash
# 1. Identify which table is hitting quota
gcloud logging read 'resource.type=bigquery_resource
  AND protoPayload.status.message:quota
  AND timestamp>="2026-02-01T16:00:00Z"' \
  --limit=20 \
  --format="table(timestamp,resource.labels.table_id,protoPayload.methodName)"

# 2. Check if batching fix is deployed
git log --oneline | grep -i "batch\|quota"
# Look for commit c07d5433 or similar batching fix

# 3. Check deployment dates vs commit dates
./bin/check-deployment-drift.sh --verbose
```

**If batching NOT deployed**:
```bash
# Deploy updated services with batching fix
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh nba-phase2-processors

# Verify deployment
gcloud run revisions list --service=nba-phase3-analytics-processors \
  --region=us-west2 --limit=1 \
  --format="table(metadata.name,metadata.creationTimestamp,metadata.labels.commit-sha)"
```

**If batching IS deployed but still hitting quota**:
- Issue may be volume-based, not implementation
- Consider further optimizations:
  - Increase batch size
  - Reduce logging frequency
  - Add write throttling

#### Prevention
1. **Always deploy after committing bug fixes** (Session 58 learning)
2. Run `./bin/check-deployment-drift.sh` before validation
3. Monitor BigQuery quota usage proactively in Phase 0

---

### Issue 2: Phase 3 Incomplete - Only 3/5 Processors Ran

**Severity**: 🔴 P1 CRITICAL
**Discovered**: Phase 2 pipeline completeness check
**Impact**: Phase 4 NOT triggered, downstream pipeline completely stalled

#### Current State
```
Phase 3 Completion Status (2026-02-01):
  Processors complete: 3/5
  Phase 4 triggered: FALSE

Completed:
  ✓ team_defense_game_summary
  ✓ team_offense_game_summary
  ✓ upcoming_player_game_context

MISSING:
  ✗ player_game_summary  <-- CRITICAL! Core analytics table
  ✗ upcoming_team_game_context
```

#### Impact Analysis

**Missing `player_game_summary`**:
- **Most critical Phase 3 processor**
- Produces core analytics table with rolling averages, usage rates, shot zones
- Used by Phase 4 feature store
- Used by Phase 5 predictions
- **Without this, entire prediction pipeline is blocked**

**Missing `upcoming_team_game_context`**:
- Less critical but still important
- Provides team-level context for upcoming games
- Used by feature engineering

**Phase 4 NOT triggered**:
- Orchestrator requires 5/5 Phase 3 processors complete
- ML feature store NOT generated
- Cache NOT updated
- Prediction generation blocked

#### Evidence

**Firestore Check**:
```python
# Checked phase3_completion/2026-02-01
{
  'team_defense_game_summary': {...},
  'team_offense_game_summary': {...},
  'upcoming_player_game_context': {...},
  '_triggered': False  # Phase 4 NOT triggered
}
```

**Raw Data Availability**:
- ✅ BDL boxscores: 212 records for Jan 31
- ✅ NBAC gamebook: Data present
- ✅ All 6 games have complete data
- **Data is NOT the problem - processor failed**

**Analytics Table Status**:
```sql
-- player_game_summary for 2026-01-31
Records: 212 (118 active players, 94 DNP)
Games: 6
Minutes coverage: 55.7% (all missing are DNP - CORRECT)

-- team_offense_game_summary for 2026-01-31
Records: 24 (expected 12 - possible duplicate processing?)
```

**Interesting Note**: `player_game_summary` table HAS 212 records for Jan 31, but processor didn't mark completion in Firestore. This suggests:
- Processor ran and wrote data
- Processor failed AFTER writes (during finalize/completion step)
- Known pattern: Session 60 `registry AttributeError`

#### Suspected Root Cause

**Session 60 Registry Bug**:
```python
# Known bug in player_game_summary_processor.py
# Lines 1066, 1067, 1667 (fixed in Session 60)
self.registry.upsert_player(...)  # AttributeError: 'PlayerGameSummaryProcessor' object has no attribute 'registry'

# Should be:
self.registry_handler.upsert_player(...)
```

**If this bug exists**:
- Processor writes BigQuery data successfully
- Processor fails during finalize() when updating registry
- Firestore completion NOT marked
- Orchestrator sees 3/5, doesn't trigger Phase 4

#### Recommended Actions

**Step 1: Check Processor Logs** (Next 10 Minutes):
```bash
# Look for AttributeError in logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=200 \
  --format="table(timestamp,textPayload)" \
  | grep -B 10 -A 10 "player_game_summary\|AttributeError\|registry\|ERROR"

# Check for specific registry error
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50 \
  | grep -i "has no attribute 'registry'"
```

**Step 2: Verify Fix Deployment**:
```bash
# Check if Session 60 fix is in deployed code
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Compare to repo
git log --oneline --grep="registry\|Session 60" | head -5

# Check specific fix in code
grep -n "registry_handler\|self.registry" \
  data_processors/analytics/player_game_summary/player_game_summary_processor.py \
  | grep -E "(1066|1067|1667)"
```

**Step 3: Manual Recovery** (If processor failed but data exists):
```bash
# Check if data actually exists in BigQuery
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records, COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-01-31')"

# If data exists (212 records, 6 games), manually mark Phase 3 complete:
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client()
doc_ref = db.collection('phase3_completion').document('2026-02-01')

# Update to mark player_game_summary complete
doc_ref.set({
    'player_game_summary': {
        'status': 'complete',
        'completed_at': firestore.SERVER_TIMESTAMP,
        'records_processed': 212,
        'manual_override': True,
        'reason': 'Data exists in BigQuery, processor failed at finalize step'
    }
}, merge=True)

print("Marked player_game_summary as complete")
EOF

# Then manually trigger Phase 4
gcloud scheduler jobs run same-day-phase4
```

**Step 4: If Fix NOT Deployed**:
```bash
# Redeploy with Session 60 fix
./bin/deploy-service.sh nba-phase3-analytics-processors

# Wait for deployment to complete
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 --format="value(status.url)"

# Verify fix is present
curl -s $(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 --format="value(status.url)")/health | jq '.'
```

**Step 5: Reprocess If Needed**:
```bash
# If data quality is questionable, reprocess Jan 31
curl -X POST https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process \
  -H "Content-Type: application/json" \
  -d '{
    "processor_name": "player_game_summary",
    "data_date": "2026-01-31",
    "mode": "backfill"
  }'

# Monitor logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50 --follow
```

#### Prevention

1. **Post-commit deployment checklist** (Session 58 learning):
   - Fix committed → Deploy immediately
   - Verify deployment with `check-deployment-drift.sh`
   - Check service logs for first run

2. **Processor completion validation**:
   - Add more robust error handling in finalize()
   - If data writes succeed but finalize fails, still mark completion with warning
   - Add retry logic for Firestore writes

3. **Monitoring improvements**:
   - Alert on Phase 3 completion <5/5 within 2 hours of expected time
   - Daily validation should check Phase 3 status first

---

### Issue 3: Feature Store Vegas Line Coverage 40.1%

**Severity**: 🔴 P1 CRITICAL
**Discovered**: Phase 2 feature store validation
**Impact**: Directly degrades prediction quality - Session 62 proved this causes hit rate drops

#### Current State
```sql
-- Feature Store Vegas Line Coverage (last 7 days)
Vegas line populated: 40.1%
Total records: 2141
Days: 8
Status: CRITICAL (expected ≥80%)
```

#### Expected Baseline
- **Last season (2025)**: 99%+ Vegas line coverage
- **Minimum acceptable**: 80% coverage
- **Current**: 40.1% (less than half expected)

#### Impact on Predictions

**Session 62 Discovery**:
- Vegas line is feature #26 in the 33-feature ML model
- Low coverage means model trains/predicts without critical betting context
- **Result**: Predictions less competitive vs sportsbooks
- Historical correlation: Low Vegas line coverage → lower hit rates

**Why Vegas Line Matters**:
1. Model uses it to understand betting market consensus
2. Helps calibrate confidence scores
3. Identifies value bets (model significantly disagrees with Vegas)
4. Feature importance: Medium-high in CatBoost models

#### Root Cause Analysis

**Session 62 Backfill Mode Bug** (likely cause):
```python
# Pre-Session 62: Backfill mode didn't join betting tables
# Result: All players in roster (300-500/day) but no Vegas lines

# Post-Session 62: Backfill mode should join betting tables
# But fix may not be deployed or backfill ran with old code
```

**Two scenarios**:
1. **Session 62 fix NOT deployed** → Feature store processor still using old code
2. **Backfill ran before fix deployed** → Data generated with old code, needs regeneration

#### Evidence Supporting Root Cause

**Phase 3 Coverage**:
```sql
-- Check if betting data exists upstream
SELECT
  ROUND(100.0 * COUNTIF(current_points_line > 0) / COUNT(*), 1) as line_coverage
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

-- If this is >80%, problem is in Phase 4 join
-- If this is also ~40%, problem is in Phase 3 betting workflow
```

**Deployment Check Needed**:
```bash
# Verify Session 62 fix is in deployed code
git log --oneline --grep="Session 62\|betting.*backfill\|feature.*vegas" | head -5

# Check deployment timestamp
gcloud run revisions list --service=nba-phase4-precompute-processors \
  --region=us-west2 --limit=1 \
  --format="table(metadata.name,metadata.creationTimestamp)"

# Compare to Session 62 fix commit date
```

#### Recommended Actions

**Step 1: Verify Session 62 Fix Status** (Next 10 Minutes):
```bash
# 1. Check if fix exists in codebase
git log --oneline | grep -i "session 62\|betting.*feature"

# 2. Read the fix in code
cat data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  | grep -A 20 "backfill.*betting\|betting.*backfill"

# 3. Check if deployed
./bin/check-deployment-drift.sh nba-phase4-precompute-processors

# 4. Check deployment commit
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
```

**Step 2: Check Upstream Data** (Determine if Phase 3 or Phase 4 issue):
```bash
bq query --use_legacy_sql=false "
-- Check if betting lines exist in Phase 3 output
SELECT
  game_date,
  COUNT(*) as total_players,
  COUNTIF(current_points_line IS NOT NULL AND current_points_line > 0) as has_line,
  ROUND(100.0 * COUNTIF(current_points_line IS NOT NULL AND current_points_line > 0) / COUNT(*), 1) as pct
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC"

# If Phase 3 has >80% coverage → Issue is Phase 4 join
# If Phase 3 has ~40% coverage → Issue is Phase 3 betting workflow
```

**Step 3A: If Fix NOT Deployed**:
```bash
# Deploy Session 62 fix
./bin/deploy-service.sh nba-phase4-precompute-processors

# Regenerate feature store for last 7 days
for date in $(seq -7 0 | xargs -I {} date -d "{} days" +%Y-%m-%d); do
  echo "Regenerating feature store for $date"
  curl -X POST https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process \
    -H "Content-Type: application/json" \
    -d "{
      \"processor_name\": \"ml_feature_store\",
      \"data_date\": \"$date\",
      \"mode\": \"backfill\"
    }"
  sleep 30
done

# Verify coverage improved
bq query --use_legacy_sql=false "
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33"
```

**Step 3B: If Fix IS Deployed** (Data needs regeneration):
```bash
# Check when feature store was last generated
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas,
  MAX(created_at) as last_generated
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33
GROUP BY game_date
ORDER BY game_date DESC"

# If last_generated is before Session 62 fix deployment → Regenerate
# Use same regeneration loop from Step 3A
```

**Step 4: Validate Fix**:
```bash
# After regeneration, verify coverage
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as records,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as coverage_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33
GROUP BY game_date
ORDER BY game_date DESC"

# Expected: coverage_pct > 80% for all recent dates
```

**Step 5: Regenerate Predictions** (If needed):
```bash
# If predictions were generated with bad feature store → Regenerate
# Wait for corrected feature store, then:

for date in $(seq -7 0 | xargs -I {} date -d "{} days" +%Y-%m-%d); do
  echo "Regenerating predictions for $date"
  gcloud scheduler jobs run prediction-coordinator-trigger
  # Or use prediction backfill job
  sleep 60
done
```

#### Prevention

1. **Feature store validation** in daily checks:
   - Add Vegas line coverage check to validation script
   - Alert if <80% for any date
   - Block prediction generation if feature store incomplete

2. **Deployment verification** before backfills:
   - Run `./bin/verify-deployment-before-backfill.sh` (Session 64 script)
   - Verify latest commit includes all relevant fixes
   - Check deployment timestamp vs fix commit timestamp

3. **Post-backfill validation**:
   - Always run `/validate-feature-drift` after feature store backfills
   - Compare feature distributions to baseline
   - Verify coverage metrics before proceeding to predictions

---

## High Priority Issues (P2)

### Issue 4: Incomplete Grading Coverage for Ensemble Models

**Severity**: 🟡 P2 HIGH
**Impact**: Can't accurately assess ensemble model performance
**Discovered**: Phase 0 grading completeness check

#### Current State
```
Model Grading Coverage (last 7 days):

catboost_v9:     902 predictions, 687 graded (76.2%) ✅ Acceptable
catboost_v8:    1691 predictions, 362 graded (21.4%) ⚠️ Poor
ensemble_v1_1:  1238 predictions, 237 graded (19.1%) 🔴 Critical
ensemble_v1:    1238 predictions,  35 graded  (2.8%) 🔴 Critical

Thresholds:
  ≥80%: OK
  50-79%: WARNING
  <50%: CRITICAL
```

#### Root Cause

**Session 68 Pattern**:
- Predictions exist in `player_prop_predictions` table
- Grading pipeline (`prediction_accuracy` table) hasn't processed them
- Likely causes:
  1. Grading backfill not run for these models
  2. Grading coordinator not configured for ensemble models
  3. Predictions generated but grading job failed

#### Impact

**For catboost_v9** (76.2%):
- Acceptable but could be better
- 226 predictions ungraded (15 predictions × 15 days ≈ missing ~1-2 days)
- Minor impact on analysis

**For ensemble models** (<20%):
- **Cannot validate if ensemble is working correctly**
- Missing 80%+ of grading data
- Can't compare ensemble vs base models
- Blocks decision on whether to promote ensemble to production

#### Recommended Actions

**Immediate**:
```bash
# Run grading backfill for all models, last 7 days
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-25 \
  --end-date 2026-02-01 \
  --systems catboost_v8,catboost_v9,ensemble_v1,ensemble_v1_1

# Monitor progress
watch -n 10 'bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE(\"2026-01-25\")
GROUP BY system_id"'
```

**Verify Grading Pipeline Configuration**:
```bash
# Check if ensemble models are in grading coordinator config
grep -r "ensemble" orchestration/grading_coordinator/

# Check prediction_accuracy table schema includes all model system_ids
bq query --use_legacy_sql=false "
SELECT DISTINCT system_id, COUNT(*) as records
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE('2026-01-01')
GROUP BY system_id
ORDER BY system_id"
```

**If grading pipeline missing ensemble models**:
```python
# Update grading coordinator config to include ensemble models
# File: orchestration/grading_coordinator/config.py
ACTIVE_MODELS = [
    'catboost_v8',
    'catboost_v9',
    'ensemble_v1',      # Add if missing
    'ensemble_v1_1',    # Add if missing
]
```

#### Prevention

1. **Add grading check to daily validation**:
   - Verify all active models have ≥80% grading coverage
   - Alert if coverage drops below 80%

2. **Automated grading backfill**:
   - Run nightly grading backfill for T-1 (yesterday)
   - Ensures grading stays current

3. **Model registration process**:
   - When deploying new model, add to grading coordinator
   - Add to daily validation checks
   - Document in model deployment runbook

---

### Issue 5: catboost_v9 Hit Rate Degradation

**Severity**: 🟡 P2 HIGH
**Impact**: Model performance declining, approaching breakeven threshold
**Discovered**: Phase 2 model drift monitoring

#### Performance Trend (Last 4 Weeks)

```
catboost_v9 Weekly Performance:

Week of Jan 25: 51.6% hit rate (450 predictions) ⚠️ WARNING
Week of Jan 18: 56.4% hit rate (392 predictions) ✅ OK
Week of Jan 11: 55.6% hit rate (453 predictions) ✅ OK
Week of Jan 04: 54.2% hit rate (144 predictions) ✅ OK

Bias: -0.12 pts (slight under-prediction)
```

**Alert Thresholds**:
- ≥60%: OK
- 55-59%: WARNING
- **<55%: CRITICAL** ← Current: 51.6%

#### Context

**Model Version**: catboost_v9
- **Training**: Current season only (Nov 2025+)
- **Deployed**: Jan 31, 2026
- **Features**: 33 features (same as V8)
- **Design**: Monthly retraining expected

**Comparison to V8**:
- V8 week of Jan 25: 56.5% hit rate (better than V9)
- V8 week of Jan 18: 48.7% hit rate (worse than V9)
- V8 has more variance, longer history

#### Analysis Needed

**Hypothesis 1: Sample Size**
- Week of Jan 25: Only 450 predictions (lowest volume)
- Could be statistical noise
- Need to check if this continues into Feb

**Hypothesis 2: Feature Drift**
- Vegas line coverage is 40.1% (Issue #3)
- **If V9's 450 predictions lack Vegas lines → Model blind to betting context**
- This would directly explain performance drop

**Hypothesis 3: Tier-Specific Degradation**
- Model may be failing on specific player tiers (stars vs bench)
- Session 28 analysis pattern: Check tier breakdown

**Hypothesis 4: Need for Retraining**
- V9 designed for monthly retraining
- Last training: End of January
- Player form changes, team dynamics shift → model drift

#### Recommended Actions

**Step 1: Check Vegas Line Coverage for V9 Predictions** (PRIORITY):
```bash
# Are V9's predictions from week of Jan 25 missing Vegas lines?
bq query --use_legacy_sql=false "
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  COUNTIF(line_value IS NOT NULL AND line_value > 0) as has_line,
  ROUND(100.0 * COUNTIF(line_value IS NOT NULL AND line_value > 0) / COUNT(*), 1) as line_pct
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE('2026-01-25')
GROUP BY week
ORDER BY week DESC"

# If week of Jan 25 has low line_pct → Issue #3 is causing Issue #5!
```

**Step 2: Tier-Specific Analysis**:
```bash
# Run hit rate analysis by player tier
/hit-rate-analysis

# Or manual query:
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN actual_points >= 25 THEN '1_Stars_25+'
    WHEN actual_points >= 15 THEN '2_Starters_15-25'
    WHEN actual_points >= 5 THEN '3_Rotation_5-15'
    ELSE '4_Bench_<5'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE('2026-01-25')
  AND prediction_correct IS NOT NULL
GROUP BY tier
ORDER BY tier"
```

**Step 3: Weekly Breakdown (Next Week's Data)**:
```bash
# Check if degradation continues into Feb
# Run this query on Feb 7 to check week of Feb 1

bq query --use_legacy_sql=false "
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE('2026-02-01')
  AND prediction_correct IS NOT NULL
GROUP BY week"

# If Feb week also <55% → Time to retrain
```

**Step 4: Consider Monthly Retraining** (If pattern persists):
```bash
# V9 is designed for monthly retraining
# If degradation continues through Feb 7:

PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V9_FEB_RETRAIN" \
  --train-start 2025-11-02 \
  --train-end 2026-01-31 \
  --model catboost_v9

# This will:
# 1. Retrain on current season data (Nov 2025 - Jan 2026)
# 2. Evaluate on holdout set
# 3. Generate performance report
# 4. Create new model artifact for deployment
```

#### Prevention

1. **Weekly model drift monitoring** (already in place):
   - Track hit rate by week
   - Alert if <55% for 2 consecutive weeks
   - Tier breakdown for root cause analysis

2. **Feature quality monitoring** (MISSING - ADD):
   - Track Vegas line coverage for predictions
   - Alert if <80%
   - Link feature quality to model performance

3. **Monthly retraining schedule** (V9 design):
   - Schedule retraining for first week of each month
   - Compare new model to production before deployment
   - Document performance improvements

---

### Issue 6: Historical Scraped Data Coverage Gaps

**Severity**: 🟡 P2 HIGH
**Impact**: Missing game lines for historical dates, affects backfills and analysis
**Discovered**: Phase 2 scraped data coverage check

#### Coverage Status (Last 7 Days)

```
Date       | Scheduled | Game Lines | Player Props | Status
-----------|-----------|------------|--------------|--------
2026-02-01 |    10     |     10     |     136      | ✅ OK
2026-01-31 |     6     |      6     |      97      | ✅ OK
2026-01-30 |     9     |      9     |     100      | ✅ OK
2026-01-29 |     8     |      8     |      38      | 🟡 Low props
2026-01-28 |     9     |      9     |     121      | ✅ OK
2026-01-27 |     7     |      3     |      40      | 🔴 43% lines
2026-01-26 |     7     |      1     |      88      | 🔴 14% lines
```

**Issues**:
- Jan 27: Only 3/7 games have spreads (43% coverage)
- Jan 26: Only 1/7 games have spreads (14% coverage)
- Recent days (Jan 28+): 100% coverage ✅

#### Analysis

**Good News**:
- Current scraping is working (Feb 1, Jan 31, Jan 30 all 100%)
- Issue is isolated to Jan 26-27

**Possible Causes**:
1. **Scraper was down Jan 26-27**: Service outage, quota issue, or deployment
2. **API rate limiting**: Odds API throttled requests
3. **Data not available**: Some games weren't covered by odds providers
4. **Processing failure**: Data exists in GCS but didn't load to BigQuery

**Player Props Volume**:
- Jan 29: Only 38 players with props (low, but could be early lines)
- Jan 27: 40 players (low)
- Other days: 88-136 players (normal)

#### Recommended Actions

**Step 1: Determine If Data Exists in GCS**:
```bash
# Check GCS for odds data from Jan 26-27
gsutil ls gs://nba-scraped-data/odds-api/game-lines/2026/01/26/ | wc -l
gsutil ls gs://nba-scraped-data/odds-api/game-lines/2026/01/27/ | wc -l

# If files exist → Processing issue
# If files missing → Scraping issue
```

**Step 2A: If Data Exists in GCS** (Processing Issue):
```bash
# Reprocess odds data for Jan 26-27
PYTHONPATH=. python backfill_jobs/raw/odds_processor/odds_processor_backfill.py \
  --start-date 2026-01-26 \
  --end-date 2026-01-27 \
  --data-types game_lines,player_props

# Verify data loaded
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_raw.odds_api_game_lines
WHERE game_date IN ('2026-01-26', '2026-01-27')
  AND market_key = 'spreads'
GROUP BY game_date"
```

**Step 2B: If Data Missing from GCS** (Scraping Issue):
```bash
# Check if historical scraping is possible
# Odds API may have historical data available

# Run historical scraper for Jan 26-27
gcloud run jobs execute odds-historical-backfill --region=us-west2 \
  --args="--start-date=2026-01-26,--end-date=2026-01-27"

# Or use manual scraper trigger
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "odds_api_game_lines",
    "start_date": "2026-01-26",
    "end_date": "2026-01-27",
    "mode": "backfill"
  }'
```

**Step 3: Investigate Root Cause** (Why Jan 26-27?):
```bash
# Check scraper logs for Jan 26-27
gcloud logging read 'resource.labels.service_name="nba-scrapers"
  AND jsonPayload.scraper_name="odds_api_game_lines"
  AND timestamp>="2026-01-26T00:00:00Z"
  AND timestamp<="2026-01-28T00:00:00Z"' \
  --limit=50 \
  --format="table(timestamp,jsonPayload.message,jsonPayload.status)"

# Look for:
# - "Rate limit exceeded"
# - "API quota exceeded"
# - "Service unavailable"
# - No logs at all (scraper didn't run)
```

**Step 4: Validate Fix**:
```bash
# After backfill, verify coverage
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNT(DISTINCT game_id) as games_with_lines,
  (SELECT COUNT(*) FROM nba_reference.nba_schedule s
   WHERE s.game_date = ogl.game_date AND s.game_status = 3) as scheduled_games
FROM nba_raw.odds_api_game_lines ogl
WHERE game_date IN ('2026-01-26', '2026-01-27')
  AND market_key = 'spreads'
GROUP BY game_date"
```

#### Impact Assessment

**Low Impact** because:
- Only affects 2 days (Jan 26-27)
- Current scraping is working (Jan 28+)
- Not blocking production predictions

**But important for**:
- Historical model training (missing training data)
- Backfill accuracy validation (can't compare predictions to lines)
- Analysis and reporting (incomplete historical data)

#### Prevention

1. **Scraper monitoring**:
   - Daily check: "Did all scrapers run in last 24 hours?"
   - Alert on 0 files written to GCS
   - Alert on BigQuery table row count = 0 for previous day

2. **Automated gap detection**:
   - Weekly job: Scan for dates with <90% game line coverage
   - Auto-trigger historical backfill for gaps >7 days old
   - Report gaps to monitoring channel

3. **GCS vs BigQuery reconciliation**:
   - Check that files in GCS match rows in BigQuery
   - If mismatch → Auto-trigger processor
   - Add to weekly `/validate-scraped-data` skill

---

## Additional Observations

### Positive Findings

1. **Data Quality Excellent**:
   - 100% spot check accuracy (5/5 samples)
   - Rolling averages calculating correctly
   - Usage rates valid (no anomalies >50%)

2. **DNP Handling Correct**:
   - 94 players marked as DNP (is_dnp=TRUE)
   - All have valid dnp_reason text
   - Minutes correctly NULL for DNP players
   - 55.7% "minutes coverage" is actually **100% coverage of active players**

3. **Raw Data Complete**:
   - All 6 games have BDL boxscore data (212 records)
   - NBAC gamebook data present
   - Both data sources healthy

4. **Scraper Health Good**:
   - nbac_player_movement: 1 day fresh ✅
   - nbac_injury_report: 1 day fresh ✅
   - Recent scraping working (Jan 28+)

5. **Team Summary Tables Working**:
   - team_offense_game_summary: 24 records
   - team_defense_game_summary: Completed
   - Only player-level processor failed

### Unusual Observations

1. **Team Offense Has 24 Records for 6 Games**:
   - Expected: 12 records (2 teams × 6 games)
   - Actual: 24 records
   - **Possible duplicate processing?**
   - Need to investigate if this is correct (e.g., pre-game + post-game context)

2. **Phase Execution Log Completely Empty**:
   - New logging system (`phase_execution_log`) has no data
   - Processor_run_history also doesn't exist
   - Suggests logging infrastructure not fully deployed
   - Not blocking, but limits observability

3. **Ensemble Models Low Usage**:
   - ensemble_v1: Only 21 predictions week of Jan 25
   - ensemble_v1_1: 144 predictions week of Jan 25
   - catboost_v9: 450 predictions (primary)
   - Are ensemble models being generated for all games?

---

## System Context

### Orchestration Status

**Phase 2 → Phase 3**:
- ✅ Scrapers ran overnight (BDL, NBAC both have data)
- ❌ Phase 3 only 3/5 complete
- ❌ Phase 4 NOT triggered

**Phase 3 → Phase 4**:
- ⏸️ **BLOCKED** waiting for Phase 3 completion (5/5 required)

**Phase 4 → Phase 5**:
- ⏸️ **BLOCKED** waiting for Phase 4 (feature store)

**Current Pipeline State**: **STALLED at Phase 3**

### Table Status for Jan 31

| Table | Records | Status |
|-------|---------|--------|
| `bdl_player_boxscores` (raw) | 212 | ✅ Complete |
| `nbac_gamebook_player_boxscores` (raw) | Present | ✅ Complete |
| `player_game_summary` (analytics) | 212 | ⚠️ Data exists but processor didn't mark complete |
| `team_offense_game_summary` | 24 | ✅ Complete |
| `team_defense_game_summary` | ? | ✅ Complete |
| `upcoming_player_game_context` | ? | ✅ Complete |
| `player_daily_cache` | ? | ⏭️ Skipped verification |
| `ml_feature_store_v2` | ? | ⏸️ Not generated (Phase 4 blocked) |
| `player_prop_predictions` | 94 (V9) | ⚠️ Generated but Vegas line coverage low |
| `prediction_accuracy` | 50 graded | 🟡 Partial grading |

---

## Next Session Priorities

### Immediate Actions (Next Session Start)

1. **Fix Phase 3 Completion** (15 minutes):
   - Check logs for `player_game_summary` error
   - Verify Session 60 registry fix deployed
   - Manually mark complete if data exists
   - Trigger Phase 4

2. **Deploy Quota Batching Fix** (10 minutes):
   - Verify fix deployed to all services
   - Check quota usage decreased

3. **Investigate Feature Store Vegas Line Coverage** (20 minutes):
   - Check if Session 62 fix deployed
   - Determine if regeneration needed
   - Run feature store backfill if required

### Follow-Up Actions (Within 24 Hours)

4. **Run Grading Backfill** (30 minutes):
   - Backfill grading for all models, last 7 days
   - Verify ensemble model coverage reaches 80%+

5. **Analyze Model Degradation** (30 minutes):
   - Check if V9's low hit rate correlates with low Vegas line coverage
   - Run tier-specific analysis
   - Determine if retraining needed

6. **Historical Odds Backfill** (20 minutes):
   - Backfill Jan 26-27 game lines
   - Investigate root cause (scraper down? API issue?)

### Monitoring Improvements (Next Week)

7. **Add Feature Quality Monitoring**:
   - Vegas line coverage check in daily validation
   - Alert if <80%
   - Block predictions if feature store incomplete

8. **Improve Orchestrator Observability**:
   - Deploy phase_execution_log if not present
   - Add Firestore completion checks to validation
   - Alert on <5/5 Phase 3 processors

9. **Automate Grading**:
   - Add daily grading backfill for T-1
   - Ensure all active models included
   - Monitor coverage in daily validation

---

## Reference Documentation

### Related Sessions
- **Session 58**: Deployment drift issues (fix committed but not deployed)
- **Session 59**: Silent BigQuery write failures, quota issues
- **Session 60**: Registry AttributeError in player_game_summary_processor
- **Session 62**: Feature store Vegas line coverage bug in backfill mode
- **Session 64**: Backfill with stale code (verify deployment before backfill)
- **Session 68**: Incomplete grading coverage analysis

### Key Documents
- `docs/02-operations/daily-operations-runbook.md` - Daily procedures
- `docs/02-operations/troubleshooting-matrix.md` - Issue decision trees
- `docs/08-projects/current/feature-quality-monitoring/` - Feature drift monitoring
- `docs/08-projects/current/catboost-v8-performance-analysis/` - Model degradation analysis
- `CLAUDE.md` - Project instructions and common issues

### Useful Commands

```bash
# Check deployment drift
./bin/check-deployment-drift.sh --verbose

# Verify Phase 3 completion
python3 -c "from google.cloud import firestore; db = firestore.Client(); \
  doc = db.collection('phase3_completion').document('2026-02-01').get(); \
  print(doc.to_dict() if doc.exists else 'No record')"

# Check feature store Vegas line coverage
bq query --use_legacy_sql=false "
SELECT ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33"

# Run grading backfill
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-25 --end-date 2026-02-01

# Manual Phase 3 completion (if data exists)
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client()
doc_ref = db.collection('phase3_completion').document('2026-02-01')
doc_ref.set({'player_game_summary': {'status': 'complete', 'manual_override': True}}, merge=True)
EOF

# Trigger Phase 4 manually
gcloud scheduler jobs run same-day-phase4
```

---

## Conclusion

This validation uncovered significant pipeline issues:

**Critical (P1)**:
- BigQuery quota exceeded
- Phase 3 incomplete (missing player_game_summary)
- Feature store Vegas line coverage 40% (expected 80%+)

**High Priority (P2)**:
- Ensemble model grading incomplete
- catboost_v9 hit rate degrading
- Historical odds data gaps

**Root Cause Patterns**:
1. **Deployment drift** (Session 58 pattern) - Fixes committed but not deployed
2. **Pipeline stalling** - One processor failure blocks entire downstream pipeline
3. **Data quality degradation** - Feature store issue directly impacts model performance

**Positive Notes**:
- Data quality excellent (100% spot check accuracy)
- Raw data complete and correct
- DNP handling working perfectly
- Current scraping operational

**Immediate Next Steps**:
1. Fix Phase 3 completion (check logs, verify deployment, manual override if needed)
2. Investigate and fix feature store Vegas line coverage
3. Deploy quota batching fix

This document should serve as a complete handoff for the next session to address these issues systematically.
