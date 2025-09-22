#!/bin/bash
# File: bin/shared/deploy_common.sh
# Common deployment functions for all processor types

set -e

# Common configuration discovery
discover_config_file() {
    local processor_type="$1"
    local input="$2"
    
    if [[ -f "$input" ]]; then
        echo "$input"
        return 0
    fi
    
    local patterns=(
        "backfill_jobs/${processor_type}/${input}/job-config.env"
        "backfill_jobs/${processor_type}/${input/_/-}/job-config.env"  
        "backfill_jobs/${processor_type}/${input//-/_}/job-config.env"
    )
    
    for pattern in "${patterns[@]}"; do
        if [[ -f "$pattern" ]]; then
            echo "$pattern"
            return 0
        fi
    done
    
    return 1
}

# Build function with background progress timer
build_and_push_image() {
    local dockerfile="$1"
    local job_script="$2" 
    local job_name="$3"
    local project_id="$4"
    local image_name="gcr.io/$project_id/$job_name"
    
    echo "Building and pushing image: $image_name" >&2
    echo "Started at: $(date '+%H:%M:%S')" >&2
    
    local build_start=$(date +%s)
    
    # Start background progress timer
    show_continuous_progress "$build_start" &
    local progress_pid=$!
    
    # Run build and capture exit code
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
        --project="$project_id" \
        --quiet >/dev/null 2>&1
    
    local build_exit_code=$?
    
    # Stop background progress
    kill $progress_pid 2>/dev/null
    wait $progress_pid 2>/dev/null
    
    local build_end=$(date +%s)
    local build_duration=$((build_end - build_start))
    
    echo "" >&2  # New line after progress
    
    if [ $build_exit_code -eq 0 ]; then
        echo "Build completed successfully in ${build_duration}s" >&2
        echo "$image_name"  # ONLY return image name to stdout
        return 0
    else
        echo "Build failed after ${build_duration}s" >&2
        return 1
    fi
}

# Background function that shows continuous progress
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

# Remove the old parse_build_progress function since we're not using it anymore

# Common Cloud Run deployment
deploy_cloud_run_job() {
    local job_name="$1"
    local image_name="$2"
    local region="$3"
    local project_id="$4"
    local task_timeout="$5"
    local memory="$6" 
    local cpu="$7"
    local env_vars="$8"
    
    echo ""
    if gcloud run jobs describe "$job_name" --region="$region" --project="$project_id" &>/dev/null; then
        echo "Updating existing job..."
        gcloud run jobs update "$job_name" \
            --image="$image_name" \
            --region="$region" \
            --project="$project_id" \
            --task-timeout="$task_timeout" \
            --memory="$memory" \
            --cpu="$cpu" \
            --max-retries=1 \
            --tasks=1 \
            --set-env-vars="$env_vars" \
            --quiet
    else
        echo "Creating new job..."
        gcloud run jobs create "$job_name" \
            --image="$image_name" \
            --region="$region" \
            --project="$project_id" \
            --task-timeout="$task_timeout" \
            --memory="$memory" \
            --cpu="$cpu" \
            --max-retries=1 \
            --tasks=1 \
            --set-env-vars="$env_vars" \
            --quiet
    fi
}

# Common validation
validate_required_vars() {
    local config_file="$1"
    shift
    local required_vars=("$@")
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            echo "Error: $var not set in config file: $config_file"
            exit 1
        fi
    done
}

# Common file verification
verify_required_files() {
    local job_script="$1"
    local dockerfile="$2"
    
    if [[ ! -f "$job_script" ]]; then
        echo "Error: Job script not found: $job_script"
        exit 1
    fi
    
    if [[ ! -f "$dockerfile" ]]; then
        echo "Error: Dockerfile not found: $dockerfile"
        exit 1
    fi
    
    echo "Required files found"
}