#!/bin/bash
# FILE: bin/scrapers/deploy/deploy_scrapers_backfill_job.sh
# 
# Simplified deployment script using single parameterized Dockerfile
# Auto-discovers config file from job name for cleaner usage

set -e

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo "✅ Environment variables loaded"
else
    echo "⚠️  No .env file found - email alerting may not work"
fi

# Check if job name provided
if [[ -z "$1" ]]; then
    echo "Usage: $0 <job-name-or-config-path>"
    echo ""
    echo "Examples (clean approach):"
    echo "  $0 bdl_boxscore                    # Auto-finds backfill_jobs/scrapers/bdl_boxscore/job-config.env"
    echo "  $0 bdl-boxscore-backfill          # Auto-finds based on job name"
    echo "  $0 nbac_gamebook                  # Auto-finds backfill_jobs/scrapers/nbac_gamebook/job-config.env"
    echo ""
    echo "Examples (explicit path - still supported):"
    echo "  $0 backfill_jobs/scrapers/bdl_boxscore/job-config.env"
    echo ""
    echo "Available jobs:"
    find backfill_jobs/scrapers/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/scrapers/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found yet"
    exit 1
fi

JOB_INPUT="$1"

# Auto-discover config file from job name
discover_config_file() {
    local input="$1"
    
    # If it's already a path to a file, use it directly
    if [[ -f "$input" ]]; then
        echo "$input"
        return 0
    fi
    
    # Convert job name variations to directory name
    local job_dir=""
    
    # Try various patterns to find the config
    local patterns=(
        "backfill_jobs/scrapers/${input}/job-config.env"                    # bdl_boxscore → backfill_jobs/scrapers/bdl_boxscore/job-config.env
        "backfill_jobs/scrapers/${input/_/-}/job-config.env"                # bdl_boxscore → backfill_jobs/scrapers/bdl-boxscore/job-config.env  
        "backfill_jobs/scrapers/${input//-/_}/job-config.env"               # bdl-boxscore → backfill_jobs/scrapers/bdl_boxscore/job-config.env
        "backfill_jobs/scrapers/${input%-backfill}/job-config.env"          # bdl-boxscore-backfill → backfill_jobs/scrapers/bdl-boxscore/job-config.env
        "backfill_jobs/scrapers/${input%-backfill}/job-config.env"          # bdl_boxscore_backfill → backfill_jobs/scrapers/bdl_boxscore/job-config.env
    )
    
    for pattern in "${patterns[@]}"; do
        if [[ -f "$pattern" ]]; then
            echo "$pattern"
            return 0
        fi
    done
    
    # Not found
    return 1
}

# Find the config file
CONFIG_FILE=$(discover_config_file "$JOB_INPUT")

if [[ -z "$CONFIG_FILE" ]]; then
    echo "❌ Error: Could not find config file for: $JOB_INPUT"
    echo ""
    echo "Tried looking for:"
    echo "  backfill_jobs/scrapers/${JOB_INPUT}/job-config.env"
    echo "  backfill_jobs/scrapers/${JOB_INPUT/_/-}/job-config.env"
    echo "  backfill_jobs/scrapers/${JOB_INPUT//-/_}/job-config.env"
    echo ""
    echo "Available jobs:"
    find backfill_jobs/scrapers/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/scrapers/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found yet"
    echo ""
    echo "💡 Create the config file or use explicit path:"
    echo "   $0 backfill_jobs/scrapers/your-job/job-config.env"
    exit 1
fi

echo "📁 Using config file: $CONFIG_FILE"

# Source the job-specific configuration
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "❌ Error: Config file not found: $CONFIG_FILE"
    exit 1
fi

source "$CONFIG_FILE"

# Validate required config variables
required_vars=("JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "❌ Error: $var not set in config file"
        exit 1
    fi
done

# Default values
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
SERVICE_URL="${SERVICE_URL:-https://nba-scrapers-f7p3g7f6ya-wl.a.run.app}"

# Build environment variables for the job
ENV_VARS="SCRAPER_SERVICE_URL=$SERVICE_URL"

# Add email configuration if available
if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo "✅ Adding email alerting configuration..."
    
    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Scrapers Backfill}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    
    # Alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"
    
    EMAIL_STATUS="ENABLED"
else
    echo "⚠️  Email configuration missing - email alerting will be disabled"
    EMAIL_STATUS="DISABLED"
fi

echo "🏀 Deploying Scraper Backfill Job: $JOB_NAME"
echo "=============================================="
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION"
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo ""

# Verify required files exist
if [[ ! -f "$JOB_SCRIPT" ]]; then
    echo "❌ Error: Job script not found: $JOB_SCRIPT"
    exit 1
fi

if [[ ! -f "docker/backfill.Dockerfile" ]]; then
    echo "❌ Error: Consolidated Dockerfile not found: docker/backfill.Dockerfile"
    echo "   Make sure you've set up the consolidated Docker infrastructure"
    echo "   Run: ./bin/setup/setup_consolidated_docker.sh"
    exit 1
fi

echo "✅ Required files found"

# Build the job image using parameterized Dockerfile
IMAGE_NAME="gcr.io/$PROJECT_ID/$JOB_NAME"
echo ""
echo "🏗️ Building job image..."
echo "   Using: docker/backfill.Dockerfile"
echo "   Job script: $JOB_SCRIPT"

# Build with job script as build argument
gcloud builds submit . \
    --config=<(cat <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: [
    'build',
    '-f', 'docker/backfill.Dockerfile',
    '--build-arg', 'JOB_SCRIPT=$JOB_SCRIPT',
    '--build-arg', 'JOB_NAME=$JOB_NAME',
    '-t', '$IMAGE_NAME',
    '.'
  ]
- name: 'gcr.io/cloud-builders/docker'
  args: ['push', '$IMAGE_NAME']
options:
  logging: CLOUD_LOGGING_ONLY
timeout: '600s'
EOF
) \
    --project="$PROJECT_ID" \
    --quiet

echo "✅ Image built and pushed successfully"

# Delete existing job and create new one
echo ""
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "📝 Job exists - deleting and recreating..."
    gcloud run jobs delete "$JOB_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --quiet
    echo "   ✅ Old job deleted"
fi

echo "🆕 Creating Cloud Run job..."
gcloud run jobs create "$JOB_NAME" \
    --image="$IMAGE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --task-timeout="$TASK_TIMEOUT" \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="$ENV_VARS" \
    --quiet

echo ""
echo "✅ Job deployed successfully!"

echo ""
echo "📧 Email Alerting Status: $EMAIL_STATUS"
if [[ "$EMAIL_STATUS" = "ENABLED" ]]; then
    echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
    echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "   From Email: ${BREVO_FROM_EMAIL}"
fi

echo ""
echo "🧪 To test with dry run:"
echo "   gcloud run jobs execute $JOB_NAME --args=\"--dry-run\" --region=$REGION"
echo ""
echo "🚀 To start the full backfill:"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   ./bin/scrapers/monitoring/$(echo $JOB_NAME | tr '-' '_')_monitor.sh"
echo ""
echo "🔍 To validate data:"
echo "   ./bin/scrapers/validation/validate_$(echo $JOB_NAME | tr '-' '_').sh recent 5"
echo ""
echo "🎯 Next time, deploy even faster:"
echo "   $0 $(basename "$(dirname "$CONFIG_FILE")")"