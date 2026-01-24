#!/bin/bash
# File: bin/utilities/test_deployment_system.sh
# Test the deployment system infrastructure

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
REGION="${REGION:-us-west2}"

echo "NBA Props Platform - Deployment System Test"
echo "==========================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Test 1: Check shared library exists and is functional
echo "🧪 Test 1: Shared Library Validation"
echo "------------------------------------"

if [[ ! -f "bin/shared/deploy_common.sh" ]]; then
    echo "❌ FAIL: Shared library not found: bin/shared/deploy_common.sh"
    exit 1
fi

# Source the library and test a function
source bin/shared/deploy_common.sh

echo "✅ PASS: Shared library found and sourced"

# Test discover_config_file function
if command -v discover_config_file >/dev/null 2>&1; then
    echo "✅ PASS: discover_config_file function available"
else
    echo "❌ FAIL: discover_config_file function not found"
    exit 1
fi

echo ""

# Test 2: Check deployment scripts exist
echo "🧪 Test 2: Deployment Scripts Validation"
echo "----------------------------------------"

scripts=(
    "bin/reference/deploy/deploy_reference_processor_backfill.sh"
    "bin/analytics/deploy/deploy_analytics_processor_backfill.sh"
    "bin/raw/deploy/deploy_processor_backfill_job.sh"
)

for script in "${scripts[@]}"; do
    if [[ -f "$script" ]]; then
        echo "✅ PASS: $script exists"
        # Test if it can source the shared library
        if grep -q "source.*deploy_common.sh" "$script"; then
            echo "✅ PASS: $script sources shared library"
        else
            echo "⚠️  WARN: $script doesn't source shared library"
        fi
    else
        echo "❌ FAIL: $script not found"
    fi
done

echo ""

# Test 3: Check Docker files
echo "🧪 Test 3: Docker Configuration Validation"
echo "------------------------------------------"

dockerfiles=(
    "docker/processor.Dockerfile"
    "docker/reference.Dockerfile"
    "docker/analytics.Dockerfile"
)

for dockerfile in "${dockerfiles[@]}"; do
    if [[ -f "$dockerfile" ]]; then
        echo "✅ PASS: $dockerfile exists"
    else
        echo "⚠️  WARN: $dockerfile not found (will use processor.Dockerfile)"
    fi
done

echo ""

# Test 4: Check job configurations
echo "🧪 Test 4: Job Configuration Validation"
echo "---------------------------------------"

# Check for job configurations
reference_jobs=$(find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | wc -l)
analytics_jobs=$(find backfill_jobs/analytics/ -name "job-config.env" 2>/dev/null | wc -l)
raw_jobs=$(find backfill_jobs/raw/ -name "job-config.env" 2>/dev/null | wc -l)

echo "Reference jobs configured: $reference_jobs"
echo "Analytics jobs configured: $analytics_jobs"
echo "Raw jobs configured: $raw_jobs"

if [[ $reference_jobs -gt 0 ]]; then
    echo "✅ PASS: Reference jobs found"
    
    # Test one reference job config
    first_ref_config=$(find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | head -1)
    if [[ -n "$first_ref_config" ]]; then
        echo "Testing config: $first_ref_config"
        source "$first_ref_config"
        
        required_vars=("JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU")
        config_valid=true
        
        for var in "${required_vars[@]}"; do
            if [[ -z "${!var}" ]]; then
                echo "❌ FAIL: Required variable $var not set in $first_ref_config"
                config_valid=false
            fi
        done
        
        if [[ "$config_valid" == true ]]; then
            echo "✅ PASS: Reference job config validation successful"
        fi
    fi
else
    echo "⚠️  WARN: No reference jobs configured"
fi

echo ""

# Test 5: GCP Authentication
echo "🧪 Test 5: GCP Authentication & Access"
echo "--------------------------------------"

if gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 >/dev/null 2>&1; then
    active_account=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1)
    echo "✅ PASS: Authenticated as $active_account"
    
    # Test project access
    if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
        echo "✅ PASS: Can access project $PROJECT_ID"
    else
        echo "❌ FAIL: Cannot access project $PROJECT_ID"
    fi
    
    # Test Cloud Run access
    if gcloud run jobs list --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
        echo "✅ PASS: Can access Cloud Run in $REGION"
    else
        echo "❌ FAIL: Cannot access Cloud Run in $REGION"
    fi
    
else
    echo "❌ FAIL: Not authenticated with gcloud"
    echo "Run: gcloud auth login"
fi

echo ""

# Test 6: Utility Scripts
echo "🧪 Test 6: Utility Scripts Validation"
echo "-------------------------------------"

utilities=(
    "bin/utilities/deployment_status.sh"
    "bin/utilities/list_deployable_jobs.sh"
)

for utility in "${utilities[@]}"; do
    if [[ -f "$utility" ]]; then
        echo "✅ PASS: $utility exists"
        if [[ -x "$utility" ]]; then
            echo "✅ PASS: $utility is executable"
        else
            echo "⚠️  WARN: $utility is not executable (run: chmod +x $utility)"
        fi
    else
        echo "⚠️  INFO: $utility not found (optional utility)"
    fi
done

echo ""

# Summary
echo "🏁 Test Summary"
echo "==============="
echo ""

# Provide next steps based on test results
if [[ $reference_jobs -gt 0 ]]; then
    echo "Ready to test deployment! Try:"
    echo ""
    
    first_job_dir=$(find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | head -1 | xargs dirname | xargs basename)
    if [[ -n "$first_job_dir" ]]; then
        echo "  ./bin/reference/deploy/deploy_reference_processor_backfill.sh $first_job_dir"
        echo ""
        echo "  # Then test with summary mode:"
        source "$(find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | head -1)"
        echo "  gcloud run jobs execute $JOB_NAME --args=--summary-only --region=$REGION"
    fi
else
    echo "No jobs configured yet. Next steps:"
    echo "  1. Create job configuration files in backfill_jobs/"
    echo "  2. Test deployment with a simple job"
fi

echo ""
echo "Available utilities:"
echo "  ./bin/utilities/deployment_status.sh      # Check deployed jobs"
echo "  ./bin/utilities/list_deployable_jobs.sh   # List available jobs"