#!/bin/bash
# File: bin/reference/deploy/deploy_reference_processors.sh
# Deploy reference processor service to Cloud Run (name resolution system)

SERVICE_NAME="nba-reference-processors"
REGION="us-west2"

# Start timing
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "Deploying NBA Reference Processors Service"
echo "=========================================="
echo "Start time: $DEPLOY_START_DISPLAY"

# Function to show elapsed time
show_elapsed_time() {
    local start_time="$1"
    local current_time=$(date +%s)
    local elapsed=$((current_time - start_time))
    local minutes=$((elapsed / 60))
    local seconds=$((elapsed % 60))
    printf "[%02d:%02d]" "$minutes" "$seconds"
}

# Phase 1: Setup with proper timing
SETUP_START=$(date +%s)
echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 1: Setup starting..."

# Check for reference Dockerfile in the correct location
REFERENCE_DOCKERFILE="docker/reference-service.Dockerfile"
if [ ! -f "$REFERENCE_DOCKERFILE" ]; then
    echo "$(show_elapsed_time $DEPLOY_START_TIME) Reference Dockerfile not found at $REFERENCE_DOCKERFILE"
    echo "$(show_elapsed_time $DEPLOY_START_TIME) ERROR: Reference service Dockerfile is required!"
    exit 1
else
    echo "$(show_elapsed_time $DEPLOY_START_TIME) Using docker/reference-service.Dockerfile"
fi

# Copy Dockerfile to root
echo "$(show_elapsed_time $DEPLOY_START_TIME) Copying $REFERENCE_DOCKERFILE to root..."
cp "$REFERENCE_DOCKERFILE" ./Dockerfile

# Verify required reference files exist
echo "$(show_elapsed_time $DEPLOY_START_TIME) Verifying reference files..."
REQUIRED_FILES=(
    "data_processors/reference/__init__.py"
    "data_processors/reference/main_reference_service.py"
    "shared/requirements.txt"
    "data_processors/reference/requirements.txt"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "$(show_elapsed_time $DEPLOY_START_TIME) ERROR: Required file missing: $file"
        echo "$(show_elapsed_time $DEPLOY_START_TIME) Cannot proceed with deployment"
        rm -f ./Dockerfile
        exit 1
    fi
done

echo "$(show_elapsed_time $DEPLOY_START_TIME) All required files found"

SETUP_END=$(date +%s)
SETUP_DURATION=$((SETUP_END - SETUP_START))
echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 1 completed in ${SETUP_DURATION}s"

# Phase 2: Deployment with real-time progress
DEPLOY_PHASE_START=$(date +%s)
echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 2: Cloud Run deployment starting..."

# Start deployment in background and track progress
(
    gcloud run deploy $SERVICE_NAME \
        --source=. \
        --region=$REGION \
        --platform=managed \
        --no-allow-unauthenticated \
        --port=8080 \
        --memory=4Gi \
        --cpu=2 \
        --timeout=1800 \
        --concurrency=1 \
        --min-instances=0 \
        --max-instances=3 \
        --set-env-vars="GCP_PROJECT_ID=nba-props-platform,BUCKET_NAME=nba-scraped-data" \
        > /tmp/deploy_output.log 2>&1
    echo $? > /tmp/deploy_status.txt
) &

DEPLOY_PID=$!

# Show real-time progress
while kill -0 $DEPLOY_PID 2>/dev/null; do
    printf "\r$(show_elapsed_time $DEPLOY_START_TIME) Cloud Run deployment in progress..."
    sleep 2
done

wait $DEPLOY_PID
DEPLOY_STATUS=$(cat /tmp/deploy_status.txt 2>/dev/null || echo "1")
DEPLOY_PHASE_END=$(date +%s)
DEPLOY_PHASE_DURATION=$((DEPLOY_PHASE_END - DEPLOY_PHASE_START))

echo ""
echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 2 completed in ${DEPLOY_PHASE_DURATION}s"

# Phase 3: Cleanup
CLEANUP_START=$(date +%s)
echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 3: Cleaning up temporary Dockerfile..."
rm -f ./Dockerfile
CLEANUP_END=$(date +%s)
CLEANUP_DURATION=$((CLEANUP_END - CLEANUP_START))
echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 3 completed in ${CLEANUP_DURATION}s"

# Calculate total time
DEPLOY_END_TIME=$(date +%s)
TOTAL_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))
DEPLOY_END_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

# Format duration nicely
format_duration() {
    local duration="$1"
    if [ $duration -lt 60 ]; then
        echo "${duration}s"
    elif [ $duration -lt 3600 ]; then
        local minutes=$((duration / 60))
        local seconds=$((duration % 60))
        echo "${minutes}m ${seconds}s"
    else
        local hours=$((duration / 3600))
        local minutes=$(((duration % 3600) / 60))
        local seconds=$((duration % 60))
        echo "${hours}h ${minutes}m ${seconds}s"
    fi
}

DURATION_DISPLAY=$(format_duration $TOTAL_DURATION)

echo ""
echo "DEPLOYMENT TIMING SUMMARY"
echo "========================"
echo "Start:      $DEPLOY_START_DISPLAY"
echo "End:        $DEPLOY_END_DISPLAY"
echo "Duration:   $DURATION_DISPLAY"
echo ""
echo "Phase Breakdown:"
echo "  Setup:      ${SETUP_DURATION}s"
echo "  Deployment: ${DEPLOY_PHASE_DURATION}s"
echo "  Cleanup:    ${CLEANUP_DURATION}s"
echo "  Total:      ${TOTAL_DURATION}s"

# Check deployment result
if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo "Deployment completed successfully in $DURATION_DISPLAY!"
    
    # Phase 4: Testing with real-time progress
    TEST_START=$(date +%s)
    echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 4: Testing health endpoint..."
    
    # Wait for service to be ready
    for i in {1..10}; do
        printf "\r$(show_elapsed_time $DEPLOY_START_TIME) Waiting for service to be ready... ${i}s"
        sleep 1
    done
    echo ""
    
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.url)" 2>/dev/null)
    
    if [ ! -z "$SERVICE_URL" ]; then
        echo "$(show_elapsed_time $DEPLOY_START_TIME) Service URL: $SERVICE_URL"
        
        # Test health endpoint
        echo "$(show_elapsed_time $DEPLOY_START_TIME) Testing health endpoint..."
        HEALTH_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X GET "$SERVICE_URL/health" \
            -H "Authorization: Bearer $(gcloud auth print-identity-token)" 2>/dev/null)
        
        HTTP_CODE=$(echo "$HEALTH_RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
        RESPONSE_BODY=$(echo "$HEALTH_RESPONSE" | grep -v "HTTP_CODE:")
        
        if [ "$HTTP_CODE" = "200" ]; then
            echo "$(show_elapsed_time $DEPLOY_START_TIME) Health check passed!"
            echo "$RESPONSE_BODY" | jq '.' 2>/dev/null || echo "$RESPONSE_BODY"
        else
            echo "$(show_elapsed_time $DEPLOY_START_TIME) Health check failed (HTTP $HTTP_CODE)"
            echo "$RESPONSE_BODY"
        fi
        
        TEST_END=$(date +%s)
        TEST_DURATION=$((TEST_END - TEST_START))
        echo "$(show_elapsed_time $DEPLOY_START_TIME) Phase 4 completed in ${TEST_DURATION}s"
        
        # Final total with test time
        FINAL_TOTAL=$((TEST_END - DEPLOY_START_TIME))
        FINAL_DURATION_DISPLAY=$(format_duration $FINAL_TOTAL)
        
        echo ""
        echo "FINAL TIMING SUMMARY"
        echo "==================="
        echo "Total time (including tests): $FINAL_DURATION_DISPLAY"
        echo "Service URL: $SERVICE_URL"
        
    fi
else
    echo ""
    echo "Deployment failed after $DURATION_DISPLAY!"
    echo "Check build logs with: gcloud beta run jobs logs read --job=$SERVICE_NAME --region=$REGION"
    
    # Show deployment output for debugging
    if [ -f /tmp/deploy_output.log ]; then
        echo ""
        echo "Deployment output:"
        cat /tmp/deploy_output.log
    fi
    
    exit 1
fi

# Cleanup temp files
rm -f /tmp/deploy_output.log /tmp/deploy_status.txt