# MLB Environment Configuration Issues - Handoff Document

**Date**: 2026-01-17
**Context**: Discovered during CatBoost V8 incident investigation (NBA)
**Priority**: HIGH - Multiple MLB services have critical configuration issues
**Audience**: MLB team/developer

---

## 🎯 EXECUTIVE SUMMARY

During investigation of the NBA CatBoost V8 incident (missing environment variable causing 3-day outage), we conducted a comprehensive audit of all Cloud Run services. This audit revealed **several critical configuration issues in MLB services** that pose production risks:

### Critical Issues Found:
1. ❌ **mlb-prediction-worker**: Missing multi-model configuration (only single model configured)
2. 🔒 **mlb-phase1-scrapers**: API keys stored as plain text (security risk)
3. ⚠️ **mlb-phase3-analytics-processors**: Missing email alerting configuration

### Impact:
- MLB predictions may not be using the intended ensemble model system
- API keys exposed in environment variables (security vulnerability)
- No email alerts on MLB pipeline failures

**Estimated Time to Fix**: 2-3 hours
**Risk Level**: HIGH (production service potentially broken + security issue)

---

## 📊 DETAILED FINDINGS

### Issue 1: mlb-prediction-worker - Missing Multi-Model Configuration

#### Current State (BROKEN)
**Service**: `mlb-prediction-worker`
**Region**: `us-west2`

**Current Environment Variables**:
```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "MLB_MODEL_PATH": "gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json",
  "MLB_PREDICTIONS_TABLE": "mlb_predictions.pitcher_strikeouts",
  "PYTHONPATH": "/app"
}
```

#### What's Wrong

**The code expects multi-system configuration** (from `/home/naji/code/nba-stats-scraper/predictions/mlb/config.py`):

```python
@dataclass
class SystemConfig:
    active_systems: str = field(default_factory=lambda: os.environ.get('MLB_ACTIVE_SYSTEMS', 'v1_baseline'))

    v1_model_path: str = field(default_factory=lambda: os.environ.get(
        'MLB_V1_MODEL_PATH',
        'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json'
    ))

    v1_6_model_path: str = field(default_factory=lambda: os.environ.get(
        'MLB_V1_6_MODEL_PATH',
        'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
    ))

    ensemble_v1_weight: float = field(default_factory=lambda: float(os.environ.get('MLB_ENSEMBLE_V1_WEIGHT', '0.3')))
    ensemble_v1_6_weight: float = field(default_factory=lambda: float(os.environ.get('MLB_ENSEMBLE_V1_6_WEIGHT', '0.5')))
```

**Missing Environment Variables**:
- `MLB_ACTIVE_SYSTEMS` - Which prediction systems to use
- `MLB_V1_MODEL_PATH` - Path to V1 baseline model
- `MLB_V1_6_MODEL_PATH` - Path to V1.6 rolling model
- `MLB_ENSEMBLE_V1_WEIGHT` - Weight for V1 in ensemble
- `MLB_ENSEMBLE_V1_6_WEIGHT` - Weight for V1.6 in ensemble

**Also Missing** (Optional but recommended):
- Email alerting configuration (BREVO_*)

#### Expected State

Based on the deployment script at `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`:

```bash
ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID}"
ENV_VARS="${ENV_VARS},MLB_MODEL_PATH=${MODEL_PATH}"  # Legacy, may be unused
ENV_VARS="${ENV_VARS},MLB_PREDICTIONS_TABLE=mlb_predictions.pitcher_strikeouts"
ENV_VARS="${ENV_VARS},PYTHONPATH=/app"

# Multi-model configuration (MISSING from current deployment)
ENV_VARS="${ENV_VARS},MLB_ACTIVE_SYSTEMS=v1_baseline,v1_6_rolling"
ENV_VARS="${ENV_VARS},MLB_V1_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json"
ENV_VARS="${ENV_VARS},MLB_V1_6_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json"
ENV_VARS="${ENV_VARS},MLB_ENSEMBLE_V1_WEIGHT=0.3"
ENV_VARS="${ENV_VARS},MLB_ENSEMBLE_V1_6_WEIGHT=0.5"

# Email alerting (if configured)
if [[ -n "${BREVO_SMTP_PASSWORD:-}" ]]; then
    ENV_VARS="${ENV_VARS},BREVO_SMTP_HOST=smtp-relay.brevo.com"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_PORT=587"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_USERNAME=98104dYOUR_EMAIL@smtp-brevo.com"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="${ENV_VARS},BREVO_FROM_EMAIL=alert@989.ninja"
    ENV_VARS="${ENV_VARS},BREVO_FROM_NAME=MLB Prediction System"
    ENV_VARS="${ENV_VARS},EMAIL_ALERTS_TO=nchammas@gmail.com"
    ENV_VARS="${ENV_VARS},EMAIL_CRITICAL_TO=nchammas@gmail.com"
fi
```

#### Impact

**Current Behavior**:
- Service likely using defaults (v1_baseline only)
- Not running ensemble predictions
- V1.6 model not being used despite being the latest

**Correct Behavior**:
- Run both V1 and V1.6 models
- Produce ensemble predictions
- Use configurable weights for ensemble

#### Fix Instructions

**Option 1: Use Deployment Script (RECOMMENDED)**

```bash
cd /home/naji/code/nba-stats-scraper

# Export Brevo password if email alerts desired
export BREVO_SMTP_PASSWORD="xsmtpsib-YOUR_SMTP_KEY_HERE"

# Run deployment script
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh

# Verify deployment
gcloud run services describe mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq '.spec.template.spec.containers[0].env'
```

**Option 2: Manual Update (if script fails)**

```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="\
MLB_ACTIVE_SYSTEMS=v1_baseline,v1_6_rolling,\
MLB_V1_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json,\
MLB_V1_6_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json,\
MLB_ENSEMBLE_V1_WEIGHT=0.3,\
MLB_ENSEMBLE_V1_6_WEIGHT=0.5"
```

**Verification Query**:

```sql
-- Check if predictions are coming from multiple systems
SELECT
  prediction_date,
  COUNT(DISTINCT system_id) as systems_count,
  STRING_AGG(DISTINCT system_id ORDER BY system_id) as systems
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE prediction_date = CURRENT_DATE()
GROUP BY prediction_date
```

**Expected**: `systems_count = 3`, `systems = "ensemble_v1,v1_6_rolling,v1_baseline"`

---

### Issue 2: mlb-phase1-scrapers - Security Issue (API Keys in Plain Text)

#### Current State (INSECURE)

**Service**: `mlb-phase1-scrapers`
**Region**: `us-west2`

**Current Environment Variables** (SECURITY RISK):
```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "SPORT": "mlb",
  "GCS_BUCKET": "nba-scraped-data",
  "COMMIT_SHA": "b855a1d",
  "GIT_BRANCH": "main",
  "DEPLOY_TIMESTAMP": "2026-01-08T05:09:29Z",
  "BDL_API_KEY": "REDACTED",  ← PLAIN TEXT!
  "ODDS_API_KEY": "REDACTED"      ← PLAIN TEXT!
}
```

#### What's Wrong

**Security Issue**: API keys are stored as plain text environment variables instead of using Google Secret Manager.

**Risk**:
- API keys visible to anyone with Cloud Run viewer access
- Keys logged in deployment history
- Keys exposed in Cloud Console UI
- Violates security best practices

#### Expected State (SECURE)

**Reference**: NBA scrapers use Secret Manager correctly

```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "SPORT": "mlb",
  "GCS_BUCKET": "nba-scraped-data",
  "BDL_API_KEY": {
    "secretKeyRef": {
      "key": "latest",
      "name": "BDL_API_KEY"
    }
  },
  "ODDS_API_KEY": {
    "secretKeyRef": {
      "key": "latest",
      "name": "ODDS_API_KEY"
    }
  }
}
```

#### Fix Instructions

**Step 1: Store Secrets in Secret Manager**

```bash
# Store BDL API key
echo -n "REDACTED" | \
  gcloud secrets create BDL_API_KEY \
    --project=nba-props-platform \
    --replication-policy="automatic" \
    --data-file=-

# Store ODDS API key
echo -n "REDACTED" | \
  gcloud secrets create ODDS_API_KEY \
    --project=nba-props-platform \
    --replication-policy="automatic" \
    --data-file=-
```

**Step 2: Grant Service Account Access**

```bash
# Get service account name
SERVICE_ACCOUNT=$(gcloud run services describe mlb-phase1-scrapers \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.serviceAccountName)")

echo "Service account: $SERVICE_ACCOUNT"

# Grant access to BDL_API_KEY
gcloud secrets add-iam-policy-binding BDL_API_KEY \
  --project=nba-props-platform \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

# Grant access to ODDS_API_KEY
gcloud secrets add-iam-policy-binding ODDS_API_KEY \
  --project=nba-props-platform \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

**Step 3: Update Deployment Script**

Update `/home/naji/code/nba-stats-scraper/bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`:

```bash
# BEFORE (INSECURE):
ENV_VARS="${ENV_VARS},BDL_API_KEY=${BDL_API_KEY}"
ENV_VARS="${ENV_VARS},ODDS_API_KEY=${ODDS_API_KEY}"

# AFTER (SECURE):
# Use Secret Manager references instead of plain text
gcloud run deploy mlb-phase1-scrapers \
  --image="$IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --set-secrets="BDL_API_KEY=BDL_API_KEY:latest,ODDS_API_KEY=ODDS_API_KEY:latest" \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,SPORT=mlb,GCS_BUCKET=nba-scraped-data"
```

**Step 4: Redeploy Service**

```bash
cd /home/naji/code/nba-stats-scraper
./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh
```

**Step 5: Verify**

```bash
# Check that secrets are referenced, not plain text
gcloud run services describe mlb-phase1-scrapers \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq '.spec.template.spec.containers[0].env[] | select(.name=="BDL_API_KEY" or .name=="ODDS_API_KEY")'

# Should show secretKeyRef, NOT plain value
```

**Step 6: Remove Old Plain Text Keys (CRITICAL)**

After verifying the service works with Secret Manager:

```bash
# This removes the plain text env vars
gcloud run services update mlb-phase1-scrapers \
  --region=us-west2 \
  --project=nba-props-platform \
  --remove-env-vars=BDL_API_KEY,ODDS_API_KEY

# Secrets are still accessible via secretKeyRef
```

---

### Issue 3: mlb-phase3-analytics-processors - Missing Email Alerting

#### Current State

**Service**: `mlb-phase3-analytics-processors`
**Region**: `us-west2`

**Current Environment Variables**:
```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "SPORT": "mlb",
  "COMMIT_SHA": "e8f0791",
  "GIT_BRANCH": "main",
  "DEPLOY_TIMESTAMP": "2026-01-16T16:54:48Z"
}
```

**Missing**: All email alerting configuration

#### What's Wrong

**Comparison with NBA**: The NBA phase3-analytics-processors has full email alerting:

```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "COMMIT_SHA": "6eabcf9",
  "BREVO_SMTP_HOST": "smtp-relay.brevo.com",
  "BREVO_SMTP_PORT": "587",
  "BREVO_SMTP_USERNAME": "98104dYOUR_EMAIL@smtp-brevo.com",
  "BREVO_SMTP_PASSWORD": "xsmtpsib-...",
  "BREVO_FROM_EMAIL": "alert@989.ninja",
  "BREVO_FROM_NAME": "PK",
  "EMAIL_ALERTS_TO": "nchammas@gmail.com",
  "EMAIL_CRITICAL_TO": "nchammas@gmail.com",
  "EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD": "50",
  "EMAIL_ALERT_SUCCESS_RATE_THRESHOLD": "90.0",
  "EMAIL_ALERT_MAX_PROCESSING_TIME": "30"
}
```

**Impact**:
- No email alerts when MLB Phase 3 analytics fails
- Silent failures in MLB pipeline
- Harder to detect and respond to issues

#### Fix Instructions

**Option 1: Use Update Command**

```bash
gcloud run services update mlb-phase3-analytics-processors \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="\
BREVO_SMTP_HOST=smtp-relay.brevo.com,\
BREVO_SMTP_PORT=587,\
BREVO_SMTP_USERNAME=98104dYOUR_EMAIL@smtp-brevo.com,\
BREVO_SMTP_PASSWORD=xsmtpsib-YOUR_SMTP_KEY_HERE,\
BREVO_FROM_EMAIL=alert@989.ninja,\
BREVO_FROM_NAME=MLB Analytics,\
EMAIL_ALERTS_TO=nchammas@gmail.com,\
EMAIL_CRITICAL_TO=nchammas@gmail.com,\
EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=50,\
EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=90.0,\
EMAIL_ALERT_MAX_PROCESSING_TIME=30"
```

**Option 2: Update Deployment Script**

Update `/home/naji/code/nba-stats-scraper/bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`:

Add email configuration section (see NBA script for reference):

```bash
# Email alerting configuration (same as NBA)
if [[ -n "${BREVO_SMTP_PASSWORD:-}" && -n "${EMAIL_ALERTS_TO:-}" ]]; then
    ENV_VARS="${ENV_VARS},BREVO_SMTP_HOST=smtp-relay.brevo.com"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_PORT=587"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_USERNAME=98104dYOUR_EMAIL@smtp-brevo.com"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="${ENV_VARS},BREVO_FROM_EMAIL=alert@989.ninja"
    ENV_VARS="${ENV_VARS},BREVO_FROM_NAME=MLB Analytics"
    ENV_VARS="${ENV_VARS},EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="${ENV_VARS},EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-${EMAIL_ALERTS_TO}}"
    ENV_VARS="${ENV_VARS},EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="${ENV_VARS},EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="${ENV_VARS},EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"
fi
```

Then redeploy:

```bash
export BREVO_SMTP_PASSWORD="xsmtpsib-YOUR_SMTP_KEY_HERE"
export EMAIL_ALERTS_TO="nchammas@gmail.com"
export EMAIL_CRITICAL_TO="nchammas@gmail.com"

./bin/analytics/deploy/mlb/deploy_mlb_analytics.sh
```

---

## 📋 QUICK CHECKLIST

### Pre-Deployment Checks
- [ ] Read this entire document
- [ ] Have access to `nba-props-platform` GCP project
- [ ] Have `gcloud` CLI configured and authenticated
- [ ] Have Cloud Run Admin permissions

### Fix mlb-prediction-worker
- [ ] Review current environment variables
- [ ] Run deployment script or manual update
- [ ] Verify MLB_ACTIVE_SYSTEMS is set
- [ ] Verify all model paths are set
- [ ] Check BigQuery for multiple system predictions
- [ ] Monitor logs for model loading success

### Fix mlb-phase1-scrapers Security
- [ ] Create secrets in Secret Manager
- [ ] Grant service account access to secrets
- [ ] Update deployment script to use --set-secrets
- [ ] Redeploy service
- [ ] Verify secrets are referenced (not plain text)
- [ ] Remove old plain text env vars
- [ ] Test scraper still works

### Fix mlb-phase3-analytics Email Alerts
- [ ] Add email configuration to service
- [ ] Verify BREVO_SMTP_PASSWORD is set
- [ ] Verify EMAIL_ALERTS_TO is set
- [ ] Redeploy service
- [ ] Trigger a test failure to verify alerts work

### Post-Deployment Verification
- [ ] All services passing health checks
- [ ] No error logs in Cloud Logging
- [ ] Predictions being generated correctly
- [ ] Email alerts working
- [ ] Document completion date

---

## 🔍 VERIFICATION QUERIES

### Check MLB Prediction Systems

```sql
-- Verify multiple systems are running
SELECT
  prediction_date,
  COUNT(DISTINCT system_id) as num_systems,
  STRING_AGG(DISTINCT system_id ORDER BY system_id) as active_systems,
  COUNT(*) as total_predictions
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE prediction_date >= CURRENT_DATE() - 1
GROUP BY prediction_date
ORDER BY prediction_date DESC

-- Expected: num_systems = 3 (v1_baseline, v1_6_rolling, ensemble_v1)
```

### Check for Ensemble Predictions

```sql
-- Verify ensemble predictions exist
SELECT
  prediction_date,
  system_id,
  COUNT(*) as predictions,
  AVG(confidence) as avg_confidence
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE prediction_date = CURRENT_DATE()
  AND system_id = 'ensemble_v1'
GROUP BY prediction_date, system_id

-- Expected: predictions > 0
```

### Check Model Loading Logs

```bash
# Check for successful model loading
gcloud logging read 'resource.type=cloud_run_revision
  AND resource.labels.service_name=mlb-prediction-worker
  AND (textPayload=~"model loaded successfully" OR textPayload=~"Model loaded")' \
  --project=nba-props-platform \
  --limit=10 \
  --format="table(timestamp,textPayload)"
```

---

## 📚 REFERENCE FILES

### Deployment Scripts
- `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`
- `/home/naji/code/nba-stats-scraper/bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`
- `/home/naji/code/nba-stats-scraper/bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`

### Code Files
- `/home/naji/code/nba-stats-scraper/predictions/mlb/config.py` - Configuration expectations
- `/home/naji/code/nba-stats-scraper/predictions/mlb/worker.py` - Worker implementation

### Related Documentation
- NBA CatBoost V8 Root Cause Analysis: `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`
- Comprehensive Fix Todo List: `docs/08-projects/current/catboost-v8-jan-2026-incident/COMPREHENSIVE-FIX-TODO-LIST.md`

---

## ⚠️ IMPORTANT NOTES

### About Deployment Methods

**CRITICAL**: MLB deployment scripts (like NBA scripts) use `--set-env-vars` which **REPLACES ALL** environment variables. This means:

- Any env var not explicitly in the deployment script will be **DELETED**
- Manual console changes will be **LOST** on next deployment
- Use `--update-env-vars` for targeted updates (doesn't delete other vars)

**Safe Update Command**:
```bash
# This preserves other env vars
gcloud run services update SERVICE_NAME \
  --update-env-vars="KEY1=value1,KEY2=value2"
```

**Dangerous Deployment Command**:
```bash
# This deletes env vars not in the string
gcloud run deploy SERVICE_NAME \
  --set-env-vars="KEY1=value1"  # ← All other vars deleted!
```

### About Email Alerting

Email alerting is **OPTIONAL** but highly recommended. The code checks if email configuration is present:

```python
# From shared/utils/email_alerting.py
if not all([smtp_host, smtp_user, smtp_password, from_email]):
    logger.warning("Email alerting not configured - alerts will be skipped")
    return
```

If you skip email configuration:
- Service will work normally
- No alerts will be sent on failures
- Silent failures possible

### About Secret Manager

Storing API keys in Secret Manager (vs plain text env vars) provides:
- ✅ Access control (IAM permissions)
- ✅ Audit logging (who accessed when)
- ✅ Automatic rotation support
- ✅ Versioning
- ✅ Not visible in Cloud Console UI
- ✅ Security best practice compliance

---

## 🎯 SUCCESS CRITERIA

This handoff is complete when:

1. ✅ **mlb-prediction-worker**:
   - MLB_ACTIVE_SYSTEMS set
   - All model paths configured
   - Ensemble predictions being generated
   - Email alerts configured (optional)

2. ✅ **mlb-phase1-scrapers**:
   - API keys stored in Secret Manager
   - Service using secretKeyRef (not plain text)
   - Old plain text env vars removed
   - Scraper still functioning correctly

3. ✅ **mlb-phase3-analytics-processors**:
   - Email alerting configured
   - Test alert successfully sent

4. ✅ **Verification**:
   - All services passing health checks
   - No errors in logs
   - BigQuery shows expected predictions
   - Documentation updated with completion date

---

## 📞 QUESTIONS OR ISSUES?

If you encounter problems:

1. **Check Cloud Logging**:
   ```bash
   gcloud logging read 'resource.type=cloud_run_revision
     AND resource.labels.service_name=SERVICE_NAME
     AND severity>=ERROR' \
     --project=nba-props-platform \
     --limit=50
   ```

2. **Verify Current State**:
   ```bash
   gcloud run services describe SERVICE_NAME \
     --region=us-west2 \
     --project=nba-props-platform \
     --format=json | jq '.spec.template.spec.containers[0].env'
   ```

3. **Rollback if Needed**:
   ```bash
   # List recent revisions
   gcloud run revisions list --service=SERVICE_NAME --region=us-west2

   # Route traffic to previous revision
   gcloud run services update-traffic SERVICE_NAME \
     --region=us-west2 \
     --to-revisions=PREVIOUS_REVISION=100
   ```

4. **Contact**: Reference the NBA CatBoost V8 incident documentation and audit reports for context

---

**Document Created**: 2026-01-17
**Last Updated**: 2026-01-17
**Status**: Ready for MLB team handoff
