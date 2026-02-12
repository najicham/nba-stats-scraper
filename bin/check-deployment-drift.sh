#!/bin/bash
# bin/check-deployment-drift.sh
#
# Check for deployment drift - services that may have stale code deployed
#
# Usage:
#   ./bin/check-deployment-drift.sh              # Check all services
#   ./bin/check-deployment-drift.sh --verbose    # Include git history details
#
# This script compares:
#   1. When each Cloud Run service was last deployed
#   2. When the source code for that service was last modified
#   3. Reports services that may need redeployment

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

VERBOSE="${1:-}"

# Map services to their source directories
# Add new services here as they're created
declare -A SERVICE_SOURCES=(
    # Predictions
    ["prediction-worker"]="predictions/worker shared"
    ["prediction-coordinator"]="predictions/coordinator shared"

    # NBA Processing
    ["nba-phase1-scrapers"]="scrapers"
    ["nba-phase2-raw-processors"]="data_processors/phase2"
    ["nba-phase3-analytics-processors"]="data_processors/phase3 shared"
    ["nba-phase4-precompute-processors"]="data_processors/phase4 shared"

    # Grading
    ["nba-grading-service"]="data_processors/grading/nba shared predictions/shared"

    # Cloud Functions (Session 209: fixed source paths)
    ["phase3-to-phase4-orchestrator"]="orchestration/cloud_functions/phase3_to_phase4"
    ["phase4-to-phase5-orchestrator"]="orchestration/cloud_functions/phase4_to_phase5"
    ["phase5-to-phase6-orchestrator"]="orchestration/cloud_functions/phase5_to_phase6"
    ["phase5b-grading"]="orchestration/cloud_functions/grading"

    # Admin
    ["nba-admin-dashboard"]="admin_dashboard"
)

echo -e "${BLUE}=== Deployment Drift Check ===${NC}"
echo "Project: $PROJECT_ID | Region: $REGION"
echo "Checking $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# Get git repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
cd "$REPO_ROOT"

drift_found=0
total_checked=0

for service in "${!SERVICE_SOURCES[@]}"; do
    source_dirs="${SERVICE_SOURCES[$service]}"

    # Session 209: Detect if this is a Cloud Function (has "orchestrator" or "grading" in name)
    is_function=false
    if [[ "$service" == *"orchestrator"* ]] || [[ "$service" == *"grading"* ]]; then
        is_function=true
    fi

    # Get deployment info (different for Cloud Run vs Cloud Function)
    if [ "$is_function" = true ]; then
        # Cloud Function - use gcloud functions describe
        deploy_info=$(gcloud functions describe "$service" \
            --region="$REGION" \
            --gen2 \
            --project="$PROJECT_ID" \
            --format='value(updateTime)' 2>/dev/null || echo "NOT_FOUND")

        # Try to get BUILD_COMMIT from labels (Session 209: commit-based tracking)
        deployed_commit=$(gcloud functions describe "$service" \
            --region="$REGION" \
            --gen2 \
            --project="$PROJECT_ID" \
            --format='value(labels.commit-sha)' 2>/dev/null || echo "")
    else
        # Cloud Run Service
        deploy_info=$(gcloud run revisions list --service="$service" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --limit=1 \
            --format='value(metadata.creationTimestamp)' 2>/dev/null || echo "NOT_FOUND")

        # Try to get BUILD_COMMIT from labels (Session 209)
        deployed_commit=$(gcloud run services describe "$service" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --format='value(metadata.labels.commit-sha)' 2>/dev/null || echo "")
    fi

    if [ "$deploy_info" = "NOT_FOUND" ] || [ -z "$deploy_info" ]; then
        echo -e "${YELLOW}⚠️  $service: Service not found${NC}"
        continue
    fi

    # Convert deployment timestamp to epoch
    deploy_epoch=$(date -d "$deploy_info" +%s 2>/dev/null || echo "0")
    deploy_date=$(date -d "@$deploy_epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")

    # Get latest commit timestamp affecting the source directories
    latest_commit=""
    latest_commit_epoch=0

    for dir in $source_dirs; do
        if [ -d "$dir" ]; then
            commit_info=$(git log -1 --format="%H %at %s" -- "$dir" 2>/dev/null || echo "")
            if [ -n "$commit_info" ]; then
                commit_epoch=$(echo "$commit_info" | cut -d' ' -f2)
                if [ "$commit_epoch" -gt "$latest_commit_epoch" ]; then
                    latest_commit_epoch=$commit_epoch
                    latest_commit=$(echo "$commit_info" | cut -d' ' -f1)
                fi
            fi
        fi
    done

    if [ "$latest_commit_epoch" = "0" ]; then
        echo -e "${YELLOW}⚠️  $service: Could not determine source code timestamps${NC}"
        continue
    fi

    latest_commit_date=$(date -d "@$latest_commit_epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")

    total_checked=$((total_checked + 1))

    # Session 209: Use commit-based comparison if BUILD_COMMIT label available
    if [ -n "$deployed_commit" ] && [ "$deployed_commit" != "unknown" ]; then
        # Commit-based comparison
        current_commit=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

        if [ "$deployed_commit" != "$current_commit" ]; then
            # Check if there are changes in source dirs since deployed commit
            changes=$(git log --oneline "${deployed_commit}..HEAD" -- $source_dirs 2>/dev/null || echo "")

            if [ -n "$changes" ]; then
                drift_found=$((drift_found + 1))
                echo -e "${RED}❌ $service: STALE DEPLOYMENT (commit mismatch)${NC}"
                echo "   Deployed:  commit $deployed_commit"
                echo "   Current:   commit $current_commit"
                echo "   Last change: $latest_commit_date"

                if [ "$VERBOSE" = "--verbose" ]; then
                    echo "   Recent commits affecting service:"
                    echo "$changes" | head -5 | sed 's/^/      /'
                fi
                echo ""
            else
                echo -e "${GREEN}✓ $service: Up to date${NC} (commit $deployed_commit, deployed $deploy_date)"
            fi
        else
            echo -e "${GREEN}✓ $service: Up to date${NC} (commit $deployed_commit, deployed $deploy_date)"
        fi
    else
        # Timestamp-based comparison (fallback for services without BUILD_COMMIT)
        if [ "$latest_commit_epoch" -gt "$deploy_epoch" ]; then
            drift_found=$((drift_found + 1))
            echo -e "${RED}❌ $service: STALE DEPLOYMENT${NC}"
            echo "   Deployed:    $deploy_date"
            echo "   Code changed: $latest_commit_date"

            if [ "$VERBOSE" = "--verbose" ]; then
                # Show commits since deployment
                echo "   Recent commits:"
                git log --oneline --since="@$deploy_epoch" -- $source_dirs 2>/dev/null | head -5 | sed 's/^/      /'
            fi
            echo ""
        else
            echo -e "${GREEN}✓ $service: Up to date${NC} (deployed $deploy_date)"
        fi
    fi
done

echo ""
echo "=== Model Registry Validation ==="
echo "Checking if deployed model matches GCS manifest..."

# Get deployed model path from prediction-worker env vars
DEPLOYED_MODEL=$(gcloud run services describe prediction-worker \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format='value(spec.template.spec.containers[0].env)' 2>/dev/null | \
    tr ';' '\n' | grep "CATBOOST_V9_MODEL_PATH" | grep -o "gs://[^']*" || echo "")

if [ -z "$DEPLOYED_MODEL" ]; then
    echo -e "${YELLOW}⚠️  Could not retrieve CATBOOST_V9_MODEL_PATH from prediction-worker${NC}"
else
    # Get production model from GCS manifest
    MANIFEST_MODEL=$(gsutil cat gs://nba-props-platform-models/catboost/v9/manifest.json 2>/dev/null | python3 -c "
import json, sys
try:
    manifest = json.load(sys.stdin)
    prod_model = manifest.get('production_model', '')
    if prod_model:
        # Construct full GCS path
        print(f'gs://nba-props-platform-models/catboost/v9/{prod_model}.cbm')
except:
    pass
" || echo "")

    if [ -z "$MANIFEST_MODEL" ]; then
        echo -e "${YELLOW}⚠️  Could not retrieve production model from GCS manifest${NC}"
    else
        # Compare deployed vs manifest
        if [ "$DEPLOYED_MODEL" = "$MANIFEST_MODEL" ]; then
            echo -e "${GREEN}✓ Model deployment matches manifest${NC}"
            echo "   Deployed: $(basename "$DEPLOYED_MODEL")"
        else
            echo -e "${RED}❌ MODEL DRIFT DETECTED${NC}"
            echo "   Deployed:  $(basename "$DEPLOYED_MODEL")"
            echo "   Manifest:  $(basename "$MANIFEST_MODEL")"
            echo ""
            echo "To fix, update the env var:"
            echo "  gcloud run services update prediction-worker --region=us-west2 \\"
            echo "    --update-env-vars=\"CATBOOST_V9_MODEL_PATH=$MANIFEST_MODEL\""
            drift_found=$((drift_found + 1))
        fi
    fi
fi

echo ""
echo "=== Summary ==="
echo "Services checked: $total_checked"
if [ "$drift_found" -gt 0 ]; then
    echo -e "${RED}Services with drift: $drift_found${NC}"
    echo ""
    echo "Run the following to see what changed:"
    echo "  git log --oneline --since='2 days ago' -- <source_dir>"
    exit 1
else
    echo -e "${GREEN}All services up to date!${NC}"
    exit 0
fi
