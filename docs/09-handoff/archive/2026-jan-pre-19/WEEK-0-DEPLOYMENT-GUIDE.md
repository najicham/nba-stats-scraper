# Week 0 Security Fixes - Deployment Guide

**Created:** January 19, 2026
**Last Updated:** January 19, 2026
**Git Branch:** `week-0-security-fixes`
**Git Tag:** `week-0-security-complete` (commit 428a9676)

---

## 🎯 Overview

This guide provides step-by-step instructions for deploying the Week 0 security fixes to staging and production environments.

**What's Being Deployed:**
- ✅ 8 critical/high security issues fixed
- ✅ 334 parameterized SQL queries
- ✅ Input validation library
- ✅ Authentication on analytics endpoints
- ✅ Fail-closed error handling
- ✅ Real Cloud Logging (partial)

**Services Affected:**
- Phase 1: Scrapers (BettingPros)
- Phase 2: Raw Processors (SQL fixes)
- Phase 3: Analytics Processors (Authentication + SQL fixes)
- Phase 4: Precompute (ML Feature Store)
- Phase 5: Predictions (Worker + Coordinator)

---

## 📋 Pre-Deployment Checklist

### ✅ Code Readiness

- [x] Week 0 branch pushed to GitHub: `origin/week-0-security-fixes`
- [x] Git tag created: `week-0-security-complete`
- [x] All 8 security issues fixed and verified
- [x] Documentation complete
- [ ] Create PR to merge Week 0 branch to main (OR deploy from branch)

### 🔑 Secrets Preparation

**CRITICAL:** These secrets MUST be set before deployment:

1. **BettingPros API Key** (was hardcoded, now removed)
   - Obtain from: BettingPros dashboard
   - Recommended: Rotate the exposed key before production
   - Old key: `CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh` (ROTATE)

2. **Sentry DSN** (was hardcoded, now removed)
   - Obtain from: Sentry dashboard
   - Recommended: Rotate before production (less critical)

3. **Analytics API Keys** (NEW - required for authentication)
   - Generate with: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
   - Create at least 1 key (can create multiple for rotation)
   - Store securely (these grant access to analytics endpoints)

4. **Degraded Mode Flag** (optional)
   - Default: `ALLOW_DEGRADED_MODE=false`
   - Only set to `true` in emergency situations

### 📁 Required Files

Ensure you have:
- [ ] `.env` file with all secrets (DO NOT commit)
- [ ] Deployment scripts: `bin/deploy/week0_*.sh`
- [ ] This guide: `docs/09-handoff/WEEK-0-DEPLOYMENT-GUIDE.md`
- [ ] Checklist: `docs/08-projects/.../PHASE-A-DEPLOYMENT-CHECKLIST.md`

---

## 🚀 Staging Deployment (Step-by-Step)

### Step 1: Prepare Environment

```bash
# 1. Clone/pull the repository
git fetch origin
git checkout week-0-security-fixes
git pull origin week-0-security-fixes

# 2. Verify you're on the right commit
git log -1
# Should show: "docs: Add Week 0 deployment status and GitHub push summary" (35634ca9)
# Or later commits on this branch

# 3. Set your GCP project
gcloud config set project <YOUR_PROJECT_ID>

# 4. Authenticate (if needed)
gcloud auth login
gcloud auth application-default login
```

### Step 2: Create .env File

Create a `.env` file in the project root with your secrets:

```bash
# .env (DO NOT COMMIT THIS FILE)
BETTINGPROS_API_KEY=<your-bettingpros-key>
SENTRY_DSN=<your-sentry-dsn>
ANALYTICS_API_KEY_1=<generate-with: python -c 'import secrets; print(secrets.token_urlsafe(32))'>
# Optional: Additional API keys for rotation
# ANALYTICS_API_KEY_2=<another-key>
# ANALYTICS_API_KEY_3=<another-key>
```

**Generate API keys:**
```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
# Example output: kQ7vR2xM9pL8nB6jH5tY3wZ1cV4sA0dF2eG7hI9kJ1m

# Generate 3 keys for rotation
for i in {1..3}; do
    echo "ANALYTICS_API_KEY_$i=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
done
```

### Step 3: Setup Secrets in GCP

Run the secret setup script:

```bash
chmod +x bin/deploy/week0_setup_secrets.sh
./bin/deploy/week0_setup_secrets.sh
```

**What this does:**
- Creates/updates `bettingpros-api-key` in Secret Manager
- Creates/updates `sentry-dsn` in Secret Manager
- Creates/updates `analytics-api-keys` in Secret Manager (comma-separated list)

**Verify secrets created:**
```bash
gcloud secrets list | grep -E "bettingpros|sentry|analytics"
```

### Step 4: Grant Secret Access (If Needed)

If deploying for the first time, grant Cloud Run service account access to secrets:

```bash
# Get your default compute service account
PROJECT_ID=$(gcloud config get-value project)
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Or use a custom service account if you have one
# SERVICE_ACCOUNT="<your-service-account>@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant access to secrets
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

### Step 5: Deploy to Staging

**Option A: Dry run first (recommended)**
```bash
chmod +x bin/deploy/week0_deploy_staging.sh
./bin/deploy/week0_deploy_staging.sh --dry-run
# Review the deployment plan
```

**Option B: Deploy for real**
```bash
./bin/deploy/week0_deploy_staging.sh
# This will deploy all 6 affected services
# Deployment takes ~10-15 minutes
```

**What gets deployed:**
1. nba-phase1-scrapers (with BETTINGPROS_API_KEY)
2. nba-phase2-raw-processors (SQL fixes)
3. nba-phase3-analytics-processors (Authentication + SQL fixes)
4. nba-phase4-precompute-processors (ML feature store changes)
5. prediction-worker (validation changes)
6. prediction-coordinator (updated dependencies)

### Step 6: Run Smoke Tests

```bash
# Get one of your analytics API keys from .env
source .env

chmod +x bin/deploy/week0_smoke_tests.sh
./bin/deploy/week0_smoke_tests.sh $ANALYTICS_API_KEY_1
```

**Expected results:**
- ✅ All health endpoints return 200
- ✅ Analytics endpoint returns 401 without API key
- ✅ Analytics endpoint accepts valid API key
- ✅ Analytics endpoint rejects invalid API key
- ✅ Environment variables are set
- ✅ Secrets are accessible

**If tests fail:**
- Check service logs: `gcloud logging read 'severity>=ERROR' --freshness=1h --limit=50`
- Verify secrets: `gcloud secrets list`
- Check service status: `gcloud run services list --region=us-west2`

### Step 7: Monitor Staging (24 Hours)

Monitor these metrics for 24 hours before production deployment:

```bash
# 1. Check error rate (should not spike)
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --freshness=1h --limit=20

# 2. Check 401 unauthorized attempts (should be > 0 if auth working)
gcloud logging read 'resource.type="cloud_run_revision" \
  AND httpRequest.status=401' \
  --freshness=1h --limit=10

# 3. Check for SQL injection attempts (should be 0)
gcloud logging read 'resource.type="cloud_run_revision" \
  AND (textPayload=~"SQL injection" OR textPayload=~"malicious")' \
  --freshness=1h

# 4. Check service health
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-worker prediction-coordinator; do
  echo "=== $svc ===" curl -s "https://$svc-<hash>.a.run.app/health" | jq '.status'
done
```

**What to look for:**
- ✅ Error rate ≤ baseline (no spike from security fixes)
- ✅ 401 Unauthorized logs present (auth working)
- ✅ No SQL injection warnings
- ✅ No environment variable errors
- ✅ Services responding to health checks

---

## 🏭 Production Deployment

### Prerequisites

- [ ] Staging running successfully for 24+ hours
- [ ] All smoke tests passing
- [ ] No critical errors in staging logs
- [ ] Secrets rotated (BettingPros, Sentry)
- [ ] Stakeholders notified

### Production Deployment Strategy: Canary

**DO NOT deploy 100% immediately.** Use a phased approach:

#### Phase 1: 10% Traffic (4 hours)

```bash
# Deploy with traffic split
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --tag=week0 \
  --traffic=week0=10,LATEST=90

# Monitor for 4 hours
# Check error rate, latency, auth logs
```

**Metrics to watch:**
- Error rate ≤ baseline
- p99 latency ≤ baseline + 10%
- 401 count > 0 (auth working)
- No security incidents

#### Phase 2: 50% Traffic (4 hours)

If Phase 1 successful:

```bash
gcloud run services update-traffic nba-phase3-analytics-processors \
  --region=us-west2 \
  --to-revisions=week0=50,LATEST=50

# Monitor for 4 hours
```

#### Phase 3: 100% Traffic (48 hours)

If Phase 2 successful:

```bash
gcloud run services update-traffic nba-phase3-analytics-processors \
  --region=us-west2 \
  --to-latest

# Monitor for 48 hours
```

**Repeat for all services:**
1. nba-phase1-scrapers
2. nba-phase2-raw-processors
3. nba-phase4-precompute-processors
4. prediction-worker
5. prediction-coordinator

### Rollback Plan

If issues detected:

```bash
# Quick rollback - revert to previous revision
gcloud run services update-traffic <SERVICE_NAME> \
  --region=us-west2 \
  --to-revisions=LATEST=0,<PREVIOUS_REVISION>=100

# Or full rollback - redeploy previous code
git checkout main  # or previous stable commit
./bin/deploy/week0_deploy_staging.sh  # adjust for production
```

---

## 📊 Post-Deployment Validation

### Within 7 Days

- [ ] Rotate exposed secrets
  - [ ] BettingPros API key (critical)
  - [ ] Sentry DSN (recommended)
- [ ] Monitor security logs for anomalies
- [ ] Update alert thresholds if needed
- [ ] Document any issues encountered
- [ ] Archive deployment logs

### Security Validation Queries

```bash
# 1. Verify no eval() in production
gcloud logging read 'textPayload=~"eval" OR textPayload=~"exec"' \
  --freshness=7d --limit=10
# Expected: 0 results

# 2. Verify parameterized queries
gcloud logging read 'textPayload=~"@game_id" OR textPayload=~"@game_date"' \
  --freshness=1d --limit=5
# Expected: Multiple results showing parameterized queries

# 3. Verify authentication working
gcloud logging read 'httpRequest.status=401 \
  AND resource.labels.service_name="nba-phase3-analytics-processors"' \
  --freshness=7d --limit=10
# Expected: Some 401s (unauthorized access attempts)

# 4. Check for completeness check errors (fail-closed working)
gcloud logging read 'textPayload=~"is_error_state" OR textPayload=~"incomplete"' \
  --freshness=7d --limit=10
```

---

## 🚨 Troubleshooting

### Issue: Service won't start - "Secret not found"

**Solution:**
```bash
# Verify secret exists
gcloud secrets describe <secret-name>

# Verify service account has access
gcloud secrets get-iam-policy <secret-name>

# Grant access if missing
gcloud secrets add-iam-policy-binding <secret-name> \
  --member="serviceAccount:<SERVICE_ACCOUNT>" \
  --role="roles/secretmanager.secretAccessor"
```

### Issue: Analytics returns 401 even with valid key

**Solution:**
```bash
# Check environment variable is set
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"

# Verify secret value
gcloud secrets versions access latest --secret="analytics-api-keys"

# Check logs for auth errors
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" \
  AND textPayload=~"auth" \
  AND severity>=WARNING' --freshness=1h
```

### Issue: BettingPros API calls failing

**Solution:**
```bash
# Verify BETTINGPROS_API_KEY is set
gcloud run services describe nba-phase1-scrapers \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"

# Test the key manually
curl "https://api.bettingpros.com/v3/..." \
  -H "x-api-key: <YOUR_KEY>"

# Check if key needs rotation
# If old exposed key, rotate via BettingPros dashboard
```

### Issue: High error rate after deployment

**Solution:**
```bash
# Check error logs
gcloud logging read 'severity>=ERROR' --freshness=1h --limit=50

# Look for patterns (SQL, auth, etc.)
gcloud logging read 'severity>=ERROR AND textPayload=~"SQL"' --freshness=1h

# Rollback if critical
gcloud run services update-traffic <SERVICE> \
  --to-revisions=LATEST=0,<PREVIOUS>=100
```

---

## 📚 Related Documentation

- **Validation Results:** `docs/09-handoff/WEEK-0-VALIDATION-RESULTS.md`
- **Quick Reference:** `docs/09-handoff/WEEK-0-QUICK-REFERENCE.md`
- **Master Handoff:** `docs/09-handoff/WEEK-0-SESSION-MANAGER-HANDOFF.md`
- **Deployment Checklist:** `docs/08-projects/.../PHASE-A-DEPLOYMENT-CHECKLIST.md`
- **Deployment Status:** `docs/09-handoff/WEEK-0-DEPLOYMENT-STATUS.md`

---

## ✅ Success Criteria

Deployment is considered successful when:

- [ ] All services deployed without errors
- [ ] All smoke tests passing
- [ ] 401s present in logs (auth working)
- [ ] No SQL injection warnings
- [ ] Error rate ≤ baseline
- [ ] p99 latency ≤ baseline + 10%
- [ ] No security incidents detected
- [ ] Monitoring shows expected behavior for 24+ hours

---

**Last Updated:** January 19, 2026
**Version:** 1.0
**Maintainer:** Deployment Team
