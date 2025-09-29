#!/bin/bash
# File: bin/shared/deploy_common.sh
# Shared deployment functions for NBA processing jobs

# Function to discover config file from job name
discover_config_file() {
    local job_type="$1"
    local input="$2"
    
    # If it's already a path to a file, use it directly
    if [[ -f "$input" ]]; then
        echo "$input"
        return 0
    fi
    
    # Convert job name variations to directory name
    local patterns=(
        "backfill_jobs/${job_type}/${input}/job-config.env"                    # gamebook_registry → backfill_jobs/reference/gamebook_registry/job-config.env
        "backfill_jobs/${job_type}/${input/_/-}/job-config.env"                # gamebook_registry → backfill_jobs/reference/gamebook-registry/job-config.env  
        "backfill_jobs/${job_type}/${input//-/_}/job-config.env"               # gamebook-registry → backfill_jobs/reference/gamebook_registry/job-config.env
        "backfill_jobs/${job_type}/${input%-backfill}/job-config.env"          # gamebook-registry-backfill → backfill_jobs/reference/gamebook-registry/job-config.env
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

# Function to validate required variables from config file
validate_required_vars() {
    local config_file="$1"
    shift
    local required_vars=("$@")
    
    local missing_vars=()
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo "❌ Error: Missing required variables in $config_file:"
        printf '   %s\n' "${missing_vars[@]}"
        exit 1
    fi
}

# Function to verify required files exist
verify_required_files() {
    local job_script="$1"
    local dockerfile="$2"
    
    if [[ ! -f "$job_script" ]]; then
        echo "❌ Error: Job script not found: $job_script"
        exit 1
    fi
    
    if [[ ! -f "$dockerfile" ]]; then
        echo "❌ Error: Dockerfile not found: $dockerfile"
        exit 1
    fi
    
    echo "✅ Required files verified"
}

# Background function that shows continuous progress with real-time timer
show_continuous_progress() {
    local start_time="$1"
    local phases=("Uploading source code" "Starting build" "Downloading base image" "Installing dependencies" "Building application" "Creating layers" "Pushing to registry" "Finalizing")
    local phase_times=(10 20 30 50 80 110 140 160)  # Time thresholds for each phase
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        local minutes=$((elapsed / 60))
        local seconds=$((elapsed % 60))
        local timestamp="[$(printf "%02d:%02d" "$minutes" "$seconds")]"
        
        # Determine current phase based on elapsed time
        local current_phase="Building..."
        for i in "${!phase_times[@]}"; do
            if [[ $elapsed -ge ${phase_times[$i]} ]]; then
                if [[ $((i + 1)) -lt ${#phases[@]} ]]; then
                    current_phase="${phases[$((i + 1))]}"
                else
                    current_phase="Finalizing build"
                fi
            fi
        done
        
        # Show progress every second
        printf "\r\033[K%s %s" "$timestamp" "$current_phase" >&2
        
        sleep 1
    done
}

# Function to build and push Docker image with full timing and progress display
build_and_push_image() {
    local dockerfile="$1"
    local job_script="$2"
    local job_name="$3"
    local project_id="$4"
    
    local image_name="gcr.io/$project_id/$job_name"
    local build_start=$(date +%s)
    local build_start_display=$(date '+%H:%M:%S')
    
    # Display build info to stderr (so it doesn't interfere with image name return)
    echo "" >&2
    echo "🏗️ Building job image..." >&2
    echo "   Using: $dockerfile" >&2
    echo "   Job script: $job_script" >&2
    echo "   Image: $image_name" >&2
    echo "   Started: $build_start_display" >&2
    echo "" >&2
    
    # Start progress indicator in background
    show_continuous_progress "$build_start" &
    local progress_pid=$!
    
    # Ensure progress background process is killed when function exits
    trap "kill $progress_pid 2>/dev/null" RETURN
    
    # Run build (remove --quiet to see detailed output processed in background)
    gcloud builds submit . \
        --config=<(cat <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: [
    'build',
    '-f', '$dockerfile',
    '--build-arg', 'JOB_SCRIPT=$job_script',
    '--build-arg', 'JOB_NAME=$job_name',
    '-t', '$image_name',
    '.'
  ]
- name: 'gcr.io/cloud-builders/docker'
  args: ['push', '$image_name']
options:
  logging: CLOUD_LOGGING_ONLY
timeout: '600s'
EOF
) \
        --project="$project_id" >/dev/null 2>&1
    
    local build_result=$?
    
    # Stop progress indicator
    kill $progress_pid 2>/dev/null
    wait $progress_pid 2>/dev/null
    
    # Calculate and display timing summary
    local build_end=$(date +%s)
    local build_duration=$((build_end - build_start))
    local minutes=$((build_duration / 60))
    local seconds=$((build_duration % 60))
    
    printf "\r\033[K" >&2  # Clear progress line
    echo "" >&2
    
    if [[ $build_result -eq 0 ]]; then
        echo "✅ Successfully built in $(printf "%02d:%02d" "$minutes" "$seconds")" >&2
        echo "   Image: $image_name" >&2
        echo "" >&2
        
        # Only echo the image name to stdout (this gets captured by $(...))
        echo "$image_name"
        return 0
    else
        echo "❌ Build failed after $(printf "%02d:%02d" "$minutes" "$seconds")" >&2
        return 1
    fi
}

# Function to deploy Cloud Run job
deploy_cloud_run_job() {
    local job_name="$1"
    local image_name="$2"
    local region="$3"
    local project_id="$4"
    local task_timeout="$5"
    local memory="$6"
    local cpu="$7"
    local env_vars="$8"
    
    # Delete existing job if it exists
    if gcloud run jobs describe "$job_name" --region="$region" --project="$project_id" &>/dev/null; then
        echo "📝 Job exists - deleting and recreating..."
        gcloud run jobs delete "$job_name" \
            --region="$region" \
            --project="$project_id" \
            --quiet
        echo "   ✅ Old job deleted"
    fi
    
    echo "🆕 Creating Cloud Run job..."
    echo "   Job Name: $job_name"
    echo "   Image: $image_name"
    echo "   Memory: $memory"
    echo "   CPU: $cpu"
    echo "   Timeout: $task_timeout"
    
    # Build the gcloud command
    local gcloud_cmd="gcloud run jobs create \"$job_name\""
    gcloud_cmd="$gcloud_cmd --image=\"$image_name\""
    gcloud_cmd="$gcloud_cmd --region=\"$region\""
    gcloud_cmd="$gcloud_cmd --project=\"$project_id\""
    gcloud_cmd="$gcloud_cmd --task-timeout=\"$task_timeout\""
    gcloud_cmd="$gcloud_cmd --memory=\"$memory\""
    gcloud_cmd="$gcloud_cmd --cpu=\"$cpu\""
    gcloud_cmd="$gcloud_cmd --max-retries=1"
    gcloud_cmd="$gcloud_cmd --tasks=1"
    gcloud_cmd="$gcloud_cmd --quiet"
    
    # Add environment variables if provided
    if [[ -n "$env_vars" ]]; then
        gcloud_cmd="$gcloud_cmd --set-env-vars=\"$env_vars\""
        echo "   Environment variables: ${#env_vars} characters"
    fi
    
    # Execute the command
    eval "$gcloud_cmd"
    
    if [[ $? -eq 0 ]]; then
        echo "✅ Cloud Run job created successfully"
        return 0
    else
        echo "❌ Failed to create Cloud Run job"
        return 1
    fi
}

# Function to check email configuration and add to environment variables
add_email_config_to_env_vars() {
    local env_vars="$1"
    
    # Check if email variables are available
    if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
        echo "✅ Adding email alerting configuration..."
        
        # Add email-related environment variables
        env_vars="$env_vars,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
        env_vars="$env_vars,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
        env_vars="$env_vars,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
        env_vars="$env_vars,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
        env_vars="$env_vars,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
        env_vars="$env_vars,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Registry System}"
        env_vars="$env_vars,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
        env_vars="$env_vars,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
        
        # Optional alert thresholds
        env_vars="$env_vars,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
        env_vars="$env_vars,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
        env_vars="$env_vars,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"
        
        echo "$env_vars"
        return 0
    else
        echo "⚠️  Email configuration missing - email alerting will be disabled"
        echo "   Required: BREVO_SMTP_PASSWORD and EMAIL_ALERTS_TO in .env file"
        echo "$env_vars"
        return 1
    fi
}

# Function to display email configuration status
display_email_status() {
    if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
        echo "📧 Email Alerting Status: ENABLED"
        echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
        echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
        echo "   From Email: ${BREVO_FROM_EMAIL}"
        echo "   SMTP Host: ${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
        return 0
    else
        echo "📧 Email Alerting Status: DISABLED"
        echo "   Missing required environment variables in .env file"
        return 1
    fi
}

# Function to load environment variables from .env file
load_env_file() {
    if [ -f ".env" ]; then
        echo "📄 Loading environment variables from .env file..."
        export $(grep -v '^#' .env | grep -v '^$' | xargs)
        echo "✅ Environment variables loaded"
        return 0
    else
        echo "⚠️  No .env file found - email alerting may not work"
        return 1
    fi
}

# Function to test email configuration
test_email_config() {
    echo "🧪 Testing email configuration..."
    
    if [[ -z "$BREVO_SMTP_HOST" ]]; then
        echo "❌ BREVO_SMTP_HOST not set"
        return 1
    fi
    
    if [[ -z "$BREVO_SMTP_USERNAME" ]]; then
        echo "❌ BREVO_SMTP_USERNAME not set"
        return 1
    fi
    
    if [[ -z "$BREVO_SMTP_PASSWORD" ]]; then
        echo "❌ BREVO_SMTP_PASSWORD not set"
        return 1
    fi
    
    if [[ -z "$BREVO_FROM_EMAIL" ]]; then
        echo "❌ BREVO_FROM_EMAIL not set"
        return 1
    fi
    
    if [[ -z "$EMAIL_ALERTS_TO" ]]; then
        echo "❌ EMAIL_ALERTS_TO not set"
        return 1
    fi
    
    echo "✅ All required email configuration variables are set"
    echo "   SMTP Host: $BREVO_SMTP_HOST"
    echo "   SMTP Port: ${BREVO_SMTP_PORT:-587}"
    echo "   Username: $BREVO_SMTP_USERNAME"
    echo "   From Email: $BREVO_FROM_EMAIL"
    echo "   Alert Recipients: $EMAIL_ALERTS_TO"
    
    return 0
}