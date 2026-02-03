# Morning Deployment Check - Setup Guide

## Purpose

Automatically detect stale services every morning and send Slack alerts before issues impact production.

## Quick Start

### Manual Run
```bash
# Check all services (no Slack alert unless issues found)
python bin/monitoring/morning_deployment_check.py

# Dry run (see what would be sent without sending)
python bin/monitoring/morning_deployment_check.py --dry-run

# Test Slack webhook
python bin/monitoring/morning_deployment_check.py --slack-test

# Always send Slack (even if no issues)
python bin/monitoring/morning_deployment_check.py --always-alert
```

### Environment Variables
```bash
export SLACK_WEBHOOK_URL_WARNING="https://hooks.slack.com/services/..."
export GCP_PROJECT_ID="nba-props-platform"  # optional, defaults to this
```

## Scheduled Automation

### Option 1: Cloud Scheduler (Recommended)

Create a Cloud Scheduler job that triggers a Cloud Function:

```bash
# 1. Create a Cloud Function that runs the check
gcloud functions deploy morning-deployment-check \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=functions/monitoring/morning_deployment_check \
  --entry-point=run_check \
  --trigger-http \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=${SLACK_WEBHOOK_URL_WARNING}

# 2. Create Cloud Scheduler job (6 AM ET = 11 AM UTC)
gcloud scheduler jobs create http morning-deployment-check \
  --location=us-west2 \
  --schedule="0 11 * * *" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/morning-deployment-check" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@nba-props-platform.iam.gserviceaccount.com
```

### Option 2: GitHub Actions

Add to `.github/workflows/morning-check.yml`:
```yaml
name: Morning Deployment Check

on:
  schedule:
    - cron: '0 11 * * *'  # 6 AM ET
  workflow_dispatch:  # Manual trigger

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - uses: google-github-actions/setup-gcloud@v2
      - run: |
          pip install requests
          python bin/monitoring/morning_deployment_check.py
        env:
          SLACK_WEBHOOK_URL_WARNING: ${{ secrets.SLACK_WEBHOOK_URL_WARNING }}
```

### Option 3: Cron (Local/VM)

Add to crontab:
```bash
# Run at 6 AM ET (adjust for your timezone)
0 6 * * * cd /path/to/nba-stats-scraper && python bin/monitoring/morning_deployment_check.py >> /var/log/morning-check.log 2>&1
```

## What It Checks

| Service | Priority | Description |
|---------|----------|-------------|
| `prediction-worker` | P0 | Generates predictions |
| `prediction-coordinator` | P0 | Orchestrates prediction batches |
| `nba-phase3-analytics-processors` | P1 | Game analytics processing |
| `nba-phase4-precompute-processors` | P1 | ML feature generation |
| `nba-phase1-scrapers` | P1 | Data collection |

## Alert Format

When stale services are detected, Slack receives:

```
🚨 CRITICAL Morning Deployment Check

3 service(s) running stale code

─────────────────────────

prediction-worker (P0)
Generates predictions
• Deployed: 2026-02-02 19:26 UTC
• Code changed: 2026-02-02 19:36 UTC
• Drift: 10m

─────────────────────────

Action Required:
./bin/deploy-service.sh <service-name>
```

## Exit Codes

- `0` - All services up to date
- `1` - One or more services have drift (useful for CI/CD gates)

## Adding New Services

Edit `CRITICAL_SERVICES` in `morning_deployment_check.py`:

```python
CRITICAL_SERVICES = {
    'new-service-name': {
        'source_dirs': ['path/to/source', 'shared'],
        'priority': 'P1',
        'description': 'What this service does'
    },
    # ...
}
```

## Troubleshooting

### "Could not get deployment timestamp"
- Service may not exist or has no revisions
- Check: `gcloud run services list --region=us-west2`

### "Could not get code change timestamp"
- Source directory doesn't exist or has no commits
- Check: `git log -1 -- <source_dir>`

### Slack alerts not sending
- Verify `SLACK_WEBHOOK_URL_WARNING` is set
- Test with: `--slack-test` flag
- Check webhook URL is valid

## Integration with CI/CD

Add as a deployment gate:
```yaml
# In deploy workflow
- name: Check deployment drift
  run: python bin/monitoring/morning_deployment_check.py
  continue-on-error: false  # Fail if services are stale
```

## Related

- `bin/check-deployment-drift.sh` - Manual drift check (more verbose)
- `bin/deploy-service.sh` - Deploy a single service
- `docs/02-operations/runbooks/deployment-runbook.md` - Full deployment guide
