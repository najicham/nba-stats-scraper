# Future Improvement Opportunities

**Created:** 2026-01-24
**Session:** 122
**Purpose:** Comprehensive list of areas to improve in future sessions

---

## Priority Legend
- **P0** - Critical / blocking issues
- **P1** - High priority / should do soon
- **P2** - Medium priority / nice to have
- **P3** - Low priority / when time permits

---

## 1. Shared Code & Deployment

### P1: Cloud Function Shared Code Duplication
**Issue:** 7 Cloud Functions have copies of `shared/` directory (~12MB, ~800 files duplicated)
**Impact:** Changes require updating multiple copies, sync drift causes bugs
**Current State:** Sync script exists but not automated

**Actions:**
- [ ] Add sync check to CI/CD pipeline
- [ ] Expand `bin/maintenance/sync_shared_utils.py` to cover all files
- [ ] Create pre-deploy hook to auto-sync before deployments
- [ ] Long-term: Package shared/ as installable module in Artifact Registry

**Files:**
- `bin/maintenance/sync_shared_utils.py`
- `orchestration/cloud_functions/*/shared/`

### P1: Missing Config Files in Cloud Functions
**Issue:** Several CFs were missing `gcp_config.py` causing startup failures
**Impact:** Production outages when CFs can't start

**Actions:**
- [ ] Audit all CFs for missing config files
- [ ] Add validation script to check CF completeness before deploy
- [ ] Document required files for each CF

### P2: Local Imports Causing Shadowing
**Issue:** `from datetime import datetime as dt` inside functions shadows module imports
**Impact:** `UnboundLocalError` at runtime

**Actions:**
- [ ] Scan codebase for similar patterns: `grep -r "from datetime import.*as" --include="*.py"`
- [ ] Add linting rule to catch this pattern
- [ ] Document this anti-pattern in coding standards

---

## 2. Testing

### P1: Test Fixture Issues
**Issue:** `test_processor_dependencies` missing `processor_name` fixture
**File:** `tests/unit/patterns/test_all_phase3_processors.py`

**Actions:**
- [ ] Fix or skip the broken test
- [ ] Review other parametrized tests for similar issues

### P1: Prediction Tests Import Order
**Issue:** Tests fail when run together due to module shadowing
**Fixed in:** Session 122 (partial)

**Actions:**
- [ ] Review all prediction tests for proper isolation
- [ ] Consider using `pytest-randomly` to catch order-dependent tests

### P2: Test Coverage Gaps
**Current:** 164 unit tests passing, unknown coverage %

**Actions:**
- [ ] Run full coverage report: `pytest --cov=shared --cov=predictions --cov-report=html`
- [ ] Identify modules with <50% coverage
- [ ] Prioritize tests for critical paths (orchestration, data loading)

### P2: Deprecation Warnings
**Issue:** 2 remaining warnings from Google protobuf library
**Impact:** Will break in Python 3.14

**Actions:**
- [ ] Monitor for protobuf library updates
- [ ] Consider pinning protobuf version if needed

### P3: Integration Test Maintenance
**Issue:** Some integration tests may be outdated or flaky

**Actions:**
- [ ] Audit integration tests for reliability
- [ ] Add retry logic for flaky external API tests
- [ ] Document which tests require network access

---

## 3. Monitoring & Observability

### P1: Slack Webhook Not Configured
**Issue:** `SLACK_WEBHOOK_URL` not set in Cloud Functions
**Impact:** No Slack alerts for health checks

**Actions:**
- [ ] Configure webhook in Cloud Functions (ops task)
- [ ] Document the configuration in runbook
- [ ] Add monitoring for missing webhook config

**Reference:** `docs/08-projects/current/session-122-morning-checkup/SLACK-WEBHOOK-CONFIGURATION.md`

### P2: Add exc_info to Error Logs
**Issue:** Many error logs don't include stack traces
**Progress:** Session 11/12 added to ~300 files, more remain

**Actions:**
- [ ] Scan for remaining `logger.error()` without `exc_info=True`
- [ ] Prioritize high-traffic code paths
- [ ] Add linting rule for new code

### P2: Cloud Logging Queries
**Issue:** R-006/R-008 alerts need Cloud Logging integration

**Actions:**
- [ ] Complete Cloud Logging query integration
- [ ] Add dashboards for common queries
- [ ] Document query patterns

### P3: Metrics & Dashboards
**Actions:**
- [ ] Create BigQuery dashboard for pipeline health
- [ ] Add latency tracking for each phase
- [ ] Set up anomaly detection for data volumes

---

## 4. Error Handling & Resilience

### P1: Circuit Breaker Improvements
**Current:** Implemented in 28 files with CircuitBreakerMixin

**Actions:**
- [ ] Add circuit breakers to remaining external API calls
- [ ] Implement per-endpoint circuit breakers for multi-endpoint services
- [ ] Add metrics for circuit breaker state changes

### P2: Replace Direct Requests with HTTP Pool
**Issue:** 22+ files use direct `requests` calls instead of pooled connections
**Impact:** Connection overhead, no retry logic

**Actions:**
- [ ] Identify all direct `requests` usage
- [ ] Migrate to `shared/clients/http_pool.py`
- [ ] Add connection pooling metrics

### P2: Retry Pattern Standardization
**Issue:** Inconsistent retry implementations across codebase

**Actions:**
- [ ] Audit retry patterns in all scrapers
- [ ] Standardize on `shared/utils/retry_with_jitter.py`
- [ ] Document retry configuration best practices

### P3: Dead Letter Queue (DLQ) Configuration
**Issue:** Some Pub/Sub topics lack DLQ for failed messages

**Actions:**
- [ ] Audit all Pub/Sub subscriptions for DLQ config
- [ ] Add DLQ to critical topics
- [ ] Create DLQ monitoring/alerting

### P3: Firestore State Persistence
**Issue:** Prediction worker doesn't persist state to Firestore

**Actions:**
- [ ] Add checkpoint persistence for long-running jobs
- [ ] Implement recovery from checkpoints
- [ ] Add state cleanup for old checkpoints

---

## 5. Code Quality

### P2: Remove Dead Code
**Progress:** Session 12 removed 72,889 lines of dead duplicate code

**Actions:**
- [ ] Continue scanning for unused imports
- [ ] Remove deprecated functions
- [ ] Clean up commented-out code

### P2: Type Annotations
**Actions:**
- [ ] Add type hints to public APIs
- [ ] Configure mypy for gradual typing
- [ ] Start with shared/ utilities

### P2: Docstring Coverage
**Actions:**
- [ ] Add docstrings to public functions
- [ ] Document complex algorithms
- [ ] Generate API docs from docstrings

### P3: Code Complexity
**Actions:**
- [ ] Run complexity analysis (radon, mccabe)
- [ ] Refactor functions with high complexity
- [ ] Set complexity limits in CI

---

## 6. Infrastructure & Deployment

### P1: CI/CD Pipeline Improvements

**Actions:**
- [ ] Add shared/ sync check to PR validation
- [ ] Add test collection check (catch import errors)
- [ ] Add Cloud Function deployment validation

### P2: Deployment Automation
**Actions:**
- [ ] Create unified deploy script for all CFs
- [ ] Add rollback capability
- [ ] Implement canary deployments for critical functions

### P2: Environment Parity
**Actions:**
- [ ] Document all required environment variables
- [ ] Create validation script for env completeness
- [ ] Add env validation to startup

### P3: Infrastructure as Code
**Actions:**
- [ ] Consider Terraform for Cloud Function management
- [ ] Document current infrastructure setup
- [ ] Create disaster recovery procedures

---

## 7. Data Quality

### P2: Data Validation
**Current:** `shared/utils/completeness_checker.py` exists

**Actions:**
- [ ] Add data freshness monitoring
- [ ] Implement row count anomaly detection
- [ ] Add schema validation for BigQuery tables

### P2: Data Lineage
**Actions:**
- [ ] Track data flow through pipeline phases
- [ ] Add correlation IDs to all data
- [ ] Create data lineage dashboard

### P3: Data Retention
**Actions:**
- [ ] Define retention policies for each table
- [ ] Implement automated cleanup
- [ ] Archive historical data to cold storage

---

## 8. Security

### P1: Credentials in Source Code
**Fixed:** Session 13 removed hardcoded proxy credentials

**Actions:**
- [ ] Scan for remaining hardcoded secrets
- [ ] Add pre-commit hook for secret detection
- [ ] Rotate any exposed credentials

### P2: IAM Audit
**Actions:**
- [ ] Review service account permissions
- [ ] Implement least-privilege access
- [ ] Document required permissions per service

### P3: Dependency Security
**Actions:**
- [ ] Enable Dependabot or similar
- [ ] Regular security audits of dependencies
- [ ] Pin dependency versions

---

## 9. Performance

### P2: Query Optimization
**Actions:**
- [ ] Review slow BigQuery queries
- [ ] Add query caching where appropriate
- [ ] Optimize table partitioning

### P2: Memory Optimization
**Actions:**
- [ ] Profile memory usage in processors
- [ ] Implement streaming for large datasets
- [ ] Right-size Cloud Function memory allocations

### P3: Cold Start Optimization
**Actions:**
- [ ] Reduce import time in Cloud Functions
- [ ] Consider minimum instances for critical functions
- [ ] Lazy load heavy dependencies

---

## 10. Documentation

### P2: Runbook Updates
**Actions:**
- [ ] Document common failure scenarios
- [ ] Add troubleshooting guides
- [ ] Create on-call playbook

### P2: Architecture Diagrams
**Actions:**
- [ ] Update pipeline flow diagrams
- [ ] Document data flow between phases
- [ ] Create deployment architecture diagram

### P3: API Documentation
**Actions:**
- [ ] Document scraper service API
- [ ] Add OpenAPI specs
- [ ] Create integration guides

---

## Quick Wins (Can Do in <30 min)

1. [ ] Run sync script and commit: `python bin/maintenance/sync_shared_utils.py`
2. [ ] Add sync check to pre-commit hook
3. [ ] Fix the `test_processor_dependencies` fixture
4. [ ] Configure SLACK_WEBHOOK_URL in Cloud Functions
5. [ ] Push any unpushed commits

---

## Session Ideas

### Short Session (~1 hour)
- Fix remaining test failures
- Add sync check to CI
- Audit one CF for completeness

### Medium Session (~2-3 hours)
- Expand sync script to all shared files
- Add circuit breakers to remaining scrapers
- Improve error logging coverage

### Long Session (~4+ hours)
- Package shared/ as installable module
- Implement comprehensive data validation
- Create deployment automation

---

## Related Documents

- [Session 11 TODO](../pipeline-resilience-improvements/SESSION-11-TODO.md)
- [Session 12 TODO](../pipeline-resilience-improvements/SESSION-12-TODO.md)
- [Shared Code Analysis](./SHARED-CODE-ANALYSIS.md)
- [Slack Webhook Config](./SLACK-WEBHOOK-CONFIGURATION.md)
