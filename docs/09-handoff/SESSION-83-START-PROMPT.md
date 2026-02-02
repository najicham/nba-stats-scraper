# Session 83 Start Prompt - Post-Game Validation

**Current Time Check**: What time is it now? Games were at 7-10 PM ET on Feb 2!

---

## URGENT: Validate NEW V9 Model Performance

Session 82 restored Feb 2 predictions but **we need to verify** if they're from the NEW V9 model (MAE 4.12, 74.6% hit rate) or OLD models.

**Key Question**: Did the NEW model deployment actually work, or did we just restore old predictions?

---

## Your Mission

### Part 1: Model Performance Validation (CRITICAL)

**Check if games have finished:**
```bash
bq query --use_legacy_sql=false "
SELECT game_id, away_team_tricode, home_team_tricode, game_status,
  CASE game_status WHEN 1 THEN 'Scheduled' WHEN 2 THEN 'In Progress' WHEN 3 THEN 'Final' END as status
FROM nba_reference.nba_schedule WHERE game_date = DATE('2026-02-02')"
```

**If games are FINAL, run this validation:**

```bash
# 1. Trigger grading for Feb 2
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --dates 2026-02-02

# 2. Check catboost_v9 performance
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-02'
  AND system_id = 'catboost_v9'
  AND prediction_correct IS NOT NULL
GROUP BY system_id"

# Expected if NEW model (Session 76 retrain):
# - Hit Rate: ~74.6%
# - MAE: ~4.12
# - Should be reasonable across all confidence levels

# If OLD model (pre-fix):
# - Hit Rate: ~50-55%
# - MAE: ~5.0+
# - May have issues
```

**3. Compare with other models:**
```bash
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-02'
  AND prediction_correct IS NOT NULL
GROUP BY system_id
ORDER BY hit_rate DESC"
```

**4. RED Signal Day Validation:**

Today (Feb 2) is a **RED signal day** (70.3% UNDER bias). Historical performance:
- RED signal days: 54% hit rate
- Balanced days: 82% hit rate

Check if tonight matched the pattern:
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(recommendation = 'UNDER') as under_recs,
  COUNTIF(recommendation = 'OVER') as over_recs,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as under_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-02'
  AND system_id = 'catboost_v9'
  AND is_active = TRUE"
```

Expected: 65-75% UNDER recommendations on RED signal day.

---

### Part 2: Fix Worker Issues (If Time Permits)

Session 82 discovered **3 non-blocking issues** that make logs noisy:

#### Issue 1: Pub/Sub Authentication
**Symptom**: "The request was not authenticated"
**Impact**: Worker receives requests but they're rejected
**Check**:
```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND timestamp>="2026-02-02T21:00:00Z"
  AND textPayload=~"not authenticated"' --limit=10
```

**Fix**: Update Pub/Sub push subscription to use authentication
```bash
# Check current subscription config
gcloud pubsub subscriptions describe prediction-request-prod

# If oidc_token is missing, update it
gcloud pubsub subscriptions update prediction-request-prod \
  --push-endpoint=https://prediction-worker-f7p3g7f6ya-wl.a.run.app/predict \
  --push-auth-service-account=prediction-worker@nba-props-platform.iam.gserviceaccount.com
```

#### Issue 2: Execution Log Schema
**Symptom**: "Only optional fields can be set to NULL. Field: line_values_requested"
**Impact**: Execution logs fail to write
**Check**:
```bash
bq show --schema nba_predictions.prediction_execution_log | grep -A1 line_values_requested
```

**Fix**: Make field NULLABLE or provide default value in worker code

#### Issue 3: Pub/Sub Topic 404
**Symptom**: "404 Resource not found (resource=prediction-ready)"
**Impact**: Completion notifications fail, coordinator doesn't know batch finished
**Check**:
```bash
gcloud pubsub topics list | grep prediction
```

**Fix**: Create missing topic or update worker to use correct topic name

---

### Part 3: Deployment Process Improvements

**Document the fixes from Session 82:**

1. **Update deployment guide** with BOTH V8 and V9 model requirement
2. **Create pre-deployment checklist**
3. **Add model version tracking** to predictions table
4. **Test consolidation flow** end-to-end

---

## Context from Session 82

### What Happened

**Problem**: Session 81 deployed NEW V9 model but Feb 2 predictions were missing
**Root Cause**: Worker needed BOTH V8 and V9 models configured, Session 81 only set V9
**Fix**: Added V8 model path, manually merged predictions from staging tables

**Timeline** (Feb 2, 1:15-1:50 PM PST):
1. Found worker crashing - missing V8 model
2. Fixed deployment - added both V8 and V9 paths
3. Predictions generated but stuck in staging
4. Manual SQL MERGE restored 536 predictions
5. Completed grading backfill (Jan 27-31)

**Result**: 68 players × 8 systems ready for tonight's games

### Key Uncertainty

**We don't know for certain if predictions are from NEW or OLD model.**

Predictions created at 21:38 UTC (1:38 PM PST), which was 7 minutes AFTER deployment fix at 21:31 UTC. This suggests NEW model, but need validation.

**Three V9 variants exist** (confusing!):
1. `catboost_v9` - Should be NEW model (catboost_v9_feb_02_retrain.cbm)
2. `catboost_v9_2026_02` - OLD inferior model (MAE 5.08)
3. `catboost_v8` - V8 baseline

### Model Files

**V8**: `gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm`
**V9 (NEW)**: `gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm`
- Training: Nov 2, 2025 → Jan 31, 2026 (90 days)
- MAE: 4.12
- Hit Rate: 74.6%
- Session: 76

### Current Deployment

**Worker**: `prediction-worker-00074-vf6` (or later)
**Env vars set**:
```
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm
```

---

## Decision Tree

```
Are Feb 2 games finished?
├─ NO (still in progress or scheduled)
│  └─ Wait until after 11 PM ET, then run validation
│
└─ YES (game_status = 3)
   ├─ Run grading backfill for Feb 2
   ├─ Check catboost_v9 hit rate and MAE
   │
   ├─ Hit rate ~74.6% and MAE ~4.12?
   │  ├─ YES → ✅ NEW model working! Document success
   │  └─ NO → ❌ OLD model or issue, investigate:
   │     ├─ Check worker logs for model file loaded
   │     ├─ Compare all 3 V9 variants' performance
   │     └─ May need to regenerate with verified model
   │
   ├─ Fix worker issues (auth, schema, pub/sub)
   └─ Document deployment improvements
```

---

## Success Criteria

- [ ] Verified which model version generated Feb 2 predictions
- [ ] catboost_v9 performance matches expectations (or explained why not)
- [ ] RED signal day hypothesis validated/invalidated
- [ ] Worker issues documented and prioritized
- [ ] Deployment checklist created for future sessions

---

## Reference Documents

- **Session 82 Handoff**: `docs/09-handoff/2026-02-02-SESSION-82-HANDOFF.md`
- **Session 81 Handoff**: `docs/09-handoff/2026-02-02-SESSION-81-V9-DEPLOYMENT-HANDOFF.md`
- **Session 76 (NEW V9 model)**: Training details and performance benchmarks

---

## Quick Commands

```bash
# Check game status
bq query --use_legacy_sql=false "SELECT game_status, COUNT(*) FROM nba_reference.nba_schedule WHERE game_date = DATE('2026-02-02') GROUP BY 1"

# Grade Feb 2
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --dates 2026-02-02

# Check performance
bq query --use_legacy_sql=false "SELECT system_id, COUNT(*) as preds, ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-02' GROUP BY 1 ORDER BY 2 DESC"

# Check worker logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker"' --limit=20

# Check current deployment
gcloud run services describe prediction-worker --region=us-west2 --format="value(status.latestReadyRevisionName,metadata.labels.commit-sha)"
```

---

## TL;DR

Session 82 got predictions ready for Feb 2 games (✅ done), but we need to verify the NEW V9 model actually worked. Check tonight's results, grade them, and validate hit rate matches expectations (~74.6%). Also fix worker issues if time permits.

**Start by checking if games are finished, then run validation queries above!**
