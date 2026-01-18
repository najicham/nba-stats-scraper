# NBA Environment Variables Reference

**Last Updated**: 2026-01-17
**Purpose**: Centralized documentation of all environment variables used by NBA services
**Audience**: Developers, DevOps, Operations

---

## 📋 TABLE OF CONTENTS

1. [prediction-worker (NBA Phase 5)](#prediction-worker)
2. [prediction-coordinator](#prediction-coordinator)
3. [nba-phase1-scrapers](#nba-phase1-scrapers)
4. [nba-phase2-raw-processors](#nba-phase2-raw-processors)
5. [nba-phase3-analytics-processors](#nba-phase3-analytics-processors)
6. [nba-phase4-precompute-processors](#nba-phase4-precompute-processors)
7. [nba-monitoring-alerts](#nba-monitoring-alerts)
8. [nba-admin-dashboard](#nba-admin-dashboard)
9. [nba-reference-service](#nba-reference-service)
10. [Common Variables](#common-variables)
11. [Quick Reference Matrix](#quick-reference-matrix)

---

## prediction-worker

**Service Name**: `prediction-worker`
**Region**: `us-west2`
**Description**: NBA Phase 5 prediction service using CatBoost V8 ML model

### CRITICAL Variables (Service Degrades if Missing)

#### `CATBOOST_V8_MODEL_PATH`
- **Type**: String (GCS path)
- **Required**: YES (NO DEFAULT)
- **Example**: `gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm`
- **Purpose**: GCS path to CatBoost V8 trained model file
- **Impact if Missing**:
  - ⚠️ **CRITICAL** - Service falls back to 50% confidence predictions
  - Predictions use simple weighted average instead of ML model
  - All recommendations will be 'PASS' (conservative)
  - Silent degradation - service appears healthy but predictions are wrong
- **Validation**: Service logs error at startup if missing
- **How to Set**:
  ```bash
  gcloud run services update prediction-worker \
    --region=us-west2 \
    --project=nba-props-platform \
    --update-env-vars=CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
  ```
- **Historical Issues**:
  - **Jan 14-17, 2026**: Missing for 3 days, caused 1,071 failed predictions
  - Root cause: Deployment script didn't include variable
  - Detection: Manual investigation after user reports

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Default**: `'nba-props-platform'`
- **Example**: `nba-props-platform`
- **Purpose**: GCP project identifier for BigQuery/GCS/Pub/Sub access
- **Impact if Missing**: Service fails to initialize (startup validation)
- **How to Set**: Automatically set by deployment scripts

### Optional Variables (Has Defaults)

#### `PREDICTIONS_TABLE`
- **Type**: String (BigQuery table)
- **Required**: NO
- **Default**: `'nba_predictions.player_prop_predictions'`
- **Example**: `nba_predictions.player_prop_predictions`
- **Purpose**: BigQuery table for writing predictions
- **Impact if Missing**: Uses default (usually correct)

#### `PUBSUB_READY_TOPIC`
- **Type**: String (Pub/Sub topic)
- **Required**: NO
- **Default**: `'prediction-ready-prod'`
- **Example**: `prediction-ready-prod`
- **Purpose**: Pub/Sub topic for prediction completion events
- **Impact if Missing**: Uses default (coordinator expects this)

### Email Alerting (All or None)

If email alerts are desired, **ALL** must be set:

#### `BREVO_SMTP_HOST`
- **Default**: `smtp-relay.brevo.com`
- **Purpose**: Brevo SMTP server hostname

#### `BREVO_SMTP_PORT`
- **Default**: `587`
- **Purpose**: SMTP port (standard TLS)

#### `BREVO_SMTP_USERNAME`
- **Required**: YES (if email enabled)
- **Example**: `YOUR_EMAILYOUR_EMAIL@smtp-brevo.com`
- **Purpose**: Brevo SMTP authentication username

#### `BREVO_SMTP_PASSWORD`
- **Required**: YES (if email enabled)
- **Example**: `xsmtpsib-YOUR_SMTP_KEY_HERE`
- **Purpose**: Brevo SMTP authentication password
- **Security**: Consider using Secret Manager
- **How to Set**:
  ```bash
  gcloud run services update prediction-worker \
    --update-env-vars=BREVO_SMTP_PASSWORD=xsmtpsib-...
  ```

#### `BREVO_FROM_EMAIL`
- **Required**: YES (if email enabled)
- **Example**: `alert@989.ninja`
- **Purpose**: Email sender address

#### `BREVO_FROM_NAME`
- **Default**: `'NBA Prediction System'`
- **Example**: `NBA Predictions`
- **Purpose**: Email sender display name

#### `EMAIL_ALERTS_TO`
- **Required**: YES (if email enabled)
- **Example**: `nchammas@gmail.com`
- **Purpose**: Recipient email for standard alerts

#### `EMAIL_CRITICAL_TO`
- **Required**: NO
- **Default**: Falls back to `EMAIL_ALERTS_TO`
- **Example**: `nchammas@gmail.com`
- **Purpose**: Recipient email for critical alerts

**Impact if Email Vars Missing**: Email alerts silently disabled, no error

### Deployment Example

```bash
# Minimal deployment (uses defaults)
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="\
GCP_PROJECT_ID=nba-props-platform,\
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm"

# With email alerts
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="\
GCP_PROJECT_ID=nba-props-platform,\
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm,\
BREVO_SMTP_PASSWORD=xsmtpsib-...,\
EMAIL_ALERTS_TO=nchammas@gmail.com"
```

---

## prediction-coordinator

**Service Name**: `prediction-coordinator`
**Region**: `us-west2`
**Description**: Orchestrates daily prediction batch generation

### CRITICAL Variables

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Default**: `'nba-props-platform'`
- **Example**: `nba-props-platform`
- **Purpose**: GCP project identifier
- **Impact if Missing**: Service fails startup validation (line 136-139 of coordinator.py)
- **Validation**: Checked at module initialization

### Optional Variables (Has Defaults)

#### `PREDICTION_REQUEST_TOPIC`
- **Type**: String (Pub/Sub topic)
- **Required**: NO
- **Default**: `'prediction-request-prod'`
- **Example**: `prediction-request-prod`
- **Purpose**: Pub/Sub topic for fanning out prediction requests to workers
- **Impact if Missing**: Uses default

#### `PREDICTION_READY_TOPIC`
- **Type**: String (Pub/Sub topic)
- **Required**: NO
- **Default**: `'prediction-ready-prod'`
- **Example**: `prediction-ready-prod`
- **Purpose**: Pub/Sub topic for receiving completion events from workers
- **Impact if Missing**: Uses default

#### `BATCH_SUMMARY_TOPIC`
- **Type**: String (Pub/Sub topic)
- **Required**: NO
- **Default**: `'prediction-batch-complete'`
- **Example**: `prediction-batch-complete`
- **Purpose**: Pub/Sub topic for publishing batch completion summaries
- **Impact if Missing**: Uses default

#### `COORDINATOR_API_KEY`
- **Type**: String
- **Required**: NO
- **Default**: Loaded from Secret Manager or ENV
- **Purpose**: API key for authenticating coordinator API requests
- **Impact if Missing**: Warning logged, authenticated endpoints reject all requests
- **Security**: Stored in Secret Manager (recommended)

### Email Alerting (Same as prediction-worker)

Same variables as prediction-worker email alerting section.

### Deployment Example

```bash
gcloud run services update prediction-coordinator \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform"
```

---

## nba-phase1-scrapers

**Service Name**: `nba-phase1-scrapers`
**Region**: `us-west2`
**Description**: NBA data scrapers (Phase 1)

### CRITICAL Variables

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Default**: `'nba-props-platform'`
- **Example**: `nba-props-platform`

### API Keys (Use Secret Manager)

#### `ODDS_API_KEY`
- **Type**: Secret Reference
- **Required**: YES
- **Purpose**: The Odds API authentication
- **Security**: ✅ STORED IN SECRET MANAGER (good practice)
- **How to Set**:
  ```bash
  gcloud run services update nba-phase1-scrapers \
    --set-secrets="ODDS_API_KEY=ODDS_API_KEY:latest"
  ```

#### `BDL_API_KEY`
- **Type**: Secret Reference
- **Required**: YES
- **Purpose**: BallDontLie API authentication
- **Security**: ✅ STORED IN SECRET MANAGER (good practice)
- **How to Set**:
  ```bash
  gcloud run services update nba-phase1-scrapers \
    --set-secrets="BDL_API_KEY=BDL_API_KEY:latest"
  ```

### Deployment Metadata (Recommended)

#### `COMMIT_SHA`
- **Type**: String
- **Required**: NO (recommended)
- **Example**: `c9ed2f7`
- **Purpose**: Git commit hash for tracking deployed version
- **Set by**: Deployment script automatically

#### `COMMIT_SHA_FULL`
- **Type**: String
- **Required**: NO (recommended)
- **Example**: `c9ed2f7033b56318838797ed1bd19206aa2e773c`
- **Purpose**: Full git commit hash

#### `GIT_BRANCH`
- **Type**: String
- **Required**: NO (recommended)
- **Example**: `main`
- **Purpose**: Git branch deployed from

#### `DEPLOY_TIMESTAMP`
- **Type**: String (ISO 8601)
- **Required**: NO (recommended)
- **Example**: `2026-01-13T00:37:06Z`
- **Purpose**: When deployment occurred

### Email Alerting (Same as prediction-worker)

Same variables as prediction-worker email alerting section.

### Current Configuration

```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "COMMIT_SHA": "c9ed2f7",
  "COMMIT_SHA_FULL": "c9ed2f7033b56318838797ed1bd19206aa2e773c",
  "GIT_BRANCH": "main",
  "DEPLOY_TIMESTAMP": "2026-01-13T00:37:06Z",
  "BREVO_SMTP_HOST": "smtp-relay.brevo.com",
  "BREVO_SMTP_PORT": "587",
  "BREVO_SMTP_USERNAME": "YOUR_EMAILYOUR_EMAIL@smtp-brevo.com",
  "BREVO_SMTP_PASSWORD": "xsmtpsib-...",
  "BREVO_FROM_EMAIL": "alert@989.ninja",
  "BREVO_FROM_NAME": "PK",
  "EMAIL_ALERTS_TO": "nchammas@gmail.com",
  "EMAIL_CRITICAL_TO": "nchammas@gmail.com",
  "EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD": "50",
  "EMAIL_ALERT_SUCCESS_RATE_THRESHOLD": "90.0",
  "EMAIL_ALERT_MAX_PROCESSING_TIME": "30",
  "ODDS_API_KEY": {"secretKeyRef": {"key": "latest", "name": "ODDS_API_KEY"}},
  "BDL_API_KEY": {"secretKeyRef": {"key": "latest", "name": "BDL_API_KEY"}}
}
```

**Status**: ✅ EXCELLENT - Full email alerting + Secret Manager

---

## nba-phase2-raw-processors

**Service Name**: `nba-phase2-raw-processors`
**Region**: `us-west2`
**Description**: NBA raw data processors (Phase 2)

### CRITICAL Variables

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Example**: `nba-props-platform`

### Email Alerting (AWS SES)

This service uses **AWS SES** instead of Brevo:

#### `AWS_SES_ACCESS_KEY_ID`
- **Type**: Secret Reference
- **Required**: YES (if email enabled)
- **Security**: ✅ STORED IN SECRET MANAGER

#### `AWS_SES_SECRET_ACCESS_KEY`
- **Type**: Secret Reference
- **Required**: YES (if email enabled)
- **Security**: ✅ STORED IN SECRET MANAGER

#### `AWS_SES_REGION`
- **Default**: `us-west-2`
- **Purpose**: AWS region for SES service

#### `AWS_SES_FROM_EMAIL`
- **Example**: `alert@989.ninja`
- **Purpose**: Email sender address

#### `EMAIL_ALERTS_TO`
- **Example**: `nchammas@gmail.com`
- **Purpose**: Alert recipient

### Deployment Metadata

Same as nba-phase1-scrapers.

---

## nba-phase3-analytics-processors

**Service Name**: `nba-phase3-analytics-processors`
**Region**: `us-west2`
**Description**: NBA analytics context processors (Phase 3)

### CRITICAL Variables

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Example**: `nba-props-platform`

### Email Alerting (Brevo)

Full Brevo configuration (same as prediction-worker).

### Alert Thresholds

#### `EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD`
- **Default**: `50`
- **Type**: Integer
- **Purpose**: Trigger alert if unresolved issues exceed this count

#### `EMAIL_ALERT_SUCCESS_RATE_THRESHOLD`
- **Default**: `90.0`
- **Type**: Float (percentage)
- **Purpose**: Trigger alert if success rate falls below this percentage

#### `EMAIL_ALERT_MAX_PROCESSING_TIME`
- **Default**: `30`
- **Type**: Integer (minutes)
- **Purpose**: Trigger alert if processing takes longer than this

### Deployment Metadata

Same as nba-phase1-scrapers.

### Current Configuration

```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "COMMIT_SHA": "6eabcf9",
  "COMMIT_SHA_FULL": "6eabcf9a8b7ae9270e52b536cc3376b2ff0e1aea",
  "GIT_BRANCH": "main",
  "DEPLOY_TIMESTAMP": "2026-01-16T18:36:38Z",
  "BREVO_SMTP_HOST": "smtp-relay.brevo.com",
  "BREVO_SMTP_PORT": "587",
  "BREVO_SMTP_USERNAME": "YOUR_EMAILYOUR_EMAIL@smtp-brevo.com",
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

**Status**: ✅ EXCELLENT - Complete configuration

---

## nba-phase4-precompute-processors

**Service Name**: `nba-phase4-precompute-processors`
**Region**: `us-west2`
**Description**: NBA feature precompute processors (Phase 4)

### CRITICAL Variables

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Example**: `nba-props-platform`

### Deployment Metadata

#### `COMMIT_SHA`
- **Example**: `3eb8af8`
- **Purpose**: Track deployed version

### Current Configuration

```json
{
  "GCP_PROJECT_ID": "nba-props-platform",
  "COMMIT_SHA": "3eb8af8"
}
```

**Status**: ⚠️ MINIMAL - Missing email alerting and full metadata

**Recommendation**: Add email alerting configuration like Phase 3

---

## nba-monitoring-alerts

**Service Name**: `nba-monitoring-alerts`
**Region**: `us-west2`
**Description**: NBA monitoring and alerting service

### CRITICAL Variables

#### `SLACK_WEBHOOK_URL`
- **Type**: String (URL)
- **Required**: YES
- **Example**: `https://hooks.slack.com/services/YOUR_WORKSPACE/YOUR_CHANNEL/YOUR_TOKEN`
- **Purpose**: Slack webhook for sending alerts
- **Impact if Missing**: Alerts not sent, monitoring broken
- **Historical Issues**:
  - **Jan 17, 2026**: Was set to empty string, alerts broken
  - **Fixed**: Session 81, 19:09 UTC

#### `LOG_EXECUTION_ID`
- **Type**: String (boolean)
- **Required**: NO
- **Default**: `'true'`
- **Purpose**: Enable execution ID logging

### Current Configuration

```json
{
  "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/YOUR_WORKSPACE/YOUR_CHANNEL/YOUR_TOKEN",
  "LOG_EXECUTION_ID": "true"
}
```

**Status**: ✅ FIXED (Session 81)

---

## nba-admin-dashboard

**Service Name**: `nba-admin-dashboard`
**Region**: `us-west2`
**Description**: NBA admin dashboard web interface

### Variables

#### `GCP_PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Example**: `nba-props-platform`

**Status**: ⚠️ NOT FULLY AUDITED

**Note**: Admin dashboard configuration needs further documentation.

---

## nba-reference-service

**Service Name**: `nba-reference-service`
**Region**: `us-west2`
**Description**: NBA reference data service

### CRITICAL Variables

#### `PROJECT_ID`
- **Type**: String
- **Required**: YES
- **Example**: `nba-props-platform`
- **Note**: ⚠️ Uses `PROJECT_ID` instead of standard `GCP_PROJECT_ID`

**Status**: ⚠️ NON-STANDARD - Should be migrated to `GCP_PROJECT_ID`

**Recommendation**: Standardize to `GCP_PROJECT_ID` for consistency

---

## Common Variables

These variables are used across multiple NBA services:

### Project Identification

#### `GCP_PROJECT_ID`
- **Used By**: Almost all services (standard)
- **Default**: `'nba-props-platform'`
- **Purpose**: GCP project identifier

#### `PROJECT_ID`
- **Used By**: nba-reference-service (non-standard)
- **Recommendation**: Migrate to `GCP_PROJECT_ID`

### Email Alerting (Brevo)

All services can use the same email configuration:
- `BREVO_SMTP_HOST` = `smtp-relay.brevo.com`
- `BREVO_SMTP_PORT` = `587`
- `BREVO_SMTP_USERNAME` = `YOUR_EMAILYOUR_EMAIL@smtp-brevo.com`
- `BREVO_SMTP_PASSWORD` = `xsmtpsib-YOUR_SMTP_KEY_HERE`
- `BREVO_FROM_EMAIL` = `alert@989.ninja`
- `BREVO_FROM_NAME` = Varies by service
- `EMAIL_ALERTS_TO` = `nchammas@gmail.com`
- `EMAIL_CRITICAL_TO` = `nchammas@gmail.com`

### Deployment Metadata

Recommended for all services:
- `COMMIT_SHA` - Short git commit hash
- `COMMIT_SHA_FULL` - Full git commit hash
- `GIT_BRANCH` - Git branch name
- `DEPLOY_TIMESTAMP` - ISO 8601 timestamp

---

## Quick Reference Matrix

| Service | GCP_PROJECT_ID | Critical Vars | Email | Secrets | Status |
|---------|----------------|---------------|-------|---------|--------|
| prediction-worker | ✅ | CATBOOST_V8_MODEL_PATH | Brevo | No | ✅ Good |
| prediction-coordinator | ✅ | None | Brevo | Optional | ✅ Good |
| nba-phase1-scrapers | ✅ | API Keys | Brevo | ✅ Yes | ✅ Excellent |
| nba-phase2-raw-processors | ✅ | None | AWS SES | ✅ Yes | ✅ Good |
| nba-phase3-analytics-processors | ✅ | None | Brevo | No | ✅ Excellent |
| nba-phase4-precompute-processors | ✅ | None | ❌ No | No | ⚠️ Minimal |
| nba-monitoring-alerts | ❌ (N/A) | SLACK_WEBHOOK_URL | No | No | ✅ Fixed |
| nba-admin-dashboard | ✅ | Unknown | Unknown | Unknown | ⚠️ Needs Audit |
| nba-reference-service | ⚠️ PROJECT_ID | None | Unknown | Unknown | ⚠️ Non-standard |

---

## Deployment Best Practices

### 1. Always Use `--update-env-vars` for Targeted Updates

**SAFE** (Preserves other env vars):
```bash
gcloud run services update SERVICE_NAME \
  --update-env-vars="KEY1=value1,KEY2=value2"
```

**DANGEROUS** (Deletes other env vars):
```bash
gcloud run deploy SERVICE_NAME \
  --set-env-vars="KEY1=value1"  # ← All other vars deleted!
```

### 2. Validate Before Deploying

Create a pre-deployment checklist:
- [ ] All required env vars present
- [ ] Model paths point to existing GCS files
- [ ] API keys are in Secret Manager (not plain text)
- [ ] Email configuration complete (if desired)
- [ ] Deployment metadata included

### 3. Use Secret Manager for Sensitive Data

**Don't**:
```bash
--set-env-vars="API_KEY=plain_text_secret"
```

**Do**:
```bash
--set-secrets="API_KEY=SECRET_NAME:latest"
```

### 4. Document Changes

After deployment:
- Update this document if new env vars added
- Document in deployment script comments
- Update Dockerfile comments

---

## Troubleshooting

### Service Appears Healthy But Not Working

**Symptoms**:
- Health check passes
- No errors in logs
- But functionality is broken

**Likely Cause**: Missing optional env var with default fallback

**Example**: CatBoost V8 incident (Jan 14-17, 2026)
- `CATBOOST_V8_MODEL_PATH` missing
- Service started successfully
- Health check passed
- But predictions used fallback (50% confidence)

**Fix**: Check for these log messages:
```
"FALLBACK_PREDICTION"
"model FAILED to load"
"Using default"
"Using fallback"
```

### Email Alerts Not Sending

**Check**:
1. All BREVO_* vars set?
2. EMAIL_ALERTS_TO set?
3. SMTP password correct?

**Verify**:
```bash
gcloud run services describe SERVICE_NAME \
  --region=us-west2 \
  --format=json | jq '.spec.template.spec.containers[0].env[] | select(.name | startswith("BREVO") or startswith("EMAIL"))'
```

### Slack Alerts Not Sending

**Check**: `SLACK_WEBHOOK_URL` is set and not empty

**Verify**:
```bash
gcloud run services describe nba-monitoring-alerts \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env[?name=='SLACK_WEBHOOK_URL'].value)"
```

---

## Change Log

| Date | Service | Change | Reason |
|------|---------|--------|--------|
| 2026-01-17 | prediction-worker | Added CATBOOST_V8_MODEL_PATH | Fix CatBoost V8 incident |
| 2026-01-17 | nba-monitoring-alerts | Set SLACK_WEBHOOK_URL | Was empty, alerts broken |
| 2026-01-17 | - | Created this document | Prevent future incidents |

---

## Related Documentation

- **Root Cause Analysis**: `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`
- **NBA Fix Todo List**: `docs/08-projects/current/catboost-v8-jan-2026-incident/NBA-FOCUSED-FIX-TODO-LIST.md`
- **Deployment Scripts**: `bin/predictions/deploy/`

---

**Maintained By**: Platform Team
**Questions?**: See troubleshooting section or contact platform team
