# Deployment Monitoring Runbook

**Layer 1 of Resilience System** - Session 135

## Overview

Automated deployment drift detection that alerts every 2 hours when services have stale code deployed.

**Alert Channel:** `#deployment-alerts`
**Schedule:** Every 2 hours (12 AM, 2 AM, 4 AM, ...)
**Detection Window:** ~2 hours max

## Alert Format

```
⚠️ *Deployment Drift Detected*

Found 2 service(s) with stale deployments:

*prediction-worker*
• Deployed: 2026-02-04 18:00
• Code changed: 2026-02-05 09:00
• Drift: 15.0 hours behind
• Recent commits:
  - abc1234 fix: Fix prediction edge calculation
  - def5678 feat: Add new feature store metrics
  - ghi9012 docs: Update documentation
• Deploy: `./bin/deploy-service.sh prediction-worker`

*nba-phase3-analytics-processors*
• Deployed: 2026-02-03 12:00
• Code changed: 2026-02-05 08:00
• Drift: 44.0 hours behind
• Recent commits:
  - jkl3456 fix: Fix possession calculation bug
  - mno7890 refactor: Improve performance
• Deploy: `./bin/deploy-service.sh nba-phase3-analytics-processors`

_Run `./bin/check-deployment-drift.sh --verbose` for full details_
```

## Response Procedure

### 1. Assess Severity

**Critical (Deploy Immediately):**
- Bug fixes that affect production correctness
- Security patches
- Data quality issues
- Services: prediction-worker, prediction-coordinator, phase3/4 processors

**Medium (Deploy Within 4 Hours):**
- Feature additions
- Performance improvements
- Non-critical refactoring
- Services: orchestrators, grading service

**Low (Deploy Next Business Day):**
- Documentation changes
- Non-functional updates
- Admin dashboard changes

### 2. Review Changes

```bash
# Get detailed drift info
./bin/check-deployment-drift.sh --verbose

# Review recent commits for affected service
git log --oneline --since='2 days ago' -- <source_dir>

# Check what changed
git diff <deployed_commit> HEAD -- <source_dir>
```

### 3. Deploy Stale Services

```bash
# Deploy single service
./bin/deploy-service.sh <service-name>

# Example: Deploy prediction worker
./bin/deploy-service.sh prediction-worker

# Verify deployment
./bin/whats-deployed.sh
```

### 4. Verify Service Health

```bash
# Check service logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=<service-name>" \
  --limit 50 --project nba-props-platform

# Check health endpoint
curl https://<service-url>/health/deep

# For prediction services: verify recent predictions
bq query --use_legacy_sql=false "
  SELECT COUNT(*) as count
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date = CURRENT_DATE()
  AND updated_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
"
```

## Services Monitored

| Service | Source Directories | Priority |
|---------|-------------------|----------|
| prediction-worker | predictions/worker, shared | CRITICAL |
| prediction-coordinator | predictions/coordinator, shared | CRITICAL |
| nba-phase3-analytics-processors | data_processors/phase3, shared | CRITICAL |
| nba-phase4-precompute-processors | data_processors/phase4, shared | CRITICAL |
| nba-phase2-raw-processors | data_processors/phase2 | HIGH |
| nba-phase1-scrapers | scrapers | HIGH |
| nba-grading-service | data_processors/grading/nba, shared, predictions/shared | MEDIUM |
| phase3-to-phase4-orchestrator | orchestration/phase3_to_phase4 | MEDIUM |
| phase4-to-phase5-orchestrator | orchestration/phase4_to_phase5 | MEDIUM |
| nba-admin-dashboard | admin_dashboard | LOW |

## Troubleshooting

### No Alerts When Expected

**Check scheduler status:**
```bash
gcloud scheduler jobs describe nba-deployment-drift-alerter-trigger \
  --location us-west2 --project nba-props-platform
```

**Check recent executions:**
```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=nba-deployment-drift-alerter" \
  --limit 10 --project nba-props-platform
```

**Manual trigger:**
```bash
gcloud run jobs execute nba-deployment-drift-alerter \
  --region us-west2 --project nba-props-platform
```

### False Positives

**Shared code changes affecting multiple services:**
- Changes to `shared/` directory affect many services
- Review if change actually impacts service functionality
- If low impact, deploy during next maintenance window

**Documentation-only changes:**
- Docs in service directory trigger drift detection
- Can be deployed opportunistically

**Auto-generated files:**
- Lock files, compiled code
- Usually safe to deploy

### Alert Fatigue

**If getting too many alerts:**

1. **Review deployment frequency** - Services with frequent commits may need more frequent deployments
2. **Tune alert threshold** - Consider 4-hour or 6-hour window instead of 2-hour
3. **Batch deployments** - Deploy multiple related services together
4. **Improve CI/CD** - Consider auto-deploy for low-risk services

## Manual Testing

```bash
# Test locally
python bin/monitoring/deployment_drift_alerter.py

# Test all components
./bin/monitoring/test_resilience_components.sh

# Check for drift without alerts
./bin/check-deployment-drift.sh --verbose
```

## Configuration

### Scheduler Schedule

**Current:** Every 2 hours (`0 */2 * * *`)

**To change:**
```bash
gcloud scheduler jobs update http nba-deployment-drift-alerter-trigger \
  --schedule "0 */4 * * *" \  # Every 4 hours
  --location us-west2 \
  --project nba-props-platform
```

### Slack Webhook

**Environment variable:** `SLACK_WEBHOOK_URL_DEPLOYMENT_ALERTS`

**To update:**
```bash
# Update secret
gcloud secrets versions add slack-webhook-deployment-alerts \
  --data-file=<(echo "https://hooks.slack.com/services/NEW/WEBHOOK/URL") \
  --project nba-props-platform

# Redeploy job to pick up new secret
./bin/monitoring/setup_deployment_drift_scheduler.sh
```

### Service List

**To add new service:**

1. Update `SERVICE_SOURCES` in `bin/monitoring/deployment_drift_alerter.py`
2. Update `SERVICE_SOURCES` in `bin/check-deployment-drift.sh`
3. Redeploy: `./bin/monitoring/setup_deployment_drift_scheduler.sh`

## Metrics

**Success Criteria:**
- Drift detected within 2 hours: 100%
- False positive rate: <5%
- Alert-to-deployment time: <1 hour for critical services

**Monitor:**
- Number of alerts per week
- Average drift duration
- Time to deployment after alert

## Related Documentation

- [Canary Failure Response](canary-failure-response.md)
- [Health Checks and Smoke Tests](../../05-development/health-checks-and-smoke-tests.md)
- [Deployment Guide](../deployment.md)

## History

- **2026-02-05:** Initial implementation (Session 135)
- Replaces manual 6-hour GitHub Actions checks
- Reduces MTTD from 6 hours to 2 hours
