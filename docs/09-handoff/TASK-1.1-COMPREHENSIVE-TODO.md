# Task 1.1 Health Endpoints - Comprehensive TODO List

**Created:** January 18, 2026
**Status:** Implementation Complete, Testing & Deployment Pending
**Review Status:** 🔴 NEEDS REVIEW

This document contains EVERYTHING that needs to be done to fully complete Task 1.1. Items are organized by priority and category.

---

## 🚨 CRITICAL - Must Do Before Any Deployment

### Code Validation

- [ ] **TEST-001**: Verify shared module imports locally
  ```bash
  cd /home/naji/code/nba-stats-scraper
  python -c "from shared.endpoints.health import HealthChecker, create_health_blueprint; print('✅ Imports work')"
  ```
  **Risk:** Import errors will cause service startup failures
  **Time:** 2 minutes

- [ ] **TEST-002**: Test HealthChecker instantiation
  ```python
  from shared.endpoints.health import HealthChecker
  checker = HealthChecker(project_id='nba-props-platform', service_name='test')
  print(checker.run_all_checks())
  ```
  **Risk:** Runtime errors in HealthChecker constructor
  **Time:** 5 minutes

- [ ] **TEST-003**: Run smoke tests locally (import checks only)
  ```bash
  pytest tests/smoke/test_health_endpoints.py::test_shared_health_module_importable -v
  pytest tests/smoke/test_health_endpoints.py::test_critical_dependencies_importable -v
  ```
  **Risk:** Test failures indicate broken implementation
  **Time:** 5 minutes

### Dependency Verification

- [ ] **DEP-001**: Check if coordinator needs new dependencies
  - Current: Has BigQuery
  - Added checks: BigQuery (already has it)
  - **Action:** ✅ No changes needed
  - **Time:** 2 minutes

- [ ] **DEP-002**: Check if MLB worker needs new dependencies
  - Current: Has BigQuery, GCS
  - Added checks: BigQuery, GCS (already has them)
  - **Action:** ✅ No changes needed
  - **Time:** 2 minutes

- [ ] **DEP-003**: Check if admin dashboard needs new dependencies
  - Current: Has BigQuery, Firestore
  - Added checks: BigQuery, Firestore (already has them)
  - **Action:** ✅ No changes needed
  - **Time:** 2 minutes

- [ ] **DEP-004**: Check if analytics processor needs new dependencies
  - Current: Has BigQuery
  - Added checks: BigQuery (already has it)
  - **Action:** ✅ No changes needed
  - **Time:** 2 minutes

- [ ] **DEP-005**: Check if precompute processor needs new dependencies
  - Current: Has BigQuery
  - Added checks: BigQuery (already has it)
  - **Action:** ✅ No changes needed
  - **Time:** 2 minutes

### Permission Verification

- [ ] **PERM-001**: Verify GCS bucket permissions for MLB worker
  - Bucket: `nba-scraped-data`
  - Required: `storage.objects.get`, `storage.objects.list`
  - Test: Health check tries to list blobs
  - **Risk:** 403 Forbidden will mark service as unhealthy
  - **Time:** 5 minutes

- [ ] **PERM-002**: Verify Firestore permissions for admin dashboard
  - Collection: `_health_check` (system collection)
  - Required: `datastore.entities.get`
  - Test: Health check tries to read collection
  - **Risk:** 403 Forbidden will mark service as unhealthy
  - **Time:** 5 minutes

- [ ] **PERM-003**: Verify BigQuery permissions for all services
  - Required: `bigquery.jobs.create` (for SELECT 1)
  - Should work: All services already query BigQuery
  - **Risk:** Low (existing functionality)
  - **Time:** 5 minutes

### Code Issues to Fix

- [ ] **CODE-001**: Fix placeholder URLs in smoke test
  - File: `tests/smoke/test_health_endpoints.py`
  - Lines: 30-45
  - Issue: URLs contain "XXXXX" placeholder
  - **Action:** Get real service URLs or make them configurable
  - **Time:** 10 minutes

- [ ] **CODE-002**: Review NBA Worker migration strategy
  - File: `predictions/worker/health_checks.py` (existing, comprehensive)
  - File: `predictions/worker/worker.py` (needs review)
  - Question: Should we migrate worker to use shared module or keep existing?
  - **Decision needed:** Keep separate (worker has custom model checks) or migrate?
  - **Time:** 30 minutes review + potential migration

- [ ] **CODE-003**: Add error handling for lazy client initialization
  - Issue: If BigQuery client fails to initialize, error is unclear
  - Files: `shared/endpoints/health.py` lines 95-115
  - **Action:** Add try/except with clear error messages
  - **Time:** 15 minutes

- [ ] **CODE-004**: Add logging for health check execution
  - Current: Only errors are logged
  - Needed: Log when checks start, duration, results
  - **Benefit:** Easier debugging of slow health checks
  - **Time:** 20 minutes

---

## ⚠️ HIGH PRIORITY - Do Before Production

### Local Testing

- [ ] **LOCAL-001**: Test coordinator locally
  ```bash
  cd predictions/coordinator
  export GCP_PROJECT_ID=nba-props-platform
  python coordinator.py
  # In another terminal:
  curl localhost:8080/health
  curl localhost:8080/ready
  ```
  **Expected:** Both return 200, /ready shows check details
  **Time:** 10 minutes

- [ ] **LOCAL-002**: Test MLB worker locally
  ```bash
  cd predictions/mlb
  export GCP_PROJECT_ID=nba-props-platform
  export MLB_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/...
  python worker.py
  curl localhost:8080/health
  curl localhost:8080/ready
  ```
  **Time:** 10 minutes

- [ ] **LOCAL-003**: Test admin dashboard locally
  ```bash
  cd services/admin_dashboard
  export GCP_PROJECT_ID=nba-props-platform
  export ADMIN_DASHBOARD_API_KEY=test-key
  python main.py
  curl localhost:8080/health
  curl localhost:8080/ready
  ```
  **Time:** 10 minutes

- [ ] **LOCAL-004**: Test analytics processor locally
  ```bash
  cd data_processors/analytics
  export GCP_PROJECT_ID=nba-props-platform
  python main_analytics_service.py
  curl localhost:8080/health
  curl localhost:8080/ready
  ```
  **Time:** 10 minutes

- [ ] **LOCAL-005**: Test precompute processor locally
  ```bash
  cd data_processors/precompute
  export GCP_PROJECT_ID=nba-props-platform
  python main_precompute_service.py
  curl localhost:8080/health
  curl localhost:8080/ready
  ```
  **Time:** 10 minutes

### Error Scenario Testing

- [ ] **ERROR-001**: Test with missing environment variables
  - Remove required env var, verify /ready returns 503
  - Verify error message is clear
  - **Time:** 10 minutes

- [ ] **ERROR-002**: Test with BigQuery unavailable
  - Mock BigQuery failure, verify /ready returns 503
  - Verify error details in response
  - **Time:** 15 minutes

- [ ] **ERROR-003**: Test with GCS bucket not accessible
  - Mock GCS failure, verify /ready returns 503
  - **Time:** 10 minutes

- [ ] **ERROR-004**: Test timeout behavior
  - Mock slow dependency (>2s), verify timeout works
  - Verify overall timeout (5s) is respected
  - **Time:** 15 minutes

### Staging Deployment

- [ ] **STAGE-001**: Deploy coordinator to staging
  ```bash
  cd predictions/coordinator
  gcloud run deploy prediction-coordinator \
    --source . \
    --region us-west2 \
    --project nba-props-platform \
    --tag staging
  ```
  **Time:** 10 minutes

- [ ] **STAGE-002**: Test staging coordinator health endpoints
  ```bash
  STAGING_URL="https://staging---prediction-coordinator-xyz-uw.a.run.app"
  curl $STAGING_URL/health | jq
  curl $STAGING_URL/ready | jq
  ```
  **Expected:** /health returns 200, /ready returns 200 or 503 with details
  **Time:** 5 minutes

- [ ] **STAGE-003**: Deploy MLB worker to staging
  **Time:** 10 minutes

- [ ] **STAGE-004**: Deploy admin dashboard to staging
  **Time:** 10 minutes

- [ ] **STAGE-005**: Deploy analytics processor to staging
  **Time:** 10 minutes

- [ ] **STAGE-006**: Deploy precompute processor to staging
  **Time:** 10 minutes

- [ ] **STAGE-007**: Run smoke test suite against staging
  ```bash
  export ENVIRONMENT=staging
  export COORDINATOR_URL="https://staging---..."
  # ... configure all service URLs
  pytest tests/smoke/test_health_endpoints.py -v
  ```
  **Expected:** All tests pass
  **Time:** 15 minutes

### Monitoring Setup

- [ ] **MON-001**: Get actual service URLs for production
  ```bash
  gcloud run services list --platform=managed --region=us-west2
  ```
  **Action:** Update smoke test file with real URLs
  **Time:** 5 minutes

- [ ] **MON-002**: Create Cloud Monitoring dashboard
  - Metric: Health check duration (from /ready response)
  - Metric: Health check success rate
  - Metric: Failed checks by service
  - **Time:** 30 minutes

- [ ] **MON-003**: Set up alerts for failing health checks
  - Alert: Any service /ready returns 503 for >5 minutes
  - Alert: Health check duration >3 seconds
  - Notification: Slack + email
  - **Time:** 20 minutes

- [ ] **MON-004**: Monitor staging for 24 hours
  - Check logs for errors
  - Verify health checks aren't causing performance issues
  - Verify health checks aren't hitting BigQuery rate limits
  - **Time:** 5 minutes review + 24 hours wait

---

## 📋 MEDIUM PRIORITY - Should Do Soon

### Testing Improvements

- [ ] **TEST-004**: Add unit tests for HealthChecker class
  - Test: Each check method independently
  - Test: Parallel vs sequential execution
  - Test: Timeout behavior
  - Test: Custom checks
  - **File:** `tests/unit/test_health_checker.py` (new)
  - **Time:** 1 hour

- [ ] **TEST-005**: Add integration tests for Flask blueprint
  - Test: Blueprint registration
  - Test: Endpoint routing
  - Test: Response format validation
  - **File:** `tests/integration/test_health_endpoints.py` (new)
  - **Time:** 1 hour

- [ ] **TEST-006**: Add performance tests
  - Test: 100 concurrent health check requests
  - Test: Health check duration under load
  - Verify: No resource exhaustion
  - **Time:** 1 hour

### Documentation

- [ ] **DOC-001**: Document Cloud Run health check configuration
  ```yaml
  # Example: Configure Cloud Run to use /ready for health checks
  # Add to service.yaml or gcloud command
  ```
  **File:** Add to TASK-1.1-HEALTH-ENDPOINTS-IMPLEMENTATION.md
  **Time:** 30 minutes

- [ ] **DOC-002**: Create troubleshooting guide
  - Issue: /ready returns 503 - what to check?
  - Issue: Health check slow (>2s) - how to debug?
  - Issue: BigQuery check fails - permissions?
  - **File:** `docs/troubleshooting/health-checks.md` (new)
  - **Time:** 45 minutes

- [ ] **DOC-003**: Document expected response times
  - /health: <100ms baseline
  - /ready: <500ms typical, <5s max
  - Per-check benchmarks
  - **Time:** 20 minutes

- [ ] **DOC-004**: Create runbook for on-call engineers
  - What to do when health alerts fire
  - How to interpret health check responses
  - Common fixes for failing checks
  - **File:** `docs/runbooks/health-check-failures.md` (new)
  - **Time:** 1 hour

### Code Quality

- [ ] **QUAL-001**: Add comprehensive type hints
  - Current: Partially typed
  - Target: 100% type coverage in health.py
  - Run: `mypy shared/endpoints/health.py`
  - **Time:** 30 minutes

- [ ] **QUAL-002**: Add docstring examples
  - Current: Basic docstrings
  - Add: Usage examples for each method
  - Add: Response format examples
  - **Time:** 30 minutes

- [ ] **QUAL-003**: Add inline comments for complex logic
  - Parallel execution logic
  - Timeout handling
  - Lazy client initialization
  - **Time:** 20 minutes

- [ ] **QUAL-004**: Run linting and fix issues
  ```bash
  flake8 shared/endpoints/health.py
  black shared/endpoints/health.py
  ```
  **Time:** 10 minutes

### Performance Optimization

- [ ] **PERF-001**: Add response caching for /health endpoint
  - Current: Computes response every time
  - Optimization: Cache for 10 seconds
  - Benefit: Reduce CPU during health check storms
  - **Time:** 30 minutes

- [ ] **PERF-002**: Add circuit breaker for failing checks
  - If BigQuery check fails 5 times, skip for 60s
  - Prevents hammering failing dependencies
  - **Time:** 1 hour

- [ ] **PERF-003**: Optimize BigQuery health check
  - Current: Runs SELECT 1 every time
  - Alternative: Check last query time, skip if recent
  - **Time:** 30 minutes

---

## 🔵 LOW PRIORITY - Nice to Have

### Enhanced Functionality

- [ ] **FEAT-001**: Add custom check examples
  - Example: Check model file exists
  - Example: Check Pub/Sub topic exists
  - Example: Check API rate limit remaining
  - **File:** Add to documentation
  - **Time:** 1 hour

- [ ] **FEAT-002**: Add Pub/Sub connectivity check
  - Check: Can publish test message
  - Benefit: Catch Pub/Sub issues early
  - **Time:** 45 minutes

- [ ] **FEAT-003**: Add Secret Manager health check
  - Check: Can read test secret
  - Benefit: Catch auth/permission issues
  - **Time:** 30 minutes

- [ ] **FEAT-004**: Add model availability check (for workers)
  - Check: Model file exists and is valid
  - Check: Model can be loaded (metadata only)
  - **Specific to:** MLB worker, NBA worker
  - **Time:** 1 hour

- [ ] **FEAT-005**: Add database schema version check
  - Check: BigQuery tables exist
  - Check: Expected columns present
  - Benefit: Catch schema migration issues
  - **Time:** 1 hour

- [ ] **FEAT-006**: Add memory/disk usage checks
  - Check: Available memory >100MB
  - Check: Available disk >1GB
  - Benefit: Predict OOM errors
  - **Time:** 45 minutes

### Metrics & Analytics

- [ ] **METRIC-001**: Export health check metrics to Cloud Monitoring
  - Metric: health_check_duration_ms (by service, by check)
  - Metric: health_check_success (by service, by check)
  - **Time:** 1 hour

- [ ] **METRIC-002**: Create SLOs for health check availability
  - SLO: 99.9% of health checks succeed
  - SLO: 95% of health checks complete in <1s
  - **Time:** 30 minutes

- [ ] **METRIC-003**: Track health check trends
  - Dashboard: Health check duration over time
  - Dashboard: Health check failure rate by check type
  - Alert: Increasing duration trend
  - **Time:** 1 hour

### Security

- [ ] **SEC-001**: Security review of health endpoints
  - Question: Do health checks expose sensitive info?
  - Question: Can health checks be used for DoS?
  - Question: Should health checks require authentication?
  - **Action:** Security team review
  - **Time:** 1 hour meeting

- [ ] **SEC-002**: Add rate limiting to health endpoints
  - Limit: 100 requests/minute per IP
  - Prevent: Health check abuse
  - **Note:** Admin dashboard already has this
  - **Time:** 30 minutes

- [ ] **SEC-003**: Sanitize error messages in health responses
  - Review: Are we exposing internal details?
  - Fix: Redact sensitive info from error messages
  - **Time:** 30 minutes

### Integration

- [ ] **INT-001**: Integrate with canary deployment (Task 1.3)
  - Canary script checks /ready before promoting
  - Automatic rollback if /ready fails
  - **Dependency:** Task 1.3 must be complete
  - **Time:** 30 minutes

- [ ] **INT-002**: Configure Cloud Run liveness probes
  - Use /health for liveness
  - Configure: Check interval, timeout, failure threshold
  - **Time:** 20 minutes per service (2 hours total)

- [ ] **INT-003**: Configure Cloud Run startup probes
  - Use /ready for startup
  - Prevent: Traffic to unhealthy instances
  - **Time:** 20 minutes per service (2 hours total)

- [ ] **INT-004**: Add to CI/CD pipeline
  - Step 1: Build service
  - Step 2: Deploy to staging
  - Step 3: Run health checks ← NEW
  - Step 4: Promote to production if healthy
  - **Time:** 1 hour

### Load Testing

- [ ] **LOAD-001**: Test with 1000 requests/second
  - Tool: Apache Bench or k6
  - Target: /health endpoint
  - Verify: No errors, latency <200ms p95
  - **Time:** 1 hour

- [ ] **LOAD-002**: Test concurrent health checks
  - Scenario: 100 concurrent /ready requests
  - Verify: No connection pool exhaustion
  - Verify: All complete within timeout
  - **Time:** 1 hour

- [ ] **LOAD-003**: Cost analysis
  - Measure: BigQuery query cost per health check
  - Estimate: Monthly cost at 1 check/minute
  - Optimize: If cost >$10/month
  - **Time:** 1 hour

---

## 📅 PRODUCTION DEPLOYMENT CHECKLIST

Complete these in order when ready for production:

1. [ ] **DEPLOY-001**: All CRITICAL items complete
2. [ ] **DEPLOY-002**: All HIGH PRIORITY items complete
3. [ ] **DEPLOY-003**: Staging deployed and tested for 24+ hours
4. [ ] **DEPLOY-004**: Monitoring dashboard created
5. [ ] **DEPLOY-005**: Alerts configured
6. [ ] **DEPLOY-006**: Team notified of changes
7. [ ] **DEPLOY-007**: Runbook updated for on-call
8. [ ] **DEPLOY-008**: Rollback plan documented
9. [ ] **DEPLOY-009**: Deploy coordinator to production
10. [ ] **DEPLOY-010**: Verify coordinator health endpoints
11. [ ] **DEPLOY-011**: Monitor for 30 minutes
12. [ ] **DEPLOY-012**: Deploy remaining services (one at a time)
13. [ ] **DEPLOY-013**: Run smoke tests against production
14. [ ] **DEPLOY-014**: Update Cloud Run health check configs
15. [ ] **DEPLOY-015**: Monitor for 24 hours
16. [ ] **DEPLOY-016**: Mark Task 1.1 as COMPLETE

---

## 📊 Time Estimates

| Category | Items | Estimated Time |
|----------|-------|----------------|
| **CRITICAL** | 17 | 2.5 hours |
| **HIGH PRIORITY** | 21 | 8 hours |
| **MEDIUM PRIORITY** | 15 | 9.5 hours |
| **LOW PRIORITY** | 23 | 19 hours |
| **TOTAL** | 76 | 39 hours |

**Note:** Original estimate for Task 1.1 was 8 hours. We've completed the implementation in 4 hours, but comprehensive testing/deployment adds significant work.

---

## 🎯 Recommended Approach

### Phase 1: Validate (Do Today)
- All CRITICAL items (2.5 hours)
- Ensures nothing is broken before deployment

### Phase 2: Staging (Do This Week)
- All HIGH PRIORITY items (8 hours)
- Safe to deploy to production after this

### Phase 3: Production (Next Week)
- Production deployment checklist
- Monitor and iterate

### Phase 4: Polish (Ongoing)
- MEDIUM and LOW priority items as time allows
- Can be done after Task 1.2 and 1.3

---

## 🤔 Open Questions / Decisions Needed

1. **NBA Worker Migration**: Keep separate health checks or migrate to shared module?
   - Recommendation: Keep separate (has custom model checks)
   - Alternative: Extend shared module with custom checks

2. **Rate Limiting**: Should all health endpoints have rate limiting?
   - Current: Only admin dashboard has it
   - Recommendation: Add if we see abuse

3. **Authentication**: Should /health and /ready require auth?
   - Current: Unauthenticated (standard practice)
   - Recommendation: Keep unauthenticated, they don't expose secrets

4. **Caching**: Should we cache health check results?
   - Pro: Reduce load on dependencies
   - Con: Stale data could be misleading
   - Recommendation: Short cache (10s) for /health only

5. **Metrics**: Should we export to Cloud Monitoring?
   - Recommendation: Yes, but as LOW priority (not blocking deployment)

---

## 📞 Next Steps

**For Review Session:**
1. Go through this list together
2. Identify must-dos vs nice-to-haves
3. Decide on NBA Worker migration strategy
4. Prioritize based on time available
5. Create action plan for next session

**After Review:**
1. Update todo list with agreed priorities
2. Start with CRITICAL items
3. Work through systematically

---

**Document Status:** Draft for Review
**Created:** January 18, 2026
**Next Review:** With user in current session
