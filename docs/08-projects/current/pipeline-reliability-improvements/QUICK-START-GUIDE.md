# Quick Start Guide: Architectural Improvements

**Status:** Ready for Action
**Created:** January 18, 2026
**For:** Platform Engineering Team

---

## 🚨 CRITICAL: Start Here (Within 24 Hours)

### Phase 0: Security Emergency

**YOU MUST DO THIS FIRST - SECRETS ARE EXPOSED IN GIT**

```bash
cd /home/naji/code/nba-stats-scraper

# 1. Read the security section
cat docs/08-projects/current/pipeline-reliability-improvements/COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md | grep -A 200 "SECURITY BREACH"

# 2. Rotate all secrets (login to each service)
# - Odds API: https://the-odds-api.com/
# - BDL API: Email support@balldontlie.io
# - Brevo: https://www.brevo.com/
# - AWS SES: Use AWS CLI
# - Anthropic: https://console.anthropic.com/
# - Slack: Regenerate webhook

# 3. Create secrets in GCP Secret Manager
# Run the migration script from the plan

# 4. Update code to use Secret Manager
# Follow the SecretManager class implementation

# 5. Remove .env from git history
# COORDINATE WITH TEAM FIRST - this rewrites history
```

**Time:** 8 hours
**Can't skip this** - it's a security breach

---

## 📋 Week 1: Critical Fixes

### Day 1-2: Deployment Safety (20 hours)

**Goal:** Never deploy broken code to production again

**What to do:**
1. Add health endpoints to all services
2. Create smoke test suite
3. Implement canary deployment script

**Start with:** Most critical service (prediction-worker)

**Files to create:**
- `shared/endpoints/health.py`
- `tests/smoke/test_deployment.py`
- `bin/deploy/canary_deploy.sh`

**Test it:**
```bash
# Deploy to staging first
./bin/deploy/canary_deploy.sh prediction-worker staging-revision

# If successful, deploy to production
./bin/deploy/canary_deploy.sh prediction-worker production-revision
```

### Day 3: Add Jitter (12 hours)

**Goal:** Stop thundering herd during failures

**What to do:**
1. Create `shared/utils/retry_with_jitter.py`
2. Replace retry logic in BigQuery operations
3. Replace retry logic in Pub/Sub operations
4. Replace retry logic in Firestore locks

**Priority order:**
1. BigQuery retries (affects all processors)
2. Firestore lock acquisition (affects grading)
3. Pub/Sub publish retries (affects orchestration)
4. External API retries (affects scrapers)

**Test it:**
```bash
# Create test that simulates concurrent retries
pytest tests/unit/test_retry_jitter.py -v

# Verify jitter is applied
# Should see retry delays vary by ±30%
```

### Day 4: Connection Pooling (16 hours)

**Goal:** Stop creating new connections for every request

**What to do:**
1. Create `shared/clients/bigquery_pool.py`
2. Create `shared/clients/http_pool.py`
3. Update all processors to use pools
4. Update all scrapers to use HTTP pool

**Migration order:**
1. Phase 4 processors (most BigQuery usage)
2. Phase 3 processors
3. Scrapers (HTTP usage)
4. Prediction worker/coordinator

**Test it:**
```bash
# Monitor connection count before/after
# Should see dramatic reduction

# Load test to verify pooling works
```

### Day 5: Dependency Consolidation Planning (8 hours)

**Goal:** Understand current state and plan migration

**What to do:**
1. Run dependency audit script
2. Document all version conflicts
3. Create migration plan for Poetry
4. Test Poetry migration on one service

**Don't migrate everything yet** - that's Week 2

---

## 📊 Week 2: Validation & Monitoring

### Day 6-7: Finish Deployment Validation (16 hours)

**Goal:** All services have canary deployments

**What to do:**
1. Add health endpoints to remaining services
2. Expand smoke tests
3. Create monitoring dashboards for deployments
4. Document runbooks

### Day 8-9: Complete Dependency Migration (24 hours)

**Goal:** Single lock file for all dependencies

**What to do:**
1. Migrate all services to Poetry
2. Update all Dockerfiles
3. Test builds
4. Deploy to staging
5. Deploy to production (canary)

### Day 10: Monitoring Setup (16 hours)

**Goal:** Know when things break

**What to do:**
1. Set up error rate alerts
2. Set up deployment alerts
3. Create daily health check automation
4. Set up Slack notifications

---

## 🎯 Success Criteria (End of Week 2)

You should have:
- [ ] ✅ All secrets in Secret Manager (not in code)
- [ ] ✅ Health endpoints on all services
- [ ] ✅ Smoke tests running in CI/CD
- [ ] ✅ Canary deployments working
- [ ] ✅ Jitter in all retry logic
- [ ] ✅ Connection pooling implemented
- [ ] ✅ Single dependency lock file
- [ ] ✅ Alerts configured for failures

**Metrics to track:**
- Deployment failure rate should drop from 15% → <10%
- MTTR should improve from 2-4 hours → 30-60 minutes
- Resource usage should decrease (connection pooling)

---

## 📚 Where to Find Everything

### Main Documents

**Incident Analysis:**
- `incidents/2026-01-18/README.md` - Start here for context
- `incidents/2026-01-18/INCIDENT-REPORT.md` - What happened
- `incidents/2026-01-18/FIX-AND-ROBUSTNESS-PLAN.md` - Incident-specific fixes

**Architectural Analysis:**
- `COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md` - **THE MASTER PLAN**
- `RECURRING-ISSUES.md` - Historical patterns
- `FUTURE-IMPROVEMENTS.md` - Optional optimizations

### Code Examples

All code examples in the master plan can be copied directly:
- Health endpoint implementation
- Retry with jitter decorator
- BigQuery connection pool
- HTTP session pool
- Secret Manager client

### Scripts

Create these scripts as you go:
- `scripts/security/migrate_secrets_to_sm.sh`
- `scripts/dependencies/migrate_to_poetry.py`
- `bin/deploy/canary_deploy.sh`
- `scripts/daily_orchestration_check.sh`

---

## 💡 Pro Tips

### 1. Do One Thing at a Time
Don't try to implement everything at once. Follow the order in this guide.

### 2. Test in Staging First
Every change should be tested in staging before production.

### 3. Use Feature Flags
For big changes, use feature flags so you can toggle them off if needed.

### 4. Monitor Closely
After each deployment, watch logs and metrics for 30 minutes.

### 5. Document As You Go
Update runbooks and documentation as you implement changes.

### 6. Communicate
Let the team know what you're working on and when deployments happen.

---

## 🚨 If Something Goes Wrong

### Rollback Quick Reference

**Service Deployment Rollback:**
```bash
gcloud run services update-traffic SERVICE_NAME \
  --to-revisions=PREVIOUS=100 \
  --region=us-west2
```

**Canary Rollback:**
```bash
gcloud run services update-traffic SERVICE_NAME \
  --to-revisions=LATEST=100 \
  --region=us-west2
```

**Secret Manager Rollback:**
```bash
# Revert to previous version
gcloud secrets versions access VERSION_NUMBER \
  --secret=SECRET_NAME
```

**Code Rollback:**
```bash
git revert HEAD
git push
# Then redeploy
```

---

## ❓ Common Questions

### Q: Can I skip Phase 0 (Security)?
**A:** NO. This is a security breach that must be fixed immediately.

### Q: Can I do Phase 2 before Phase 1?
**A:** No. Phase 1 builds foundation for everything else.

### Q: What if I don't have 80 hours in 2 weeks?
**A:** Prioritize in this order:
1. Phase 0 (security) - MUST DO
2. Deployment validation - Prevents incidents
3. Jitter - Prevents cascading failures
4. Connection pooling - Prevents resource issues
5. Dependencies - Can wait if needed

### Q: How do I know if it's working?
**A:** Check the success criteria at end of each week. Monitor the metrics.

### Q: What if we have an incident during implementation?
**A:** Pause improvements, handle incident, then resume. Canary deployments minimize this risk.

---

## 📞 Getting Help

### Documentation
- Read the master plan: `COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md`
- Check incident docs: `incidents/2026-01-18/`
- Review recurring issues: `RECURRING-ISSUES.md`

### Code Examples
- All in the master plan
- Can be copied directly
- Tested patterns

### Questions
- Check the plan first
- Document questions for team discussion
- Create issues for blockers

---

## Next Steps

1. **TODAY:** Complete Phase 0 (security)
2. **Week 1:** Deployment validation + jitter + pooling
3. **Week 2:** Finish validation + dependencies + monitoring
4. **Week 3+:** Infrastructure hardening (see master plan)

**Start with Phase 0 security fixes - everything else can wait, but secrets can't!**

---

**Last Updated:** January 18, 2026
**Status:** Ready for Implementation
**Owner:** Platform Engineering Team
