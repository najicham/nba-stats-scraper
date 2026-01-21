# Master TODO List - Health Endpoints & Phase 1 Implementation

**Last Updated:** January 18, 2026
**Status:** Implementation 40% Complete, Ready for Execution
**Based on:** Agent analysis + comprehensive codebase review

---

## 📊 Executive Summary

**Current State:**
- ✅ Health endpoint module fully implemented (shared/endpoints/health.py)
- ✅ Comprehensive test suite (47 tests passing)
- ⚠️ Services NOT YET integrated (0/6 services have endpoints registered)
- ❌ Remaining Phase 1 tasks not started (canary, jitter, pooling, Poetry)

**Critical Finding:** The last session created excellent infrastructure but **did not integrate** health endpoints into any services. The blueprint registration code was added to service files but services haven't been restarted/deployed.

---

## 🎯 COMPREHENSIVE TODO LIST

### PHASE 1.1: HEALTH ENDPOINTS (15 hours remaining)

#### Critical - Service Integration (4 hours)

- [ ] **INT-001: Verify Current Service State**
  - Check if services have been redeployed since health endpoint code was added
  - Test each service URL for /health endpoint
  - Document which services are actually running new code
  - **Files:** All services in predictions/, services/, data_processors/
  - **Time:** 30 min

- [ ] **INT-002: Complete Missing Integration - NBA Worker**
  - File: `predictions/nba/worker.py` or `predictions/worker/worker.py`
  - Find the actual NBA worker file location
  - Add HealthChecker configuration:
    ```python
    from shared.endpoints.health import create_health_blueprint, HealthChecker

    health_checker = HealthChecker(
        project_id=PROJECT_ID,
        service_name='nba-prediction-worker',
        check_bigquery=True,
        check_gcs=True,
        gcs_buckets=['nba-scraped-data'],
        custom_checks={'model_availability': create_model_check(...)},
        required_env_vars=['GCP_PROJECT_ID', 'NBA_MODEL_PATH']
    )
    app.register_blueprint(create_health_blueprint(health_checker))
    ```
  - **Time:** 30 min

- [ ] **INT-003: Add Model Availability Checks to ML Workers**
  - Update MLB worker to use model availability check
  - Update NBA worker to use model availability check
  - Files: `predictions/mlb/worker.py`, `predictions/nba/worker.py`
  - **Time:** 1 hour

- [ ] **INT-004: Deploy All Services to Staging**
  - Deploy with --tag staging for safety
  - Verify health endpoints respond
  - Run smoke tests against staging
  - Monitor for 2-4 hours
  - **Time:** 2 hours

#### High Priority - Validation (2 hours)

- [ ] **VAL-001: Local Testing**
  - Test each service locally with curl
  - Verify /health returns 200
  - Verify /ready executes checks
  - Document any configuration issues
  - **Time:** 1 hour

- [ ] **VAL-002: Production Smoke Tests**
  - Run smoke tests against production URLs
  - Verify all services have endpoints
  - Check response times (<100ms /health, <5s /ready)
  - **Time:** 30 min

- [ ] **VAL-003: Permission Verification**
  - Test GCS bucket access for MLB worker
  - Test Firestore access for admin dashboard
  - Fix any permission issues
  - **Time:** 30 min

#### Medium Priority - Integration Improvements (4 hours)

- [ ] **IMP-001: Integrate Validation System Metrics**
  - Add custom check for prediction coverage
  - Add custom check for data freshness
  - Add custom check for recent validation failures
  - Files: Create `shared/health/validation_checks.py`
  - **Time:** 2 hours
  - **Reference:** Agent analysis Section 6 (validation integration)

- [ ] **IMP-002: Cloud Run Health Check Configuration**
  - Update Cloud Run services to use /health for liveness
  - Update Cloud Run services to use /ready for startup
  - Document configuration in deployment scripts
  - **Time:** 1 hour

- [ ] **IMP-003: Add Health Metrics to BigQuery**
  - Create table: `monitoring.health_check_results`
  - Log all health check executions
  - Enable trend analysis dashboard
  - **Time:** 1 hour

#### Documentation (2 hours)

- [ ] **DOC-001: Service Integration Guide**
  - Step-by-step guide for adding health endpoints
  - Configuration examples for each service type
  - Troubleshooting common issues
  - **File:** `docs/08-projects/current/health-endpoints-implementation/INTEGRATION-GUIDE.md`
  - **Time:** 1 hour

- [ ] **DOC-002: Health Check Runbook**
  - What to do when /ready returns 503
  - How to interpret health check responses
  - Common failures and fixes
  - **File:** `docs/08-projects/current/health-endpoints-implementation/RUNBOOK.md`
  - **Time:** 1 hour

#### Low Priority - Polish (3 hours)

- [ ] **POL-001: Add Prometheus Metrics Export**
  - Create /metrics endpoint
  - Export health check duration
  - Export success/failure counts
  - **Time:** 2 hours

- [ ] **POL-002: Response Caching for /health**
  - Cache /health response for 10 seconds
  - Reduce load during health check storms
  - **Time:** 30 min

- [ ] **POL-003: Circuit Breaker for Failing Checks**
  - Skip check if failed 5 times in 60s
  - Prevent hammering failing dependencies
  - **Time:** 30 min

---

### PHASE 1.2: SMOKE TESTS CI/CD INTEGRATION (8 hours)

#### Critical - CI/CD Integration (4 hours)

- [ ] **CI-001: Create Deployment Pipeline Integration**
  - Add smoke test execution to Cloud Build
  - Run tests after each deployment
  - Block deployment on test failure
  - **File:** `.cloudbuild.yaml` or create deployment script
  - **Time:** 2 hours

- [ ] **CI-002: Service URL Discovery Automation**
  - Script to get Cloud Run URLs automatically
  - Update smoke test configuration
  - Support staging and production environments
  - **Time:** 1 hour

- [ ] **CI-003: Baseline Performance Recording**
  - Record expected response times
  - Set thresholds for alerts
  - Document in test configuration
  - **Time:** 1 hour

#### High Priority - Test Coverage (2 hours)

- [ ] **TEST-001: Add Tests for Raw Data Processors**
  - Extend smoke tests to Phase 2 services
  - Test NBAC, BDL, Odds API scrapers
  - **Time:** 1 hour

- [ ] **TEST-002: Add End-to-End Pipeline Test**
  - Test full orchestration flow
  - Verify health at each phase
  - **Time:** 1 hour

#### Medium Priority - Monitoring (2 hours)

- [ ] **MON-001: Configure Smoke Test Alerts**
  - Alert on test failures
  - Alert on performance degradation
  - Slack/email notifications
  - **Time:** 1 hour

- [ ] **MON-002: Create Test Results Dashboard**
  - Historical test pass rate
  - Response time trends
  - Service availability SLOs
  - **Time:** 1 hour

---

### PHASE 1.3: CANARY DEPLOYMENT SCRIPT (4 hours)

#### Critical - Script Creation (2 hours)

- [ ] **CAN-001: Create Canary Deploy Script**
  - **File:** `bin/deploy/canary_deploy.sh`
  - Implement 0% → 5% → 50% → 100% progression
  - Add error rate monitoring at each stage
  - Add smoke test execution between stages
  - Add automatic rollback on failures
  - **Reference:** COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md lines 902-1080
  - **Time:** 2 hours

#### High Priority - Testing & Documentation (2 hours)

- [ ] **CAN-002: Test Canary Script on Staging**
  - Deploy a test service
  - Verify traffic split works
  - Verify rollback works
  - **Time:** 1 hour

- [ ] **CAN-003: Document Canary Deployment Process**
  - Usage guide
  - Rollback procedures
  - Monitoring during deployment
  - **File:** `docs/08-projects/current/health-endpoints-implementation/CANARY-DEPLOYMENT.md`
  - **Time:** 1 hour

---

### PHASE 1.4: RETRY JITTER (12 hours)

#### Critical - Core Implementation (4 hours)

- [ ] **JITTER-001: Create Retry Decorator**
  - **File:** `shared/utils/retry_with_jitter.py`
  - Implement decorrelated jitter algorithm
  - Support configurable parameters
  - Add comprehensive docstring with examples
  - **Reference:** COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md lines 686-769
  - **Time:** 2 hours

- [ ] **JITTER-002: Write Unit Tests**
  - Test jitter randomization
  - Test exponential backoff
  - Test max attempts
  - Test exception handling
  - **File:** `tests/unit/test_retry_with_jitter.py`
  - **Time:** 2 hours

#### High Priority - Integration (8 hours)

- [ ] **JITTER-003: Update BigQuery Retries**
  - Find all bigquery_retry.py files (~5 files)
  - Replace with retry_with_jitter
  - Test with concurrent requests
  - **Time:** 3 hours

- [ ] **JITTER-004: Update Pub/Sub Retries**
  - Find all Pub/Sub publish calls
  - Add retry_with_jitter decorator
  - **Time:** 2 hours

- [ ] **JITTER-005: Update Firestore Lock Retries**
  - Update distributed_lock.py
  - Replace fixed 5s with jittered retry
  - **Time:** 1 hour

- [ ] **JITTER-006: Update External API Retries**
  - Update scraper retry logic
  - Apply to Odds API, BDL API, NBA.com
  - **Time:** 2 hours

---

### PHASE 1.5: CONNECTION POOLING (16 hours)

#### Critical - Pool Implementation (8 hours)

- [ ] **POOL-001: Create BigQuery Client Pool**
  - **File:** `shared/clients/bigquery_pool.py`
  - Thread-safe singleton pattern
  - Lazy initialization per project/thread
  - Client reuse logic
  - **Reference:** COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md lines 775-849
  - **Time:** 4 hours

- [ ] **POOL-002: Write BigQuery Pool Tests**
  - Test thread safety
  - Test client reuse
  - Test connection limits
  - **File:** `tests/unit/test_bigquery_pool.py`
  - **Time:** 2 hours

- [ ] **POOL-003: Create HTTP Session Pool**
  - **File:** `shared/clients/http_pool.py`
  - Connection pooling with urllib3
  - Retry strategy configuration
  - Thread-safe session management
  - **Reference:** COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md lines 850-899
  - **Time:** 2 hours

#### High Priority - Integration (8 hours)

- [ ] **POOL-004: Update All BigQuery Usage**
  - Phase 3 processors (~10 files)
  - Phase 4 processors (~10 files)
  - Prediction workers (~3 files)
  - Admin services (~3 files)
  - Measure connection count before/after
  - **Time:** 4 hours

- [ ] **POOL-005: Update All HTTP Scrapers**
  - Odds API scraper
  - BDL scraper
  - NBA.com scrapers (~5 files)
  - ESPN scraper
  - Measure connection count reduction
  - **Time:** 4 hours

---

### PHASE 1.6: DEPENDENCY CONSOLIDATION (20 hours)

#### Critical - Poetry Migration (12 hours)

- [ ] **POET-001: Audit All Dependencies**
  - Run dependency audit on all 50+ requirements.txt
  - Document version conflicts
  - Create conflict resolution plan
  - **Tool:** Create audit script or use Poetry's resolver
  - **Time:** 4 hours

- [ ] **POET-002: Create Complete pyproject.toml**
  - Add all dependencies with versions
  - Resolve all conflicts
  - Configure Poetry settings
  - **Time:** 4 hours

- [ ] **POET-003: Generate poetry.lock**
  - Run `poetry lock`
  - Verify all dependencies resolve
  - Test builds locally
  - **Time:** 2 hours

- [ ] **POET-004: Update All Dockerfiles**
  - Replace pip install with poetry install
  - Update all service Dockerfiles (~10 files)
  - Test builds for each service
  - **Time:** 2 hours

#### High Priority - Validation & Deployment (8 hours)

- [ ] **POET-005: Deploy to Staging**
  - Deploy all services with Poetry
  - Run full test suite
  - Monitor for dependency issues
  - **Time:** 4 hours

- [ ] **POET-006: Clean Up Old Files**
  - Archive old requirements.txt files
  - Update documentation
  - Update deployment scripts
  - **Time:** 2 hours

- [ ] **POET-007: Document New Process**
  - Poetry usage guide
  - Dependency update workflow
  - Troubleshooting guide
  - **Time:** 2 hours

---

### PHASE 1.7: MONITORING & ALERTS (8 hours)

#### Critical - Alert Configuration (4 hours)

- [ ] **ALERT-001: Configure Error Rate Alerts**
  - Worker error rate >5 in 5min
  - Phase 3 processor errors
  - Deployment failure alerts
  - **Time:** 2 hours

- [ ] **ALERT-002: Configure Deployment Alerts**
  - Canary stage failures
  - Rollback events
  - Smoke test failures
  - **Time:** 2 hours

#### High Priority - Automation (4 hours)

- [ ] **AUTO-001: Automated Daily Health Checks**
  - Create cron job for daily validation
  - Email notifications
  - Slack integration
  - **Time:** 2 hours

- [ ] **AUTO-002: Create Deployment Dashboard**
  - Cloud Monitoring dashboard
  - Deployment success rate
  - Canary durations
  - Error rate trends
  - **Time:** 2 hours

---

## 📋 VALIDATION SYSTEM INTEGRATION TASKS (10 hours)

### Critical - Integration Design (4 hours)

- [ ] **VALID-001: Create Validation Health Checks Module**
  - **File:** `shared/health/validation_checks.py`
  - Implement prediction coverage check
  - Implement data freshness check
  - Implement cross-validation check
  - **Reference:** Agent analysis Section 6
  - **Time:** 3 hours

- [ ] **VALID-002: Integrate with Health Endpoints**
  - Add validation checks to service health
  - Configure thresholds (coverage <90% = warning)
  - Test integration
  - **Time:** 1 hour

### High Priority - Unified Monitoring (4 hours)

- [ ] **VALID-003: Create Pipeline Health Dashboard**
  - Combine infrastructure + data quality metrics
  - Schedule → Raw → Analytics → Predictions flow
  - Alert on pipeline degradation
  - **Time:** 2 hours

- [ ] **VALID-004: Health-Triggered Validation**
  - Health check failures trigger targeted validation
  - Validation failures degrade health status
  - Coordinated remediation
  - **Time:** 2 hours

### Medium Priority - Enhancement (2 hours)

- [ ] **VALID-005: Validation Result Caching**
  - Cache validation results (TTL: 1 hour)
  - Avoid repeated BigQuery queries
  - Include in /ready endpoint
  - **Time:** 1 hour

- [ ] **VALID-006: Cross-Processor Validation**
  - ESPN vs BDL score consistency
  - Schedule vs game data alignment
  - **Time:** 1 hour

---

## 🎯 PRIORITY EXECUTION ORDER

### Week 1: Health Endpoints & Deployment Safety (28 hours)

**Day 1-2: Complete Health Endpoint Integration (8 hours)**
1. INT-001 through INT-004 (Service integration)
2. VAL-001 through VAL-003 (Validation)
3. Deploy to staging and verify

**Day 3: Canary Deployment (4 hours)**
1. CAN-001 through CAN-003 (Script creation and testing)

**Day 4-5: Smoke Tests & Monitoring (16 hours)**
1. CI-001 through CI-003 (CI/CD integration)
2. TEST-001 through TEST-002 (Test coverage)
3. MON-001 through MON-002 (Monitoring)
4. ALERT-001 through AUTO-002 (Alerts and automation)

### Week 2: Resilience & Dependencies (52 hours)

**Day 1-2: Retry Jitter (12 hours)**
1. JITTER-001 through JITTER-006 (All retry updates)

**Day 3-4: Connection Pooling (16 hours)**
1. POOL-001 through POOL-005 (All pooling implementation)

**Day 5-7: Poetry Migration (20 hours)**
1. POET-001 through POET-007 (Complete dependency consolidation)

**Optional: Validation Integration (10 hours)**
1. VALID-001 through VALID-006 (If time permits)

---

## 📊 COMPLETION METRICS

### Phase 1.1 Success Criteria:
- [ ] All 6 services have health/readiness endpoints
- [ ] Smoke tests pass in production
- [ ] Cloud Run health checks configured
- [ ] Response times: /health <100ms, /ready <5s
- [ ] Health check failures alert within 5 minutes

### Phase 1.2-1.7 Success Criteria:
- [ ] Canary deployments automated
- [ ] Smoke tests run on every deployment
- [ ] Jitter in all retry logic (no thundering herd)
- [ ] Connection pooling reduces resource usage by 40%+
- [ ] Single poetry.lock file, zero version conflicts
- [ ] Automated daily health checks running
- [ ] MTTR improved: 2-4 hours → 30-60 minutes
- [ ] Deployment failure rate <10%

---

## 🚨 CRITICAL BLOCKERS

1. **Service Integration**: Must complete before canary deployment can be tested
2. **Smoke Test Integration**: Required for automated deployment validation
3. **Poetry Migration**: Should complete before other changes to avoid dependency conflicts
4. **Monitoring Setup**: Need dashboards before can measure MTTR improvement

---

## 📁 FILES TO CREATE/UPDATE

### New Files to Create:
- `bin/deploy/canary_deploy.sh` - Canary deployment script
- `shared/utils/retry_with_jitter.py` - Retry decorator
- `shared/clients/bigquery_pool.py` - BigQuery connection pool
- `shared/clients/http_pool.py` - HTTP session pool
- `shared/health/validation_checks.py` - Validation integration
- `tests/unit/test_retry_with_jitter.py` - Retry tests
- `tests/unit/test_bigquery_pool.py` - Pool tests
- `docs/08-projects/current/health-endpoints-implementation/INTEGRATION-GUIDE.md`
- `docs/08-projects/current/health-endpoints-implementation/RUNBOOK.md`
- `docs/08-projects/current/health-endpoints-implementation/CANARY-DEPLOYMENT.md`

### Files to Update:
- All service files for health endpoint integration (~10 files)
- All BigQuery usage for connection pooling (~30 files)
- All HTTP scrapers for session pooling (~20 files)
- All retry logic for jitter (~25 files)
- All Dockerfiles for Poetry (~10 files)
- `.cloudbuild.yaml` or deployment scripts for CI/CD integration

---

## 📅 ESTIMATED TIMELINE

**Total Phase 1 Effort:** ~120 hours

**With 2 engineers:**
- Week 1: Health endpoints complete + canary + monitoring (28 hours)
- Week 2: Jitter + pooling + Poetry (52 hours)
- **Complete by:** February 1, 2026

**With 1 engineer:**
- Weeks 1-2: Health endpoints + canary + monitoring (28 hours)
- Weeks 3-4: Jitter + pooling (28 hours)
- Weeks 5-6: Poetry migration (20 hours)
- **Complete by:** March 1, 2026

---

## ✅ NEXT STEPS

1. **Review this TODO with user** - Confirm priorities and timeline
2. **Start with INT-001** - Verify current service state
3. **Execute Week 1 tasks** - Complete health endpoint integration
4. **Update this document** - Mark items complete as work progresses

---

**Document Version:** 2.0
**Based on:** Comprehensive agent analysis of codebase + Phase 1 plan
**Confidence Level:** HIGH - All tasks have clear implementation paths
