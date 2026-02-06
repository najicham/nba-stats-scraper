#!/bin/bash
#
# Feature Store Daily Monitor
#
# Runs daily health check and sends Slack alerts if issues found.
# Designed to run via Cloud Scheduler.
#
# Usage:
#   ./bin/monitoring/feature_store_daily_monitor.sh [YYYY-MM-DD]
#

set -e

# Configuration
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"  # Set via env var or Cloud Run secret

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
CHECK_DATE="${1:-$(date +%Y-%m-%d)}"

echo "🔍 Feature Store Daily Monitor"
echo "Date: $CHECK_DATE"
echo "Project: $PROJECT_DIR"
echo ""

# Change to project directory
cd "$PROJECT_DIR"

# Run health check and capture output
TEMP_FILE=$(mktemp)
if python bin/monitoring/feature_store_health_check.py --date "$CHECK_DATE" > "$TEMP_FILE" 2>&1; then
    HEALTH_STATUS="HEALTHY"
    EXIT_CODE=0
else
    HEALTH_STATUS="UNHEALTHY"
    EXIT_CODE=1
fi

# Print output
cat "$TEMP_FILE"

# Parse results from output
OVERALL_STATUS=$(grep "Overall Status:" "$TEMP_FILE" | awk -F': ' '{print $2}')

# Send Slack alert if issues found
if [ "$EXIT_CODE" -ne 0 ] && [ -n "$SLACK_WEBHOOK_URL" ]; then
    echo ""
    echo "📢 Sending Slack alert..."

    # Extract key metrics
    SUMMARY=$(grep "Summary:" "$TEMP_FILE" || echo "No summary available")

    # Build Slack message
    SLACK_PAYLOAD=$(cat <<EOF
{
  "text": "⚠️ Feature Store Health Check Failed",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "⚠️ Feature Store Health Check Alert"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Date:*\n$CHECK_DATE"
        },
        {
          "type": "mrkdwn",
          "text": "*Status:*\n$OVERALL_STATUS"
        },
        {
          "type": "mrkdwn",
          "text": "*Summary:*\n$SUMMARY"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "\`\`\`$(grep -E "^(✅|⚠️|❌|🚨)" "$TEMP_FILE" | head -10)\`\`\`"
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "Run health check manually: \`python bin/monitoring/feature_store_health_check.py --date $CHECK_DATE\`"
        }
      ]
    }
  ]
}
EOF
)

    # Send to Slack
    curl -X POST -H 'Content-type: application/json' \
        --data "$SLACK_PAYLOAD" \
        "$SLACK_WEBHOOK_URL" \
        2>/dev/null || echo "Failed to send Slack alert"
fi

# Cleanup
rm "$TEMP_FILE"

# Exit with health check status
exit $EXIT_CODE
