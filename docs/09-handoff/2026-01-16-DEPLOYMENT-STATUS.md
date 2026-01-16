# MLB Monitoring Deployment Status

**Date**: 2026-01-16
**Status**: ✅ READY TO DEPLOY

---

## Deployment Readiness Checklist

### Code & Configuration ✅
- [x] 5 monitoring modules written and tested
- [x] 3 validators written and tested
- [x] 3 YAML validator configs created
- [x] 4 exporters written and tested
- [x] AlertManager integrated in 4 MLB services
- [x] All schema fixes applied

### Docker & Deployment Configs ✅
- [x] 7 Dockerfiles created (4 monitoring + 3 validators)
- [x] 7 Cloud Run job YAML configs created
- [x] 2 scheduler YAML config files created (9 jobs total)
- [x] Deployment script created (`deployment/scripts/deploy-mlb-monitoring.sh`)

### Documentation ✅
- [x] Deployment runbook written
- [x] Alerting runbook written
- [x] Pre-season checklist created (100+ items)
- [x] Session handoff documents complete
- [x] Test results documented

### Testing ✅
- [x] All validators tested with historical data (2025-08-15)
- [x] All monitors tested locally
- [x] All exporters tested with --dry-run
- [x] Schema compatibility verified

---

## Deployment Components

### Monitoring Jobs (4)
1. **mlb-gap-detection** - Detects missing data in GCS/BigQuery
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.gap-detection`
   - Config: `deployment/cloud-run/mlb/monitoring/mlb-gap-detection.yaml`
   - Schedule: Daily at 8 AM ET

2. **mlb-freshness-checker** - Validates data freshness
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.freshness-checker`
   - Config: `deployment/cloud-run/mlb/monitoring/mlb-freshness-checker.yaml`
   - Schedule: Every 2 hours during season

3. **mlb-prediction-coverage** - Checks prediction completeness
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.prediction-coverage`
   - Config: `deployment/cloud-run/mlb/monitoring/mlb-prediction-coverage.yaml`
   - Schedule: Pre-game (5 PM ET) and post-game (2 AM ET)

4. **mlb-stall-detector** - Detects pipeline stalls
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.stall-detector`
   - Config: `deployment/cloud-run/mlb/monitoring/mlb-stall-detector.yaml`
   - Schedule: Hourly during season

### Validator Jobs (3)
1. **mlb-schedule-validator** - Validates schedule data quality
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.schedule-validator`
   - Config: `deployment/cloud-run/mlb/validators/mlb-schedule-validator.yaml`
   - Schedule: Daily at 6 AM ET

2. **mlb-pitcher-props-validator** - Validates pitcher props data
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.pitcher-props-validator`
   - Config: `deployment/cloud-run/mlb/validators/mlb-pitcher-props-validator.yaml`
   - Schedule: Every 4 hours during season

3. **mlb-prediction-coverage-validator** - Validates prediction coverage
   - Dockerfile: `deployment/dockerfiles/mlb/Dockerfile.prediction-coverage-validator`
   - Config: `deployment/cloud-run/mlb/validators/mlb-prediction-coverage-validator.yaml`
   - Schedule: Pre-game (5 PM ET) and post-game (2 AM ET)

### Cloud Schedulers (9)
**Monitoring Schedules** (5):
- mlb-gap-detection-daily
- mlb-freshness-checker-hourly
- mlb-prediction-coverage-pregame
- mlb-prediction-coverage-postgame
- mlb-stall-detector-hourly

**Validator Schedules** (4):
- mlb-schedule-validator-daily
- mlb-pitcher-props-validator-4hourly
- mlb-prediction-coverage-validator-pregame
- mlb-prediction-coverage-validator-postgame

---

## Deployment Script Usage

### Full Deployment
```bash
cd /home/naji/code/nba-stats-scraper
./deployment/scripts/deploy-mlb-monitoring.sh
```

### Dry Run (Test Only)
```bash
./deployment/scripts/deploy-mlb-monitoring.sh --dry-run
```

### Partial Deployment Options
```bash
# Skip service account setup (if already exists)
./deployment/scripts/deploy-mlb-monitoring.sh --skip-service-account

# Skip Docker build (if images already pushed)
./deployment/scripts/deploy-mlb-monitoring.sh --skip-build

# Skip Cloud Run deployment (if jobs already deployed)
./deployment/scripts/deploy-mlb-monitoring.sh --skip-deploy

# Skip scheduler setup (if schedulers already configured)
./deployment/scripts/deploy-mlb-monitoring.sh --skip-schedulers

# Deploy specific version
./deployment/scripts/deploy-mlb-monitoring.sh --version v1.0.1
```

---

## Pre-Deployment Checklist

Before running deployment:

- [ ] Verify `gcloud` CLI is authenticated: `gcloud auth list`
- [ ] Verify project is set: `gcloud config get-value project`
- [ ] Verify Docker is running: `docker ps`
- [ ] Verify Docker authenticated to Artifact Registry: `gcloud auth configure-docker us-west2-docker.pkg.dev`
- [ ] Review deployment script: `cat deployment/scripts/deploy-mlb-monitoring.sh`
- [ ] Run dry-run first: `./deployment/scripts/deploy-mlb-monitoring.sh --dry-run`
- [ ] Check Artifact Registry repositories exist:
  - `gcloud artifacts repositories describe mlb-monitoring --location=us-west2`
  - `gcloud artifacts repositories describe mlb-validators --location=us-west2`

---

## Expected Deployment Time

| Phase | Duration | Notes |
|-------|----------|-------|
| Service Account Setup | 5 min | One-time only |
| Docker Build (7 images) | 30-60 min | Depends on machine |
| Docker Push | 10-20 min | Depends on bandwidth |
| Cloud Run Deploy | 10 min | 7 jobs |
| Scheduler Setup | 5 min | 9 schedulers |
| Testing | 15-30 min | Manual job execution |
| **Total** | **1.5-2.5 hours** | First-time deployment |

Subsequent deployments (with --skip-service-account) take ~1 hour.

---

## Post-Deployment Verification

After deployment completes:

1. **Verify Jobs Deployed**
   ```bash
   gcloud run jobs list --region=us-west2 | grep mlb-
   ```
   Should show 7 jobs.

2. **Verify Schedulers Created**
   ```bash
   gcloud scheduler jobs list --location=us-west2 | grep mlb-
   ```
   Should show 9 schedulers.

3. **Test Each Job**
   ```bash
   gcloud run jobs execute mlb-gap-detection --region=us-west2 --wait
   gcloud run jobs execute mlb-schedule-validator --region=us-west2 --wait
   # etc...
   ```

4. **Check Logs**
   ```bash
   gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=mlb-gap-detection" --limit=20
   ```

5. **Monitor Slack Channel**
   - Check #mlb-alerts for any alerts sent
   - Verify alert formatting and content

---

## Known Issues

### 1. Artifact Registry Repositories
**Issue**: Repositories may not exist yet
**Solution**: Create before deployment:
```bash
gcloud artifacts repositories create mlb-monitoring \
  --repository-format=docker \
  --location=us-west2 \
  --description="MLB monitoring Docker images"

gcloud artifacts repositories create mlb-validators \
  --repository-format=docker \
  --location=us-west2 \
  --description="MLB validator Docker images"
```

### 2. First-Time Docker Build
**Issue**: First build downloads base images and dependencies
**Solution**: Expect 30-60 minutes for initial build, ~10 minutes for subsequent builds

### 3. Service Account Permissions Propagation
**Issue**: IAM permissions can take 60-120 seconds to propagate
**Solution**: Wait 2 minutes after service account setup before deploying jobs

---

## Rollback Plan

If deployment fails or causes issues:

1. **Pause Schedulers**
   ```bash
   gcloud scheduler jobs pause mlb-gap-detection-daily --location=us-west2
   # Repeat for all 9 schedulers
   ```

2. **Rollback to Previous Image**
   ```bash
   gcloud run jobs update mlb-gap-detection \
     --region=us-west2 \
     --image=us-west2-docker.pkg.dev/nba-props-platform/mlb-monitoring/gap-detection:v0.9.0
   ```

3. **Delete Jobs (Last Resort)**
   ```bash
   gcloud run jobs delete mlb-gap-detection --region=us-west2
   ```

---

## Support & Contacts

- **Documentation**: `docs/runbooks/mlb/deployment-runbook.md`
- **Troubleshooting**: `docs/runbooks/mlb/alerting-runbook.md`
- **Slack Channel**: #mlb-infrastructure
- **On-Call**: Check PagerDuty

---

## Deployment History

| Date | Version | Deployer | Status | Notes |
|------|---------|----------|--------|-------|
| 2026-01-16 | v1.0.0 | TBD | Pending | Initial deployment |

---

**Status**: ✅ READY TO DEPLOY
**Last Updated**: 2026-01-16
**Next Review**: After initial deployment
