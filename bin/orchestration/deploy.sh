#!/bin/bash
# bin/orchestration/deploy.sh
# 
# Deploy NBA Props Platform - Phase 1 Orchestration to Cloud Run
# Version: 1.0 - November 11, 2025
#
# Usage:
#   ./bin/orchestration/deploy.sh           # Full deployment
#   ./bin/orchestration/deploy.sh --update  # Update existing deployment

set -e  # Exit on error

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_NAME="nba-orchestration-service"
SERVICE_ACCOUNT="cloud-run-orchestration@${PROJECT_ID}.iam.gserviceaccount.com"

# Parse arguments
UPDATE_ONLY=false
if [[ "$1" == "--update" ]]; then
    UPDATE_ONLY=true
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 NBA Props Platform - Orchestration Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo ""
if [[ "$UPDATE_ONLY" == true ]]; then
    echo "Mode: UPDATE ONLY (Cloud Scheduler jobs)"
else
    echo "Mode: FULL DEPLOYMENT (Cloud Run + Scheduler)"
fi
echo ""

# Confirm deployment
if [[ "$UPDATE_ONLY" == false ]]; then
    read -p "Deploy orchestration to Cloud Run? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 0
    fi
fi

# Function to create or update scheduler job
create_or_update_scheduler_job() {
    local job_name=$1
    local schedule=$2
    local uri=$3
    local timeout=$4
    
    echo ""
    echo "📅 Setting up scheduler job: ${job_name}"
    echo "   Schedule: ${schedule}"
    echo "   Endpoint: ${uri}"
    
    # Try to create
    if gcloud scheduler jobs describe ${job_name} \
        --location=${REGION} \
        --project=${PROJECT_ID} &>/dev/null; then
        
        echo "   Job exists, updating..."
        gcloud scheduler jobs update http ${job_name} \
            --location=${REGION} \
            --schedule="${schedule}" \
            --time-zone="America/New_York" \
            --uri="${uri}" \
            --http-method=POST \
            --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
            --headers="Content-Type=application/json" \
            --message-body='{}' \
            --attempt-deadline=${timeout}s \
            --project=${PROJECT_ID} \
            --quiet
        
        echo "   ✅ Updated: ${job_name}"
    else
        echo "   Creating new job..."
        gcloud scheduler jobs create http ${job_name} \
            --location=${REGION} \
            --schedule="${schedule}" \
            --time-zone="America/New_York" \
            --uri="${uri}" \
            --http-method=POST \
            --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
            --headers="Content-Type=application/json" \
            --message-body='{}' \
            --attempt-deadline=${timeout}s \
            --project=${PROJECT_ID} \
            --quiet
        
        echo "   ✅ Created: ${job_name}"
    fi
}

# If update only, skip to scheduler jobs
if [[ "$UPDATE_ONLY" == true ]]; then
    echo "Skipping Cloud Run deployment (update mode)"
    
    # Get existing service URL
    SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
        --platform=managed \
        --region=${REGION} \
        --format="value(status.url)" \
        --project=${PROJECT_ID} 2>/dev/null)
    
    if [[ -z "$SERVICE_URL" ]]; then
        echo "❌ Error: Cloud Run service not found. Run without --update flag first."
        exit 1
    fi
else
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 1: Building Docker Image"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # Build and push Docker image
    gcloud builds submit \
        --config=cloudbuild_orchestration.yaml \
        --project=${PROJECT_ID}
    
    echo ""
    echo "✅ Docker image built successfully"
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 2: Deploying Cloud Run Service"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    gcloud run deploy ${SERVICE_NAME} \
        --image=gcr.io/${PROJECT_ID}/nba-orchestration:latest \
        --platform=managed \
        --region=${REGION} \
        --service-account=${SERVICE_ACCOUNT} \
        --memory=2Gi \
        --cpu=1 \
        --timeout=900 \
        --max-instances=5 \
        --min-instances=0 \
        --concurrency=10 \
        --no-allow-unauthenticated \
        --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID}" \
        --project=${PROJECT_ID}
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
        --platform=managed \
        --region=${REGION} \
        --format="value(status.url)" \
        --project=${PROJECT_ID})
    
    echo ""
    echo "✅ Cloud Run service deployed"
    echo "   URL: ${SERVICE_URL}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Creating/Updating Cloud Scheduler Jobs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create service account for Cloud Scheduler if it doesn't exist
if ! gcloud iam service-accounts describe scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com \
    --project=${PROJECT_ID} &>/dev/null; then
    
    echo "Creating scheduler service account..."
    gcloud iam service-accounts create scheduler-orchestration \
        --display-name="Cloud Scheduler - Orchestration Jobs" \
        --project=${PROJECT_ID}
    
    # Grant permission to invoke Cloud Run
    gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
        --member="serviceAccount:scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
        --role="roles/run.invoker" \
        --region=${REGION} \
        --project=${PROJECT_ID}
    
    echo "✅ Service account created"
fi

# Create/update scheduler jobs using function
# Job schedules defined here (SINGLE SOURCE OF TRUTH)

# Job 1: Daily Schedule Locker - 5 AM ET (10 AM UTC)
create_or_update_scheduler_job \
    "daily-schedule-locker" \
    "0 10 * * *" \
    "${SERVICE_URL}/generate-daily-schedule" \
    "180"

# Job 2: Master Controller - Hourly 6 AM - 11 PM ET
create_or_update_scheduler_job \
    "master-controller-hourly" \
    "0 6-23 * * *" \
    "${SERVICE_URL}/evaluate-workflows" \
    "300"

# Job 3: Cleanup Processor - Every 15 minutes
create_or_update_scheduler_job \
    "cleanup-processor" \
    "*/15 * * * *" \
    "${SERVICE_URL}/run-cleanup" \
    "180"

if [[ "$UPDATE_ONLY" == false ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 4: Testing Endpoints"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # Get auth token
    echo "Getting authentication token..."
    AUTH_TOKEN=$(gcloud auth print-identity-token)
    
    # Test health check
    echo ""
    echo "Testing health check..."
    curl -s -H "Authorization: Bearer ${AUTH_TOKEN}" \
        "${SERVICE_URL}/health" | jq '.'
    
    echo ""
    echo "✅ Service is healthy"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deployment Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Service URL: ${SERVICE_URL}"
echo ""
echo "Scheduler Jobs (America/New_York timezone):"
echo "  1. daily-schedule-locker  - 5:00 AM ET daily (10:00 UTC)"
echo "  2. master-controller      - Every hour 6 AM-11 PM ET (11:00-04:00 UTC)"
echo "  3. cleanup-processor      - Every 15 minutes"
echo ""
echo "View schedules:"
echo "  gcloud scheduler jobs list --location=${REGION}"
echo ""
echo "Update schedules only (without redeploying):"
echo "  ./bin/orchestration/deploy.sh --update"
echo ""
echo "Manual testing commands:"
echo "  ./bin/orchestration/test.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
