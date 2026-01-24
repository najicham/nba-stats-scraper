# MLB Deployment Runbook

**Version**: 1.0
**Last Updated**: 2026-01-16
**Owner**: MLB Infrastructure Team

---

## Overview

This runbook covers deployment procedures for the MLB prediction infrastructure including monitoring, validation, and export services.

---

## Pre-Deployment Checklist

Before deploying any MLB service:

- [ ] Code changes reviewed and approved
- [ ] All tests passing locally
- [ ] Schema compatibility verified
- [ ] Service account permissions confirmed
- [ ] Deployment configs updated with correct image tags
- [ ] Rollback plan documented

---

## Service Account Setup

### Create MLB Monitoring Service Account

```bash
# Create service account
gcloud iam service-accounts create mlb-monitoring-sa \
  --display-name="MLB Monitoring Service Account" \
  --project=nba-props-platform

# Grant BigQuery permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

# Grant Storage permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator"

# Grant Secret Manager access (for API keys)
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## Deploying Monitoring Services

### 1. Build Docker Images

```bash
cd /path/to/nba-stats-scraper

# Build gap detection
docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.gap-detection .

# Build freshness checker
docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/freshness-checker:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.freshness-checker .

# Build prediction coverage
docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/prediction-coverage:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.prediction-coverage .

# Build stall detector
docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/stall-detector:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.stall-detector .
```

### 2. Push Images to Artifact Registry

```bash
# Push all images
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.0
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/freshness-checker:v1.0.0
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/prediction-coverage:v1.0.0
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/stall-detector:v1.0.0

# Tag as latest
docker tag us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.0 \
  us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:latest
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:latest
# Repeat for other images...
```

### 3. Deploy Cloud Run Jobs

```bash
# Deploy monitoring jobs
gcloud run jobs replace deployment/cloud-run/mlb/monitoring/mlb-gap-detection.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/monitoring/mlb-freshness-checker.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/monitoring/mlb-prediction-coverage.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/monitoring/mlb-stall-detector.yaml \
  --region=us-west2
```

### 4. Test Jobs Manually

```bash
# Execute each job to verify it works
gcloud run jobs execute mlb-gap-detection --region=us-west2 --wait
gcloud run jobs execute mlb-freshness-checker --region=us-west2 --wait
gcloud run jobs execute mlb-prediction-coverage --region=us-west2 --wait
gcloud run jobs execute mlb-stall-detector --region=us-west2 --wait
```

### 5. Set Up Schedulers

```bash
# Create scheduler jobs (monitoring)
gcloud scheduler jobs create http mlb-gap-detection-daily \
  --location=us-west2 \
  --schedule="0 13 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/mlb-gap-detection:run" \
  --http-method=POST \
  --oauth-service-account-email=mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com

gcloud scheduler jobs create http mlb-freshness-checker-hourly \
  --location=us-west2 \
  --schedule="0 11-5/2 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/mlb-freshness-checker:run" \
  --http-method=POST \
  --oauth-service-account-email=mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com

# Add remaining scheduler jobs...
```

---

## Deploying Validators

### 1. Build and Push Validator Images

```bash
# Build validators
docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/schedule-validator:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.schedule-validator .

docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/pitcher-props-validator:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.pitcher-props-validator .

docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/prediction-coverage-validator:v1.0.0 \
  -f deployment/dockerfiles/mlb/Dockerfile.prediction-coverage-validator .

# Push images
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/schedule-validator:v1.0.0
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/pitcher-props-validator:v1.0.0
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/prediction-coverage-validator:v1.0.0
```

### 2. Deploy Validator Jobs

```bash
# Deploy validators
gcloud run jobs replace deployment/cloud-run/mlb/validators/mlb-schedule-validator.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/validators/mlb-pitcher-props-validator.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/validators/mlb-prediction-coverage-validator.yaml \
  --region=us-west2
```

### 3. Set Up Validator Schedulers

```bash
# Schedule validator jobs
gcloud scheduler jobs create http mlb-schedule-validator-daily \
  --location=us-west2 \
  --schedule="0 11 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/mlb-schedule-validator:run" \
  --http-method=POST \
  --oauth-service-account-email=mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com

# Add remaining validator schedulers...
```

---

## Troubleshooting

### Job Fails to Start

**Symptoms**: Job shows as "Failed" immediately without execution
**Possible Causes**:
- Service account lacks permissions
- Docker image doesn't exist or is inaccessible
- Invalid job configuration

**Resolution**:
```bash
# Check service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com"

# Verify image exists
gcloud artifacts docker images list us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring

# Check job configuration
gcloud run jobs describe mlb-gap-detection --region=us-west2
```

### Job Times Out

**Symptoms**: Job runs but times out before completion
**Possible Causes**:
- Query takes too long
- Insufficient CPU/memory
- Network issues

**Resolution**:
1. Increase timeout in job config:
   ```yaml
   timeoutSeconds: 1200  # Increase to 20 minutes
   ```
2. Add more resources:
   ```yaml
   resources:
     limits:
       cpu: "2000m"      # Increase CPU
       memory: "1024Mi"  # Increase memory
   ```
3. Optimize queries (add indexes, limit date ranges)

### No Alerts Received

**Symptoms**: Jobs run but no alerts sent
**Possible Causes**:
- AlertManager not configured
- Slack webhook invalid
- Alert threshold not met

**Resolution**:
```bash
# Check AlertManager configuration
# Verify environment variables set in job
gcloud run jobs describe mlb-gap-detection --region=us-west2 --format=yaml

# Check logs for alert attempts
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=mlb-gap-detection" \
  --limit=50 \
  --format=json | grep -i alert

# Test AlertManager directly
python -c "from shared.alerts.alert_manager import get_alert_manager; \
  mgr = get_alert_manager(); \
  mgr.send_alert('info', 'Test', 'Testing alerts', 'test')"
```

### High Error Rate

**Symptoms**: Multiple job failures
**Possible Causes**:
- BigQuery quota exceeded
- Schema changes broke queries
- Data quality issues

**Resolution**:
1. Check BigQuery quotas:
   ```bash
   gcloud alpha monitoring policies list --filter="displayName:'BigQuery API Requests'"
   ```
2. Review recent schema changes in affected tables
3. Run validation manually to inspect errors:
   ```bash
   PYTHONPATH=. python monitoring/mlb/mlb_gap_detection.py --date 2026-01-16 --dry-run
   ```

---

## Rollback Procedures

### Rollback Cloud Run Job

```bash
# List revisions
gcloud run jobs revisions list --job=mlb-gap-detection --region=us-west2

# Update job to use previous revision/image
gcloud run jobs update mlb-gap-detection \
  --region=us-west2 \
  --image=us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v0.9.0
```

### Pause Scheduler

```bash
# Pause scheduler while troubleshooting
gcloud scheduler jobs pause mlb-gap-detection-daily --location=us-west2

# Resume when fixed
gcloud scheduler jobs resume mlb-gap-detection-daily --location=us-west2
```

---

## Monitoring Deployment Health

### View Job Executions

```bash
# List recent executions
gcloud run jobs executions list --job=mlb-gap-detection --region=us-west2 --limit=10

# View execution logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=mlb-gap-detection" \
  --limit=100 \
  --format=json
```

### Check Scheduler Status

```bash
# List all MLB schedulers
gcloud scheduler jobs list --location=us-west2 | grep mlb-

# View scheduler execution history
gcloud scheduler jobs describe mlb-gap-detection-daily --location=us-west2
```

### Monitor Costs

```bash
# Check Cloud Run costs
gcloud billing accounts list
gcloud billing projects describe nba-props-platform

# View BigQuery slot usage
bq ls --jobs --max_results=100 | grep mlb_
```

---

## Post-Deployment Verification

After deployment, verify:

- [ ] All jobs execute successfully
- [ ] Schedulers trigger at correct times
- [ ] Alerts are sent to Slack
- [ ] BigQuery queries complete within timeout
- [ ] Logs show expected output
- [ ] Costs are within budget

---

## Contacts

- **On-Call Engineer**: Check PagerDuty
- **Slack Channel**: #mlb-infrastructure
- **Runbook Issues**: File in GitHub under `mlb-infrastructure` label

---

**Last Tested**: 2026-01-16
**Next Review**: Before 2026 MLB Season
