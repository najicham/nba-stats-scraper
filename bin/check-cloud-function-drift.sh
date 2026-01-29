#!/bin/bash
# bin/check-cloud-function-drift.sh
#
# Check for deployment drift in Cloud Functions - functions that may have stale code deployed
#
# Usage:
#   ./bin/check-cloud-function-drift.sh              # Check all functions
#   ./bin/check-cloud-function-drift.sh --verbose    # Include git history details
#
# This script compares:
#   1. When each Cloud Function was last deployed
#   2. When the source code for that function was last modified
#   3. Reports functions that may need redeployment
#   4. Flags functions with drift > 24 hours as stale

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

# Drift threshold in seconds (24 hours)
DRIFT_THRESHOLD=$((24 * 60 * 60))

# Map Cloud Functions to their source directories
# Directory names use underscores, deployed function names use hyphens
declare -A FUNCTION_SOURCES=(
    # Phase orchestrators
    ["phase2-to-phase3"]="orchestration/cloud_functions/phase2_to_phase3 shared"
    ["phase3-to-phase4-orchestrator"]="orchestration/cloud_functions/phase3_to_phase4 shared"
    ["phase4-to-phase5"]="orchestration/cloud_functions/phase4_to_phase5 shared"
    ["phase5-to-phase6"]="orchestration/cloud_functions/phase5_to_phase6 shared"

    # Backfill and auto-retry
    ["auto-backfill-orchestrator"]="orchestration/cloud_functions/auto_backfill_orchestrator shared"
    ["backfill-trigger"]="orchestration/cloud_functions/backfill_trigger shared"
    ["auto-retry-processor"]="orchestration/cloud_functions/auto_retry_processor shared"

    # Health and monitoring
    ["daily-health-check"]="orchestration/cloud_functions/daily_health_check shared"
    ["daily-health-summary"]="orchestration/cloud_functions/daily_health_summary shared"
    ["self-heal"]="orchestration/cloud_functions/self_heal shared"
    ["line-quality-self-heal"]="orchestration/cloud_functions/line_quality_self_heal shared"

    # Alerts
    ["box-score-completeness-alert"]="orchestration/cloud_functions/box_score_completeness_alert shared"
    ["game-coverage-alert"]="orchestration/cloud_functions/game_coverage_alert shared"
    ["phase4-failure-alert"]="orchestration/cloud_functions/phase4_failure_alert shared"
    ["prediction-health-alert"]="orchestration/cloud_functions/prediction_health_alert shared"
    ["grading-alert"]="orchestration/cloud_functions/grading_alert shared"
    ["data-quality-alerts"]="orchestration/cloud_functions/data_quality_alerts shared"

    # Monitors
    ["transition-monitor"]="orchestration/cloud_functions/transition_monitor shared"
    ["stale-processor-monitor"]="orchestration/cloud_functions/stale_processor_monitor shared"
    ["scraper-availability-monitor"]="orchestration/cloud_functions/scraper_availability_monitor shared"
    ["grading-readiness-monitor"]="orchestration/cloud_functions/grading_readiness_monitor shared"
    ["phase4-timeout-check"]="orchestration/cloud_functions/phase4_timeout_check shared"
    ["live-freshness-monitor"]="orchestration/cloud_functions/live_freshness_monitor shared"
    ["prediction-monitoring"]="orchestration/cloud_functions/prediction_monitoring shared"
    ["dlq-monitor"]="orchestration/cloud_functions/dlq_monitor shared"

    # Dashboards and reports
    ["pipeline-dashboard"]="orchestration/cloud_functions/pipeline_dashboard shared"
    ["scraper-dashboard"]="orchestration/cloud_functions/scraper_dashboard shared"
    ["shadow-performance-report"]="orchestration/cloud_functions/shadow_performance_report shared"

    # Cleanup and maintenance
    ["upcoming-tables-cleanup"]="orchestration/cloud_functions/upcoming_tables_cleanup shared"
    ["stale-running-cleanup"]="orchestration/cloud_functions/stale_running_cleanup shared"
    ["firestore-cleanup"]="orchestration/cloud_functions/firestore_cleanup shared"

    # Other orchestration
    ["pipeline-reconciliation"]="orchestration/cloud_functions/pipeline_reconciliation shared"
    ["phase6-export"]="orchestration/cloud_functions/phase6_export shared"
    ["grading"]="orchestration/cloud_functions/grading shared"
    ["enrichment-trigger"]="orchestration/cloud_functions/enrichment_trigger shared"
    ["news-fetcher"]="orchestration/cloud_functions/news_fetcher shared"
    ["live-export"]="orchestration/cloud_functions/live_export shared"
    ["scraper-gap-backfiller"]="orchestration/cloud_functions/scraper_gap_backfiller shared"

    # MLB functions
    ["mlb-phase3-to-phase4"]="orchestration/cloud_functions/mlb_phase3_to_phase4 shared"
    ["mlb-phase4-to-phase5"]="orchestration/cloud_functions/mlb_phase4_to_phase5 shared"
    ["mlb-phase5-to-phase6"]="orchestration/cloud_functions/mlb_phase5_to_phase6 shared"
    ["mlb-self-heal"]="orchestration/cloud_functions/mlb_self_heal shared"
)

echo -e "${BLUE}=== Cloud Function Deployment Drift Check ===${NC}"
echo "Project: $PROJECT_ID | Region: $REGION"
echo "Checking $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Drift threshold: 24 hours"
echo ""

# Get git repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
cd "$REPO_ROOT"

drift_found=0
stale_found=0
total_checked=0

for function_name in "${!FUNCTION_SOURCES[@]}"; do
    source_dirs="${FUNCTION_SOURCES[$function_name]}"

    # Get deployment timestamp using gen2 format
    deploy_info=$(gcloud functions describe "$function_name" \
        --region="$REGION" \
        --gen2 \
        --format='value(updateTime)' 2>/dev/null || echo "NOT_FOUND")

    if [ "$deploy_info" = "NOT_FOUND" ] || [ -z "$deploy_info" ]; then
        echo -e "${YELLOW}⚠️  $function_name: Function not found${NC}"
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
        echo -e "${YELLOW}⚠️  $function_name: Could not determine source code timestamps${NC}"
        continue
    fi

    latest_commit_date=$(date -d "@$latest_commit_epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")

    total_checked=$((total_checked + 1))

    # Calculate drift in seconds
    drift_seconds=$((latest_commit_epoch - deploy_epoch))

    # Compare timestamps - if code is newer than deployment, flag it
    if [ "$latest_commit_epoch" -gt "$deploy_epoch" ]; then
        drift_found=$((drift_found + 1))

        # Check if drift exceeds 24 hours
        if [ "$drift_seconds" -gt "$DRIFT_THRESHOLD" ]; then
            stale_found=$((stale_found + 1))
            drift_hours=$((drift_seconds / 3600))
            echo -e "${RED}❌ $function_name: STALE DEPLOYMENT (${drift_hours}h behind)${NC}"
        else
            drift_hours=$((drift_seconds / 3600))
            echo -e "${YELLOW}⚠️  $function_name: Drift detected (${drift_hours}h behind)${NC}"
        fi

        echo "   Deployed:    $deploy_date"
        echo "   Code changed: $latest_commit_date"

        if [ "$VERBOSE" = "--verbose" ]; then
            # Show commits since deployment
            echo "   Recent commits:"
            git log --oneline --since="@$deploy_epoch" -- $source_dirs 2>/dev/null | head -5 | sed 's/^/      /'
        fi
        echo ""
    else
        echo -e "${GREEN}✓ $function_name: Up to date${NC} (deployed $deploy_date)"
    fi
done

echo ""
echo "=== Summary ==="
echo "Functions checked: $total_checked"
if [ "$stale_found" -gt 0 ]; then
    echo -e "${RED}Functions with stale deployments (>24h): $stale_found${NC}"
elif [ "$drift_found" -gt 0 ]; then
    echo -e "${YELLOW}Functions with drift (<24h): $drift_found${NC}"
fi

if [ "$drift_found" -gt 0 ]; then
    echo ""
    echo "Run the following to see what changed:"
    echo "  git log --oneline --since='2 days ago' -- orchestration/cloud_functions/<function_dir>"
    echo ""
    echo "To redeploy a function:"
    echo "  gcloud functions deploy <function-name> --region=$REGION --gen2"

    if [ "$stale_found" -gt 0 ]; then
        exit 1
    else
        exit 0
    fi
else
    echo -e "${GREEN}All functions up to date!${NC}"
    exit 0
fi
