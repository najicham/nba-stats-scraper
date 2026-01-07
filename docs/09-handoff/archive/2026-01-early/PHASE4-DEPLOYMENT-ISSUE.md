# Phase 4 Deployment Issue - 2025-12-31

## Problem Summary

Phase 4 (Precompute) deployment failed during overnight testing session.

**Status:** ❌ FAILED
**Impact:** Cannot test Phase 4 with dataset_prefix support
**Workaround:** Test Phase 3 alone, defer Phase 4 testing

---

## Deployment Attempt Details

**Time:** 2025-12-31 01:41:03 - 01:54:38 (13m 35s)
**Script:** `bin/precompute/deploy/deploy_precompute_processors.sh`
**Commit:** `a51aae7`
**Result:** Build failed

**Error Message:**
```
Building using Buildpacks and deploying container to Cloud Run service...
Building Container.......failed
ERROR: (gcloud.run.deploy) Build failed; check build logs for details
```

**Build ID:** `c3c052da-ddd1-46eb-9d3a-7219a9909377`
**Log URL:** https://console.cloud.google.com/cloud-build/builds/c3c052da-ddd1-46eb-9d3a-7219a9909377?project=756957797294

---

## Key Observations

### 1. Buildpacks vs Dockerfile

**Phase 3 (Success):**
```
Building using Dockerfile and deploying container...
```

**Phase 4 (Failed):**
```
Building using Buildpacks and deploying container...
```

Cloud Run chose **Buildpacks** for Phase 4 instead of using the Dockerfile, which caused the build to fail.

### 2. Current Running Service

Phase 4 has an existing working revision:
- **Revision:** `nba-phase4-precompute-processors-00029-fdx`
- **Created:** 2025-12-29T23:13:37Z
- **Commit:** `476352a` (OLD - before dataset_prefix code)
- **Status:** Running and healthy
- **IAM:** ✅ Secured (no allUsers)

### 3. Dataset Prefix Status

The currently running Phase 4 service **does NOT** have dataset_prefix support because:
- Running commit: `476352a` (Dec 29)
- Dataset_prefix added in: `5ee366a` (Dec 30)
- Current code: `a51aae7` (Dec 31)

**Implication:** Cannot safely test Phase 4 replay without risking production data writes.

---

## Root Cause Analysis

### Possible Causes

1. **Dockerfile Not Found**
   - Script copies Dockerfile to root
   - Cleanup might have removed it prematurely
   - Cloud Run didn't detect Dockerfile

2. **Source Flag Behavior**
   - `--source=.` may default to Buildpacks if Dockerfile detection fails
   - Need explicit `--dockerfile` parameter?

3. **Buildpack Auto-Detection**
   - Cloud Run may have detected Python files
   - Chose Buildpacks instead of Dockerfile
   - Buildpacks failed due to project structure

4. **Previous Deployment State**
   - Service might have cached Buildpack preference
   - Need to force Dockerfile usage

### Phase 3 vs Phase 4 Script Comparison

Both scripts are nearly identical:
```bash
# Phase 3 (Works)
cp docker/analytics-processor.Dockerfile ./Dockerfile
gcloud run deploy nba-phase3-analytics-processors --source=. ...

# Phase 4 (Fails)
cp docker/precompute-processor.Dockerfile ./Dockerfile
gcloud run deploy nba-phase4-precompute-processors --source=. ...
```

**No obvious difference** in the deployment commands.

---

## Attempted Diagnostics

1. **Get Build Logs:** Failed - `gcloud builds log` command errors
2. **Console Link:** Build log URL provided (requires browser access)
3. **Service Logs:** Only show 403 errors (security working correctly)

---

## Recommended Fixes

### Option 1: Use Cloud Build Explicitly (Recommended)

Replace `--source=.` with explicit Cloud Build config:

```yaml
# cloudbuild-precompute.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/nba-phase4-precompute-processors', '-f', 'docker/precompute-processor.Dockerfile', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/nba-phase4-precompute-processors']

images:
  - 'gcr.io/$PROJECT_ID/nba-phase4-precompute-processors'
```

Then deploy:
```bash
gcloud builds submit --config cloudbuild-precompute.yaml
gcloud run deploy nba-phase4-precompute-processors \
  --image gcr.io/nba-props-platform/nba-phase4-precompute-processors \
  --region=us-west2 \
  --no-allow-unauthenticated \
  ...
```

### Option 2: Force Dockerfile Usage

Add `--no-use-google-dev-pack` flag:
```bash
gcloud run deploy $SERVICE_NAME \
  --source=. \
  --no-use-google-dev-pack \
  ...
```

### Option 3: Use Docker Build Locally

```bash
# Build locally
docker build -f docker/precompute-processor.Dockerfile -t gcr.io/nba-props-platform/nba-phase4-precompute-processors .

# Push to registry
docker push gcr.io/nba-props-platform/nba-phase4-precompute-processors

# Deploy from image
gcloud run deploy nba-phase4-precompute-processors \
  --image gcr.io/nba-props-platform/nba-phase4-precompute-processors \
  ...
```

### Option 4: Match Phase 3 Pattern Exactly

Check if Phase 3's Dockerfile has something Phase 4's doesn't:
```bash
diff docker/analytics-processor.Dockerfile docker/precompute-processor.Dockerfile
```

---

## Workaround for Testing

Since Phase 4 deployment failed, proceed with:

1. **Test Phase 3 Alone**
   - Phase 3 deployed successfully with dataset_prefix
   - Can validate analytics processing works correctly
   - Proves dataset isolation concept

2. **Document Limitations**
   - Phase 4 cannot be tested until redeployed
   - Full Phase 3→4 replay deferred
   - Phase 3 testing still valuable

3. **Security Audit**
   - Independent of deployments
   - Can proceed with access log analysis
   - Critical for security follow-up

---

## Testing Completed Despite Issue

Even without Phase 4, valuable testing can be done:

### ✅ Testable
- Phase 3 deployment success
- Phase 3 health endpoint
- Phase 3 dataset_prefix parameter
- Phase 3 writes to test datasets
- Production data remains untouched
- Security audit
- IAM policy verification

### ❌ Blocked
- Phase 4 deployment
- Phase 4 dataset_prefix testing
- Full Phase 3→4 replay
- End-to-end pipeline test

---

## Next Steps (Morning)

### Immediate (5-10 min)
1. Open build log URL in browser
2. Review actual build failure details
3. Identify specific error

### Fix Deployment (15-30 min)
1. Try Option 1 (Cloud Build explicit)
2. If fails, try Option 2 (force Dockerfile)
3. Verify deployment succeeds
4. Test health endpoint
5. Test dataset_prefix parameter

### Resume Testing (30-60 min)
1. Re-run full Phase 3→4 replay
2. Validate both phases write to test datasets
3. Compare with production
4. Complete test plan

---

## Files to Review

**Deployment Scripts:**
- `bin/precompute/deploy/deploy_precompute_processors.sh` (failed script)
- `bin/analytics/deploy/deploy_analytics_processors.sh` (working reference)

**Dockerfiles:**
- `docker/precompute-processor.Dockerfile`
- `docker/analytics-processor.Dockerfile`

**Build Logs:**
- Console: https://console.cloud.google.com/cloud-build/builds/c3c052da-ddd1-46eb-9d3a-7219a9909377?project=756957797294

---

## Questions to Answer

1. **Why did Cloud Run choose Buildpacks for Phase 4 but Dockerfile for Phase 3?**
2. **What failed in the Buildpack build process?**
3. **Is there a way to force Dockerfile usage in `--source` mode?**
4. **Should we switch all deployments to explicit Cloud Build?**

---

## Impact on Session Goals

**Original Plan:**
- ✅ Fix security issues (COMPLETE)
- 🟡 Deploy Phase 3 & 4 with dataset_prefix (PARTIAL - 3 done, 4 failed)
- 🟡 Test full Phase 3→4 replay (BLOCKED by Phase 4)
- ✅ Security audit (CAN PROCEED)

**Adjusted Plan:**
- ✅ Test Phase 3 alone
- ✅ Verify dataset isolation works
- ✅ Security audit
- 📝 Document Phase 4 issue
- ⏰ Defer Phase 4 testing to morning

**Value Delivered:**
- Proof of concept for dataset isolation (Phase 3)
- Security audit completed
- Issue well-documented for quick resolution
- No production data at risk

---

*Documented: 2025-12-31 02:00 AM*
*Status: Awaiting morning review*
*Priority: P1 - Blocks full testing*
*Estimated Fix Time: 30-60 minutes*
