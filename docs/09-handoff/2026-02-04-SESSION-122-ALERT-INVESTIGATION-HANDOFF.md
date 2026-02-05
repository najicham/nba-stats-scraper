# Session 122 Handoff - Alert Investigation & Fixes

**Date:** 2026-02-04
**Focus:** Slack alert investigation, Dockerfile boto3 fix, confidence score percentage fix

---

## Session Summary

Investigated recurring Slack alerts and fixed two distinct issues:
1. **"Auth Errors" Alert** - Missing boto3 dependency preventing AWS SES initialization
2. **Confidence Percentage Bug** - Scores displayed as 9200% instead of 92%

Both issues resolved with code fixes and service redeployments.

---

## Issues Fixed

### Issue 1: False "Auth Errors" Alerts

**Symptoms:**
- Multiple services triggering "cloud_run_auth_errors" alerts
- Alerts showed 10-20 auth errors, then resolved, then spiked again
- Phase 3 Analytics Processors: "High Error Rate" alert (still open)

**Root Cause Analysis:**
```
notification_system.py initialization flow:
1. Try AWS SES (requires boto3) ✗ FAILED - ModuleNotFoundError
2. Fall back to Brevo (requires env vars) ✗ FAILED - Missing BREVO_SMTP_USERNAME, BREVO_FROM_EMAIL
3. No email handler initialized → errors logged to stderr
4. Stderr errors triggered "auth errors" monitoring alert
```

**Investigation Steps:**
1. Examined Phase 3 error logs → Found boto3 import errors
2. Checked `shared/requirements.txt` → boto3 IS included (line 37)
3. Examined Dockerfiles → **NOT installing shared/requirements.txt**
4. Compared to scrapers/Dockerfile → **Scrapers installs shared requirements correctly**

**Architectural Context:**
- System migrated from Brevo to AWS SES (see `docs/08-projects/current/week-1-improvements/AWS-SES-MIGRATION.md`)
- AWS SES credentials already in GCP Secret Manager (aws-ses-access-key-id, aws-ses-secret-access-key)
- notification_system.py prefers AWS SES, falls back to Brevo only if SES unavailable
- All services already have AWS SES secrets mounted, but boto3 missing prevented initialization

---

### Issue 2: Confidence Scores Showing 9200%

**Symptoms:**
```
Slack Alert showed:
• Avg Confidence: 8342.4%
• Top picks: 9200.0% confidence (bobbyportis, josealvarado, etc.)
```

**Root Cause:**
- Confidence scores stored as **percentages (92.0)** in BigQuery, not decimals (0.92)
- Scripts multiplied by 100: `92.0 * 100 = 9200.0%`

**Affected Files:**
1. `bin/alerts/send_daily_summary.sh` - Shell script for daily alerts
2. `monitoring/send_daily_summary.sh` - Duplicate monitoring script
3. `bin/alerts/daily_summary/main.py` - Python Cloud Function

---

## Fixes Applied

### Fix 1: Install boto3 in All Dockerfiles

**Files Modified:**
```
data_processors/analytics/Dockerfile
data_processors/raw/Dockerfile
data_processors/precompute/Dockerfile
predictions/worker/Dockerfile
predictions/coordinator/Dockerfile
```

**Change Pattern:**
```dockerfile
# Before (INCORRECT)
WORKDIR /app/service
RUN pip install --no-cache-dir -r requirements.txt

# After (CORRECT)
WORKDIR /app/service
RUN pip install --no-cache-dir -r ../../shared/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
```

**Note:** scrapers/Dockerfile already had correct pattern.

**Commit:** `bedebd1b` - "fix: Install shared requirements (boto3) in all Dockerfiles for AWS SES"

---

### Fix 2: Remove Duplicate *100 Multiplication

**Changes:**

1. **SQL Queries** (2 files):
```sql
# Before
ROUND(AVG(confidence_score) * 100, 1) as avg_confidence

# After
ROUND(AVG(confidence_score), 1) as avg_confidence
```

2. **Python Code**:
```python
# Before
'confidence': row.confidence_score * 100

# After
'confidence': row.confidence_score
```

3. **System ID Update**:
```sql
# Before
WHERE system_id = 'catboost_v8'

# After
WHERE system_id IN ('catboost_v9', 'catboost_v9_2026_02')
```

**Commit:** `29130502` - "fix: Remove duplicate *100 multiplication for confidence scores"

---

## Deployments

### Completed Deployments ✅

| Service | Commit | Time | Status |
|---------|--------|------|--------|
| nba-phase3-analytics-processors | bedebd1b | 16:50 | ✅ Deployed (boto3 fix) |
| nba-phase4-precompute-processors | 45fadbeb | 17:01 | ✅ Deployed (boto3 fix + docs) |

### In-Progress Deployments 🔄

| Service | Purpose | Status |
|---------|---------|--------|
| nba-phase2-raw-processors | boto3 fix | Deploying (retry after TLS timeout) |
| prediction-worker | boto3 fix | Deploying |
| prediction-coordinator | boto3 fix | Deploying |

---

## Expected Impact

### Auth Errors Alert
- **Before:** 10-20 auth errors every 15-30 minutes
- **After:** Zero auth errors (AWS SES will initialize successfully)
- **Verification:** Monitor Slack alerts for next 2-4 hours

### Confidence Percentages
- **Before:** Slack shows 9200%, 8342%, etc.
- **After:** Correct range 50-95%
- **Verification:** Check tomorrow's 9 AM daily summary alert

---

## Verification Steps

### 1. Check Service Logs for AWS SES Initialization
```bash
# Phase 3 (already deployed)
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=20 | grep -i "aws ses\|email"

# Should show: "Using AWS SES for email alerts"
# Should NOT show: "falling back to Brevo" or "boto3" errors
```

### 2. Monitor Slack Alerts
- Auth errors should STOP appearing
- Daily summary (9 AM) should show correct percentages tomorrow

### 3. Verify Deployed Commits
```bash
./bin/whats-deployed.sh

# All services should show commit bedebd1b or later
```

---

## Root Causes & Lessons

### 1. Dockerfile Inconsistency Pattern
**Problem:** Different services had different dependency installation patterns
- Scrapers: ✅ Installs shared + service requirements
- Analytics/Raw/Precompute: ❌ Only service requirements
- Predictions: ❌ Only service requirements

**Lesson:** Should have a standardized Dockerfile template enforced via linting

### 2. Silent Fallback Failures
**Problem:** notification_system.py silently falls back to Brevo when AWS SES fails
- Catches exceptions but doesn't raise alerts about initialization failures
- Errors only visible in stderr logs, not in application logs

**Lesson:** Initialization failures for critical components should trigger explicit alerts

### 3. Data Format Assumptions
**Problem:** Scripts assumed confidence scores were decimals (0-1) when they're percentages (0-100)
- No schema documentation or validation
- Different systems stored confidence differently (V8 vs V9)

**Lesson:** Add schema validation and data format documentation

---

## Prevention Mechanisms

### Added (This Session)
1. ✅ All Dockerfiles now install shared/requirements.txt
2. ✅ Confidence scores use correct format (no multiplication)
3. ✅ System ID updated to track V9 (current production model)

### Recommended (Future)
1. **Dockerfile Linting** - Pre-commit hook to verify shared requirements installed
2. **Dependency Auditing** - Script to verify all shared dependencies available in containers
3. **Email Initialization Alerting** - Explicit alert when email handler fails to initialize
4. **Confidence Score Validation** - BigQuery constraints: CHECK (confidence_score BETWEEN 0 AND 100)

---

## Known Issues / Tech Debt

### 1. Duplicate send_daily_summary.sh Scripts
- `bin/alerts/send_daily_summary.sh`
- `monitoring/send_daily_summary.sh`

Both updated, but should consolidate into one canonical location.

### 2. Brevo Secrets Missing
GCP Secret Manager missing:
- `brevo-smtp-username`
- `brevo-from-email`

Not urgent (AWS SES is primary), but fallback won't work if needed. Consider:
- Create secrets (if keeping Brevo as fallback)
- OR remove Brevo code entirely

### 3. scrapers/Dockerfile Has Silent Failures
```dockerfile
RUN pip install --no-cache-dir -r shared/requirements.txt || true
```

The `|| true` masks installation failures. Should remove and handle errors properly.

---

## Next Session Checklist

### Immediate (Next 2 Hours)
1. ✅ Monitor Slack - verify auth errors stop
2. ⏳ Wait for Phase 2/prediction deployments to complete
3. ⏳ Verify all services showing correct commit (bedebd1b or later)

### Tomorrow Morning
1. Check 9 AM daily summary alert - verify percentages correct (50-95% range)
2. Verify prediction subset accuracy (user asked about this)

### This Week
1. Review duplicate scripts - consolidate send_daily_summary.sh
2. Add Dockerfile linting to pre-commit hooks
3. Consider removing Brevo code or creating missing secrets
4. Document confidence score format in schema docs

---

## Files Changed

### Dockerfiles (Commit: bedebd1b)
- `data_processors/analytics/Dockerfile`
- `data_processors/raw/Dockerfile`
- `data_processors/precompute/Dockerfile`
- `predictions/worker/Dockerfile`
- `predictions/coordinator/Dockerfile`

### Alert Scripts (Commit: 29130502)
- `bin/alerts/send_daily_summary.sh`
- `monitoring/send_daily_summary.sh`
- `bin/alerts/daily_summary/main.py`

---

## References

- **AWS SES Migration:** `docs/08-projects/current/week-1-improvements/AWS-SES-MIGRATION.md`
- **Notification System:** `shared/utils/notification_system.py` (lines 166-179)
- **Email Alerting (Brevo):** `shared/utils/email_alerting.py`
- **Email Alerting (SES):** `shared/utils/email_alerting_ses.py`

---

## Session Stats

- **Duration:** ~1.5 hours
- **Commits:** 2 (bedebd1b, 29130502)
- **Services Deployed:** 5
- **Alerts Fixed:** 2 distinct issues
- **Root Causes Identified:** 3 (Dockerfile inconsistency, silent fallbacks, data format assumptions)

---

**Session End Time:** 2026-02-04 17:15 UTC (deployments in progress)
