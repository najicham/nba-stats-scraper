# AWS SES Migration - Email Alert System

## Issue Summary

**Problem:** All alert emails are being sent via Brevo instead of AWS SES, even though we switched to AWS SES.

**Root Cause:** Deployment scripts were not configured to pass AWS SES credentials to Cloud Run services. The notification system attempts to use AWS SES first, but when credentials are missing, it falls back to Brevo.

## Fix Applied

### Files Updated

1. **`bin/shared/deploy_common.sh`** (Shared deployment utilities)
   - Updated `add_email_config_to_env_vars()` to prefer AWS SES
   - Falls back to Brevo if AWS SES not configured
   - Updated `display_email_status()` to show which provider is active
   - Updated `test_email_config()` to validate AWS SES or Brevo

2. **`bin/analytics/deploy/deploy_analytics_processors.sh`** (Analytics processors)
   - Updated to use AWS SES as primary email provider
   - Added Brevo fallback configuration
   - Updated status display to show which provider is active

### AWS SES Configuration

**Important:** AWS SES credentials are stored in **GCP Secret Manager**, not in the `.env` file.

#### Secrets in GCP Secret Manager (Already Done ✅)

- `aws-ses-access-key-id` - AWS SES access key
- `aws-ses-secret-access-key` - AWS SES secret key

The `SecretManager` class automatically retrieves these secrets. No action needed.

#### Configuration in .env File (Required)

Only **configuration values** (not secrets) go in your `.env` file:

```bash
# AWS SES Configuration (config only, secrets in Secret Manager)
AWS_SES_REGION=us-west-2
AWS_SES_FROM_EMAIL=alert@989.ninja
AWS_SES_FROM_NAME="NBA System Alerts"

# Email Recipients (Required)
EMAIL_ALERTS_TO=your-email@example.com
EMAIL_CRITICAL_TO=your-email@example.com

# Optional: Alert Thresholds
EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=50
EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=90.0
EMAIL_ALERT_MAX_PROCESSING_TIME=30

# Brevo Configuration (Fallback - Optional)
# Note: brevo-smtp-password is also in Secret Manager
BREVO_SMTP_HOST=smtp-relay.brevo.com
BREVO_SMTP_PORT=587
BREVO_SMTP_USERNAME=98104d001@smtp-brevo.com
BREVO_FROM_EMAIL=alert@989.ninja
BREVO_FROM_NAME="NBA System"
```

**Do NOT add these to .env (they're in Secret Manager):**
- ❌ `AWS_SES_ACCESS_KEY_ID`
- ❌ `AWS_SES_SECRET_ACCESS_KEY`
- ❌ `BREVO_SMTP_PASSWORD`

See [`SECRET-MANAGEMENT-REFERENCE.md`](./SECRET-MANAGEMENT-REFERENCE.md) for details.

## Deployment Scripts Still Requiring Manual Update

The following deployment scripts still have Brevo-only configuration and need to be updated manually:

### High Priority (Production Services)
- `bin/scrapers/deploy/deploy_scrapers_simple.sh`
- `bin/raw/deploy/deploy_processors_simple.sh`
- `bin/precompute/deploy/deploy_precompute_processors.sh`
- `bin/reference/deploy/deploy_reference_processors.sh`

### Medium Priority (MLB Services)
- `bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`
- `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`
- `bin/precompute/deploy/mlb/deploy_mlb_precompute.sh`
- `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`
- `bin/phase6/deploy/mlb/deploy_mlb_grading.sh`

### Low Priority
- `bin/monitoring/deploy/deploy_freshness_monitor.sh`
- `bin/scrapers/deploy/deploy_scrapers_backfill_job.sh`

### Update Pattern

For each script, replace this pattern:

```bash
# OLD - Brevo only
if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo "✅ Adding email alerting configuration..."

    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"

    EMAIL_STATUS="ENABLED"
else
    echo "⚠️  Email configuration missing"
    EMAIL_STATUS="DISABLED"
fi
```

With this pattern:

```bash
# NEW - AWS SES preferred, Brevo fallback
if [[ -n "$AWS_SES_ACCESS_KEY_ID" && -n "$AWS_SES_SECRET_ACCESS_KEY" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo "✅ Adding AWS SES email alerting configuration..."

    ENV_VARS="$ENV_VARS,AWS_SES_ACCESS_KEY_ID=${AWS_SES_ACCESS_KEY_ID}"
    ENV_VARS="$ENV_VARS,AWS_SES_SECRET_ACCESS_KEY=${AWS_SES_SECRET_ACCESS_KEY}"
    ENV_VARS="$ENV_VARS,AWS_SES_REGION=${AWS_SES_REGION:-us-west-2}"
    ENV_VARS="$ENV_VARS,AWS_SES_FROM_EMAIL=${AWS_SES_FROM_EMAIL:-alert@989.ninja}"
    ENV_VARS="$ENV_VARS,AWS_SES_FROM_NAME=${AWS_SES_FROM_NAME:-NBA System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"

    # Alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"

    EMAIL_STATUS="ENABLED (AWS SES)"
elif [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo "⚠️  AWS SES not configured, falling back to Brevo..."

    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"

    # Alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"

    EMAIL_STATUS="ENABLED (Brevo - fallback)"
else
    echo "⚠️  Email configuration missing - email alerting will be disabled"
    EMAIL_STATUS="DISABLED"
fi
```

## How to Verify

### 1. Check Environment Variables

```bash
# Verify AWS SES credentials are in .env
grep "AWS_SES" .env

# Should show:
# AWS_SES_ACCESS_KEY_ID=...
# AWS_SES_SECRET_ACCESS_KEY=...
# AWS_SES_REGION=us-west-2
# AWS_SES_FROM_EMAIL=alert@989.ninja
```

### 2. Verify Deployment Shows AWS SES

After deployment, you should see:

```
📧 Email Alerting Status: ENABLED (AWS SES)
   Alert Recipients: your-email@example.com
   Critical Recipients: your-email@example.com
   From Email: alert@989.ninja
   AWS Region: us-west-2
```

Instead of:

```
📧 Email Alerting Status: ENABLED (Brevo - fallback)
```

### 3. Test Email Sending

Trigger a test alert and verify:
- Email arrives from `alert@989.ninja`
- Email headers show "X-SES-Message-ID" (AWS SES header)
- No Brevo-related headers

### 4. Check Cloud Run Environment Variables

```bash
# Check deployed service environment
gcloud run services describe nba-phase3-analytics-processors \
    --region=us-west2 \
    --format="value(spec.template.spec.containers[0].env)"

# Should include:
# AWS_SES_ACCESS_KEY_ID
# AWS_SES_SECRET_ACCESS_KEY
# AWS_SES_REGION
# AWS_SES_FROM_EMAIL
```

## Rollback Plan

If AWS SES has issues, the system will automatically fall back to Brevo if Brevo credentials are still in the `.env` file. No action needed.

To force Brevo usage:
1. Remove AWS SES credentials from `.env`
2. Redeploy the service
3. System will use Brevo

## Next Steps

1. **✅ AWS SES credentials** - Already in Secret Manager, no action needed
2. **Update your `.env` file** - Remove secrets, keep only configuration:
   ```bash
   # Remove these lines (they're in Secret Manager):
   # AWS_SES_ACCESS_KEY_ID=...
   # AWS_SES_SECRET_ACCESS_KEY=...
   # BREVO_SMTP_PASSWORD=...

   # Keep these (configuration only):
   AWS_SES_REGION=us-west-2
   AWS_SES_FROM_EMAIL=alert@989.ninja
   EMAIL_ALERTS_TO=your-email@example.com
   ```
3. **Redeploy analytics processors** (already updated):
   ```bash
   ./bin/analytics/deploy/deploy_analytics_processors.sh
   ```
4. **Update remaining deployment scripts** using the pattern above
5. **Redeploy all services** to apply AWS SES configuration
6. **Monitor email alerts** to verify they're using AWS SES
   - Check logs for "Using AWS SES credentials from Secret Manager"
   - Verify email headers show "X-SES-Message-ID"

See [`SECRET-MANAGEMENT-REFERENCE.md`](./SECRET-MANAGEMENT-REFERENCE.md) for complete guide.

## Benefits of AWS SES

- **Lower cost**: AWS SES is significantly cheaper than Brevo
- **Better deliverability**: AWS SES has excellent reputation
- **Higher limits**: 50,000 emails/day without approval
- **Better integration**: Native AWS service, easier to manage
- **Email tracking**: Better bounce/complaint handling
