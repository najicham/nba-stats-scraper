#!/bin/bash
# Script to update deployment scripts to use AWS SES instead of Brevo
# Updates all deployment scripts to prefer AWS SES with Brevo fallback

set -euo pipefail

echo "🔧 Updating deployment scripts to use AWS SES..."
echo ""

# List of scripts to update (excluding those already updated)
SCRIPTS=(
    "bin/analytics/deploy/mlb/deploy_mlb_analytics.sh"
    "bin/reference/deploy/deploy_reference_processors.sh"
    "bin/phase6/deploy/mlb/deploy_mlb_grading.sh"
    "bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh"
    "bin/precompute/deploy/deploy_precompute_processors.sh"
    "bin/precompute/deploy/mlb/deploy_mlb_precompute.sh"
    "bin/monitoring/deploy/deploy_freshness_monitor.sh"
    "bin/raw/deploy/deploy_processors_simple.sh"
    "bin/scrapers/deploy/deploy_scrapers_backfill_job.sh"
    "bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh"
    "bin/scrapers/deploy/deploy_scrapers_simple.sh"
)

updated_count=0
skipped_count=0

for script in "${SCRIPTS[@]}"; do
    if [[ ! -f "$script" ]]; then
        echo "⚠️  Skipping (not found): $script"
        ((skipped_count++))
        continue
    fi

    # Check if this script has Brevo config but not AWS SES
    if grep -q "BREVO_SMTP_PASSWORD" "$script" && ! grep -q "AWS_SES_ACCESS_KEY_ID" "$script"; then
        echo "📝 Updating: $script"

        # Create backup
        cp "$script" "${script}.backup.$(date +%Y%m%d_%H%M%S)"

        # Use sed to replace the Brevo-only config with AWS SES + Brevo fallback
        # This is a complex sed operation, so we'll use a temporary file
        awk '
        BEGIN { in_email_block = 0; block_start = 0; }

        # Detect the start of email configuration block
        /^if \[\[ -n "\$BREVO_SMTP_PASSWORD" && -n "\$EMAIL_ALERTS_TO" \]\]; then/ {
            in_email_block = 1;
            block_start = NR;
            # Output the new AWS SES-first configuration
            print "# Add email configuration if available (AWS SES preferred, Brevo fallback)";
            print "if [[ -n \"$AWS_SES_ACCESS_KEY_ID\" && -n \"$AWS_SES_SECRET_ACCESS_KEY\" && -n \"$EMAIL_ALERTS_TO\" ]]; then";
            print "    echo \"✅ Adding AWS SES email alerting configuration...\"";
            print "";
            print "    ENV_VARS=\"$ENV_VARS,AWS_SES_ACCESS_KEY_ID=${AWS_SES_ACCESS_KEY_ID}\"";
            print "    ENV_VARS=\"$ENV_VARS,AWS_SES_SECRET_ACCESS_KEY=${AWS_SES_SECRET_ACCESS_KEY}\"";
            print "    ENV_VARS=\"$ENV_VARS,AWS_SES_REGION=${AWS_SES_REGION:-us-west-2}\"";
            print "    ENV_VARS=\"$ENV_VARS,AWS_SES_FROM_EMAIL=${AWS_SES_FROM_EMAIL:-alert@989.ninja}\"";
            # Get the FROM_NAME from original if present, else use default
            print "    ENV_VARS=\"$ENV_VARS,AWS_SES_FROM_NAME=${AWS_SES_FROM_NAME:-NBA System}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}\"";
            print "";
            # Preserve alert thresholds if they exist
            next;
        }

        # Skip lines in the email block until we find the else/fi
        in_email_block == 1 && /^else$/ {
            # Output the Brevo fallback
            print "    # Alert thresholds (if present)";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}\"";
            print "";
            print "    EMAIL_STATUS=\"ENABLED (AWS SES)\"";
            print "elif [[ -n \"$BREVO_SMTP_PASSWORD\" && -n \"$EMAIL_ALERTS_TO\" ]]; then";
            print "    echo \"⚠️  AWS SES not configured, falling back to Brevo...\"";
            print "";
            print "    ENV_VARS=\"$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}\"";
            print "    ENV_VARS=\"$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}\"";
            print "    ENV_VARS=\"$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}\"";
            print "    ENV_VARS=\"$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}\"";
            print "    ENV_VARS=\"$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}\"";
            print "    ENV_VARS=\"$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA System}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}\"";
            print "";
            print "    # Alert thresholds";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}\"";
            print "    ENV_VARS=\"$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}\"";
            print "";
            print "    EMAIL_STATUS=\"ENABLED (Brevo - fallback)\"";
            next;
        }

        # Skip the old "echo email configuration missing" line after else
        in_email_block == 1 && /Email configuration missing.*email alerting will be disabled/ {
            next;
        }

        # Handle the old EMAIL_STATUS setting
        in_email_block == 1 && /EMAIL_STATUS="ENABLED"/ {
            next;
        }

        # End of email block
        in_email_block == 1 && /^fi$/ {
            print "else";
            print "    echo \"⚠️  Email configuration missing - email alerting will be disabled\"";
            print "    EMAIL_STATUS=\"DISABLED\"";
            print "fi";
            in_email_block = 0;
            next;
        }

        # Skip all lines in the email configuration block (between if and fi)
        in_email_block == 1 {
            next;
        }

        # Print all other lines as-is
        { print }
        ' "$script" > "${script}.tmp"

        # Replace original with updated version
        mv "${script}.tmp" "$script"
        chmod +x "$script"

        echo "   ✅ Updated successfully"
        ((updated_count++))
    else
        echo "⏭️  Skipping (already has AWS SES or no Brevo): $script"
        ((skipped_count++))
    fi
    echo ""
done

echo ""
echo "📊 Summary:"
echo "   Updated: $updated_count scripts"
echo "   Skipped: $skipped_count scripts"
echo ""
echo "✅ All deployment scripts updated to prefer AWS SES!"
echo ""
echo "Next steps:"
echo "1. Add AWS SES credentials to your .env file:"
echo "   AWS_SES_ACCESS_KEY_ID=your-access-key-id"
echo "   AWS_SES_SECRET_ACCESS_KEY=your-secret-key"
echo "   AWS_SES_REGION=us-west-2"
echo "   AWS_SES_FROM_EMAIL=alert@989.ninja"
echo ""
echo "2. Redeploy services to apply the new configuration"
