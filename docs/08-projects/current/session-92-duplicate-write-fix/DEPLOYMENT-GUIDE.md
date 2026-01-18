# Session 92: Duplicate-Write Fix - Deployment Guide

**Quick deployment guide for the distributed lock fix**

---

## Pre-Deployment Checklist

- [x] Distributed lock implementation reviewed
- [x] Post-consolidation validation tested
- [x] Documentation complete
- [ ] Firestore access verified for worker service account
- [ ] Deployment window scheduled (low-traffic period preferred)
- [ ] Rollback plan reviewed

---

## Deployment Steps

### 1. Verify Firestore Access

```bash
# Check if worker service account has Firestore permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:[WORKER_SA]" \
  --format="table(bindings.role)"

# Should include: roles/datastore.user
```

If missing, add permission:
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:[WORKER_SA_EMAIL]" \
  --role="roles/datastore.user"
```

### 2. Deploy Worker

```bash
cd /home/naji/code/nba-stats-scraper

# Build and deploy worker with new distributed_lock.py
./bin/predictions/deploy/deploy_prediction_worker.sh
```

### 3. Verify Deployment

```bash
# Get latest revision
REVISION=$(gcloud run services describe prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --format='value(status.latestCreatedRevisionName)')

echo "Latest revision: $REVISION"

# Check health
curl "https://prediction-worker-[YOUR-HASH]-uc.a.run.app/health"

# Check deep health
curl "https://prediction-worker-[YOUR-HASH]-uc.a.run.app/health/deep"
```

### 4. Monitor First Consolidation

Watch logs for lock acquisition and validation:
```bash
gcloud logging read "resource.type=cloud_run_revision AND \
  resource.labels.service_name=prediction-coordinator AND \
  (textPayload=~'Acquiring consolidation lock' OR \
   textPayload=~'Post-consolidation validation' OR \
   textPayload=~'MERGE complete')" \
  --project=nba-props-platform \
  --limit=20 \
  --format=json
```

Expected log output:
```
🔒 Acquiring consolidation lock for game_date=2026-01-17, batch=20260117_120000
✅ Acquired consolidation lock: consolidation_2026-01-17 (batch=20260117_120000, timeout=300s)
🔄 Executing MERGE for batch=20260117_120000 with 15 staging tables
✅ MERGE complete: 587 rows affected in 8234.5ms (batch=20260117_120000)
🔍 Running post-consolidation validation for game_date=2026-01-17...
✅ Post-consolidation validation PASSED (0 duplicates)
🔓 Released consolidation lock: consolidation_2026-01-17 (batch=20260117_120000)
```

### 5. Validate No Duplicates

```bash
# Check for duplicates in today's data
bq query --use_legacy_sql=false "
SELECT COUNT(*) as duplicate_business_keys
FROM (
    SELECT
        game_id,
        player_lookup,
        system_id,
        CAST(COALESCE(current_points_line, -1) AS INT64) as line,
        COUNT(*) as cnt
    FROM \`nba_predictions.player_prop_predictions\`
    WHERE game_date = CURRENT_DATE
    GROUP BY 1,2,3,4
    HAVING cnt > 1
)
"
```

**Expected result:** 0 rows

### 6. Check Firestore Lock State

```bash
# List all locks in Firestore
gcloud firestore export gs://nba-props-platform-backups/firestore-export-$(date +%Y%m%d) \
  --collection-ids=consolidation_locks \
  --project=nba-props-platform

# Or query directly
gcloud alpha firestore documents list \
  --collection-path=consolidation_locks \
  --project=nba-props-platform
```

**Expected:** Empty (all locks released) OR single lock if consolidation in progress

---

## Post-Deployment Validation

### Day 1: Monitor Closely

```bash
# Check every hour for duplicates
watch -n 3600 'bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(*) as dupes
  FROM (
    SELECT game_id, player_lookup, system_id, current_points_line, game_date, COUNT(*) as cnt
    FROM \`nba_predictions.player_prop_predictions\`
    WHERE game_date >= CURRENT_DATE - 1
    GROUP BY 1,2,3,4,5
    HAVING cnt > 1
  )
  GROUP BY game_date
"'
```

### Day 2-7: Daily Checks

Run daily data quality check (includes duplicate validation):
```bash
./bin/validation/daily_data_quality_check.sh
```

### Week 2: Performance Review

Check consolidation duration hasn't increased significantly:
```bash
# Extract consolidation timings from logs
gcloud logging read "resource.type=cloud_run_revision AND \
  resource.labels.service_name=prediction-coordinator AND \
  textPayload=~'MERGE complete' AND \
  timestamp>='2026-01-17T00:00:00Z'" \
  --project=nba-props-platform \
  --limit=100 \
  --format="table(timestamp, textPayload)"
```

**Expected:** Consolidation time < 60 seconds (was typically 5-30s before fix)

---

## Rollback Procedure

If duplicates detected or lock issues occur:

### Option A: Disable Lock (Quick Fix)

Edit `predictions/coordinator/coordinator.py`:
```python
# Line ~926 and ~1066
consolidation_result = consolidator.consolidate_batch(
    batch_id=batch_id,
    game_date=game_date,
    cleanup=True,
    use_lock=False  # TEMPORARILY DISABLE LOCK
)
```

Redeploy coordinator only:
```bash
./bin/predictions/deploy/deploy_prediction_coordinator.sh
```

### Option B: Full Rollback

```bash
# Rollback to previous revision
gcloud run services update-traffic prediction-worker \
  --to-revisions=prediction-worker-00065-jb8=100 \
  --project=nba-props-platform \
  --region=us-west2

gcloud run services update-traffic prediction-coordinator \
  --to-revisions=prediction-coordinator-00048-xyz=100 \
  --project=nba-props-platform \
  --region=us-west2
```

### After Rollback

1. Investigate root cause
2. Fix issue
3. Test in development environment
4. Schedule re-deployment

---

## Troubleshooting

### Lock Acquisition Fails

**Symptom:** Logs show "Lock acquisition failed" or "Cannot acquire consolidation lock"

**Diagnosis:**
```bash
# Check for stuck locks
gcloud alpha firestore documents list \
  --collection-path=consolidation_locks \
  --project=nba-props-platform \
  --format=json
```

**Fix:**
```bash
# Force release lock (if confirmed stuck)
python -c "
from predictions.worker.distributed_lock import ConsolidationLock
lock = ConsolidationLock('nba-props-platform')
lock.force_release('2026-01-17')  # Use actual game_date
"
```

### Validation Detects Duplicates

**Symptom:** Logs show "POST-CONSOLIDATION VALIDATION FAILED"

**Diagnosis:**
```bash
# Check duplicates
bq query --use_legacy_sql=false "
SELECT
    game_id,
    player_lookup,
    system_id,
    current_points_line,
    COUNT(*) as count,
    STRING_AGG(prediction_id, ', ') as prediction_ids
FROM \`nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-17'
GROUP BY 1,2,3,4
HAVING COUNT(*) > 1
"
```

**Fix:**
1. Staging tables should still exist (cleanup skipped on validation failure)
2. Investigate staging tables to understand how duplicates occurred
3. Run Session 91's de-duplication script if needed
4. File incident report with logs

### Consolidation Timeout

**Symptom:** Consolidation takes > 5 minutes, lock times out

**Diagnosis:**
- Check BigQuery job queue
- Check staging table size
- Check network connectivity

**Fix:**
- Increase lock timeout in `distributed_lock.py` (LOCK_TIMEOUT_SECONDS)
- Optimize MERGE query if needed
- Consider splitting very large batches

---

## Success Criteria

✅ **Deployment successful if:**
- No duplicates detected in post-consolidation validation
- Consolidation completes within normal time (<60s)
- Logs show lock acquisition/release working correctly
- No lock acquisition failures
- No errors in Cloud Run logs

❌ **Rollback if:**
- Duplicates detected after 24 hours
- Lock acquisition fails consistently (>10% of batches)
- Consolidation times out (>5 minutes)
- Firestore errors (quota exceeded, permission denied)

---

## Contact & Support

- **Documentation:** See `SESSION-92-DUPLICATE-WRITE-FIX.md`
- **Code:** `predictions/worker/distributed_lock.py`, `predictions/worker/batch_staging_writer.py`
- **Logs:** Cloud Run > prediction-worker, prediction-coordinator
- **Firestore:** Console > Firestore > consolidation_locks collection

---

**Last Updated:** 2026-01-17
**Deployment Status:** Ready for deployment
