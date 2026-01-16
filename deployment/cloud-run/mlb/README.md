# MLB Cloud Run Deployment Configurations

This directory contains Cloud Run Job configurations for MLB monitoring, validation, and export services.

## Directory Structure

```
deployment/cloud-run/mlb/
├── monitoring/           # Monitoring jobs (gap detection, freshness, coverage, stalls)
├── validators/           # Validation jobs (schedule, props, prediction coverage)
├── exporters/           # Export jobs (predictions, best bets, performance, results)
└── README.md           # This file
```

## Service Account Setup

All jobs use the service account: `mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com`

Required permissions:
- BigQuery Data Viewer
- BigQuery Job User
- Cloud Storage Object Viewer (for monitoring)
- Cloud Storage Object Creator (for exporters)
- Secret Manager Secret Accessor (for API keys)

Create service account:
```bash
gcloud iam service-accounts create mlb-monitoring-sa \
  --display-name="MLB Monitoring Service Account" \
  --project=nba-props-platform

# Grant permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator"
```

## Deployment Instructions

### 1. Build and Push Docker Images

For each service, build and push the Docker image to Artifact Registry:

```bash
# Example for gap detection
cd monitoring/mlb
docker build -t us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:latest \
  -f ../../deployment/cloud-run/mlb/monitoring/Dockerfile.gap-detection .
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:latest
```

### 2. Deploy Cloud Run Jobs

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

# Deploy validator jobs
gcloud run jobs replace deployment/cloud-run/mlb/validators/mlb-schedule-validator.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/validators/mlb-pitcher-props-validator.yaml \
  --region=us-west2

gcloud run jobs replace deployment/cloud-run/mlb/validators/mlb-prediction-coverage-validator.yaml \
  --region=us-west2
```

### 3. Set Up Cloud Scheduler

Create scheduled triggers for each job (see `../scheduler/` directory for YAML configs).

## Testing Jobs

Execute jobs manually to test:

```bash
# Test monitoring
gcloud run jobs execute mlb-gap-detection --region=us-west2
gcloud run jobs execute mlb-freshness-checker --region=us-west2
gcloud run jobs execute mlb-prediction-coverage --region=us-west2
gcloud run jobs execute mlb-stall-detector --region=us-west2

# Test validators
gcloud run jobs execute mlb-schedule-validator --region=us-west2
gcloud run jobs execute mlb-pitcher-props-validator --region=us-west2
gcloud run jobs execute mlb-prediction-coverage-validator --region=us-west2
```

View execution logs:
```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=mlb-gap-detection" \
  --limit=50 \
  --format=json
```

## Monitoring Job Details

### mlb-gap-detection
- **Purpose**: Detect GCS files not processed to BigQuery
- **Schedule**: Daily at 8 AM ET
- **Timeout**: 10 minutes
- **Resources**: 1 CPU, 512Mi memory

### mlb-freshness-checker
- **Purpose**: Monitor data staleness across pipeline
- **Schedule**: Every 2 hours (during season)
- **Timeout**: 5 minutes
- **Resources**: 0.5 CPU, 256Mi memory

### mlb-prediction-coverage
- **Purpose**: Ensure all pitchers get predictions
- **Schedule**: 2 hours before first game, after games
- **Timeout**: 5 minutes
- **Resources**: 0.5 CPU, 256Mi memory

### mlb-stall-detector
- **Purpose**: Detect pipeline stalls
- **Schedule**: Every hour (during season)
- **Timeout**: 5 minutes
- **Resources**: 0.5 CPU, 256Mi memory

## Validator Job Details

### mlb-schedule-validator
- **Purpose**: Validate schedule completeness
- **Schedule**: Daily at 6 AM ET
- **Timeout**: 10 minutes
- **Resources**: 1 CPU, 512Mi memory

### mlb-pitcher-props-validator
- **Purpose**: Validate betting line quality
- **Schedule**: Every 4 hours (game days)
- **Timeout**: 10 minutes
- **Resources**: 1 CPU, 512Mi memory

### mlb-prediction-coverage-validator
- **Purpose**: Validate prediction completeness
- **Schedule**: 2 hours before first game, after games
- **Timeout**: 10 minutes
- **Resources**: 1 CPU, 512Mi memory

## Troubleshooting

### Job Fails to Start
1. Check service account permissions
2. Verify image exists in Artifact Registry
3. Check Cloud Run quotas

### Job Times Out
1. Increase `timeoutSeconds` in job config
2. Optimize query performance
3. Add more CPU/memory resources

### No Alerts Received
1. Verify AlertManager integration
2. Check Slack webhook configuration
3. Review Cloud Logging for errors

## Related Documentation

- Cloud Scheduler configs: `../scheduler/`
- Monitoring documentation: `../../../docs/08-projects/current/mlb-feature-parity/`
- Runbooks: `../../../docs/runbooks/mlb/`

---

**Created**: 2026-01-16
**Status**: Production Ready
