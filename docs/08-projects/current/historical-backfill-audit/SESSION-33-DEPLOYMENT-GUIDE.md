# Session 33 Deployment Guide
**Date:** 2026-01-14
**Purpose:** Deploy tracking bug fixes to all Phase 2/3/4 services

## Current Status (Before Deployment)

### Code Status
- **Latest Commit:** d22c4d8 - Fix tracking bug in 24 processors
- **Previous Commit:** 92b8735 - Session 32 handoff
- **Fixes Included:**
  - Tracking bug fix (24 processors - Session 33)
  - Idempotency fix (run_history_mixin - Session 30-31)
  - BDL boxscores tracking fix (Session 32)

### Service Deployment Status (Before)

| Service | Current Revision | Current Commit | Commits Behind | Has All Fixes |
|---------|------------------|----------------|----------------|---------------|
| Phase 2 Raw | 00088-c4l | e6cc27d | 3 | ❌ NO (missing 24 processor fixes) |
| Phase 3 Analytics | 00053-tsq | af2de62 | 54 | ❌ NO (missing all fixes) |
| Phase 4 Precompute | 00037-xj2 | 9213a93 | 30 | ❌ NO (missing all fixes) |

**All services need to be updated to commit d22c4d8.**

## Deployment Plan

### ⚠️ CRITICAL: Local Deployments HANG - Use Cloud Shell Only

**CONFIRMED IN SESSION 33:** Local (WSL2) deployments hang indefinitely after "Validating Service" step.

**Issue:** GCP Cloud Run gRPC incident (Session 32) - still affecting local deployments
**Symptom:** Deployment appears to validate successfully but never completes routing traffic
**Duration:** Hangs indefinitely (tested up to 10 minutes with no progress)

**SOLUTION: All deployments MUST be done via Cloud Shell.**

**Cloud Shell URL:**
```
https://console.cloud.google.com/cloudshell?project=nba-props-platform
```

**What Was Attempted:**
- Session 33 attempted Phase 3/4 deployments from local WSL2
- Both hung after "Validating Service...........done"
- No progress after 3+ minutes
- Killed after confirming hang

**Cloud Shell Works:** Session 32 successfully deployed Phase 2 via Cloud Shell.

## Phase 2: Raw Processors

### Deploy Command
```bash
# In Cloud Shell
cd ~/nba-stats-scraper
git pull
bash bin/raw/deploy/deploy_processors_simple.sh
```

### Expected Outcome
- New revision created (00089-xxx or higher)
- Commit label: d22c4d8
- All 24 processor fixes deployed

### Verification
```bash
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"
```

**Expected:** `00089-xxx d22c4d8` (or higher revision)

### Test Tracking Fix Works
```sql
-- Should show actual record counts, not 0
SELECT
  processor_name,
  data_date,
  records_processed,
  status
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name IN ('BdlActivePlayersProcessor', 'BdlStandingsProcessor')
  AND data_date >= '2026-01-14'
  AND status = 'success'
ORDER BY started_at DESC
LIMIT 10
```

## Phase 3: Analytics Processors

### Current State
- **Current commit:** af2de62 (54 commits behind)
- **Missing:** Idempotency fix + tracking bug fixes + BDL fix

### Deploy Command
```bash
# In Cloud Shell
cd ~/nba-stats-scraper
git pull
bash bin/analytics/deploy/deploy_analytics_simple.sh
```

### Expected Outcome
- New revision created (00054-xxx or higher)
- Commit label: d22c4d8
- Idempotency fix deployed
- Any analytics processors with custom save_data() now have tracking

### Verification
```bash
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"
```

**Expected:** `00054-xxx d22c4d8` (or higher revision)

### Note on Analytics Processors
According to the audit, analytics processors don't override `save_data()`, so they don't have the tracking bug. However, they still need the idempotency fix from Session 30-31.

## Phase 4: Precompute Processors

### Current State
- **Current commit:** 9213a93 (30 commits behind)
- **Missing:** Idempotency fix + tracking bug fixes + BDL fix

### Deploy Command
```bash
# In Cloud Shell
cd ~/nba-stats-scraper
git pull
bash bin/precompute/deploy/deploy_precompute_simple.sh
```

### Expected Outcome
- New revision created (00038-xxx or higher)
- Commit label: d22c4d8
- Idempotency fix deployed
- Any precompute processors with custom save_data() now have tracking

### Verification
```bash
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"
```

**Expected:** `00038-xxx d22c4d8` (or higher revision)

### Note on Precompute Processors
According to the audit, precompute processors don't override `save_data()`, so they don't have the tracking bug. However, they still need the idempotency fix from Session 30-31.

## Post-Deployment Verification

### 1. Check All Services Are Updated
```bash
echo "=== Phase 2 Raw Processors ==="
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"

echo "=== Phase 3 Analytics Processors ==="
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"

echo "=== Phase 4 Precompute Processors ==="
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"
```

**All should show commit: d22c4d8**

### 2. Test Tracking Fix in Production

Wait for next scheduled processor run, then check:

```sql
-- Check recent runs show actual record counts
SELECT
  processor_name,
  data_date,
  records_processed,
  status,
  started_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name IN (
  'BdlActivePlayersProcessor',
  'BdlStandingsProcessor',
  'BdlInjuriesProcessor',
  'BdlPlayerBoxScoresProcessor',
  'MlbLineupsProcessor'
)
  AND data_date >= '2026-01-14'
  AND status = 'success'
ORDER BY started_at DESC
LIMIT 20
```

**Expected:** Should see actual record counts (100s-1000s), not 0.

### 3. Test Idempotency Fix

```sql
-- Check if processors can retry after 0-record runs
SELECT
  processor_name,
  data_date,
  records_processed,
  status,
  started_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= '2026-01-14'
  AND records_processed = 0
ORDER BY started_at DESC
LIMIT 10
```

**Expected:** Next runs for same date should be allowed (not blocked by idempotency).

## Troubleshooting

### Issue: Deployment Hangs

**Symptom:** Deployment stuck at "Validating Service" or "Routing traffic"

**Cause:** GCP Cloud Run gRPC incident (Session 32)

**Solution:**
- Use Cloud Shell instead of local WSL2
- If Cloud Shell also hangs, check GCP status page
- Wait 10 minutes max, then cancel and retry

### Issue: Commit SHA Doesn't Match

**Symptom:** Deployed service shows old commit

**Cause:** Git pull didn't fetch latest, or wrong branch

**Solution:**
```bash
cd ~/nba-stats-scraper
git fetch origin
git checkout main
git reset --hard origin/main
git log -1 --oneline  # Should show d22c4d8
# Then retry deployment
```

### Issue: Tests Fail During Deployment

**Symptom:** Pre-deployment tests fail

**Cause:** Code changes may have broken tests

**Solution:**
1. Check test output for specific failures
2. Run tests locally: `pytest tests/`
3. Fix any broken tests before deploying
4. Commit fixes and retry

### Issue: Service Won't Start After Deployment

**Symptom:** New revision fails health checks

**Cause:** Code error or missing dependency

**Solution:**
1. Check Cloud Run logs in GCP Console
2. Look for Python exceptions or import errors
3. Fix code issues and redeploy
4. Rollback if needed: Use GCP Console to route traffic to previous revision

## Expected Timeline

- **Phase 2 deployment:** 3-5 minutes
- **Phase 3 deployment:** 3-5 minutes
- **Phase 4 deployment:** 3-5 minutes
- **Total:** 15-20 minutes for all three services

## Success Criteria

✅ **All services deployed:**
- Phase 2: Revision 00089+ with commit d22c4d8
- Phase 3: Revision 00054+ with commit d22c4d8
- Phase 4: Revision 00038+ with commit d22c4d8

✅ **Tracking fix verified:**
- Recent processor runs show actual record counts
- No more false "0 record" runs for processors that have data

✅ **Idempotency fix verified:**
- Processors can retry after 0-record runs
- Previous 0-record runs don't block retries

## Next Steps After Deployment

From Session 32 handoff:

1. **Re-run monitoring script** to get accurate data loss counts:
   ```bash
   PYTHONPATH=. python scripts/monitor_zero_record_runs.py \
     --start-date 2025-10-01 \
     --end-date 2026-01-14 \
     > /tmp/monitoring_after_fix.txt
   ```

2. **Create accurate data loss inventory:**
   - Cross-reference zero-record runs with BigQuery data
   - Distinguish: real data loss vs legitimate zero vs not-yet-fixed

3. **Deploy backfill improvements** (Session 30 work)

4. **Deploy BettingPros reliability fix** (Session 29-31 work)

## Files Location

- This guide: `docs/08-projects/current/historical-backfill-audit/SESSION-33-DEPLOYMENT-GUIDE.md`
- Audit report: `docs/08-projects/current/historical-backfill-audit/PROCESSOR-TRACKING-BUG-AUDIT.md`
- Session 32 handoff: `docs/09-handoff/2026-01-14-SESSION-32-COMPREHENSIVE-HANDOFF.md`
