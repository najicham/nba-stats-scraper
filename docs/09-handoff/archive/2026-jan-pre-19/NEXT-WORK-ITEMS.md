# Next Work Items - Priority Queue

**Date:** January 19, 2026
**Status:** Active Task List
**Context:** After Week 0 deployment prep completion

---

## 🔥 IMMEDIATE (Today - January 19)

### 1. Daily Orchestration Validation
**Priority:** CRITICAL
**Estimated Time:** 30 minutes
**Tasks:**
- [ ] Check today's predictions generated (game_date = 2026-01-19)
- [ ] Verify BettingPros props scraped for today
- [ ] Check gamebook completeness for yesterday (Jan 18)
- [ ] Verify Phase 3, 4, 5 ran successfully this morning
- [ ] Check prediction quality scores (>70% threshold)
- [ ] Verify no critical errors in last 6 hours

**Scripts to Run:**
```bash
# Check today's predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY game_date"

# Check scheduler job history
gcloud scheduler jobs list --location=us-west2 --format="table(name,lastAttemptTime,state)"
```

### 2. Week 0 Staging Deployment
**Priority:** HIGH
**Estimated Time:** 2-3 hours
**Tasks:**
- [ ] Review deployment guide one more time
- [ ] Create .env file with all secrets
- [ ] Obtain BettingPros API key (rotate if needed)
- [ ] Generate analytics API keys
- [ ] Run week0_setup_secrets.sh
- [ ] Deploy to staging: week0_deploy_staging.sh
- [ ] Run smoke tests: week0_smoke_tests.sh
- [ ] Monitor staging for first hour

**Blockers:** Need BettingPros API key, Sentry DSN

---

## 🎯 SHORT-TERM (This Week)

### 3. Week 0 Production Deployment
**Priority:** HIGH
**Estimated Time:** 8-12 hours (spread over days)
**Prerequisites:**
- Staging validated for 24 hours
- All smoke tests passing
- Secrets rotated (BettingPros, Sentry)

**Tasks:**
- [ ] Review 24-hour staging metrics
- [ ] Rotate exposed secrets
- [ ] Schedule production deployment window
- [ ] Execute canary deployment (10% → 50% → 100%)
- [ ] Monitor at each phase (4 hours each)
- [ ] Post-deployment validation

### 4. Daily Orchestration Improvements
**Priority:** MEDIUM-HIGH
**Estimated Time:** 4-6 hours

**Based on docs/02-operations/daily-monitoring.md findings:**

**4a. Improve Morning Orchestration Reliability**
- [ ] Add retry logic to Phase 3 same-day processor
- [ ] Add quality checks before Phase 5 triggers
- [ ] Create automated recovery for failed Phase 4
- [ ] Add Slack alerts for prediction quality < 70%

**4b. Gamebook Backfill Automation**
- [ ] Create auto-backfill trigger when yesterday incomplete
- [ ] Add morning validation: "Are yesterday's gamebooks complete?"
- [ ] Automate: If incomplete → trigger backfill → reprocess Phase 4 → regenerate predictions

**4c. Prediction Quality Monitoring**
- [ ] Add daily report: prediction count vs expected
- [ ] Alert if predictions < 1500 on game days
- [ ] Dashboard showing quality score trends
- [ ] Automated diagnosis when quality drops

### 5. Complete Input Validation Implementation (Week 0 Deferred)
**Priority:** MEDIUM
**Estimated Time:** 6-8 hours

**What was deferred from Week 0:**
- Input validation library created (`shared/utils/validation.py`)
- Not yet integrated into all endpoints

**Tasks:**
- [ ] Integrate validation into Phase 3 analytics endpoints
- [ ] Add validation to Phase 4 precompute endpoints
- [ ] Add validation to prediction endpoints
- [ ] Create validation tests
- [ ] Update documentation

**Files to update:**
- data_processors/analytics/main_analytics_service.py
- data_processors/precompute/main_precompute_service.py
- predictions/coordinator/coordinator.py
- predictions/worker/main.py

### 6. Cloud Logging Enhancement (Week 0 Partial)
**Priority:** MEDIUM
**Estimated Time:** 4-6 hours

**Current state:** Cloud Logging client instantiated but not fully used

**Tasks:**
- [ ] Replace `_count_worker_errors()` stub with real Cloud Logging query
- [ ] Add structured logging to all processors
- [ ] Create log-based metrics for security events
- [ ] Add log-based alerts for SQL injection attempts
- [ ] Implement log sampling for high-volume endpoints

**Files to update:**
- bin/monitoring/diagnose_prediction_batch.py
- shared/logging/ (create logging utilities)

---

## 📈 MEDIUM-TERM (Next 2 Weeks)

### 7. Automated Daily Health Checks
**Priority:** MEDIUM
**Estimated Time:** 3-4 hours

**Enhance bin/monitoring/quick_pipeline_check.sh:**
- [ ] Add Week 0 security checks (401 counts, SQL warnings)
- [ ] Add prediction quality validation
- [ ] Add gamebook completeness check
- [ ] Output to dashboard (not just email)
- [ ] Add trend analysis (compare to yesterday)

### 8. Prediction Pipeline Optimization
**Priority:** MEDIUM
**Estimated Time:** 8-12 hours

**Based on recent quality issues:**

**8a. Quality Score Improvements**
- [ ] Investigate quality score < 70% root causes
- [ ] Add feature completeness checks before prediction
- [ ] Improve error messages when quality low
- [ ] Add automatic data validation before ML models run

**8b. Same-Day Prediction Reliability**
- [ ] Add dependency checks (Phase 3 → Phase 4 → Phase 5)
- [ ] Implement intelligent retry (only retry if data changed)
- [ ] Add prediction staleness detection
- [ ] Create prediction regeneration on demand

### 9. Monitoring & Alerting Enhancements
**Priority:** MEDIUM
**Estimated Time:** 6-8 hours

**Tasks:**
- [ ] Create Slack alert for 401 spike (potential attack)
- [ ] Alert when prediction count < expected
- [ ] Alert when gamebooks incomplete at 10 AM ET
- [ ] Dashboard for Week 0 security metrics
- [ ] Alert for SQL query performance degradation

### 10. Documentation Consolidation
**Priority:** LOW-MEDIUM
**Estimated Time:** 4-6 hours

**Too many handoff docs - need organization:**
- [ ] Archive old session handoffs (move to docs/09-handoff/archive/)
- [ ] Create master index of active documentation
- [ ] Consolidate Week 0 docs into single source
- [ ] Update README with deployment instructions
- [ ] Create runbook index

---

## 🔮 FUTURE (Nice to Have)

### 11. Security Hardening Phase 2 (Medium Severity Issues)
**Priority:** LOW-MEDIUM
**Estimated Time:** 12-16 hours

**Week 0 deferred issues #10-13:**
- Issue #10: Rate limiting on public endpoints
- Issue #11: CORS configuration hardening
- Issue #12: Secret rotation automation
- Issue #13: Audit logging for admin actions

### 12. Testing Infrastructure
**Priority:** LOW-MEDIUM
**Estimated Time:** 8-12 hours

**Tasks:**
- [ ] Add integration tests for security fixes
- [ ] Create test suite for authentication
- [ ] Add SQL injection prevention tests
- [ ] Create regression test suite
- [ ] Add smoke test to CI/CD

### 13. Performance Optimization
**Priority:** LOW
**Estimated Time:** Variable

**Based on monitoring data:**
- [ ] Optimize BigQuery query costs
- [ ] Add caching for repeated queries
- [ ] Optimize ML feature extraction
- [ ] Reduce Cloud Run cold starts
- [ ] Database connection pooling audit

### 14. Disaster Recovery Planning
**Priority:** LOW
**Estimated Time:** 8-12 hours

**Tasks:**
- [ ] Document rollback procedures for each service
- [ ] Create backup/restore procedures
- [ ] Test disaster recovery scenarios
- [ ] Create incident response playbook
- [ ] Set up automated backups for critical data

### 15. Developer Experience
**Priority:** LOW
**Estimated Time:** 6-8 hours

**Tasks:**
- [ ] Create local development setup guide
- [ ] Add pre-commit hooks for security checks
- [ ] Create deployment CLI tool
- [ ] Add VS Code debugging configurations
- [ ] Create development Docker containers

---

## 📊 Prioritization Matrix

**Critical Path (This Week):**
1. Daily Orchestration Validation (30 min) ← DO NOW
2. Week 0 Staging Deployment (2-3 hours)
3. Monitor Staging 24 hours
4. Week 0 Production Deployment (phased, 2-3 days)

**High Value, Quick Wins:**
- Daily health check enhancement (3-4 hours)
- Gamebook auto-backfill (4-6 hours)
- Prediction quality monitoring (4-6 hours)

**High Value, Longer Term:**
- Input validation integration (6-8 hours)
- Cloud Logging enhancement (4-6 hours)
- Security Phase 2 (12-16 hours)

**Nice to Have:**
- Documentation consolidation
- Testing infrastructure
- Developer experience improvements

---

## 🎯 Recommended Next Session Focus

**If you have 1 hour:**
→ Daily Orchestration Validation + Check today's predictions

**If you have 3 hours:**
→ Week 0 Staging Deployment (full cycle with tests)

**If you have 6 hours:**
→ Staging Deployment + Daily Orchestration Improvements

**If you have a full day:**
→ Staging → Monitor → Start Production Deployment

---

**Last Updated:** January 19, 2026, 8:50 PM PST
**Next Review:** After Week 0 production deployment complete
