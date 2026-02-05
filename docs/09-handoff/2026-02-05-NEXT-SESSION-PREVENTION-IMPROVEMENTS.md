# Next Session: Preventing Silent Failure Bugs

**Date:** 2026-02-05 (for next session)
**Context:** Sessions 129-130 revealed a pattern of "silent failure" bugs
**Goal:** Implement preventative measures to catch these bugs before deployment

---

## Background: The Silent Failure Pattern

### What Happened (Sessions 129-130)

**Session 129:** Grading service was broken for 39 hours
- **Cause:** Missing `predictions/` module in Dockerfile
- **Symptom:** Service deployed successfully, started fine, but crashed on first request
- **Detection:** Only discovered when manually checking grading coverage

**Session 130:** Grading service still broken after "fix"
- **Cause:** Missing `db-dtypes` Python package
- **Symptom:** Service deployed successfully, started fine, but crashed when querying BigQuery
- **Detection:** Manual testing of regrading endpoints

### The Pattern

**All bugs shared these characteristics:**
1. ✅ Docker build succeeded
2. ✅ Dependency tests passed (basic imports)
3. ✅ Service deployed to Cloud Run
4. ✅ Service started and `/health` endpoint responded
5. ❌ **Service crashed when actually processing requests**

**Root Cause:** Testing validates startup behavior, not runtime behavior.

---

## Current Defense Layers (What We Have)

### Layer 1: Build-Time Validation
- **Tool:** `bin/deploy-service.sh` dependency testing
- **Tests:** Imports critical modules after Docker build
- **Gap:** Only tests imports that happen at startup, not during request processing

### Layer 2: Deep Health Checks
- **Tool:** `/health/deep` endpoint
- **Tests:** Module imports, BigQuery connectivity, Firestore connectivity
- **Gap:** Tests connectivity but not end-to-end operations (e.g., BigQuery→pandas conversion)

### Layer 3: Smoke Tests
- **Tool:** Deployment script smoke tests
- **Tests:** Calls health endpoints after deployment
- **Gap:** Can't test authenticated endpoints (fails with 403)

### Layer 4: Drift Monitoring
- **Tool:** Cloud Function checking deployment timestamps
- **Tests:** Alerts when deployed code is stale
- **Gap:** Missing Slack webhook secret, can't send alerts

---

## Proposed Improvements

### Priority 1: Enhanced Deep Health Checks

**Problem:** Current deep health checks test connectivity but not actual operations.

**Example of gap:**
```python
# Current: Tests BigQuery connectivity
result = client.query("SELECT 1 as test").result()  # ✅ Works

# Missing: Tests BigQuery→pandas conversion (requires db-dtypes)
df = client.query("SELECT 1 as test").to_dataframe()  # ❌ Would have caught db-dtypes bug
```

**Solution:** Add end-to-end operation tests to `/health/deep` endpoint.

**Implementation checklist:**
- [ ] Add BigQuery→pandas conversion test (catches db-dtypes)
- [ ] Add Firestore read/write test (catches missing permissions)
- [ ] Add Pub/Sub publish test (catches missing auth)
- [ ] Test all critical code paths that happen during request processing
- [ ] Return detailed error messages with module/operation that failed

**Files to update:**
- `data_processors/grading/nba/main_nba_grading_service.py` (add to `/health/deep`)
- `predictions/worker/main.py` (if deep health check exists)
- `predictions/coordinator/main.py` (if deep health check exists)
- Other services that process requests

**Example implementation:**
```python
@app.route('/health/deep', methods=['GET'])
def health_check_deep():
    checks = {}
    all_healthy = True

    # Check 1: Critical imports
    try:
        from predictions.shared.distributed_lock import DistributedLock
        from shared.clients.bigquery_pool import get_bigquery_client
        checks['imports'] = {'status': 'ok'}
    except ImportError as e:
        checks['imports'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    # Check 2: BigQuery END-TO-END (not just connectivity)
    try:
        from shared.clients.bigquery_pool import get_bigquery_client
        client = get_bigquery_client()
        # NEW: Test actual pandas conversion (catches db-dtypes)
        df = client.query("SELECT 1 as test").to_dataframe()
        if len(df) != 1:
            raise ValueError("Query returned wrong number of rows")
        checks['bigquery'] = {'status': 'ok', 'operations': ['query', 'to_dataframe']}
    except ImportError as e:
        checks['bigquery'] = {'status': 'failed', 'error': f'Import error: {str(e)}'}
        all_healthy = False
    except Exception as e:
        checks['bigquery'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    # Check 3: Firestore operations
    try:
        from google.cloud import firestore
        db = firestore.Client()
        # NEW: Test actual write operation, not just connectivity
        test_ref = db.collection('_health_checks').document('test')
        test_ref.set({'timestamp': datetime.now(timezone.utc).isoformat()})
        test_ref.delete()
        checks['firestore'] = {'status': 'ok', 'operations': ['write', 'delete']}
    except Exception as e:
        checks['firestore'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    status_code = 200 if all_healthy else 503
    return jsonify({
        "status": "healthy" if all_healthy else "unhealthy",
        "service": "nba_grading_service",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks
    }), status_code
```

---

### Priority 2: Authenticated Smoke Tests

**Problem:** Smoke tests can't access authenticated endpoints (403 errors).

**Current behavior:**
```bash
# Fails with 403
curl https://nba-grading-service-*.run.app/health/deep
```

**Solution Option A: Make health endpoints publicly accessible**
```bash
# Allow unauthenticated access to health endpoints only
gcloud run services add-iam-policy-binding nba-grading-service \
  --region=us-west2 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

**Pros:**
- Smoke tests work immediately
- External monitoring tools can check health
- Standard practice for health endpoints

**Cons:**
- Exposes service to public (though health endpoint is read-only)
- Need to ensure deep health check doesn't leak sensitive info

**Solution Option B: Add auth tokens to smoke tests**
```bash
# In bin/deploy-service.sh smoke tests
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" https://SERVICE_URL/health/deep
```

**Pros:**
- Maintains security
- More realistic test (uses actual auth flow)

**Cons:**
- Requires token generation in deployment script
- Tokens expire (need refresh logic)

**Recommendation:** Use **Option A** (public health endpoints) for simplicity and standard practice. Health endpoints are designed to be safe to expose publicly.

---

### Priority 3: Fix Drift Monitoring Alerts

**Problem:** Drift monitoring function runs but can't send Slack alerts.

**Error:**
```
404 Secret [projects/756957797294/secrets/SLACK_WEBHOOK_URL] not found
```

**Solution:** Create the missing secret or update function to use existing secret name.

**Investigation needed:**
1. Check if Slack webhook secret exists under different name:
   ```bash
   gcloud secrets list --project=nba-props-platform | grep -i slack
   ```

2. If exists with different name, update function to use correct name

3. If doesn't exist, create it:
   ```bash
   echo "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" | \
     gcloud secrets create SLACK_WEBHOOK_URL --data-file=-
   ```

4. Grant function access:
   ```bash
   gcloud secrets add-iam-policy-binding SLACK_WEBHOOK_URL \
     --member="serviceAccount:deployment-drift-monitor@nba-props-platform.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```

---

### Priority 4: Dockerfile Dependency Validation

**Problem:** Services import modules not copied in Dockerfile.

**Examples:**
- Session 129: Grading service imported `predictions.shared` but Dockerfile didn't copy `predictions/`
- Session 130: Service used BigQuery→pandas but didn't install `db-dtypes`

**Solution:** Static analysis to validate Dockerfile matches Python imports.

**Implementation:**
```bash
#!/bin/bash
# bin/validate-dockerfile-dependencies.sh
#
# Validates that all Python imports have corresponding COPY or pip install in Dockerfile

SERVICE_DIR="$1"
DOCKERFILE="$SERVICE_DIR/Dockerfile"
MAIN_PY=$(find "$SERVICE_DIR" -name "*.py" | head -1)

# Extract Python imports from service code
imports=$(grep -rh "^import\|^from" "$SERVICE_DIR" --include="*.py" | \
  sed 's/from \([^ ]*\).*/\1/' | sed 's/import \([^ ]*\).*/\1/' | \
  sort -u | grep -E "^(shared|predictions|data_processors)")

# Extract COPY commands from Dockerfile
copies=$(grep "^COPY" "$DOCKERFILE" | awk '{print $2}')

# Check for missing dependencies
missing=()
for import in $imports; do
  base_module=$(echo "$import" | cut -d. -f1)
  if ! echo "$copies" | grep -q "$base_module"; then
    missing+=("$import")
  fi
done

if [ ${#missing[@]} -gt 0 ]; then
  echo "❌ DOCKERFILE VALIDATION FAILED"
  echo ""
  echo "The following imports are used but not copied in Dockerfile:"
  for m in "${missing[@]}"; do
    echo "  - $m"
  done
  exit 1
else
  echo "✅ Dockerfile validation passed"
fi
```

**Usage:**
```bash
# Run manually
./bin/validate-dockerfile-dependencies.sh data_processors/grading/nba

# Add to pre-commit hook
# Add to deployment script before build
```

---

### Priority 5: Runtime Dependency Testing

**Problem:** pip dependency resolution is slow and can pick wrong versions.

**Observation from Session 130:**
```
INFO: pip is looking at multiple versions of grpcio-status...
INFO: This is taking longer than usual...
```

**Solution:** Pin ALL transitive dependencies, not just direct dependencies.

**Current (requirements.txt):**
```
flask==3.0.0
pandas==2.1.3
google-cloud-bigquery==3.13.0
db-dtypes==1.2.0  # Added in Session 130
```

**Proposed (requirements-lock.txt):**
```
# Generated by: pip freeze
flask==3.0.0
pandas==2.1.3
google-cloud-bigquery==3.13.0
db-dtypes==1.2.0
grpcio==1.76.0  # Pinned transitive dependency
grpcio-status==1.62.3  # Pinned version (no more backtracking!)
# ... all transitive dependencies pinned
```

**Implementation:**
1. Generate lock file: `pip freeze > requirements-lock.txt`
2. Update Dockerfile: `RUN pip install -r requirements-lock.txt`
3. Regenerate lock file when adding new dependencies

**Benefits:**
- Faster builds (no dependency resolution)
- Deterministic builds (same versions every time)
- Easier to audit dependencies

---

## Testing Plan

### 1. Test Current Services for Silent Failures

**Goal:** Identify if other services have similar issues.

**Method:** Call `/health/deep` endpoint for all services and verify response.

**Services to test:**
- [ ] nba-grading-service
- [ ] prediction-worker
- [ ] prediction-coordinator
- [ ] nba-phase3-analytics-processors
- [ ] nba-phase4-precompute-processors

**For each service:**
1. Check if `/health/deep` endpoint exists
2. If yes, verify it tests actual operations (not just connectivity)
3. If no, add deep health check endpoint
4. Test manually with curl (with auth token)
5. Verify smoke tests can access it

### 2. Audit All Dockerfiles

**Goal:** Find services with missing dependencies before they break.

**Method:** Run dependency validation script on all services.

**Services to audit:**
- [ ] data_processors/grading/nba/Dockerfile
- [ ] predictions/worker/Dockerfile
- [ ] predictions/coordinator/Dockerfile
- [ ] data_processors/analytics/Dockerfile
- [ ] data_processors/precompute/Dockerfile
- [ ] scrapers/Dockerfile

**For each Dockerfile:**
1. Run `bin/validate-dockerfile-dependencies.sh`
2. Fix any missing COPY commands
3. Verify all Python imports have corresponding dependencies
4. Check requirements.txt has all needed packages

### 3. Test Drift Monitoring

**Goal:** Verify drift monitoring can actually send alerts.

**Steps:**
1. Fix Slack webhook secret issue
2. Create intentional drift (commit code change without deploying)
3. Wait for scheduled run or trigger manually
4. Verify Slack alert appears in #nba-alerts channel
5. Deploy fix to clear drift
6. Verify alert resolves

---

## Success Criteria

After completing these improvements, we should have:

### ✅ Detection: Catch bugs before production
- [ ] Deep health checks test actual operations (not just connectivity)
- [ ] Smoke tests can verify service functionality after deployment
- [ ] Dockerfile validation prevents missing dependencies
- [ ] All services have deep health checks

### ✅ Prevention: Stop bugs from being introduced
- [ ] Dependency lock files prevent version issues
- [ ] Pre-deployment validation catches common mistakes
- [ ] Clear documentation of required patterns

### ✅ Monitoring: Know when things break
- [ ] Drift monitoring sends Slack alerts when code is stale
- [ ] Health check failures trigger alerts
- [ ] Grading coverage monitoring detects service failures

### ✅ Recovery: Fix issues quickly
- [ ] Deep health check output shows exactly what failed
- [ ] Smoke tests provide immediate feedback on deployment
- [ ] Drift monitoring triggers automatic redeployment (future)

---

## Recommended Session Plan

### Session Start (15 min)
1. Read this document
2. Review Session 129-130 handoffs
3. Understand the silent failure pattern
4. Choose which improvements to tackle

### Phase 1: Quick Wins (30-45 min)
1. **Fix Slack webhook secret** (15 min)
   - Investigate secret name
   - Create or update secret
   - Test drift monitoring

2. **Make health endpoints public** (15 min)
   - Update IAM policy for grading service
   - Test smoke tests pass
   - Apply to other services

3. **Add BigQuery→pandas test to deep health check** (15 min)
   - Update grading service `/health/deep`
   - Deploy and test
   - Verify catches db-dtypes issue

### Phase 2: Systematic Improvements (60-90 min)
4. **Enhance deep health checks for all services** (45 min)
   - Add to prediction-worker
   - Add to prediction-coordinator
   - Add to analytics/precompute processors
   - Test all endpoints

5. **Create Dockerfile validation script** (30 min)
   - Write validation logic
   - Test on all services
   - Fix any issues found
   - Add to pre-commit hooks

6. **Generate dependency lock files** (15 min)
   - For each service, generate requirements-lock.txt
   - Update Dockerfiles to use lock files
   - Test build performance improvement

### Phase 3: Documentation & Testing (30 min)
7. **Update documentation** (15 min)
   - Add to deployment guide
   - Update troubleshooting docs
   - Document new validation tools

8. **Test end-to-end** (15 min)
   - Deploy a service with all improvements
   - Verify smoke tests pass
   - Verify deep health check works
   - Create intentional error and verify detection

---

## Key Questions to Answer

1. **Should all services have public health endpoints?**
   - Recommendation: Yes, health endpoints are designed to be safe
   - Consider: Add rate limiting if concerned about abuse

2. **How deep should deep health checks go?**
   - Recommendation: Test the most critical operation each service performs
   - Don't test every edge case, just core functionality

3. **Should we auto-deploy when drift is detected?**
   - Recommendation: Not yet - alert first, learn patterns
   - Future: Consider auto-deploy for low-risk services

4. **What about other services (not grading)?**
   - Recommendation: Audit prediction-worker first (has drift)
   - Then analytics/precompute services
   - Then scrapers (lower risk)

---

## Resources

**Related Documentation:**
- Session 129 Handoff: `docs/09-handoff/2026-02-05-SESSION-129-HANDOFF.md`
- Session 130 Handoff: `docs/09-handoff/2026-02-05-SESSION-130-HANDOFF.md`
- Health Checks Guide: `docs/05-development/health-checks-and-smoke-tests.md`
- Deployment Guide: `docs/02-operations/deployment.md`

**Tools:**
- Deployment script: `bin/deploy-service.sh`
- Drift check script: `bin/check-deployment-drift.sh`
- Deep health check example: `data_processors/grading/nba/main_nba_grading_service.py:51-133`

**GCP Resources:**
- Cloud Run services: `gcloud run services list --region=us-west2`
- Secrets: `gcloud secrets list --project=nba-props-platform`
- Cloud Functions: `gcloud functions list --region=us-west2`

---

## Final Note

These improvements aren't about preventing ALL bugs - that's impossible. They're about:

1. **Catching bugs earlier** - Before they hit production
2. **Detecting failures faster** - Minutes instead of hours
3. **Making debugging easier** - Clear error messages showing what failed
4. **Building confidence** - Deploy without fear

The goal is to move from "hope it works" to "know it works" through systematic validation at every layer.

Good luck! 🚀
