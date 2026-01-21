# Secret Management Reference

## Overview

The system uses **GCP Secret Manager** as the primary source for all secrets (API keys, passwords, tokens). The `.env` file should only contain **configuration values**, not secrets.

## Architecture

```
Application Code
    ↓
SecretManager class (shared/utils/secrets.py)
    ↓
Try: GCP Secret Manager (PRIMARY)
    ↓ (if fails)
Fallback: Environment Variable (.env file)
```

## What's in GCP Secret Manager

All secrets are stored in `nba-props-platform` project:

### API Keys
- `odds-api-key` - The Odds API key
- `bdl-api-key` - Ball Don't Lie API key
- `bettingpros-api-key` - BettingPros API key
- `analytics-api-keys` - Analytics service keys

### Email Credentials
- `aws-ses-access-key-id` - AWS SES access key (PRIMARY)
- `aws-ses-secret-access-key` - AWS SES secret key (PRIMARY)
- `brevo-smtp-password` - Brevo SMTP password (FALLBACK)

### Slack Webhooks
- `slack-webhook-url` - Default Slack channel
- `slack-webhook-url-reminders` - Reminders channel
- `slack-webhook-default` - Default webhook
- `slack-webhook-error` - Error alerts
- `slack-webhook-monitoring-error` - Monitoring errors
- `slack-webhook-monitoring-warning` - Monitoring warnings
- `nba-daily-summary-slack-webhook` - Daily summaries
- `nba-grading-slack-webhook` - Grading alerts

### Other Secrets
- `anthropic-api-key` - Claude API key
- `coordinator-api-key` - Internal coordinator authentication
- `sentry-dsn` - Sentry error tracking
- `bdb-drive-key` - Database drive key

## What Goes in .env File

Your `.env` file should contain **configuration only**, not secrets:

```bash
# Project Configuration
PROJECT_ID=nba-props-platform
ENVIRONMENT=production

# Email Recipients (not secrets, just config)
EMAIL_ALERTS_TO=your-email@example.com
EMAIL_CRITICAL_TO=your-email@example.com

# AWS SES Configuration (not secrets, just config)
AWS_SES_REGION=us-west-2
AWS_SES_FROM_EMAIL=alert@989.ninja
AWS_SES_FROM_NAME="NBA System Alerts"

# Brevo Configuration (not secrets, just config)
BREVO_SMTP_HOST=smtp-relay.brevo.com
BREVO_SMTP_PORT=587
BREVO_SMTP_USERNAME=98104d001@smtp-brevo.com
BREVO_FROM_EMAIL=alert@989.ninja

# Thresholds and Settings
EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=50
EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=90.0
EMAIL_ALERT_MAX_PROCESSING_TIME=30
```

## How It Works

### 1. Application Code

```python
from shared.utils.secrets import get_secret_manager

# Get singleton instance
secrets = get_secret_manager()

# Retrieve secrets - tries Secret Manager first, falls back to env
aws_key = secrets.get_aws_ses_access_key_id()
aws_secret = secrets.get_aws_ses_secret_key()
```

### 2. SecretManager Class

The `SecretManager` class (in `shared/utils/secrets.py`) has methods for each secret:

```python
def get_aws_ses_access_key_id(self) -> str:
    """Get AWS SES access key ID."""
    return self.get_secret(
        'aws-ses-access-key-id',  # Secret Manager key
        fallback_env_var='AWS_SES_ACCESS_KEY_ID'  # Env var fallback
    )
```

### 3. Automatic Fallback

If Secret Manager fails (local dev, network issues), it automatically falls back to environment variables:

```
1. Try: projects/nba-props-platform/secrets/aws-ses-access-key-id/versions/latest
   ↓ (success)
   Return secret value

2. If failed:
   ↓
   Try: os.environ.get('AWS_SES_ACCESS_KEY_ID')
   ↓ (success)
   Return env value

3. If failed:
   ↓
   Raise ValueError
```

## Deployment

When deploying to Cloud Run, you **do NOT** need to pass secret values as environment variables. The SecretManager will automatically retrieve them from GCP Secret Manager.

### Updated Deployment Pattern

**Before (❌ Old way - passes secrets as env vars):**
```bash
ENV_VARS="AWS_SES_ACCESS_KEY_ID=${AWS_SES_ACCESS_KEY_ID}"
ENV_VARS="$ENV_VARS,AWS_SES_SECRET_ACCESS_KEY=${AWS_SES_SECRET_ACCESS_KEY}"
```

**After (✅ New way - only passes configuration):**
```bash
# Only pass configuration, not secrets
ENV_VARS="AWS_SES_REGION=${AWS_SES_REGION:-us-west-2}"
ENV_VARS="$ENV_VARS,AWS_SES_FROM_EMAIL=${AWS_SES_FROM_EMAIL:-alert@989.ninja}"
ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
```

The service will automatically retrieve `AWS_SES_ACCESS_KEY_ID` and `AWS_SES_SECRET_ACCESS_KEY` from Secret Manager.

## Managing Secrets

### View Secret Value

```bash
# View latest version
gcloud secrets versions access latest --secret="aws-ses-access-key-id"

# View specific version
gcloud secrets versions access 1 --secret="aws-ses-access-key-id"
```

### Update Secret

```bash
# From file
echo -n "new-secret-value" > /tmp/secret.txt
gcloud secrets versions add aws-ses-access-key-id --data-file=/tmp/secret.txt
rm /tmp/secret.txt

# From stdin
echo -n "new-secret-value" | gcloud secrets versions add aws-ses-access-key-id --data-file=-
```

### Create New Secret

```bash
# Create secret
gcloud secrets create my-new-secret \
    --replication-policy="automatic" \
    --project=nba-props-platform

# Add initial value
echo -n "initial-value" | gcloud secrets versions add my-new-secret --data-file=-
```

### List All Secrets

```bash
gcloud secrets list --format="table(name, created)" --project=nba-props-platform
```

## Local Development

For local development, you have two options:

### Option 1: Use Secret Manager (Recommended)

Ensure you're authenticated with GCP:

```bash
gcloud auth application-default login
```

The SecretManager will automatically fetch secrets from GCP.

### Option 2: Use .env Fallback

If you can't access Secret Manager (no internet, testing), add secrets to `.env`:

```bash
# .env (for local dev only - DO NOT COMMIT)
AWS_SES_ACCESS_KEY_ID=your-local-key
AWS_SES_SECRET_ACCESS_KEY=your-local-secret
ODDS_API_KEY=your-local-key
# etc.
```

The system will automatically fall back to these values.

## Security Best Practices

1. **Never commit secrets to git**
   - `.env` is in `.gitignore`
   - Always use Secret Manager for production

2. **Use Secret Manager for all environments**
   - Production: Always Secret Manager
   - Staging: Always Secret Manager
   - Development: Secret Manager or .env fallback

3. **Rotate secrets regularly**
   - API keys: Every 90 days
   - Passwords: Every 60 days
   - Use Secret Manager versioning

4. **Principle of least privilege**
   - Only grant Secret Manager access to services that need it
   - Use IAM roles, not hardcoded credentials

5. **Audit secret access**
   ```bash
   # View audit logs
   gcloud logging read "resource.type=secretmanager.googleapis.com/Secret" \
       --limit 50 \
       --format json
   ```

## Troubleshooting

### "Failed to retrieve secret from Secret Manager"

**Cause:** Service doesn't have permission or Secret Manager is unavailable

**Solution:**
1. Check service account has `roles/secretmanager.secretAccessor` role
2. Verify secret exists: `gcloud secrets list`
3. Check logs for detailed error

### "Secret Manager unavailable, using env var"

**Cause:** This is a warning, not an error. System is using fallback.

**Solution:**
- For production: Grant Secret Manager permissions
- For local dev: This is expected behavior

### Email alerting not working

**Check:**
1. Verify secrets exist:
   ```bash
   gcloud secrets describe aws-ses-access-key-id
   gcloud secrets describe aws-ses-secret-access-key
   ```

2. Verify service can access secrets:
   ```bash
   # Test from Cloud Run
   gcloud run services describe SERVICE_NAME --format="value(spec.template.spec.serviceAccountName)"

   # Check service account permissions
   gcloud projects get-iam-policy nba-props-platform \
       --flatten="bindings[].members" \
       --filter="bindings.members:serviceAccount:SERVICE_ACCOUNT_EMAIL"
   ```

3. Check application logs for Secret Manager errors

## Migration Checklist

If you're migrating from .env to Secret Manager:

- [x] All secrets already in Secret Manager
- [x] SecretManager class has methods for all secrets
- [x] EmailAlerterSES updated to use Secret Manager
- [ ] Update deployment scripts to not pass secrets as env vars
- [ ] Remove secrets from .env file (keep only config)
- [ ] Test services can retrieve secrets
- [ ] Verify email alerts work
- [ ] Document for team

## AWS SES Credentials Status

**Current Status:** ✅ In Secret Manager

The AWS SES credentials are already in Secret Manager:
- `aws-ses-access-key-id` - ✅ Exists
- `aws-ses-secret-access-key` - ✅ Exists

**What You Need to Do:**

1. **Update your .env file** - Remove secret values, keep only config:
   ```bash
   # Remove these (they're in Secret Manager):
   # AWS_SES_ACCESS_KEY_ID=...
   # AWS_SES_SECRET_ACCESS_KEY=...

   # Keep these (they're config):
   AWS_SES_REGION=us-west-2
   AWS_SES_FROM_EMAIL=alert@989.ninja
   EMAIL_ALERTS_TO=your-email@example.com
   ```

2. **Redeploy services** - Services will automatically use Secret Manager

3. **Verify** - Check logs show "Using AWS SES credentials from Secret Manager"

## Summary

- **Secrets** (passwords, API keys) → GCP Secret Manager
- **Configuration** (regions, email addresses, thresholds) → .env file
- **Deployment** → Pass config only, secrets auto-fetched
- **Local dev** → Secret Manager with .env fallback
- **Security** → Never commit secrets, rotate regularly
