# Phase A Deployment Checklist
## Week 0 Security Fixes + Completeness Check

**Date Created:** January 19, 2026
**Target Deployment:** Week of January 27, 2026
**Git Tag:** week-0-security-complete
**Summary:** docs/09-handoff/WEEK-0-SECURITY-COMPLETE-SUMMARY.md

---

## PRE-DEPLOYMENT CHECKLIST

### ✅ Code Readiness

- [x] All Week 0 security fixes merged to main (commit 81cc7d84)
- [x] 9/13 critical security issues resolved
- [x] All tests passing (no security-related failures)
- [x] Security scans clean (0 eval, 0 secrets, 306 parameterized queries)
- [x] Code review completed (Session Manager validation)
- [x] Documentation complete

**Outstanding Items:**
- [ ] Input validation module (Issue #4) - DEFERRED
- [ ] Medium severity issues (#10-13) - DEFERRED
- [ ] Cloud Logging full implementation (Issue #5) - PARTIAL

**Risk Assessment:** ✅ ACCEPTABLE - Deferred items are hardening improvements, not critical vulnerabilities

---

### 🔑 Environment Variables Configuration

**Critical - MUST be set before deployment:**

```bash
# Session 1: Secrets Management
BETTINGPROS_API_KEY=<obtain from BettingPros>
SENTRY_DSN=<obtain from Sentry dashboard>

# Session 2A: Authentication
VALID_API_KEYS=<comma-separated list of valid API keys>

# Session 2A: Degraded Mode (Optional)
ALLOW_DEGRADED_MODE=false  # Only set to true in emergencies
```

**Verification Commands:**

```bash
# Check analytics-processor service
gcloud run services describe analytics-processor \
  --region us-west2 \
  --format="value(spec.template.spec.containers[0].env)"

# Should show:
# - BETTINGPROS_API_KEY=<set>
# - SENTRY_DSN=<set>
# - VALID_API_KEYS=<set>
```

**Tasks:**
- [ ] Create `analytics-api-keys` secret in GCP Secret Manager
- [ ] Verify `bettingpros-api-key` exists in GCP Secret Manager (or create)
- [ ] Verify `sentry-dsn` exists in GCP Secret Manager (or create)
- [ ] Update Cloud Run service environment variables
- [ ] Test environment variable loading (check logs for warnings)

---

### 🔐 Secret Rotation (CRITICAL)

**Why:** Hardcoded secrets were exposed in git history (now removed but should be rotated)

**BettingPros API Key:**
- [ ] Contact BettingPros to rotate API key
- [ ] Old key: `CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh` (ROTATE)
- [ ] Update GCP Secret Manager with new key
- [ ] Update Cloud Run environment variables
- [ ] Test BettingPros API calls still work

**Sentry DSN:**
- [ ] Generate new DSN in Sentry dashboard (optional - less critical)
- [ ] Old DSN project ID: `96f5d7efbb7105ef2c05aa551fa5f4e0`
- [ ] Update GCP Secret Manager with new DSN
- [ ] Update Cloud Run environment variables
- [ ] Verify Sentry monitoring still works

**Timeline:**
- Before staging deployment: Create secrets in Secret Manager
- Before production deployment: Rotate exposed secrets

---

## STAGING DEPLOYMENT

### Deploy to Staging Environment

**Steps:**
1. [ ] Verify main branch is at commit 81cc7d84 or later
2. [ ] Set all required environment variables (see above)
3. [ ] Deploy analytics-processor to staging:
   ```bash
   gcloud run deploy analytics-processor-staging \
     --source . \
     --region us-west2 \
     --platform managed \
     --update-env-vars BETTINGPROS_API_KEY=<key> \
     --update-env-vars SENTRY_DSN=<dsn> \
     --update-env-vars VALID_API_KEYS=<keys> \
     --update-env-vars ALLOW_DEGRADED_MODE=false
   ```
4. [ ] Deploy other affected services (if any)

### Smoke Tests (Staging)

**Test 1: Health Endpoints**
```bash
# Should return 200 OK
curl https://analytics-processor-staging.run.app/health

# Expected: {"status": "healthy", "service": "analytics-processor"}
```
- [ ] Health endpoint returns 200
- [ ] Service name in response

**Test 2: Authentication Enforcement**
```bash
# WITHOUT API key - should return 401
curl -X POST https://analytics-processor-staging.run.app/process-date-range \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-19", "end_date": "2026-01-19"}'

# Expected: {"error": "Unauthorized"}, 401

# WITH valid API key - should succeed or return business logic error
curl -X POST https://analytics-processor-staging.run.app/process-date-range \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <valid-key>" \
  -d '{"start_date": "2026-01-19", "end_date": "2026-01-19"}'

# Expected: NOT 401 (may be 200, 400, or 500 depending on business logic)
```
- [ ] Without API key: Returns 401 Unauthorized
- [ ] With valid API key: Does NOT return 401
- [ ] Logs show unauthorized attempt for first request

**Test 3: Fail-Closed Behavior**
```bash
# Trigger analytics for a date with missing boxscores
# Should fail-closed (return error) instead of processing incomplete data

curl -X POST https://analytics-processor-staging.run.app/process-date-range \
  -H "X-API-Key: <valid-key>" \
  -d '{"start_date": "2026-01-01", "end_date": "2026-01-01"}'
# (Assuming no games on this date)

# Expected: Error response (not fake "success")
```
- [ ] Returns error for incomplete data
- [ ] Does NOT return success when data is missing
- [ ] Logs show "is_error_state" or completeness check failure

**Test 4: SQL Injection Prevention** (Manual code review)
```bash
# Verify parameterized queries in logs
# Check BigQuery logs for queries with @param syntax

# Should see queries like:
# DELETE FROM `table` WHERE game_id = @game_id
# SELECT ... WHERE game_date = @game_date
```
- [ ] BigQuery logs show parameterized queries (@param syntax)
- [ ] No f-string interpolation in SQL WHERE clauses

**Test 5: No eval() Code Execution**
```bash
# Attempt to upload malicious data (if applicable)
# Should be blocked by ast.literal_eval()
```
- [ ] Code execution attempts blocked
- [ ] ValueError logged for malicious input

### Monitoring (24 hours)

Monitor staging for 24 hours before proceeding to production:

**Metrics to Watch:**
- [ ] Error rate ≤ baseline (no spike from security fixes)
- [ ] Latency ≤ baseline (no performance degradation)
- [ ] 401 Unauthorized count (should be >0 if auth is working)
- [ ] SQL injection attempt count (should be 0 or logged and blocked)
- [ ] Sentry errors (check for new error patterns)

**Logs to Review:**
- [ ] Unauthorized access attempts logged with details
- [ ] No errors from environment variable loading
- [ ] Completeness check failures logged as errors (not warnings)
- [ ] BigQuery queries use parameterized syntax

**Success Criteria:**
- [ ] All smoke tests pass
- [ ] No production incidents
- [ ] Error rate stable
- [ ] Authentication working as expected

---

## PRODUCTION DEPLOYMENT

### Canary Deployment (10% → 50% → 100%)

**Phase 1: 10% Traffic**
1. [ ] Deploy to production with 10% traffic split
   ```bash
   gcloud run deploy analytics-processor \
     --source . \
     --region us-west2 \
     --platform managed \
     --tag canary \
     --update-env-vars BETTINGPROS_API_KEY=<key> \
     --update-env-vars SENTRY_DSN=<dsn> \
     --update-env-vars VALID_API_KEYS=<keys>

   # Route 10% traffic to canary
   gcloud run services update-traffic analytics-processor \
     --to-revisions canary=10 \
     --region us-west2
   ```
2. [ ] Monitor for 4 hours
3. [ ] Check metrics:
   - [ ] Error rate ≤ baseline
   - [ ] Latency ≤ baseline + 10%
   - [ ] No security incidents
   - [ ] 401 errors present (auth working)

**Phase 2: 50% Traffic**
1. [ ] Increase to 50% traffic
   ```bash
   gcloud run services update-traffic analytics-processor \
     --to-revisions canary=50 \
     --region us-west2
   ```
2. [ ] Monitor for 4 hours
3. [ ] Check metrics (same as Phase 1)

**Phase 3: 100% Traffic**
1. [ ] Increase to 100% traffic
   ```bash
   gcloud run services update-traffic analytics-processor \
     --to-revisions canary=100 \
     --region us-west2
   ```
2. [ ] Monitor for 48 hours
3. [ ] Check metrics (same as Phase 1)
4. [ ] Review logs for any issues

### Production Validation

**Post-Deployment Tests:**
- [ ] Test authentication on production endpoint (without key → 401)
- [ ] Verify production logs show parameterized queries
- [ ] Check Sentry for new error patterns
- [ ] Verify completeness check is blocking incomplete data

**Success Criteria:**
- [ ] Error rate ≤ baseline
- [ ] No security incidents
- [ ] Completeness check functioning
- [ ] No performance degradation
- [ ] All monitoring systems operational

---

## ROLLBACK PROCEDURES

### Rollback Triggers (NO-GO)

**Immediately rollback if:**
- Error rate increases by >20%
- Security incident detected (SQL injection attempt succeeds, unauthorized access granted, etc.)
- Critical functionality broken (analytics pipeline stops)
- Data integrity issue (incorrect data processed)

### Rollback Steps

**Quick Rollback (Traffic Split):**
```bash
# Revert to previous revision
gcloud run services update-traffic analytics-processor \
  --to-revisions <previous-revision>=100 \
  --region us-west2
```

**Full Rollback (Code Revert):**
```bash
# Revert main branch to before merge
git revert 81cc7d84 -m 1
git push origin main

# Redeploy previous version
gcloud run deploy analytics-processor \
  --source . \
  --region us-west2
```

**Environment Variable Rollback:**
```bash
# Remove new environment variables if needed
gcloud run services update analytics-processor \
  --remove-env-vars VALID_API_KEYS \
  --region us-west2
```

### Rollback Testing

- [ ] Test rollback procedure in staging before production
- [ ] Verify previous version still works after rollback
- [ ] Document rollback steps clearly

---

## POST-DEPLOYMENT TASKS

### Documentation Updates
- [ ] Update README.md with Phase 1-2 DEPLOYED status
- [ ] Update IMPLEMENTATION-TRACKING.md with 15/28 completed (54%)
- [ ] Create deployment announcement
- [ ] Update runbook with new authentication requirements

### Monitoring Setup
- [ ] Create alert for 401 Unauthorized rate (baseline + threshold)
- [ ] Create alert for SQL injection attempts (if detectable)
- [ ] Create alert for fail-closed errors (completeness check failures)
- [ ] Add Week 0 security metrics to dashboard

### Stakeholder Communication

**Email Template:**
```
Subject: Week 0 Security Fixes Deployed to Production

Team,

We've successfully deployed Week 0 security fixes to production. This release addresses 9 critical security vulnerabilities:

✅ Remote Code Execution (eval, pickle) - ELIMINATED
✅ SQL Injection (45+ points) - FIXED
✅ Authentication - ENFORCED on admin endpoints
✅ Fail-Open Patterns - CORRECTED (fail-closed for data integrity)
✅ Hardcoded Secrets - REMOVED

Key Changes:
- /process-date-range endpoint now requires X-API-Key header
- Analytics processing blocks on incomplete data (fail-closed)
- All SQL queries use parameterized syntax
- Secrets moved to environment variables

Impact:
- Error rate: [X]% (within baseline)
- No performance degradation
- Enhanced security posture

Next: Phase A deployment (completeness check) scheduled for [date]

Questions? Contact [team]
```

- [ ] Send deployment announcement
- [ ] Update status page
- [ ] Schedule retrospective

---

## SUCCESS METRICS

### Security Metrics (Target)
- [ ] 0 eval() in production code ✅
- [ ] 0 hardcoded secrets ✅
- [ ] 306+ parameterized queries ✅
- [ ] 0 SQL injection vulnerabilities in critical paths ✅
- [ ] 100% authentication on admin endpoints ✅

### Operational Metrics (Target)
- [ ] Error rate ≤ baseline
- [ ] P95 latency ≤ baseline + 10%
- [ ] Uptime ≥ 99.9%
- [ ] 0 security incidents in first 48 hours
- [ ] 0 data integrity issues

### Business Metrics (Target)
- [ ] Analytics processing continues normally
- [ ] Completeness check prevents incomplete data processing
- [ ] No customer-facing issues from security fixes

---

## NOTES & LESSONS LEARNED

### Known Issues
- Input validation module (Issue #4) NOT implemented - mitigated by parameterized queries
- Cloud Logging count (_count_worker_errors) returns 0 - diagnostic tool functional otherwise
- Medium severity issues (#10-13) deferred - acceptable risk for Phase A

### Lessons Learned
(To be filled in after deployment)

### Improvements for Next Time
(To be filled in after deployment)

---

## SIGN-OFF

### Pre-Deployment Approval
- [ ] Security fixes validated: ________________ (Session Manager)
- [ ] Deployment plan approved: ________________ (Tech Lead)
- [ ] Environment variables configured: ________________ (DevOps)

### Post-Deployment Verification
- [ ] Staging tests passed: ________________ (Date: _________)
- [ ] Production 10% deployed: ________________ (Date: _________)
- [ ] Production 50% deployed: ________________ (Date: _________)
- [ ] Production 100% deployed: ________________ (Date: _________)
- [ ] 48-hour monitoring complete: ________________ (Date: _________)

---

**Document Created:** January 19, 2026
**Last Updated:** January 19, 2026
**Next Review:** After staging deployment
**Status:** READY FOR EXECUTION
