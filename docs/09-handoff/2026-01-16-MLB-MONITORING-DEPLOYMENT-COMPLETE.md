# MLB Monitoring Infrastructure - Deployment Complete

**Date**: 2026-01-16
**Status**: ✅ DEPLOYED TO PRODUCTION
**Region**: us-west2
**Project**: nba-props-platform

---

## Deployment Summary

All MLB monitoring and validation infrastructure has been successfully deployed to Google Cloud Run.

### Deployed Components

#### 1. Docker Images (7 total)

**Monitoring Images** (4):
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.0`
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/freshness-checker:v1.0.0`
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/prediction-coverage:v1.0.0`
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/stall-detector:v1.0.0`

**Validator Images** (3):
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/schedule-validator:v1.0.0`
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/pitcher-props-validator:v1.0.0`
- `us-west2-docker.pkg.dev/nba-props-platform/mlb-validators/prediction-coverage-validator:v1.0.0`

#### 2. Cloud Run Jobs (7 total)

| Job Name | Purpose | Resources |
|----------|---------|-----------|
| `mlb-gap-detection` | Detects missing data gaps in pipeline | 1 CPU, 512Mi RAM |
| `mlb-freshness-checker` | Monitors data freshness | 1 CPU, 512Mi RAM |
| `mlb-prediction-coverage` | Checks prediction coverage | 1 CPU, 512Mi RAM |
| `mlb-stall-detector` | Detects pipeline stalls | 1 CPU, 512Mi RAM |
| `mlb-schedule-validator` | Validates schedule integrity | 1 CPU, 512Mi RAM |
| `mlb-pitcher-props-validator` | Validates pitcher props | 1 CPU, 512Mi RAM |
| `mlb-prediction-coverage-validator` | Validates prediction coverage | 1 CPU, 512Mi RAM |

#### 3. Cloud Schedulers (9 total)

| Scheduler Name | Schedule | Description |
|----------------|----------|-------------|
| `mlb-gap-detection-daily` | `0 13 * * *` (8 AM ET daily) | Daily gap detection |
| `mlb-freshness-checker-hourly` | `0 */2 * 4-10 *` (Every 2 hours, Apr-Oct) | Freshness monitoring during season |
| `mlb-prediction-coverage-pregame` | `0 22 * 4-10 *` (5 PM ET, Apr-Oct) | Pre-game coverage check |
| `mlb-prediction-coverage-postgame` | `0 7 * 4-10 *` (2 AM ET, Apr-Oct) | Post-game coverage check |
| `mlb-stall-detector-hourly` | `0 * * 4-10 *` (Every hour, Apr-Oct) | Hourly stall detection during season |
| `mlb-schedule-validator-daily` | `0 11 * * *` (6 AM ET daily) | Daily schedule validation |
| `mlb-pitcher-props-validator-4hourly` | `0 10,14,18,22,2,6 * 4-10 *` (Every 4h, Apr-Oct) | 4-hourly pitcher props validation |
| `mlb-prediction-coverage-validator-pregame` | `0 22 * 4-10 *` (5 PM ET, Apr-Oct) | Pre-game validator |
| `mlb-prediction-coverage-validator-postgame` | `0 7 * 4-10 *` (2 AM ET, Apr-Oct) | Post-game validator |

#### 4. IAM Configuration

**Service Account**: `mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com`

**Permissions**:
- `roles/bigquery.dataViewer` - Read BigQuery tables
- `roles/bigquery.jobUser` - Execute BigQuery queries
- `roles/pubsub.publisher` - Publish alerts to Pub/Sub

---

## Deployment Process

### Timeline
- **Started**: 2026-01-16 10:49 UTC
- **Completed**: 2026-01-16 20:03 UTC
- **Total Duration**: ~9 hours (including troubleshooting)

### Build Method
- **Initial Attempt**: Local Docker build (failed due to WSL2 networking issues)
- **Final Method**: Google Cloud Build (succeeded)
- **Build Time**: 4 minutes 36 seconds for 5 images
- **Build ID**: 477ce141-d85f-4a17-9d94-35a98c821880

### Configuration Fixes Applied
1. Fixed CPU limits: 500m → 1000m (gen2 requirement)
2. Fixed memory limits: 256Mi → 512Mi (gen2 requirement with 1 CPU)
3. Fixed cron schedules: Removed invalid wraparound ranges (e.g., `11-5` → `*/2` or `*`)

---

## Verification

### Verify Deployments
```bash
# List all MLB Cloud Run jobs
gcloud run jobs list --region=us-west2 --format="table(name,region)" | grep mlb-

# List all MLB schedulers
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,state)" | grep mlb-

# View job details
gcloud run jobs describe mlb-gap-detection --region=us-west2

# View scheduler details
gcloud scheduler jobs describe mlb-gap-detection-daily --location=us-west2
```

### Test Jobs Manually
```bash
# Test gap detection
gcloud run jobs execute mlb-gap-detection --region=us-west2 --wait

# Test freshness checker
gcloud run jobs execute mlb-freshness-checker --region=us-west2 --wait

# Test validators
gcloud run jobs execute mlb-schedule-validator --region=us-west2 --wait
```

### Monitor Executions
```bash
# View execution history for a job
gcloud run jobs executions list \
  --job=mlb-gap-detection \
  --region=us-west2 \
  --limit=10

# View logs for latest execution
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=mlb-gap-detection" \
  --limit=100 \
  --format=json
```

---

## Alert Integration

All monitoring jobs are integrated with AlertManager:
- **Topic**: `mlb-monitoring-alerts`
- **Alert Types**: GAP, FRESHNESS, STALL, VALIDATION
- **Severity Levels**: CRITICAL, WARNING, INFO

### Alert Routing
Alerts are published to Pub/Sub topic `mlb-monitoring-alerts` and can be:
1. Forwarded to Slack via Cloud Functions
2. Stored in BigQuery for analysis
3. Sent to email via Cloud Pub/Sub subscriptions
4. Integrated with PagerDuty or other incident management systems

---

## Maintenance

### Update Images
```bash
# Rebuild and push new image version
cd /home/naji/code/nba-stats-scraper
docker build -f deployment/dockerfiles/mlb/Dockerfile.gap-detection \
  -t us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.1 .
docker push us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.1

# Update Cloud Run job
gcloud run jobs update mlb-gap-detection \
  --region=us-west2 \
  --image=us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v1.0.1
```

### Update Schedules
```bash
# Update scheduler
gcloud scheduler jobs update http mlb-gap-detection-daily \
  --location=us-west2 \
  --schedule="0 14 * * *"
```

### Pause/Resume Schedulers
```bash
# Pause during off-season
gcloud scheduler jobs pause mlb-freshness-checker-hourly --location=us-west2

# Resume for new season
gcloud scheduler jobs resume mlb-freshness-checker-hourly --location=us-west2
```

---

## Cost Estimation

**Per Execution**:
- CPU: 1 vCPU @ $0.00002400/vCPU-second
- Memory: 512Mi @ $0.00000250/GiB-second
- Typical execution: 30-60 seconds = $0.001-$0.003 per execution

**Monthly (April-October, peak season)**:
- Hourly jobs: ~5,000 executions/month
- Daily jobs: ~200 executions/month
- **Estimated monthly cost**: $15-$30/month for compute
- **Artifact Registry storage**: ~$5/month
- **Total estimated cost**: $20-$35/month during season

---

## Next Steps

1. **Monitor First Executions**: Watch scheduler-triggered executions during next MLB season (April 2026)
2. **Set Up Alert Subscriptions**: Configure Pub/Sub subscriptions for alert notifications
3. **Dashboard Creation**: Create monitoring dashboard in Cloud Console or Grafana
4. **Historical Analysis**: Review execution logs after first week to tune alert thresholds
5. **Cost Optimization**: Review actual costs and adjust schedules if needed

---

## Deployment Artifacts

### Key Files
- Dockerfiles: `deployment/dockerfiles/mlb/Dockerfile.*`
- Cloud Run configs: `deployment/cloud-run/mlb/monitoring/*.yaml`
- Scheduler configs: `deployment/scheduler/mlb/*.yaml`
- Deployment scripts:
  - `deployment/scripts/setup-mlb-prerequisites.sh`
  - `deployment/scripts/deploy-mlb-monitoring.sh`
  - `deployment/scripts/create-schedulers.sh`
  - `deployment/scripts/cloud-build-images.sh`

### Cloud Build Config
- `deployment/cloudbuild/build-remaining-images.yaml`

### Documentation
- Deployment runbook: `docs/runbooks/mlb/deployment-runbook.md`
- Session handoffs: `docs/09-handoff/2026-01-16-SESSION-*-HANDOFF.md`

---

## Troubleshooting

### Common Issues

**Issue**: Job execution fails with "No data found"
- **Cause**: Testing outside MLB season or no games scheduled
- **Solution**: Expected behavior; jobs will succeed when games are scheduled

**Issue**: Scheduler not triggering job
- **Cause**: Scheduler is paused or schedule expression is invalid
- **Solution**: Check `gcloud scheduler jobs describe <job-name>` and ensure state is ENABLED

**Issue**: Permission denied errors
- **Cause**: Service account missing required IAM roles
- **Solution**: Re-run `deployment/scripts/setup-mlb-prerequisites.sh` to grant permissions

**Issue**: Docker build fails locally
- **Cause**: WSL2 networking issues or Docker daemon configuration
- **Solution**: Use Cloud Build instead: `gcloud builds submit --config=deployment/cloudbuild/build-remaining-images.yaml`

---

## Success Criteria - ALL MET ✅

- ✅ All 7 Docker images built and pushed to Artifact Registry
- ✅ All 7 Cloud Run jobs deployed and ready
- ✅ All 9 Cloud Schedulers created and enabled
- ✅ IAM permissions configured correctly
- ✅ Alert integration with Pub/Sub configured
- ✅ Documentation complete
- ✅ Deployment scripts tested and working

---

## Contacts

**Deployment Engineer**: Claude Sonnet 4.5
**Project**: MLB Feature Parity (Sessions 70-72)
**GCP Project**: nba-props-platform
**Region**: us-west2

For issues or questions, refer to:
- Runbook: `docs/runbooks/mlb/deployment-runbook.md`
- Monitoring guide: `docs/runbooks/mlb/monitoring-guide.md`
