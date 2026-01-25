# Deployment Checklist - January 25, 2026

**Date:** 2026-01-25
**Status:** All code complete, ready for deployment
**Priority:** Deploy in order listed below

---

## ✅ Already Deployed

1. **Auto-Retry Processor** - Revision 00008-wic (Active)
2. **Sentry DSN** - In Secret Manager (Secure)
3. **BDL Backfill** - Completed (22 games backfilled)

---

## 🚀 Ready for Deployment

### Priority 1: Admin Dashboard (30 min)

**What:** Fix 3 stub operations that were returning false success

**Files Changed:**
- `services/admin_dashboard/blueprints/actions.py`

**Deploy:**
```bash
gcloud app deploy services/admin_dashboard/app.yaml --project=nba-props-platform
```

**Test:**
```bash
# Test force_predictions
curl -X POST https://admin-dashboard.nba-props-platform.appspot.com/actions/force-predictions \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-25"}'

# Test retry_phase
curl -X POST https://admin-dashboard.nba-props-platform.appspot.com/actions/retry-phase \
  -H "Content-Type: application/json" \
  -d '{"phase": "phase_3", "game_date": "2026-01-24"}'

# Test trigger_self_heal
curl -X POST https://admin-dashboard.nba-props-platform.appspot.com/actions/trigger-self-heal \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-24"}'
```

**Success Criteria:**
- ✅ Endpoints return actual message IDs (not fake success)
- ✅ Pub/Sub messages published
- ✅ Cloud Run endpoints called with authentication

---

### Priority 2: Prediction Coordinator (1 hour + 24h monitoring)

**What:** 4 major improvements

**Changes:**
1. Phase 6 stale prediction detection (was returning empty list)
2. Firestore dual-write atomicity (prevents data corruption)
3. LIMIT clauses on 3 queries (prevents OOM)
4. Error log elevation (4 DEBUG → WARNING)

**Files Changed:**
- `predictions/coordinator/player_loader.py`
- `predictions/coordinator/batch_state_manager.py`

**Deploy to Staging First:**
```bash
gcloud run deploy prediction-coordinator-staging \
  --source=predictions/coordinator \
  --region=us-west2 \
  --project=nba-props-platform
```

**Test:**
```bash
# Test Phase 6 detection
curl -X POST https://prediction-coordinator-staging-xxx.run.app/check-stale \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date": "2026-01-25"}'

# Check memory usage (should be lower)
gcloud logging read "resource.type=cloud_run_revision
  resource.labels.service_name=prediction-coordinator-staging
  textPayload=~'memory'" --limit=20
```

**Monitor for 24 Hours:**
- Firestore transaction conflicts (should be minimal)
- Memory usage (should be 50-70% lower)
- Phase 6 detection working (finds line changes)
- Error logs visible at WARNING level

**If Successful, Deploy to Production:**
```bash
gcloud run deploy prediction-coordinator \
  --source=predictions/coordinator \
  --region=us-west2 \
  --project=nba-props-platform
```

---

### Priority 3: Cloud Function Consolidation (2-3 hours)

**What:** Test symlink strategy (673 symlinks created, 12.4 MB saved)

**Strategy:** Deploy ONE function first, verify it works, then deploy remaining 6

**Test Function:**
```bash
./bin/orchestrators/deploy_phase2_to_phase3.sh
```

**Verify:**
```bash
# Check logs for import errors
gcloud functions logs read phase2-to-phase3 --region=us-west2 --limit=50 | grep -i error

# Trigger test execution
gcloud scheduler jobs run phase2-to-phase3-trigger --location=us-west2

# Verify execution
gcloud functions logs read phase2-to-phase3 --region=us-west2 --limit=100
```

**If Successful (No Import Errors), Deploy Remaining:**
```bash
./bin/orchestrators/deploy_phase3_to_phase4.sh
./bin/orchestrators/deploy_phase4_to_phase5.sh
./bin/orchestrators/deploy_phase5_to_phase6.sh
./bin/orchestrators/deploy_auto_backfill_orchestrator.sh
./bin/orchestrators/deploy_daily_health_summary.sh
./bin/orchestrators/deploy_self_heal.sh
```

**Rollback if Issues:**
```bash
# Restore from backup
cp -r .backups/cloud_function_shared_20260125_101734/phase2_to_phase3/* \
      orchestration/cloud_functions/phase2_to_phase3/shared/

# Redeploy
./bin/orchestrators/deploy_phase2_to_phase3.sh
```

---

### Priority 4: Data Processors (staged rollout)

**What:** Bug fixes for crashes and data issues

**Changes:**
1. 6 files with unsafe next() fixes (prevents StopIteration crashes)
2. Batch processor failure tracking (prevents silent data loss)
3. MLB pitcher features: SQL injection fix + race condition fix

**Files:**
- `data_processors/raw/balldontlie/bdl_player_box_scores_processor.py`
- `data_processors/raw/balldontlie/bdl_boxscores_processor.py`
- `data_processors/raw/mlb/mlb_pitcher_stats_processor.py`
- `data_processors/raw/mlb/mlb_batter_stats_processor.py`
- `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
- `data_processors/raw/oddsapi/oddsapi_batch_processor.py`
- `data_processors/precompute/mlb/pitcher_features_processor.py`

**Deploy Method:** (Depends on your deployment strategy - Cloud Run, Docker, etc.)

**Monitor:**
- No StopIteration exceptions
- Batch processing aborts when >20% files fail
- SQL queries use @game_date parameter
- MERGE operations work atomically

---

## 📊 Verification Queries

### Check Firestore Consistency
```python
from google.cloud import firestore
db = firestore.Client()
batch_ref = db.collection('prediction_batches').document('batch_id')
doc = batch_ref.get()
old_count = len(doc.get('completed_players', []))
new_count = len(list(batch_ref.collection('completed_players').stream()))
assert old_count == new_count, f"Inconsistency: {old_count} vs {new_count}"
```

### Check Phase 6 Detection
```sql
SELECT player_lookup, prediction_line, current_line,
       ABS(current_line - prediction_line) as change
FROM (
  SELECT p.player_lookup,
         p.current_points_line as prediction_line,
         c.current_points_line as current_line
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_raw.bettingpros_player_points_props c
    ON p.player_lookup = c.player_lookup
  WHERE p.game_date = CURRENT_DATE()
)
WHERE ABS(current_line - prediction_line) >= 1.0
```

### Check Memory Usage
```bash
gcloud logging read "resource.type=cloud_run_revision
  resource.labels.service_name=prediction-coordinator
  textPayload=~'memory'" --limit=50
```

---

## 🔴 Rollback Procedures

### Admin Dashboard
```bash
gcloud app versions list --service=default
gcloud app versions migrate <previous-version>
```

### Prediction Coordinator
```bash
gcloud run services update-traffic prediction-coordinator \
  --to-revisions=<previous-revision>=100 \
  --region=us-west2
```

### Cloud Functions
```bash
# Restore from backup (see Priority 3 above)
```

---

## ✅ Success Criteria

**Admin Dashboard:**
- [ ] force_predictions publishes to Pub/Sub
- [ ] retry_phase calls Cloud Run successfully
- [ ] trigger_self_heal publishes to Pub/Sub

**Prediction Coordinator:**
- [ ] Phase 6 finds stale predictions
- [ ] Firestore writes are atomic
- [ ] Memory usage reduced 50-70%
- [ ] Error logs visible

**Cloud Functions:**
- [ ] No import errors
- [ ] Functions execute successfully
- [ ] Shared code updates propagate

**Data Processors:**
- [ ] No crashes
- [ ] Failures are visible
- [ ] Data quality maintained

---

## 📝 Deployment Log

Keep track of deployments here:

**Date: ________**

- [ ] Admin Dashboard deployed at: ______
- [ ] Prediction Coordinator (staging) deployed at: ______
- [ ] Prediction Coordinator (prod) deployed at: ______
- [ ] Cloud Functions deployed: ______

**Issues Encountered:**

**Rollbacks Performed:**

**Notes:**

---

**Last Updated:** 2026-01-25
**Status:** Ready for deployment
**Estimated Time:** 4-6 hours total
